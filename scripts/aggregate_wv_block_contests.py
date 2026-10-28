#!/usr/bin/env python3
"""Aggregate RDH block-level election estimates through WV block equivalency files."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import shutil
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import shapefile

from wv_candidate_names import normalize_candidate_name


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "district_contests"

SUPPLEMENTAL_SOURCES = (
    # District-native contests are exact and always take precedence over a
    # precinct/VTD crosswalk for the same year, scope, and office.
    (DATA / "district_contests_native", None, 100.0),
    (DATA / "district_contests_precinct_geometry", {2022}, 99.0),
    # These are the historical years whose precinct coverage and district
    # counts have been validated. Earlier partial years stay diagnostic-only.
    (DATA / "district_contests_openelections", {2012, 2014, 2016, 2020}, 97.0),
)

OFFICES = {
    "PRE": "president",
    "USS": "us_senate",
    "GOV": "governor",
    "SOS": "secretary_of_state",
    "AUD": "auditor",
    "TRE": "treasurer",
    "AGR": "agriculture_commissioner",
    "ATG": "attorney_general",
}

PARTIES = {
    "D": "DEM",
    "R": "REP",
    "L": "LIB",
    "M": "MTN",
    "C": "CST",
    "I": "IND",
    "O": "OTH",
}

BEFS = {
    "congressional": DATA / "54_WV_CD118.txt",
    "state_house": DATA / "54_WV_SLDL22.txt",
    "state_senate": DATA / "54_WV_SLDU22.txt",
}

BLOCK_FILES = {
    2016: DATA / "wv_2016_gen_2020_blocks.zip",
    2018: DATA / "wv_2018_gen_2020_blocks.zip",
    2020: DATA / "wv_2020_gen_2020_blocks.zip",
    2024: DATA / "wv_2024_gen_2020_blocks_csv.zip",
}

NAME_OVERRIDES = {
    "G20AGRDBEA": "Bob Beach",
    "G20AGRRLEO": "Kent Leonhardt",
    "G20ATGDPET": "Sam Brown Petsonk",
    "G20ATGRMOR": "Patrick Morrisey",
    "G20AUDDCLA": "Mary Ann Roebuck Claytor",
    "G20AUDRMCC": 'John "JB" McCuskey',
    "G20SOSDTEN": "Natalie Tennant",
    "G20SOSRWAR": "Mac Warner",
    "G20TREDPER": "John D. Perdue",
    "G20TRERMOO": "Riley Moore",
}


def read_bef(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, skipinitialspace=True)
        geoid_field, district_field = reader.fieldnames[:2]
        return {
            str(row[geoid_field]).strip(): str(row[district_field]).strip()
            for row in reader
            if str(row.get(geoid_field) or "").strip()
        }


def party_from_label(label: str) -> str | None:
    value = str(label or "").strip().upper()
    if value.startswith("DEM"):
        return "DEM"
    if value.startswith("REP"):
        return "REP"
    if value.startswith("LIB") or value == "LBN":
        return "LIB"
    if value.startswith("MOU") or value == "MTN":
        return "MTN"
    if value.startswith("CON") or value == "CST":
        return "CST"
    if value.startswith("IND"):
        return "IND"
    if value.startswith("OTH"):
        return "OTH"
    return None


def read_candidate_metadata(archive: zipfile.ZipFile):
    text = archive.read("README.txt").decode("utf-8-sig", errors="replace")
    names = {}
    parties = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("G"):
            continue
        old = re.match(r"^(G[A-Z0-9]+)\s+-\s+(.+?)\s+\(([^)]*)\)\s*$", line)
        if old:
            names[old.group(1)] = normalize_candidate_name(old.group(2))
            parsed_party = party_from_label(old.group(3))
            if parsed_party:
                parties[old.group(1)] = parsed_party
            continue
        modern = re.match(r"^(G[A-Z0-9]+)\s{2,}(.+)$", line)
        if modern:
            pieces = [piece.strip() for piece in modern.group(2).split(",")]
            party_index = next((i for i, piece in enumerate(pieces) if party_from_label(piece)), None)
            if party_index is not None:
                names[modern.group(1)] = normalize_candidate_name(", ".join(pieces[:party_index]))
                parties[modern.group(1)] = party_from_label(pieces[party_index])
            else:
                names[modern.group(1)] = normalize_candidate_name(pieces[0])
    names.update({column: normalize_candidate_name(name) for column, name in NAME_OVERRIDES.items()})
    return names, parties


def parse_vote_column(column: str, year: int):
    if year < 2024:
        match = re.match(r"^G\d{2}([A-Z0-9]{3})([A-Z])([A-Z0-9]+)$", column)
        if not match or match.group(1) not in OFFICES:
            return None
        return OFFICES[match.group(1)], PARTIES.get(match.group(2), "OTH"), None

    statewide = re.match(r"^G24([A-Z0-9]{3})([A-Z])([A-Z0-9]+)$", column)
    if statewide and statewide.group(1) in OFFICES:
        return OFFICES[statewide.group(1)], PARTIES.get(statewide.group(2), "OTH"), None
    congressional = re.match(r"^GCON(\d{2})([A-Z])([A-Z0-9]+)$", column)
    if congressional:
        return "us_house", PARTIES.get(congressional.group(2), "OTH"), "congressional"
    house = re.match(r"^GSL(\d{3})([A-Z])([A-Z0-9]+)$", column)
    if house:
        return "state_house", PARTIES.get(house.group(2), "OTH"), "state_house"
    senate = re.match(r"^GSU(\d{2})([A-Z])([A-Z0-9]+)$", column)
    if senate:
        return "state_senate", PARTIES.get(senate.group(2), "OTH"), "state_senate"
    return None


@contextmanager
def block_rows(path: Path, year: int):
    archive = zipfile.ZipFile(path)
    names, parties = read_candidate_metadata(archive)
    try:
        if year == 2024:
            csv_name = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
            with io.TextIOWrapper(archive.open(csv_name), encoding="utf-8-sig", errors="replace", newline="") as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames or []
                yield fields, names, parties, reader
        else:
            dbf_name = next(name for name in archive.namelist() if name.lower().endswith(".dbf"))
            reader = shapefile.Reader(dbf=archive.open(dbf_name))
            fields = [field[0] for field in reader.fields[1:]]
            yield fields, names, parties, (record.as_dict() for record in reader.iterRecords())
    finally:
        archive.close()


def clean_number(value) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def signed_margin(dem: float, rep: float, total: float) -> float:
    return ((rep - dem) / total * 100.0) if total else 0.0


def winner(dem: float, rep: float, other: float) -> str:
    top = max((dem, "DEM"), (rep, "REP"), (other, "OTHER"))
    tied = sum(abs(value - top[0]) < 1e-9 for value in (dem, rep, other)) > 1
    return "TIE" if tied else top[1]


def district_sort_key(value: str):
    return (int(value) if value.isdigit() else 9999, value)


def apportion_columns(district_columns) -> dict[str, int]:
    """Round candidate estimates to integers without changing rounded totals."""
    columns = sorted({column for values in district_columns.values() for column in values})
    districts = sorted(district_columns, key=district_sort_key)
    targets = {}
    for column in columns:
        raw = {district: max(0.0, float(district_columns[district].get(column, 0.0))) for district in districts}
        target = int(math.floor(sum(raw.values()) + 0.5))
        allocated = {district: math.floor(value) for district, value in raw.items()}
        remaining = target - sum(allocated.values())
        ranked = sorted(districts, key=lambda district: (-(raw[district] - allocated[district]), district_sort_key(district)))
        for district in ranked[:remaining]:
            allocated[district] += 1
        for district in districts:
            district_columns[district][column] = int(allocated[district])
        targets[column] = target
    return targets


def build_node(scope: str, contest: str, year: int, district_columns, column_meta, candidate_names):
    results = {}
    for district, columns in sorted(district_columns.items(), key=lambda item: district_sort_key(item[0])):
        party_totals = defaultdict(int)
        party_candidates = defaultdict(list)
        for column, votes in columns.items():
            party = column_meta[column][1]
            party_totals[party] += votes
            party_candidates[party].append((votes, candidate_names.get(column, column)))
        dem = party_totals["DEM"]
        rep = party_totals["REP"]
        other = sum(value for party, value in party_totals.items() if party not in {"DEM", "REP"})
        total = dem + rep + other
        dem_name = max(party_candidates.get("DEM", [(0, "")]))[1] if dem else ""
        rep_name = max(party_candidates.get("REP", [(0, "")]))[1] if rep else ""
        results[str(int(district)) if district.isdigit() else district] = {
            "dem_votes": int(dem),
            "rep_votes": int(rep),
            "other_votes": int(other),
            "total_votes": int(total),
            "dem_candidate": dem_name,
            "rep_candidate": rep_name,
            "winner": winner(dem, rep, other),
            "margin_pct": round(signed_margin(dem, rep, total), 8),
        }
    return {
        "meta": {
            "scope": scope,
            "contest_type": contest,
            "year": year,
            "district_lines_year": 2022,
            "method": "rdh_2020_block_votes_joined_to_census_bef",
            "match_coverage_pct": 100.0,
        },
        "general": {"results": results},
    }


def merge_supplemental_slices(manifest, legacy):
    """Add validated fallbacks without replacing a block-derived slice."""
    existing = {(item["scope"], item["contest_type"], item["year"]) for item in manifest}
    expected = {"congressional": 2, "state_house": 100, "state_senate": 17}
    merged = []
    for directory, allowed_years, minimum_coverage in SUPPLEMENTAL_SOURCES:
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            continue
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", [])
        for item in source_manifest:
            year = int(item["year"])
            if item["contest_type"] == "us_house" and year not in {2022, 2024}:
                continue
            key = (item["scope"], item["contest_type"], year)
            if key in existing or (allowed_years is not None and year not in allowed_years):
                continue
            source_path = directory / item["file"]
            node = json.loads(source_path.read_text(encoding="utf-8"))
            coverage = float(node.get("meta", {}).get("match_coverage_pct", 0))
            districts = node.get("general", {}).get("results", {})
            if coverage < minimum_coverage or len(districts) != expected[item["scope"]]:
                continue
            shutil.copyfile(source_path, OUTPUT / item["file"])
            manifest.append(dict(item))
            legacy["results_by_year"].setdefault(str(year), {}).setdefault(item["scope"], {})[item["contest_type"]] = node
            existing.add(key)
            merged.append({**item, "method": node.get("meta", {}).get("method"), "match_coverage_pct": coverage})
    return merged


def main() -> int:
    assignments = {scope: read_bef(path) for scope, path in BEFS.items()}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    old_manifest_path = OUTPUT / "manifest.json"
    if old_manifest_path.exists():
        old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8")).get("files", [])
        for item in old_manifest:
            old_slice = OUTPUT / str(item.get("file") or "")
            if old_slice.parent == OUTPUT and old_slice.suffix == ".json":
                old_slice.unlink(missing_ok=True)
    manifest = []
    legacy = {"results_by_year": {}}
    qa = {"years": {}, "summary": {}}

    for year, path in BLOCK_FILES.items():
        print(f"Aggregating {year}...")
        with block_rows(path, year) as (fields, candidate_names, party_overrides, rows):
            column_meta = {
                field: (parsed[0], party_overrides.get(field, parsed[1]), parsed[2])
                for field in fields
                if (parsed := parse_vote_column(field, year)) is not None
            }
            columns_by_scope = {scope: [] for scope in assignments}
            for column, (_contest, _party, target_scope) in column_meta.items():
                if target_scope:
                    columns_by_scope[target_scope].append(column)
                else:
                    for scope in columns_by_scope:
                        columns_by_scope[scope].append(column)

            aggregated = {
                scope: defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
                for scope in assignments
            }
            source_totals = defaultdict(float)
            block_rows_seen = 0
            missing_assignment = defaultdict(int)

            for row in rows:
                block_rows_seen += 1
                geoid = str(row.get("GEOID20") or "").strip()
                values = {column: clean_number(row.get(column)) for column in column_meta}
                for column, value in values.items():
                    source_totals[column] += value
                for scope, columns in columns_by_scope.items():
                    district = assignments[scope].get(geoid)
                    if not district:
                        missing_assignment[scope] += 1
                        continue
                    for column in columns:
                        value = values[column]
                        if value:
                            contest = column_meta[column][0]
                            aggregated[scope][contest][district][column] += value

        year_qa = {
            "block_rows": block_rows_seen,
            "vote_columns": len(column_meta),
            "missing_block_assignments": dict(missing_assignment),
            "contests": {},
        }
        legacy["results_by_year"][str(year)] = {}

        for scope, contests in aggregated.items():
            legacy["results_by_year"][str(year)][scope] = {}
            for contest, district_columns in sorted(contests.items()):
                integer_targets = apportion_columns(district_columns)
                node = build_node(scope, contest, year, district_columns, column_meta, candidate_names)
                output_name = f"{scope}_{contest}_{year}.json"
                (OUTPUT / output_name).write_text(json.dumps(node, indent=2) + "\n", encoding="utf-8")
                legacy["results_by_year"][str(year)][scope][contest] = node
                manifest.append({
                    "scope": scope,
                    "contest_type": contest,
                    "year": year,
                    "file": output_name,
                })

                relevant_columns = [
                    column for column, meta in column_meta.items()
                    if meta[0] == contest and (meta[2] is None or meta[2] == scope)
                ]
                column_errors = {}
                for column in relevant_columns:
                    district_total = sum(
                        district_columns[district].get(column, 0.0)
                        for district in district_columns
                    )
                    column_errors[column] = district_total - integer_targets.get(column, 0)
                source_total = sum(integer_targets.get(column, 0) for column in relevant_columns)
                district_total = sum(
                    result["total_votes"]
                    for result in node["general"]["results"].values()
                )
                qa_key = f"{scope}_{contest}"
                year_qa["contests"][qa_key] = {
                    "districts": len(node["general"]["results"]),
                    "candidate_columns": len(relevant_columns),
                    "source_total_votes": int(source_total),
                    "district_total_votes": int(district_total),
                    "total_vote_error": int(district_total - source_total),
                    "max_candidate_vote_error": max((abs(value) for value in column_errors.values()), default=0.0),
                }
        qa["years"][str(year)] = year_qa

    supplemental_slices = merge_supplemental_slices(manifest, legacy)
    manifest.sort(key=lambda item: (item["year"], item["scope"], item["contest_type"]))
    (OUTPUT / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8")
    (DATA / "wv_district_results.json").write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")

    contest_qas = [item for year in qa["years"].values() for item in year["contests"].values()]
    expected_districts = {"congressional": 2, "state_house": 100, "state_senate": 17}
    district_count_errors = []
    for year, year_node in qa["years"].items():
        for key, item in year_node["contests"].items():
            scope = next(scope for scope in expected_districts if key.startswith(scope + "_"))
            if item["districts"] != expected_districts[scope]:
                district_count_errors.append({
                    "year": int(year), "slice": key,
                    "expected": expected_districts[scope], "actual": item["districts"],
                })
    qa["summary"] = {
        "slice_files": len(manifest),
        "max_total_vote_error": max((abs(item["total_vote_error"]) for item in contest_qas), default=0.0),
        "max_candidate_vote_error": max((item["max_candidate_vote_error"] for item in contest_qas), default=0.0),
        "all_block_assignment_gaps": sum(
            sum(year["missing_block_assignments"].values()) for year in qa["years"].values()
        ),
        "district_count_errors": district_count_errors,
        "supplemental_slices": supplemental_slices,
    }
    qa["summary"]["validation_passed"] = (
        qa["summary"]["max_total_vote_error"] < 1e-5
        and qa["summary"]["max_candidate_vote_error"] < 1e-5
        and qa["summary"]["all_block_assignment_gaps"] == 0
        and not district_count_errors
    )
    (DATA / "district_aggregation_report.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa["summary"], indent=2))

    return 0 if qa["summary"]["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
