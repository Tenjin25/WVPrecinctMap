#!/usr/bin/env python3
"""Build county-map contest JSON slices from aggregated county CSV files."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "openelections" / "wv_sos" / "county"
HISTORICAL_INPUT = ROOT / "data" / "openelections" / "wv_sos" / "historical_county"
OUTPUT = ROOT / "data" / "contests"

OFFICES = {
    "PRESIDENT": "president",
    "U S PRESIDENT": "president",
    "GOVERNOR": "governor",
    "U S SENATE": "us_senate",
    "US SENATE": "us_senate",
    "UNITED STATES SENATOR": "us_senate",
    "ATTORNEY GENERAL": "attorney_general",
    "SECRETARY OF STATE": "secretary_of_state",
    "STATE AUDITOR": "auditor",
    "AUDITOR": "auditor",
    "STATE TREASURER": "treasurer",
    "TREASURER": "treasurer",
    "COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
    "U S HOUSE": "us_house",
    "US HOUSE": "us_house",
    "U S HOUSE OF REPRESENTATIVES": "us_house",
    "UNITED STATES REPRESENTATIVE": "us_house",
}

CANDIDATE_PARTY_OVERRIDES = {
    # The 2018 county exports omit party labels in many counties.
    "JOSEPH MANCHIN": "DEM",
    "JOSEPH MANCHIN III": "DEM",
    "PATRICK MORRISEY": "REP",
    "RUSTY HOLLEN": "OTHER",
}

CANDIDATE_DISPLAY_OVERRIDES = {
    "JOSEPH MANCHIN": "JOSEPH MANCHIN III",
    "JOSEPH MANCHIN III": "JOSEPH MANCHIN III",
    "PATRICK MORRISEY": "PATRICK MORRISEY",
    "RUSTY HOLLEN": "RUSTY HOLLEN",
    # One Greenbrier export cell contains an Excel range reference in place
    # of Hollen's name; its LIB party and 216 votes complete his certified total.
    "PRECINCT 74 A662 E676": "RUSTY HOLLEN",
}

EXCLUDED_CANDIDATES_BY_CONTEST_YEAR = {
    # The certified WV SOS/FEC totals list the three ballot candidates only.
    (2018, "us_senate"): {"WRITE IN", "MARK BRAZAITIS"},
}


def token(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", value.upper())).strip()


def party_bucket(value: str) -> str:
    label = token(value)
    if label in {"D", "DEM", "DEMOCRAT", "DEMOCRATIC", "DEMOCRATIC PARTY"}:
        return "DEM"
    if label in {"R", "REP", "REPUBLICAN", "REPUBLICAN PARTY"}:
        return "REP"
    return "OTHER"


def year_from_name(path: Path) -> int:
    return int(path.name[:4])


def build_slice(path: Path) -> list[tuple[str, dict[str, object]]]:
    year = year_from_name(path)
    votes: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    candidates: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)

    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            contest = OFFICES.get(token(row["office"]))
            if not contest:
                continue
            county = row["county"].strip()
            # Official exports occasionally contain doubled spaces in names
            # (for example, "JOE  MANCHIN III"). Keep display labels stable.
            candidate = " ".join(row["candidate"].split())
            candidate = CANDIDATE_DISPLAY_OVERRIDES.get(token(candidate), candidate)
            if token(candidate) in EXCLUDED_CANDIDATES_BY_CONTEST_YEAR.get(
                (year, contest), set()
            ):
                continue
            bucket = CANDIDATE_PARTY_OVERRIDES.get(
                token(candidate), party_bucket(row["party"])
            )
            count = int(row["votes"])
            votes[(contest, county, bucket)] += count
            if candidate:
                candidates[(contest, county, bucket, candidate)] += count

    contests = sorted({contest for contest, _, _ in votes})
    output: list[tuple[str, dict[str, object]]] = []
    for contest in contests:
        counties = sorted({county for current, county, _ in votes if current == contest})
        rows = []
        for county in counties:
            dem = votes[(contest, county, "DEM")]
            rep = votes[(contest, county, "REP")]
            other = votes[(contest, county, "OTHER")]
            total = dem + rep + other

            def top_candidate(bucket: str) -> str:
                options = [
                    (count, candidate)
                    for (current, current_county, current_bucket, candidate), count in candidates.items()
                    if current == contest and current_county == county and current_bucket == bucket
                ]
                return max(options, default=(0, ""))[1]

            margin = rep - dem
            winner = "REP" if margin > 0 else "DEM" if margin < 0 else "TIE"
            rows.append(
                {
                    "county": county,
                    "dem_votes": dem,
                    "rep_votes": rep,
                    "other_votes": other,
                    "total_votes": total,
                    "dem_candidate": top_candidate("DEM"),
                    "rep_candidate": top_candidate("REP"),
                    "margin": margin,
                    "margin_pct": round(100 * margin / total, 8) if total else 0,
                    "winner": winner,
                }
            )

        output.append(
            (
                contest,
                {
                    "meta": {
                        "contest_type": contest,
                        "year": year,
                        "method": "sum_complete_precinct_returns_by_county",
                        "counties": len(rows),
                    },
                    "rows": rows,
                },
            )
        )
    return output


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    statewide_vote_checks = []

    sources_by_year = {year_from_name(path): path for path in INPUT.glob("*__county.csv")}
    # Official/legacy historical county files take precedence through 2012;
    # this preserves candidate names instead of generic party labels.
    sources_by_year.update(
        {year_from_name(path): path for path in HISTORICAL_INPUT.glob("*__county.csv")}
    )
    for year, source_path in sorted(sources_by_year.items()):
        for contest, payload in build_slice(source_path):
            filename = f"{contest}_{year}.json"
            (OUTPUT / filename).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            rows = payload["rows"]
            manifest.append(
                {"year": year, "contest_type": contest, "file": filename, "rows": len(rows)}
            )
            statewide_vote_checks.append(
                {
                    "year": year,
                    "contest_type": contest,
                    "counties": len(rows),
                    "total_votes": sum(int(row["total_votes"]) for row in rows),
                }
            )

    manifest.sort(key=lambda row: (row["year"], row["contest_type"]))
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "slice_files": len(manifest),
        "all_slices_have_55_counties": all(row["counties"] == 55 for row in statewide_vote_checks),
        "slices": statewide_vote_checks,
    }
    (ROOT / "data" / "county_contest_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
