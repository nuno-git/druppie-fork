#!/usr/bin/env python3
"""Seed script: populate DB with YAML fixture data.

Usage:
    # Reset DB first
    docker compose --profile reset-db run --rm reset-db

    # Then seed (with real Gitea repos)
    source venv/bin/activate
    DATABASE_URL=postgresql://druppie:druppie_secret@localhost:5634/druppie \
        python scripts/seed.py --gitea-url=http://localhost:3200

    # Or without Gitea (record-only, placeholder URLs)
    python scripts/seed.py

    # Custom fixtures directory
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
from druppie.testing.seed_loader import seed_all


def _default_gitea_url() -> str | None:
    """Derive the default Gitea URL from .env or environment."""
    # Explicit env var takes priority
    url = os.getenv("GITEA_URL")
    if url:
        return url

    # Try reading GITEA_PORT from the .env file next to this script
    env_path = Path(__file__).resolve().parent.parent / ".env"
    gitea_port = None
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("GITEA_PORT="):
                gitea_port = line.split("=", 1)[1].strip()
                break

    if gitea_port:
        return f"http://localhost:{gitea_port}"

    return None


def main():
    parser = argparse.ArgumentParser(description="Seed Druppie DB from YAML fixtures")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "testing" / "seeds",
        help="Directory containing YAML fixture files",
    )
    parser.add_argument(
        "--gitea-url",
        type=str,
        default=None,
        help=(
            "Gitea base URL (e.g. http://localhost:3200). "
            "When provided, real repos are created. "
            "Defaults to GITEA_URL env var or http://localhost:<GITEA_PORT> from .env."
        ),
    )
    args = parser.parse_args()

    if not args.fixtures_dir.exists():
        print(f"Error: fixtures directory not found: {args.fixtures_dir}")
        sys.exit(1)

    # Resolve Gitea URL: CLI flag > env var > .env file
    gitea_url = args.gitea_url or _default_gitea_url()

    print("=" * 60)
    print("Druppie \u2014 YAML Fixture Seeder")
    print("=" * 60)
    if gitea_url:
        print(f"  Gitea URL: {gitea_url} (will create real repos)")
    else:
        print("  Gitea URL: not set (record-only mode, placeholder URLs)")

    db = SessionLocal()
    try:
        count = seed_all(db, args.fixtures_dir, gitea_url=gitea_url)
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
