#!/usr/bin/env python3
"""Aggregate complete West Virginia precinct results to county totals.

Only years listed in COMPLETE_ELECTIONS are emitted. Add a year here after the
precinct coverage report confirms all 55 West Virginia counties are present.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRECINCT_DIR = ROOT / "data" / "openelections" / "wv_sos"
COUNTY_DIR = PRECINCT_DIR / "county"
REPORT_PATH = ROOT / "data" / "county_aggregation_report.json"

COMPLETE_ELECTIONS = {
    "2012": PRECINCT_DIR / "20121106__wv__general__precinct.csv",
    "2016": PRECINCT_DIR / "20161108__wv__general__precinct.csv",
    "2018": PRECINCT_DIR / "20181106__wv__general__precinct.csv",
    "2020": PRECINCT_DIR / "20201103__wv__general__precinct.csv",
    "2022": PRECINCT_DIR / "20221108__wv__general__precinct.csv",
    "2024": PRECINCT_DIR / "20241105__wv__general__precinct.csv",
}

KEY_FIELDS = ("county", "office", "district", "party", "candidate")
OUTPUT_FIELDS = (*KEY_FIELDS, "votes")


def aggregate_file(year: str, source_path: Path) -> dict[str, object]:
    totals: defaultdict[tuple[str, ...], int] = defaultdict(int)
    counties: set[str] = set()
    source_rows = 0
    blank_vote_rows = 0
    source_votes = 0

    with source_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"county", "precinct", "office", "district", "candidate", "party", "votes"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{source_path}: missing columns: {', '.join(sorted(missing))}")

        for line_number, row in enumerate(reader, start=2):
            source_rows += 1
            county = row["county"].strip()
            if not county:
                raise ValueError(f"{source_path}:{line_number}: blank county")
            raw_votes = row["votes"].strip()
            if not raw_votes:
                # Some OpenElections files use blank cells for candidates who
                # were not on the ballot in a particular precinct/district.
                blank_vote_rows += 1
                counties.add(county)
                continue
            try:
                votes = int(raw_votes)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{source_path}:{line_number}: invalid votes {row['votes']!r}") from exc
            if votes < 0:
                raise ValueError(f"{source_path}:{line_number}: negative votes")

            key = tuple(row[field].strip() for field in KEY_FIELDS)
            totals[key] += votes
            counties.add(county)
            source_votes += votes

    if len(counties) != 55:
        raise ValueError(
            f"{source_path}: expected complete 55-county coverage, found {len(counties)}"
        )

    output_path = COUNTY_DIR / source_path.name.replace("__precinct.csv", "__county.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        for key in sorted(totals, key=lambda value: tuple(part.casefold() for part in value)):
            writer.writerow(dict(zip(KEY_FIELDS, key), votes=totals[key]))

    output_votes = sum(totals.values())
    if output_votes != source_votes:
        raise AssertionError(f"{year}: vote conservation failed ({source_votes} != {output_votes})")

    return {
        "year": int(year),
        "source": source_path.relative_to(ROOT).as_posix(),
        "output": output_path.relative_to(ROOT).as_posix(),
        "counties": len(counties),
        "source_rows": source_rows,
        "blank_vote_rows_skipped": blank_vote_rows,
        "numeric_vote_rows": source_rows - blank_vote_rows,
        "output_rows": len(totals),
        "source_votes": source_votes,
        "output_votes": output_votes,
        "vote_conservation": True,
    }


def main() -> None:
    results = []
    for year, source_path in COMPLETE_ELECTIONS.items():
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        results.append(aggregate_file(year, source_path))

    report = {
        "description": "County totals aggregated from complete precinct-result coverage years.",
        "complete_coverage_rule": "Exactly 55 distinct West Virginia counties in the normalized precinct file.",
        "elections": results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    for result in results:
        print(
            f"{result['year']}: {result['source_rows']:,} precinct rows -> "
            f"{result['output_rows']:,} county rows; {result['output_votes']:,} votes"
        )
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
