from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


class ModelClient:
    def __init__(self) -> None:
        self.provider = "openai"
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.enabled = bool(self.api_key and OpenAI is not None)
        self._client = OpenAI(api_key=self.api_key) if self.enabled else None

    def generate_text(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float = 0.4,
        top_p: float = 1.0,
        max_output_tokens: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> str:
        if not self.enabled:
            # Local-first fallback: deterministic stub output
            return (
                "{\n"
                "  \"captions\": [\"(OPENAI_API_KEY not set) Example caption 1\", \"(OPENAI_API_KEY not set) Example caption 2\"],\n"
                "  \"hashtags\": [\"sigilzero\", \"techno\", \"house\"],\n"
                "  \"notes\": \"Set OPENAI_API_KEY to enable model generation.\",\n"
                "  \"release_campaign_md\": \"# Release Campaign\\n\\n(OPENAI_API_KEY not set)\\n\",\n"
                "  \"ig_captions_md\": \"# IG Captions\\n\\n(OPENAI_API_KEY not set)\\n\",\n"
                "  \"press_release_md\": \"# Press Release\\n\\n(OPENAI_API_KEY not set)\\n\"\n"
                "}\n"
            )

        # Use chat.completions with a single user message for predictability
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "top_p": top_p,
        }
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens

        # Seed support is model/provider-dependent; include if accepted
        if seed is not None:
            kwargs["seed"] = seed

        resp = self._client.chat.completions.create(**kwargs)  # type: ignore
        return resp.choices[0].message.content or ""


_model_client: Optional[ModelClient] = None


def get_model_client() -> ModelClient:
    """Get or create the global model client."""
    global _model_client
    if _model_client is None:
        _model_client = ModelClient()
    return _model_client


def generate_text(*, prompt: str, generation_spec: Dict[str, Any]) -> str:
    """Generate text using the configured LLM.
    
    Args:
        prompt: The prompt to send to the model
        generation_spec: Dictionary with keys: provider, model, temperature, top_p, etc.
    
    Returns:
        Generated text from the model
    """
    client = get_model_client()
    return client.generate_text(
        model=generation_spec.get("model", "gpt-4.1-mini"),
        prompt=prompt,
        temperature=generation_spec.get("temperature", 0.4),
        top_p=generation_spec.get("top_p", 1.0),
        max_output_tokens=generation_spec.get("max_output_tokens"),
        seed=generation_spec.get("seed"),
    )
