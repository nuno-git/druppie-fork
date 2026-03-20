#!/usr/bin/env python3
"""Seed script: populate DB with YAML fixture data.

Usage:
    # Reset DB first
    docker compose --profile reset-db run --rm reset-db

    # Then seed
    source venv/bin/activate
    DATABASE_URL=postgresql://druppie:druppie_secret@localhost:5533/druppie \
        python scripts/seed.py

    # Or with custom fixtures directory
    python scripts/seed.py --fixtures-dir /path/to/fixtures
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path so druppie package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set DATABASE_URL before importing druppie modules (database.py reads it at
# import time via os.getenv)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "postgresql://druppie:druppie_secret@localhost:5533/druppie"
    )

from druppie.db.database import SessionLocal
from druppie.fixtures.loader import seed_all


def main():
    parser = argparse.ArgumentParser(description="Seed Druppie DB from YAML fixtures")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "druppie" / "fixtures" / "sessions",
        help="Directory containing YAML fixture files",
    )
    args = parser.parse_args()

    if not args.fixtures_dir.exists():
        print(f"Error: fixtures directory not found: {args.fixtures_dir}")
        sys.exit(1)

    print("=" * 60)
    print("Druppie — YAML Fixture Seeder")
    print("=" * 60)

    db = SessionLocal()
    try:
        count = seed_all(db, args.fixtures_dir)
        db.commit()
        print(f"\n[DONE] Seeded {count} sessions from {args.fixtures_dir}")
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        db.close()

    print("=" * 60)


if __name__ == "__main__":
    main()
