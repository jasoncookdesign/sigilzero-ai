from __future__ import annotations

import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sigilzero.core.db import connect, init_db

def main() -> None:
    with connect() as conn:
        init_db(conn)
    print("OK: database tables ensured.")

if __name__ == "__main__":
    main()
