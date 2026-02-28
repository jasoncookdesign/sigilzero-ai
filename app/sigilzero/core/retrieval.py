"""Stage 6: Deterministic keyword-based corpus retrieval.

Implements BM25-inspired scoring with strict determinism guarantees:
- No randomness, timestamps, or UUIDs
- Deterministic tokenization and scoring
- Stable tie-breaking (lexicographic path ordering)
- Rebuildable from filesystem alone
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Set

from .hashing import sha256_bytes


def _tokenize(text: str) -> List[str]:
    """Deterministic tokenization: lowercase, alphanumeric only."""
    text = text.lower()
    # Split on non-alphanumeric, filter out empty strings
    tokens = [t for t in re.split(r'[^a-z0-9]+', text) if t]
    return tokens


def _compute_bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    doc_freq: Dict[str, int],
    num_docs: int,
    avg_doc_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """Compute BM25 score with deterministic parameters.
    
    Args:
        query_tokens: Tokenized query
        doc_tokens: Tokenized document
        doc_freq: Document frequency for each term (how many docs contain it)
        num_docs: Total number of documents
        avg_doc_length: Average document length
        k1: BM25 parameter (term frequency saturation)
        b: BM25 parameter (length normalization)
    
    Returns:
        BM25 score (float)
    """
    doc_length = len(doc_tokens)
    doc_term_freq = Counter(doc_tokens)
    score = 0.0
    
    for term in set(query_tokens):
        if term not in doc_term_freq:
            continue
        
        # Term frequency in document
        tf = doc_term_freq[term]
        
        # Inverse document frequency
        df = doc_freq.get(term, 0)
        if df == 0:
            continue
        idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
        
        # Length normalization
        norm_tf = tf / (tf + k1 * (1 - b + b * doc_length / avg_doc_length))
        
        score += idf * norm_tf
    
    return score


class RetrievalCandidate:
    """A document candidate for retrieval."""
    
    def __init__(self, path: str, content: str, sha256: str, size_bytes: int):
        self.path = path
        self.content = content
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.tokens = _tokenize(content)
        self.score: float = 0.0
    
    def __repr__(self) -> str:
        return f"RetrievalCandidate(path={self.path}, score={self.score:.4f})"


def retrieve_corpus_documents(
    repo_root: str,
    query: str,
    top_k: int,
    roots: List[str] = None,
    include_globs: List[str] = None,
    exclude_globs: List[str] = None,
    max_files: int = 200,
) -> Tuple[List[Dict], Dict[str, any]]:
    """Retrieve top-k corpus documents using deterministic keyword scoring.
    
    Args:
        repo_root: Repository root path
        query: Query string
        top_k: Number of documents to retrieve
        roots: List of root directories to search (default: ["corpus"])
        include_globs: Include patterns (default: ["**/*.md", "**/*.txt"])
        exclude_globs: Exclude patterns (default: [])
        max_files: Maximum files to consider (default: 200)
    
    Returns:
        Tuple of:
        - List of selected items (dicts with path, sha256, size_bytes, score)
        - Retrieval config dict (for auditing/verification)
    """
    roots = roots or ["corpus"]
    include_globs = include_globs or ["**/*.md", "**/*.txt"]
    exclude_globs = exclude_globs or []
    
    repo_path = Path(repo_root)
    
    # Gather candidate files (deterministic walk)
    candidates: List[RetrievalCandidate] = []
    seen_paths: Set[str] = set()
    
    for root in roots:
        root_path = repo_path / root
        if not root_path.exists():
            continue
        
        # Collect all matching files
        matched: List[Path] = []
        for pattern in include_globs:
            matched.extend(sorted(root_path.glob(pattern)))
        
        # Apply excludes
        excluded: Set[Path] = set()
        for pattern in exclude_globs:
            excluded.update(root_path.glob(pattern))
        
        # Filter and dedupe
        for file_path in matched:
            if not file_path.is_file():
                continue
            if file_path in excluded:
                continue
            
            rel_path = str(file_path.relative_to(repo_path))
            if rel_path in seen_paths:
                continue
            seen_paths.add(rel_path)
            
            try:
                content = file_path.read_text(encoding='utf-8', errors='replace')
                content_bytes = content.encode('utf-8')
                sha = sha256_bytes(content_bytes)
                
                candidate = RetrievalCandidate(
                    path=rel_path,
                    content=content,
                    sha256=sha,
                    size_bytes=len(content_bytes),
                )
                candidates.append(candidate)
                
                if len(candidates) >= max_files:
                    break
            except Exception:
                # Skip unreadable files
                continue
        
        if len(candidates) >= max_files:
            break
    
    if not candidates:
        return [], {
            "method": "keyword",
            "query": query,
            "top_k": top_k,
            "roots": roots,
            "include_globs": include_globs,
            "exclude_globs": exclude_globs,
            "max_files": max_files,
            "num_candidates": 0,
        }
    
    # Compute document statistics for BM25
    query_tokens = _tokenize(query)
    doc_freq: Dict[str, int] = defaultdict(int)
    total_doc_length = 0
    
    for candidate in candidates:
        total_doc_length += len(candidate.tokens)
        unique_terms = set(candidate.tokens)
        for term in unique_terms:
            doc_freq[term] += 1
    
    avg_doc_length = total_doc_length / len(candidates)
    num_docs = len(candidates)
    
    # Score all candidates
    for candidate in candidates:
        candidate.score = _compute_bm25_score(
            query_tokens=query_tokens,
            doc_tokens=candidate.tokens,
            doc_freq=doc_freq,
            num_docs=num_docs,
            avg_doc_length=avg_doc_length,
        )
    
    # Sort by score (descending), then by path (ascending) for deterministic tie-breaking
    candidates.sort(key=lambda c: (-c.score, c.path))
    
    # Select top-k
    selected = candidates[:top_k]
    
    # Build result items
    selected_items = [
        {
            "path": c.path,
            "sha256": c.sha256,
            "size_bytes": c.size_bytes,
            "score": c.score,
        }
        for c in selected
    ]
    
    # Build retrieval config (for snapshot auditing)
    retrieval_config = {
        "method": "keyword",
        "query": query,
        "top_k": top_k,
        "roots": roots,
        "include_globs": include_globs,
        "exclude_globs": exclude_globs,
        "max_files": max_files,
        "num_candidates": len(candidates),
        "tokenization": "lowercase_alphanumeric",
        "scoring": "bm25",
        "bm25_k1": 1.5,
        "bm25_b": 0.75,
    }
    
    return selected_items, retrieval_config
