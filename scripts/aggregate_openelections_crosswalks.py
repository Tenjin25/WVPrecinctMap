#!/usr/bin/env python3
"""Test historical OpenElections precinct CSVs through VTD and BEF crosswalks."""

from __future__ import annotations

import csv
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import shapefile

from wv_candidate_names import normalize_candidate_name


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INPUT = DATA / "openelections" / "wv_sos"
OUTPUT = DATA / "district_contests_openelections"

FILES = {
    2008: INPUT / "20081104__wv__general__precinct.csv",
    2010: INPUT / "20101102__wv__general__precinct.csv",
    2012: INPUT / "20121106__wv__general__precinct.csv",
    2014: INPUT / "20141104__wv__general__precinct.csv",
    2016: INPUT / "20161108__wv__general__precinct.csv",
    2018: INPUT / "20181106__wv__general__precinct.csv",
    2020: INPUT / "20201103__wv__general__precinct.csv",
    2022: INPUT / "20221108__wv__general__precinct.csv",
}

VINTAGE = {
    2008: 2000,
    2010: 2010,
    2012: 2010,
    2014: 2010,
    2016: 2010,
    2018: 2010,
    2020: 2020,
    2022: 2020,
}

OFFICES = {
    "PRESIDENT": "president",
    "GOVERNOR": "governor",
    "U S SENATE": "us_senate",
    "US SENATE": "us_senate",
    "UNITED STATES SENATOR": "us_senate",
    "U S HOUSE": "us_house",
    "US HOUSE": "us_house",
    "U S HOUSE OF REPRESENTATIVES": "us_house",
    "UNITED STATES REPRESENTATIVE": "us_house",
    "ATTORNEY GENERAL": "attorney_general",
    "SECRETARY OF STATE": "secretary_of_state",
    "STATE AUDITOR": "auditor",
    "AUDITOR": "auditor",
    "STATE TREASURER": "treasurer",
    "TREASURER": "treasurer",
    "COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
}

EXPECTED_DISTRICTS = {"congressional": 2, "state_house": 100, "state_senate": 17}

NAME_OVERRIDES = {
    (2012, "president", "DEM"): "Barack Obama",
    (2012, "president", "REP"): "Mitt Romney",
    (2012, "us_senate", "DEM"): "Joe Manchin III",
    (2012, "us_senate", "REP"): "John R. Raese",
    (2012, "governor", "DEM"): "Earl Ray Tomblin",
    (2012, "governor", "REP"): "Bill Maloney",
    (2012, "attorney_general", "DEM"): "Darrell V. McGraw Jr.",
    (2012, "attorney_general", "REP"): "Patrick Morrisey",
    (2012, "secretary_of_state", "DEM"): "Natalie E. Tennant",
    (2012, "secretary_of_state", "REP"): "Brian Savilla",
    (2012, "auditor", "DEM"): "Glen B. Gainer III",
    (2012, "auditor", "REP"): "Larry V. Faircloth",
    (2012, "treasurer", "DEM"): "John D. Perdue",
    (2012, "treasurer", "REP"): "Mike Hall",
    (2012, "agriculture_commissioner", "DEM"): "Walt Helmick",
    (2012, "agriculture_commissioner", "REP"): "Kent Leonhardt",
}


def token(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper())).strip()


def precinct_token(value: str) -> str:
    value = token(value)
    value = re.sub(r"\b(?:VOTING|ELECTION)\b", " ", value)
    value = re.sub(r"\b(?:PRECINCT|PCT|NO|NUMBER)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    # Keep numeric split suffixes distinct: "43-1" tokenizes to "43 1" and
    # must fall back to VTD 43, not be misread as precinct 431. Letter suffixes
    # such as "5-A" can still normalize directly to 5A.
    match = re.fullmatch(r"0*(\d+)\s*([A-Z]+)?", value)
    return f"{int(match.group(1))}{match.group(2) or ''}" if match else value


def base_precinct_token(value: str) -> str | None:
    value = precinct_token(value)
    match = re.match(r"^0*(\d+)", value)
    return str(int(match.group(1))) if match else None


def is_summary_precinct(value: str) -> bool:
    value = precinct_token(value)
    return value in {"TOTAL", "TOTALS", "FINAL TOTAL", "FINAL TOTALS", "COUNTY TOTAL", "COUNTY TOTALS"}


def office_type(value: str) -> str | None:
    return OFFICES.get(token(value))


def party_type(value: str) -> str | None:
    value = token(value)
    if value in {"D", "DEM", "DEMOCRAT", "DEMOCRATIC"}:
        return "DEM"
    if value in {"R", "REP", "REPUBLICAN"}:
        return "REP"
    if value in {"L", "LIB", "LIBERTARIAN"}:
        return "LIB"
    if value in {"M", "MT", "MTN", "MOUNTAIN"}:
        return "MTN"
    if value in {"C", "CON", "CST", "CONSTITUTION"}:
        return "CST"
    if value in {"I", "IND", "INDEPENDENT"}:
        return "IND"
    if value in {"GRN", "GREEN", "SEP", "U", "WI", "WRITE IN", "OTH", "OTHER"}:
        return "OTH"
    return None


def county_lookup():
    path = DATA / "tl_2020_54_county20.zip"
    archive = zipfile.ZipFile(path)
    try:
        dbf = next(name for name in archive.namelist() if name.lower().endswith(".dbf"))
        reader = shapefile.Reader(dbf=archive.open(dbf))
        return {token(record["NAME20"]): str(record["COUNTYFP20"]) for record in reader.iterRecords()}
    finally:
        archive.close()


def load_vintage_crosswalk(vintage: int):
    if vintage == 2020:
        payload = json.loads((DATA / "wv_vtd_2020.geojson").read_text(encoding="utf-8"))
        weights = defaultdict(list)
        source_meta = {}
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            geoid = str(props.get("GEOID20") or "")
            if not geoid:
                continue
            weights[geoid].append((geoid, 1.0))
            source_meta[geoid] = (
                str(props.get("COUNTYFP20") or ""),
                str(props.get("VTDST20") or props.get("prec_id") or ""),
                str(props.get("NAME20") or props.get("precinct_name") or ""),
            )
        return weights, source_meta
    name = "vtd2000_to_vtd2020.csv" if vintage == 2000 else "vtd2010_to_vtd2020.csv"
    rows = list(csv.DictReader((DATA / "crosswalks_nhgis" / name).open(encoding="utf-8", newline="")))
    weights = defaultdict(list)
    source_meta = {}
    for row in rows:
        source = row["source_vtd_geoid"]
        weights[source].append((row["target_vtd_geoid"], float(row["area_weight"])))
        source_meta[source] = (
            row["source_county_fips"], row["source_vtd_code"], row["source_vtd_name"]
        )
    return weights, source_meta


def load_target_district_weights():
    files = {
        "congressional": "precinct_to_congressional_2022_enacted.csv",
        "state_house": "precinct_to_state_house_2022.csv",
        "state_senate": "precinct_to_state_senate_2022.csv",
    }
    output = {}
    for scope, name in files.items():
        by_target = defaultdict(list)
        with (DATA / "crosswalks_bef" / name).open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                by_target[row["precinct_key"]].append((row["district_num"], float(row["area_weight"])))
        output[scope] = by_target
    return output


def load_current_precinct_aliases():
    payload = json.loads((DATA / "wv_vtd_2020.geojson").read_text(encoding="utf-8"))
    candidates = defaultdict(set)
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        county_fips = str(props.get("COUNTYFP20") or "")
        target = str(props.get("GEOID20") or "")
        for raw in (props.get("prec_id"), props.get("VTDST20"), props.get("NAME20")):
            if raw:
                candidates[(county_fips, precinct_token(raw))].add(target)
    return {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}


def source_aliases(source_meta):
    candidates = defaultdict(set)
    for geoid, (county_fips, code, name) in source_meta.items():
        candidates[(county_fips, precinct_token(code))].add(geoid)
        candidates[(county_fips, precinct_token(name))].add(geoid)
    return {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}


def compose_source_to_district(source_weights, district_weights):
    output = {}
    for scope, target_map in district_weights.items():
        by_source = {}
        for source, targets in source_weights.items():
            totals = defaultdict(float)
            for target, first_weight in targets:
                for district, second_weight in target_map.get(target, []):
                    totals[district] += first_weight * second_weight
            denominator = sum(totals.values())
            if denominator:
                by_source[source] = [(district, weight / denominator) for district, weight in totals.items()]
        output[scope] = by_source
    return output


def signed_margin(dem, rep, total):
    return ((rep - dem) / total * 100.0) if total else 0.0


def apportion_candidate_votes(district_data):
    """Round each candidate across districts with the largest-remainder method."""
    districts = sorted(district_data, key=lambda value: int(value))
    candidates = sorted({
        (party, candidate)
        for parties in district_data.values()
        for party, party_candidates in parties.items()
        for candidate in party_candidates
    })
    for party, candidate in candidates:
        raw = {
            district: max(0.0, float(district_data[district][party].get(candidate, 0.0)))
            for district in districts
        }
        target = int(math.floor(sum(raw.values()) + 0.5))
        allocated = {district: math.floor(value) for district, value in raw.items()}
        remaining = target - sum(allocated.values())
        ranked = sorted(districts, key=lambda district: (-(raw[district] - allocated[district]), int(district)))
        for district in ranked[:remaining]:
            allocated[district] += 1
        for district in districts:
            district_data[district][party][candidate] = int(allocated[district])


def make_node(scope, contest, year, district_data, coverage):
    results = {}
    for district, parties in sorted(district_data.items(), key=lambda item: int(item[0])):
        dem = sum(parties.get("DEM", {}).values())
        rep = sum(parties.get("REP", {}).values())
        other = sum(sum(candidates.values()) for party, candidates in parties.items() if party not in {"DEM", "REP"})
        total = dem + rep + other
        dem_candidate = max(parties.get("DEM", {"": 0}).items(), key=lambda item: item[1])[0] if dem else ""
        rep_candidate = max(parties.get("REP", {"": 0}).items(), key=lambda item: item[1])[0] if rep else ""
        winner = "REP" if rep > max(dem, other) else ("DEM" if dem > max(rep, other) else ("OTHER" if other > max(dem, rep) else "TIE"))
        results[str(int(district))] = {
            "dem_votes": int(dem),
            "rep_votes": int(rep),
            "other_votes": int(other),
            "total_votes": int(total),
            "dem_candidate": dem_candidate,
            "rep_candidate": rep_candidate,
            "winner": winner,
            "margin_pct": round(signed_margin(dem, rep, total), 8),
        }
    return {
        "meta": {
            "scope": scope,
            "contest_type": contest,
            "year": year,
            "district_lines_year": 2022,
            "source_vtd_vintage": VINTAGE[year],
            "method": "openelections_precinct_to_nhgis_vtd_lineage_to_bef",
            "match_coverage_pct": round(coverage * 100.0, 6),
            "source": "WV precinct-level general election returns normalized by OpenElections",
            "source_url": "https://github.com/openelections/openelections-data-wv",
        },
        "general": {"results": results},
    }


def main() -> int:
    counties = county_lookup()
    district_weights = load_target_district_weights()
    current_aliases = load_current_precinct_aliases()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    report = {"years": {}, "summary": {}}

    for year, path in FILES.items():
        print(f"Aggregating OpenElections {year}...")
        source_weights, source_meta = load_vintage_crosswalk(VINTAGE[year])
        aliases = source_aliases(source_meta)
        composed = compose_source_to_district(source_weights, district_weights)
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))

        candidate_party_counts = defaultdict(Counter)
        for row in rows:
            party = party_type(row.get("party", ""))
            if party:
                candidate_party_counts[token(row.get("candidate", ""))][party] += int(float(row.get("votes") or 0))
        inferred_party = {
            candidate: counts.most_common(1)[0][0]
            for candidate, counts in candidate_party_counts.items() if counts
        }

        aggregated = {scope: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float)))) for scope in EXPECTED_DISTRICTS}
        source_totals = defaultdict(int)
        matched_totals = defaultdict(int)
        matched_precincts = set()
        unmatched_precincts = Counter()
        match_methods = Counter()

        for row in rows:
            contest = office_type(row.get("office", ""))
            if not contest:
                continue
            if is_summary_precinct(row.get("precinct", "")):
                continue
            votes = int(float(row.get("votes") or 0))
            source_totals[contest] += votes
            county_fips = counties.get(token(row.get("county", "")))
            precinct = precinct_token(row.get("precinct", ""))
            base_precinct = base_precinct_token(row.get("precinct", ""))
            source_geoid = aliases.get((county_fips, precinct)) if county_fips else None
            target_geoid = None
            match_method = "source_vtd_exact"
            if not source_geoid and county_fips and base_precinct and base_precinct != precinct:
                source_geoid = aliases.get((county_fips, base_precinct))
                if source_geoid:
                    match_method = "source_vtd_base_code_fallback"
            if not source_geoid and county_fips:
                target_geoid = current_aliases.get((county_fips, precinct))
                match_method = "current_precinct_exact"
            if not source_geoid and not target_geoid and county_fips and base_precinct and base_precinct != precinct:
                target_geoid = current_aliases.get((county_fips, base_precinct))
                if target_geoid:
                    match_method = "current_precinct_base_code_fallback"
            precinct_key = f"{row.get('county', '')}|{row.get('precinct', '')}"
            if not source_geoid and not target_geoid:
                unmatched_precincts[precinct_key] += int(votes)
                continue
            party = party_type(row.get("party", "")) or inferred_party.get(token(row.get("candidate", ""))) or "OTH"
            candidate = NAME_OVERRIDES.get(
                (year, contest, party),
                normalize_candidate_name(row.get("candidate") or ""),
            )
            matched_totals[contest] += votes
            matched_precincts.add(precinct_key)
            match_methods[match_method] += 1
            for scope in EXPECTED_DISTRICTS:
                allocation = composed[scope].get(source_geoid, []) if source_geoid else district_weights[scope].get(target_geoid, [])
                for district, weight in allocation:
                    aggregated[scope][contest][district][party][candidate] += votes * weight

        year_report = {
            "source_vtd_vintage": VINTAGE[year],
            "input_rows": len(rows),
            "matched_precincts": len(matched_precincts),
            "unmatched_precincts": len(unmatched_precincts),
            "match_methods_by_rows": dict(match_methods),
            "largest_unmatched_precincts_by_votes": [
                {"precinct": key, "votes_across_selected_contests": votes}
                for key, votes in unmatched_precincts.most_common(20)
            ],
            "contests": {},
        }
        for scope, contests in aggregated.items():
            for contest, district_data in sorted(contests.items()):
                coverage = matched_totals[contest] / source_totals[contest] if source_totals[contest] else 0.0
                apportion_candidate_votes(district_data)
                node = make_node(scope, contest, year, district_data, coverage)
                filename = f"{scope}_{contest}_{year}.json"
                (OUTPUT / filename).write_text(json.dumps(node, indent=2) + "\n", encoding="utf-8")
                manifest.append({"scope": scope, "contest_type": contest, "year": year, "file": filename})
                output_total = sum(result["total_votes"] for result in node["general"]["results"].values())
                year_report["contests"][f"{scope}_{contest}"] = {
                    "districts": len(node["general"]["results"]),
                    "source_total_votes": int(source_totals[contest]),
                    "matched_total_votes": int(matched_totals[contest]),
                    "output_total_votes": int(output_total),
                    "match_coverage_pct": round(coverage * 100.0, 6),
                    "conservation_error": int(output_total - matched_totals[contest]),
                }
        report["years"][str(year)] = year_report

    manifest.sort(key=lambda row: (row["year"], row["scope"], row["contest_type"]))
    (OUTPUT / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8")
    contest_reports = [contest for year in report["years"].values() for contest in year["contests"].values()]
    district_count_warnings = []
    for year, year_node in report["years"].items():
        for key, item in year_node["contests"].items():
            scope = next(scope for scope in EXPECTED_DISTRICTS if key.startswith(scope + "_"))
            if item["districts"] != EXPECTED_DISTRICTS[scope]:
                district_count_warnings.append({
                    "slice": key, "year": int(year), "actual": item["districts"],
                    "expected": EXPECTED_DISTRICTS[scope],
                })
    report["summary"] = {
        "slice_files": len(manifest),
        "max_conservation_error": max((abs(item["conservation_error"]) for item in contest_reports), default=0.0),
        "minimum_match_coverage_pct": min((item["match_coverage_pct"] for item in contest_reports), default=0.0),
        "district_count_warnings": district_count_warnings,
    }
    complete_year_errors = [
        item for item in district_count_warnings
        if item["year"] in {2012, 2014, 2016, 2020, 2022}
    ]
    report["summary"]["complete_year_district_count_errors"] = complete_year_errors
    report["summary"]["validation_passed"] = (
        report["summary"]["max_conservation_error"] < 1e-4 and not complete_year_errors
    )
    (DATA / "openelections_crosswalk_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
