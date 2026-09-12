#!/usr/bin/env python3
"""Generate the frozen questionnaire asset through the backend source parser."""
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.seed.questionnaire_source import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
