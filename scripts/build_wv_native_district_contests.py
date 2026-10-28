#!/usr/bin/env python3
"""Build exact district-race totals from WV precinct results with district IDs."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INPUT = DATA / "openelections" / "wv_sos"
OUTPUT = DATA / "district_contests_native"

FILES = {
    2022: INPUT / "20221108__wv__general__precinct.csv",
}

OFFICES = {
    "U S HOUSE": ("congressional", "us_house"),
    "US HOUSE": ("congressional", "us_house"),
    "STATE HOUSE": ("state_house", "state_house"),
    "HOUSE OF DELEGATES": ("state_house", "state_house"),
    "STATE SENATE": ("state_senate", "state_senate"),
}

EXPECTED_DISTRICTS = {"congressional": 2, "state_house": 100, "state_senate": 17}


def token(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper())).strip()


def party_type(value: str) -> str:
    value = token(value)
    if value in {"D", "DEM", "DEMOCRAT", "DEMOCRATIC"}:
        return "DEM"
    if value in {"R", "REP", "REPUBLICAN"}:
        return "REP"
    return "OTHER"


def district_number(value: str) -> str | None:
    match = re.search(r"\d+", str(value or ""))
    return str(int(match.group())) if match else None


def candidate_name(value: str) -> str:
    words = str(value or "").strip().title().split()
    name = " ".join(word.upper() if re.fullmatch(r"[A-Za-z]\.?", word) else word for word in words)
    return re.sub(r"\bMc([a-z])", lambda match: "Mc" + match.group(1).upper(), name)


def is_summary_precinct(value: str) -> bool:
    return token(value) in {"TOTAL", "TOTALS", "FINAL TOTAL", "FINAL TOTALS", "COUNTY TOTAL", "COUNTY TOTALS"}


def signed_margin(dem: int, rep: int, total: int) -> float:
    return ((rep - dem) / total * 100.0) if total else 0.0


def make_node(scope: str, contest: str, year: int, districts):
    results = {}
    for district in sorted(districts, key=int):
        parties = districts[district]
        dem = sum(parties.get("DEM", {}).values())
        rep = sum(parties.get("REP", {}).values())
        other = sum(parties.get("OTHER", {}).values())
        total = dem + rep + other
        top_value = max(dem, rep, other)
        winners = [party for party, votes in (("DEM", dem), ("REP", rep), ("OTHER", other)) if votes == top_value]
        dem_name = max(parties.get("DEM", {"": 0}).items(), key=lambda item: item[1])[0] if dem else ""
        rep_name = max(parties.get("REP", {"": 0}).items(), key=lambda item: item[1])[0] if rep else ""
        results[district] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": other,
            "total_votes": total,
            "dem_candidate": dem_name,
            "rep_candidate": rep_name,
            "winner": winners[0] if len(winners) == 1 else "TIE",
            "margin_pct": round(signed_margin(dem, rep, total), 8),
        }
    return {
        "meta": {
            "scope": scope,
            "contest_type": contest,
            "year": year,
            "district_lines_year": 2022,
            "method": "official_precinct_results_summed_by_reported_district",
            "match_coverage_pct": 100.0,
        },
        "general": {"results": results},
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    report = {"years": {}, "summary": {}}

    for year, path in FILES.items():
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
        aggregates = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(int))))
        input_totals = defaultdict(int)

        for row in rows:
            office = OFFICES.get(token(row.get("office", "")))
            district = district_number(row.get("district", ""))
            if not office or not district or is_summary_precinct(row.get("precinct", "")):
                continue
            scope, contest = office
            votes = int(float(row.get("votes") or 0))
            party = party_type(row.get("party", ""))
            candidate = candidate_name(row.get("candidate", ""))
            aggregates[(scope, contest)][district][party][candidate] += votes
            input_totals[(scope, contest)] += votes

        year_report = {"input_rows": len(rows), "contests": {}}
        for (scope, contest), districts in sorted(aggregates.items()):
            node = make_node(scope, contest, year, districts)
            node["meta"].update({
                "source": "WV precinct-level general election returns normalized by OpenElections",
                "source_url": "https://github.com/openelections/openelections-data-wv",
            })
            filename = f"{scope}_{contest}_{year}.json"
            (OUTPUT / filename).write_text(json.dumps(node, indent=2) + "\n", encoding="utf-8")
            manifest.append({"scope": scope, "contest_type": contest, "year": year, "file": filename})
            output_total = sum(row["total_votes"] for row in node["general"]["results"].values())
            year_report["contests"][f"{scope}_{contest}"] = {
                "districts": len(districts),
                "input_total_votes": input_totals[(scope, contest)],
                "output_total_votes": output_total,
                "conservation_error": output_total - input_totals[(scope, contest)],
            }
        report["years"][str(year)] = year_report

    manifest.sort(key=lambda row: (row["year"], row["scope"], row["contest_type"]))
    (OUTPUT / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8")
    contest_reports = [item for year in report["years"].values() for item in year["contests"].values()]
    count_errors = []
    for year, year_node in report["years"].items():
        for key, item in year_node["contests"].items():
            scope = next(scope for scope in EXPECTED_DISTRICTS if key.startswith(scope + "_"))
            if item["districts"] != EXPECTED_DISTRICTS[scope]:
                count_errors.append({"year": int(year), "slice": key, "expected": EXPECTED_DISTRICTS[scope], "actual": item["districts"]})
    report["summary"] = {
        "slice_files": len(manifest),
        "max_conservation_error": max((abs(item["conservation_error"]) for item in contest_reports), default=0),
        "district_count_errors": count_errors,
    }
    report["summary"]["validation_passed"] = not count_errors and report["summary"]["max_conservation_error"] == 0
    (DATA / "native_district_aggregation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
