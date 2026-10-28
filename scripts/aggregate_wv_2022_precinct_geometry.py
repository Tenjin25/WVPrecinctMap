#!/usr/bin/env python3
"""Aggregate 2022 precinct returns with WV's official 2022 precinct shapes."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import shapefile
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform
from shapely.strtree import STRtree

from build_wv_native_district_contests import candidate_name, make_node, party_type


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = DATA / "openelections" / "wv_sos" / "20221108__wv__general__precinct.csv"
PRECINCTS = DATA / "WV_Precinct_2022_103122_UTM83.zip"
OUTPUT = DATA / "district_contests_precinct_geometry"
DISTRICTS = {
    "state_house": DATA / "wv_state_house_enacted.geojson",
    "state_senate": DATA / "wv_state_senate_enacted.geojson",
}


def token(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper())).strip()


def precinct_token(value: str) -> str:
    value = token(value)
    value = re.sub(r"\b(?:VOTING|ELECTION)\b", " ", value)
    value = re.sub(r"\b(?:PRECINCT|PCT|NO|NUMBER)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    match = re.fullmatch(r"0*(\d+)\s*([A-Z]+)?", value)
    return f"{int(match.group(1))}{match.group(2) or ''}" if match else value


def base_precinct_token(value: str) -> str | None:
    match = re.match(r"^0*(\d+)", precinct_token(value))
    return str(int(match.group(1))) if match else None


def load_precinct_shapes():
    aliases = defaultdict(set)
    base_aliases = defaultdict(set)
    geometries = []
    archive = zipfile.ZipFile(PRECINCTS)
    try:
        shp = next(name for name in archive.namelist() if name.lower().endswith(".shp"))
        shx = next(name for name in archive.namelist() if name.lower().endswith(".shx"))
        dbf = next(name for name in archive.namelist() if name.lower().endswith(".dbf"))
        reader = shapefile.Reader(shp=archive.open(shp), shx=archive.open(shx), dbf=archive.open(dbf))
        for item in reader.iterShapeRecords():
            geometry = shape(item.shape.__geo_interface__)
            if geometry.is_empty:
                continue
            index = len(geometries)
            geometries.append(geometry)
            county = token(item.record["County_Nam"])
            raw_aliases = {
                str(item.record["SHORTNAME"] or ""),
                str(item.record["SRVS_Pre_N"] or ""),
                str(item.record["Precinct_I"] or "").split("_", 1)[-1],
            }
            for raw in raw_aliases:
                normalized = precinct_token(raw)
                if normalized:
                    aliases[(county, normalized)].add(index)
                base = base_precinct_token(raw)
                if base:
                    base_aliases[(county, base)].add(index)
    finally:
        archive.close()
    return geometries, aliases, base_aliases


def load_district_weights(precinct_geometries):
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:26917", always_xy=True).transform
    output = {}
    for scope, path in DISTRICTS.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        district_ids = []
        district_geometries = []
        for feature in payload["features"]:
            district_ids.append(str(int(feature["properties"]["district"])))
            district_geometries.append(transform(to_utm, shape(feature["geometry"])))
        tree = STRtree(district_geometries)
        precinct_weights = {}
        for index, precinct_geometry in enumerate(precinct_geometries):
            overlaps = defaultdict(float)
            for district_index in tree.query(precinct_geometry):
                area = precinct_geometry.intersection(district_geometries[district_index]).area
                if area > 0:
                    overlaps[district_ids[district_index]] += area
            if overlaps:
                # Preserve raw overlap area here. When an election result maps
                # to several official polygon pieces, the final allocation is
                # then weighted by their combined area rather than giving each
                # piece equal influence.
                precinct_weights[index] = list(overlaps.items())
        output[scope] = precinct_weights
    return output


def apportion(districts):
    parties = {party for row in districts.values() for party in row}
    for party in parties:
        candidates = {candidate for row in districts.values() for candidate in row.get(party, {})}
        for candidate in candidates:
            raw = {district: districts[district][party].get(candidate, 0.0) for district in districts}
            target = round(sum(raw.values()))
            allocated = {district: int(value) for district, value in raw.items()}
            remaining = target - sum(allocated.values())
            ranked = sorted(raw, key=lambda district: (-(raw[district] - allocated[district]), int(district)))
            for district in ranked[:remaining]:
                allocated[district] += 1
            for district, votes in allocated.items():
                districts[district][party][candidate] = votes


def main() -> int:
    if not PRECINCTS.exists():
        raise SystemExit(f"Missing official WV precinct archive: {PRECINCTS}")
    precinct_geometries, aliases, base_aliases = load_precinct_shapes()
    district_weights = load_district_weights(precinct_geometries)
    rows = list(csv.DictReader(RESULTS.open(encoding="utf-8-sig", newline="")))
    aggregates = {scope: defaultdict(lambda: defaultdict(lambda: defaultdict(float))) for scope in DISTRICTS}
    source_total = 0
    matched_total = 0
    match_methods = Counter()
    unmatched = Counter()

    for row in rows:
        if token(row.get("office")) not in {"U S HOUSE", "US HOUSE"}:
            continue
        votes = int(float(row.get("votes") or 0))
        source_total += votes
        county = token(row.get("county"))
        precinct = precinct_token(row.get("precinct"))
        shape_ids = aliases.get((county, precinct), set())
        method = "official_precinct_exact"
        if not shape_ids:
            shape_ids = base_aliases.get((county, base_precinct_token(precinct)), set())
            method = "official_precinct_base_fallback"
        if not shape_ids:
            unmatched[f"{row.get('county')}|{row.get('precinct')}"] += votes
            continue
        matched_total += votes
        match_methods[method] += 1
        party = party_type(row.get("party"))
        candidate = candidate_name(row.get("candidate"))
        for scope in DISTRICTS:
            totals = defaultdict(float)
            for shape_id in shape_ids:
                for district, weight in district_weights[scope].get(shape_id, []):
                    totals[district] += weight
            denominator = sum(totals.values())
            if denominator:
                for district, weight in totals.items():
                    aggregates[scope][district][party][candidate] += votes * weight / denominator

    coverage = matched_total / source_total * 100.0 if source_total else 0.0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    contests = {}
    for scope, districts in aggregates.items():
        apportion(districts)
        node = make_node(scope, "us_house", 2022, districts)
        node["meta"].update({
            "method": "official_2022_precinct_geometry_area_weighted_to_enacted_districts",
            "match_coverage_pct": round(coverage, 6),
            "source": "WV precinct returns and WV GIS Technical Center 2022 precinct boundaries",
            "source_url": "https://data.wvgis.wvu.edu/pub/Clearinghouse/boundaries/WV_Voting_Districts_Precincts/Archive/WV_Precinct_2022_103122_UTM83.zip",
        })
        filename = f"{scope}_us_house_2022.json"
        (OUTPUT / filename).write_text(json.dumps(node, indent=2) + "\n", encoding="utf-8")
        manifest.append({"scope": scope, "contest_type": "us_house", "year": 2022, "file": filename})
        contests[f"{scope}_us_house"] = {
            "districts": len(districts),
            "output_total_votes": sum(item["total_votes"] for item in node["general"]["results"].values()),
        }
    (OUTPUT / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8")
    report = {
        "source_total_votes": source_total,
        "matched_total_votes": matched_total,
        "match_coverage_pct": round(coverage, 6),
        "match_methods_by_rows": dict(match_methods),
        "unmatched_precincts": [{"precinct": key, "votes": votes} for key, votes in unmatched.most_common()],
        "contests": contests,
        "validation_passed": coverage >= 99.0 and all(item["output_total_votes"] == matched_total for item in contests.values()),
    }
    (DATA / "precinct_geometry_aggregation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
