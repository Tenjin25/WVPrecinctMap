#!/usr/bin/env python3
"""Normalize complete 2000-2012 WV general-election county returns.

The 2000-2006 inputs are standardized OpenElections office CSVs. The
2008-2012 inputs are complete state-and-county downloads from the West Virginia
Secretary of State's historical Election Results Center.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OPEN_ELECTIONS = DATA / "openelections-data-wv"
RAW_OFFICIAL = DATA / "historical_county_sources"
OUTPUT = DATA / "openelections" / "wv_sos" / "historical_county"
REPORT = DATA / "historical_county_report.json"

ELECTION_DATES = {
    2000: "20001107",
    2002: "20021105",
    2004: "20041102",
    2006: "20061107",
    2008: "20081104",
    2010: "20101102",
    2012: "20121106",
    2014: "20141104",
}

LEGACY_FILES = {
    2000: (
        "attorney_general",
        "auditor",
        "commissioner_of_agriculture",
        "governor",
        "house",
        "president",
        "secretary_of_state",
        "senate",
        "state_treasurer",
    ),
    2002: ("house", "senate"),
    2004: (
        "attorney_general",
        "auditor",
        "commissioner_of_agriculture",
        "governor",
        "house",
        "president",
        "secretary_of_state",
        "state_treasurer",
    ),
    2006: ("house", "senate"),
}

COMBINED_LEGACY_FILES = {
    2014: OPEN_ELECTIONS / "2014" / "20141104__wv__general__county.csv",
}

OFFICIAL_DOWNLOADS = {
    2008: "https://apps.sos.wv.gov/elections/results/readfile.aspx?eid=4&format=csv&type=StateCountyTotals",
    2010: "https://apps.sos.wv.gov/elections/results/readfile.aspx?eid=6&format=csv&type=StateCountyTotals",
    2012: "https://apps.sos.wv.gov/elections/results/readfile.aspx?eid=13&format=csv&type=StateCountyTotals",
}

OUTPUT_FIELDS = ("county", "office", "district", "party", "candidate", "votes")


def token(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper())).strip()


CANONICAL_OFFICES = {
    "PRESIDENT": "President",
    "U S PRESIDENT": "President",
    "GOVERNOR": "Governor",
    "U S SENATE": "U.S. Senate",
    "US SENATE": "U.S. Senate",
    "UNITED STATES SENATOR": "U.S. Senate",
    "U S HOUSE": "U.S. House",
    "US HOUSE": "U.S. House",
    "U S HOUSE OF REPRESENTATIVES": "U.S. House",
    "UNITED STATES REPRESENTATIVE": "U.S. House",
    "ATTORNEY GENERAL": "Attorney General",
    "SECRETARY OF STATE": "Secretary of State",
    "STATE AUDITOR": "Auditor",
    "AUDITOR": "Auditor",
    "STATE TREASURER": "State Treasurer",
    "TREASURER": "State Treasurer",
    "COMMISSIONER OF AGRICULTURE": "Commissioner of Agriculture",
}


def canonical_office(value: str) -> str | None:
    return CANONICAL_OFFICES.get(token(value))


def download_official(year: int) -> Path:
    RAW_OFFICIAL.mkdir(parents=True, exist_ok=True)
    destination = RAW_OFFICIAL / f"{ELECTION_DATES[year]}__wv__general__state_county_totals.csv"
    if destination.exists() and destination.read_bytes().startswith(b"ElectionId,"):
        return destination
    request = urllib.request.Request(
        OFFICIAL_DOWNLOADS[year], headers={"User-Agent": "WVPrecinctMap/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    if not payload.startswith(b"ElectionId,"):
        raise ValueError(f"Unexpected WV SOS response for {year}")
    destination.write_bytes(payload)
    return destination


def legacy_rows(year: int):
    date = ELECTION_DATES[year]
    paths = (
        [COMBINED_LEGACY_FILES[year]]
        if year in COMBINED_LEGACY_FILES
        else [
            OPEN_ELECTIONS / str(year) / f"{date}__wv__general__{suffix}.csv"
            for suffix in LEGACY_FILES[year]
        ]
    )
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                county = str(row.get("county") or "").strip()
                office = canonical_office(str(row.get("office") or ""))
                if not county or token(county) in {"TOTAL", "TOTALS", "STATEWIDE"} or not office:
                    continue
                yield {
                    "county": county,
                    "office": office,
                    "district": str(row.get("district") or "").strip(),
                    "party": str(row.get("party") or "").strip(),
                    "candidate": str(row.get("candidate") or "").strip(),
                    "votes": int(str(row.get("votes") or "0").replace(",", "")),
                }


def official_rows(year: int):
    path = download_official(year)
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            county = str(row.get("CountyName") or "").strip()
            office = canonical_office(str(row.get("OfficeDescription") or ""))
            if (
                token(str(row.get("Type") or "")) != "COUNTY"
                or token(str(row.get("OfficialResults") or "")) != "YES"
                or not county
                or not office
            ):
                continue
            district = str(row.get("District") or "").strip()
            yield {
                "county": county,
                "office": office,
                "district": "" if district in {"", "0"} else district,
                "party": str(row.get("PartyName") or row.get("PartyCode") or "").strip(),
                "candidate": str(row.get("Name") or "").strip(),
                "votes": int(str(row.get("Votes") or "0").replace(",", "")),
            }


def write_year(year: int) -> dict[str, object]:
    uses_legacy = year in LEGACY_FILES or year in COMBINED_LEGACY_FILES
    rows = list(legacy_rows(year) if uses_legacy else official_rows(year))
    coverage: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        coverage[str(row["office"])].add(str(row["county"]))
    incomplete = {
        office: sorted(counties)
        for office, counties in coverage.items()
        if len(counties) != 55
    }
    # Never publish a partial statewide county map. Keep complete contests from
    # the same year and record source gaps for later supplementation.
    rows = [row for row in rows if str(row["office"]) not in incomplete]
    coverage = defaultdict(set)
    for row in rows:
        coverage[str(row["office"])].add(str(row["county"]))
    rows.sort(
        key=lambda row: (
            row["county"].casefold(),
            row["office"].casefold(),
            row["district"],
            row["party"].casefold(),
            row["candidate"].casefold(),
        )
    )
    output_path = OUTPUT / f"{ELECTION_DATES[year]}__wv__general__county.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    return {
        "year": year,
        "source": "OpenElections" if uses_legacy else "West Virginia Secretary of State",
        "output": output_path.relative_to(ROOT).as_posix(),
        "rows": len(rows),
        "contests": {office: len(counties) for office, counties in sorted(coverage.items())},
        "excluded_incomplete_contests": {
            office: {"counties_found": len(counties), "missing_counties": 55 - len(counties)}
            for office, counties in sorted(incomplete.items())
        },
    }


def main() -> None:
    results = [write_year(year) for year in sorted(ELECTION_DATES)]
    REPORT.write_text(
        json.dumps({"all_contests_have_55_counties": True, "elections": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"all_contests_have_55_counties": True, "elections": results}, indent=2))


if __name__ == "__main__":
    main()
