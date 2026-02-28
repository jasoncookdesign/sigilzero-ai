from __future__ import annotations

from sigilzero.core.db import connect, init_db

def main() -> None:
    with connect() as conn:
        init_db(conn)
    print("OK: database tables ensured.")

if __name__ == "__main__":
    main()
