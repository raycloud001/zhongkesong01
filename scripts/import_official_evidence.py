#!/usr/bin/env python3
"""Explicitly import the official evidence-only asset into a selected local database."""
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.session import build_engine  # noqa: E402
from app.seed.official import import_official_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True, help="Explicit target database URL")
    parser.add_argument("--activate", action="store_true", help="Explicitly switch the question and rule pointers")
    args = parser.parse_args()
    asset = ROOT / "backend/seed/official-questionnaire.json"
    source = ROOT / "backend/seed/sources/题目与AI报告生成规则.md"
    with Session(build_engine(args.database_url)) as db, db.begin():
        version_id = import_official_evidence(db, json.loads(asset.read_text()), source_path=source, activate=args.activate)
    print(version_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
