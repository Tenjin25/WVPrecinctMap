#!/usr/bin/env python3
"""Retire former cross-level U.S. House-to-legislative projections.

U.S. House results belong on the congressional district layer. Running this
script removes the obsolete state-House and state-Senate projection artifacts
and leaves an empty supplemental manifest for downstream aggregation.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "district_contests_precinct_geometry"
OBSOLETE_FILES = (
    "state_house_us_house_2022.json",
    "state_senate_us_house_2022.json",
)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename in OBSOLETE_FILES:
        (OUTPUT / filename).unlink(missing_ok=True)

    (OUTPUT / "manifest.json").write_text(
        json.dumps({"files": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "disabled_reason": "U.S. House is available only on the congressional district layer",
        "removed_files": list(OBSOLETE_FILES),
        "contests": {},
        "validation_passed": True,
    }
    (DATA / "precinct_geometry_aggregation_report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
