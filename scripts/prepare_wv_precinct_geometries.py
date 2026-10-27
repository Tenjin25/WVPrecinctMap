#!/usr/bin/env python3
"""Prepare statewide WV precinct GeoJSON from official WVGISTC sources.

The 2024 shapefile is a clean statewide county/SOS product.  The archived 2020
ArcGIS layer is a composite of Census 2020 VTDs, Census 2010 fallback VTDs, and
county-supplied geometry.  This script restores missing county/name attributes
on that composite and removes county-cover placeholder polygons that overlap a
complete set of real precinct polygons.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 .-]", "", str(value or ""))).strip().upper()


def dissolve_duplicate_precincts(features: list[dict]):
    grouped = defaultdict(list)
    for feature in features:
        grouped[feature["properties"]["precinct_norm"]].append(feature)
    output = []
    merged = 0
    for group in grouped.values():
        first = group[0]
        if len(group) == 1:
            output.append(first)
            continue
        geometry = unary_union([shape(feature["geometry"]) for feature in group])
        first["geometry"] = mapping(geometry)
        first["properties"]["merged_source_objectids"] = [
            feature["properties"].get("source_objectid") for feature in group
        ]
        output.append(first)
        merged += len(group) - 1
    return output, merged


def open_zipped_shapefile(path: Path):
    archive = zipfile.ZipFile(path)
    shp_name = next(name for name in archive.namelist() if name.lower().endswith(".shp"))
    stem = shp_name[:-4]
    reader = shapefile.Reader(
        shp=archive.open(stem + ".shp"),
        shx=archive.open(stem + ".shx"),
        dbf=archive.open(stem + ".dbf"),
    )
    return archive, reader, stem


def load_counties(data_dir: Path):
    archive, reader, _ = open_zipped_shapefile(data_dir / "tl_2020_54_county20.zip")
    rows = []
    try:
        for item in reader.iterShapeRecords():
            props = item.record.as_dict()
            rows.append((shape(item.shape.__geo_interface__), str(props["COUNTYFP20"]), str(props["NAME20"])))
    finally:
        archive.close()
    geometries = [item[0] for item in rows]
    return rows, STRtree(geometries)


def load_vtd10(data_dir: Path):
    archive, reader, _ = open_zipped_shapefile(data_dir / "tl_2012_54_vtd10.zip")
    by_county = defaultdict(list)
    try:
        for item in reader.iterShapeRecords():
            props = item.record.as_dict()
            by_county[str(props["COUNTYFP10"])].append((
                shape(item.shape.__geo_interface__),
                str(props["VTDST10"]),
                str(props["NAME10"]),
                str(props["GEOID10"]),
            ))
    finally:
        archive.close()
    return by_county


def infer_county(geometry, county_rows, county_tree):
    point = geometry.representative_point()
    hits = county_tree.query(point, predicate="within")
    if len(hits):
        return county_rows[int(hits[0])][1], county_rows[int(hits[0])][2]
    # A boundary precision issue should not discard a precinct.
    nearest = county_tree.nearest(point)
    return county_rows[int(nearest)][1], county_rows[int(nearest)][2]


def is_county_cover_placeholder(index: int, records: list[dict], county_group: list[int], county_geometry) -> bool:
    if len(county_group) < 3:
        return False
    geometry = records[index]["geometry"]
    county_share = geometry.intersection(county_geometry).area / max(county_geometry.area, 1e-30)
    if county_share < 0.97:
        return False
    others = [records[i]["geometry"] for i in county_group if i != index]
    others_share = unary_union(others).intersection(county_geometry).area / max(county_geometry.area, 1e-30)
    return others_share >= 0.90


def best_vtd10_match(geometry, candidates):
    best = None
    best_area = -1.0
    for candidate_geometry, code, name, geoid in candidates:
        if not geometry.intersects(candidate_geometry):
            continue
        overlap = geometry.intersection(candidate_geometry).area
        if overlap > best_area:
            best_area = overlap
            best = (code, name, geoid)
    return best


def prepare_2020(data_dir: Path) -> dict:
    raw_path = data_dir / "wv_vtd_2020_complete.geojson"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    county_rows, county_tree = load_counties(data_dir)
    county_by_fips = {fips: (geometry, name) for geometry, fips, name in county_rows}
    vtd10_by_county = load_vtd10(data_dir)

    records = []
    county_groups = defaultdict(list)
    for feature in payload.get("features", []):
        geometry = shape(feature["geometry"])
        if not geometry.is_valid:
            geometry = make_valid(geometry)
        county_fips, county_name = infer_county(geometry, county_rows, county_tree)
        index = len(records)
        records.append({
            "geometry": geometry,
            "raw": feature.get("properties") or {},
            "county_fips": county_fips,
            "county_name": county_name,
        })
        county_groups[county_fips].append(index)

    drop = set()
    for county_fips, indexes in county_groups.items():
        county_geometry = county_by_fips[county_fips][0]
        for index in indexes:
            if is_county_cover_placeholder(index, records, indexes, county_geometry):
                drop.add(index)

    features = []
    match_methods = Counter()
    key_counts = Counter()
    for index, record in enumerate(records):
        if index in drop:
            match_methods["dropped_county_cover_placeholder"] += 1
            continue
        # The service contains one microscopic Marion polygon (~9e-10 square
        # degrees, only a few square metres) with no 2020 block interior point.
        # It is a topology sliver, not a usable voting precinct.
        if record["geometry"].area < 1e-8:
            match_methods["dropped_topology_sliver"] += 1
            continue
        raw = record["raw"]
        county_fips = record["county_fips"]
        county_name = record["county_name"]
        code = str(raw.get("VTDST20") or "").strip()
        display_name = str(raw.get("NAME20") or "").strip()
        geoid = str(raw.get("GEOID20") or "").strip()
        if code:
            match_methods["original_2020_attributes"] += 1
        elif display_name:
            code = display_name
            match_methods["county_supplied_name"] += 1
        else:
            matched = best_vtd10_match(record["geometry"], vtd10_by_county.get(county_fips, []))
            if matched:
                code, display_name, geoid10 = matched
                # A few appended service rows retain a stale GEOID while their
                # code/name fields are blank; the spatially matched VTD10 GEOID
                # is the internally consistent identifier for those records.
                geoid = geoid10
                match_methods["restored_from_2010_vtd"] += 1
            else:
                code = f"UNRESOLVED-{raw.get('OBJECTID', index + 1)}"
                display_name = code
                match_methods["unresolved"] += 1

        code = str(code).strip()
        display_name = display_name or code
        base_key = f"{county_name} - {code}"
        key_counts[norm(base_key)] += 1
        precinct_name = base_key
        source_label = raw.get("Source") or "county_supplied"
        stable_geoid = geoid if source_label == "VTD20" else f"WV2020-{county_fips}-{code}"
        props = {
            "STATEFP20": "54",
            "COUNTYFP20": county_fips,
            "VTDST20": code,
            "GEOID20": stable_geoid,
            "NAME20": display_name,
            "county_nam": county_name,
            "county_norm": norm(county_name),
            "prec_id": code,
            "precinct_name": precinct_name,
            "precinct_norm": norm(precinct_name),
            "precinct_full_name": display_name,
            "source": source_label,
            "source_objectid": raw.get("OBJECTID"),
        }
        features.append({"type": "Feature", "properties": props, "geometry": mapping(record["geometry"])})

    features, merged_duplicates = dissolve_duplicate_precincts(features)
    output = {"type": "FeatureCollection", "features": features}
    (data_dir / "wv_vtd_2020.geojson").write_text(
        json.dumps(output, separators=(",", ":")), encoding="utf-8"
    )
    return {
        "input_features": len(records),
        "output_features": len(features),
        "counties": len({feature["properties"]["COUNTYFP20"] for feature in features}),
        "methods": dict(match_methods),
        "duplicate_precinct_parts_merged": merged_duplicates,
    }


def prepare_2024(data_dir: Path) -> dict:
    source_path = data_dir / "WV_Precinct_2024_20240213_UTM83.zip"
    archive, reader, stem = open_zipped_shapefile(source_path)
    prj = archive.read(stem + ".prj").decode("utf-8", errors="replace")
    transformer = Transformer.from_crs(CRS.from_wkt(prj), "EPSG:4326", always_xy=True).transform
    features = []
    try:
        for item in reader.iterShapeRecords():
            raw = item.record.as_dict()
            geometry = transform(transformer, shape(item.shape.__geo_interface__))
            if not geometry.is_valid:
                geometry = make_valid(geometry)
            county_name = str(raw.get("County_Nam") or "").strip()
            county_fips = str(raw.get("StCoFIPS") or "")[-3:]
            code = str(raw.get("SHORTNAME") or raw.get("SRVS_Pre_N") or "").strip()
            precinct_name = f"{county_name} - {code}"
            props = {
                "COUNTYFP20": county_fips,
                "county_nam": county_name,
                "county_norm": norm(county_name),
                "prec_id": code,
                "precinct_name": precinct_name,
                "precinct_norm": norm(precinct_name),
                "precinct_full_name": str(raw.get("LONGNAME") or code).strip(),
                "precinct_id": str(raw.get("Precinct_I") or precinct_name).strip(),
                "alpha_split": str(raw.get("AlphaSplit") or "").strip(),
                "source_objectid": raw.get("OBJECTID"),
            }
            features.append({"type": "Feature", "properties": props, "geometry": mapping(geometry)})
    finally:
        archive.close()

    features, merged_duplicates = dissolve_duplicate_precincts(features)
    output = {"type": "FeatureCollection", "features": features}
    (data_dir / "wv_precincts_2024.geojson").write_text(
        json.dumps(output, separators=(",", ":")), encoding="utf-8"
    )
    return {
        "output_features": len(features),
        "counties": len({feature["properties"]["county_norm"] for feature in features}),
        "duplicate_precinct_parts_merged": merged_duplicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    report = {
        "archived_2020": prepare_2020(data_dir),
        "current_2024": prepare_2024(data_dir),
    }
    report_path = data_dir / "precinct_geometry_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
