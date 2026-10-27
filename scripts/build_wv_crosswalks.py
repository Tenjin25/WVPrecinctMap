#!/usr/bin/env python3
"""Build West Virginia precinct/district and precinct-vintage crosswalks.

Inputs are the Census block equivalency files (BEFs), TIGER/Line block and VTD
geometry, and NHGIS block-to-block crosswalks already stored under ``data/``.
The script deliberately keeps the raw downloads zipped and writes only compact,
reviewable CSV outputs plus a QA report.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import shapefile
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree


STATE_FIPS = "54"


@dataclass(frozen=True)
class VTD:
    geoid: str
    county_fips: str
    code: str
    name: str


@dataclass
class BlockInventory:
    vintage: int
    block_to_vtd: dict[str, str]
    block_area: dict[str, float]
    vtds: dict[str, VTD]
    total_features: int
    unmatched_features: int
    unmatched_by_county_fips: dict[str, int]
    nearest_same_county_fallbacks: int = 0
    duplicate_geoids: int = 0
    conflicting_duplicate_geoids: int = 0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zipped_shapefile_parts(path: Path):
    archive = zipfile.ZipFile(path)
    shp_name = next(name for name in archive.namelist() if name.lower().endswith(".shp"))
    stem = shp_name[:-4]
    reader = shapefile.Reader(
        shp=archive.open(stem + ".shp"),
        shx=archive.open(stem + ".shx"),
        dbf=archive.open(stem + ".dbf"),
    )
    return archive, reader


def load_vtd_index(data_dir: Path, vintage: int):
    geometries = []
    metadata: list[VTD] = []
    prepared_geojson = data_dir / ("wv_vtd_2000.geojson" if vintage == 2000 else "wv_vtd_2020.geojson")
    if vintage == 2000 or (vintage == 2020 and prepared_geojson.exists()):
        payload = json.loads(prepared_geojson.read_text(encoding="utf-8"))
        records = ((feature["properties"], shape(feature["geometry"])) for feature in payload["features"])
        archive = None
    else:
        suffix = "10" if vintage == 2010 else "20"
        zip_path = data_dir / f"tl_{2012 if vintage == 2010 else 2020}_54_vtd{suffix}.zip"
        archive, reader = zipped_shapefile_parts(zip_path)
        records = (
            (shape_record.record.as_dict(), shape(shape_record.shape.__geo_interface__))
            for shape_record in reader.iterShapeRecords()
        )

    suffix = str(vintage)[-2:]
    try:
        for props, geometry in records:
            geoid = str(props.get(f"GEOID{suffix}") or props.get(f"VTDIDFP{suffix}") or "").strip()
            county = str(props.get(f"COUNTYFP{suffix}") or props.get("COUNTYFP") or "").zfill(3)
            code = str(props.get(f"VTDST{suffix}") or props.get("prec_id") or "").strip()
            name = str(props.get(f"NAME{suffix}") or props.get("precinct_full_name") or code).strip()
            if not geoid or geometry.is_empty:
                continue
            geometries.append(geometry)
            metadata.append(VTD(geoid=geoid, county_fips=county, code=code, name=name))
    finally:
        if archive is not None:
            archive.close()

    return geometries, metadata, STRtree(geometries)


def match_point_to_vtd(point: Point, tree: STRtree, geometries, metadata: list[VTD]) -> str | None:
    hits = tree.query(point, predicate="within")
    if len(hits) == 1:
        return metadata[int(hits[0])].geoid
    if len(hits) > 1:
        # Appended county sources can contain tiny slivers of overlap. The
        # smaller polygon is the specific precinct; the larger is usually a
        # remnant or county-cover feature.
        selected = min((int(index) for index in hits), key=lambda index: (geometries[index].area, metadata[index].geoid))
        return metadata[selected].geoid
    # Numerical precision occasionally puts an internal point exactly on a VTD edge.
    hits = tree.query(point, predicate="intersects")
    if len(hits):
        return min(metadata[int(index)].geoid for index in hits)
    return None


def build_block_inventory(data_dir: Path, vintage: int) -> BlockInventory:
    vtd_geometries, vtd_meta, tree = load_vtd_index(data_dir, vintage)
    vtds = {item.geoid: item for item in vtd_meta}
    year_suffix = str(vintage)[-2:]
    tiger_year = {2000: 2008, 2010: 2012, 2020: 2020}[vintage]
    block_zip = data_dir / f"tl_{tiger_year}_54_tabblock{year_suffix if vintage else ''}.zip"
    if vintage == 2000:
        block_zip = data_dir / "tl_2008_54_tabblock00.zip"

    archive, reader = zipped_shapefile_parts(block_zip)
    projection = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
    pieces: dict[str, list[tuple[str, float]]] = defaultdict(list)
    total_features = 0
    unmatched = 0
    unmatched_by_county = Counter()
    nearest_fallbacks = 0
    vtd_indexes_by_county = defaultdict(list)
    for index, item in enumerate(vtd_meta):
        vtd_indexes_by_county[item.county_fips].append(index)
    try:
        for shape_record in reader.iterShapeRecords():
            total_features += 1
            props = shape_record.record.as_dict()
            shp = shape_record.shape
            if vintage == 2000:
                geoid = "".join(
                    str(props.get(field) or "")
                    for field in ("STATEFP00", "COUNTYFP00", "TRACTCE00", "BLOCKCE00")
                )
                geometry = shape(shp.__geo_interface__)
                point = geometry.representative_point()
                area = float(transform(projection, geometry).area)
            else:
                geoid = str(props.get("GEOID20" if vintage == 2020 else "GEOID") or "")
                point = Point(float(props["INTPTLON20" if vintage == 2020 else "INTPTLON"]),
                              float(props["INTPTLAT20" if vintage == 2020 else "INTPTLAT"]))
                land = float(props.get("ALAND20" if vintage == 2020 else "ALAND") or 0)
                water = float(props.get("AWATER20" if vintage == 2020 else "AWATER") or 0)
                area = land if land > 0 else water

            if not geoid.startswith(STATE_FIPS):
                continue
            vtd_geoid = match_point_to_vtd(point, tree, vtd_geometries, vtd_meta)
            if not vtd_geoid:
                county_field = "COUNTYFP20" if vintage == 2020 else ("COUNTYFP10" if vintage == 2010 else "COUNTYFP00")
                block_county = str(props.get(county_field) or props.get("COUNTYFP") or "").zfill(3)
                same_county = vtd_indexes_by_county.get(block_county, [])
                if same_county:
                    nearest_index = min(same_county, key=lambda index: point.distance(vtd_geometries[index]))
                    vtd_geoid = vtd_meta[nearest_index].geoid
                    nearest_fallbacks += 1
                else:
                    unmatched += 1
                    unmatched_by_county[block_county] += 1
                    continue
            pieces[geoid].append((vtd_geoid, max(area, 0.0)))
    finally:
        archive.close()

    block_to_vtd = {}
    block_area = {}
    duplicate_geoids = 0
    conflicting = 0
    for geoid, geoid_pieces in pieces.items():
        if len(geoid_pieces) > 1:
            duplicate_geoids += 1
        by_vtd = defaultdict(float)
        for vtd_geoid, area in geoid_pieces:
            by_vtd[vtd_geoid] += area
        if len(by_vtd) > 1:
            conflicting += 1
        selected_vtd = max(by_vtd.items(), key=lambda item: (item[1], item[0]))[0]
        block_to_vtd[geoid] = selected_vtd
        block_area[geoid] = sum(by_vtd.values())

    return BlockInventory(
        vintage=vintage,
        block_to_vtd=block_to_vtd,
        block_area=block_area,
        vtds=vtds,
        total_features=total_features,
        unmatched_features=unmatched,
        unmatched_by_county_fips=dict(sorted(unmatched_by_county.items())),
        nearest_same_county_fallbacks=nearest_fallbacks,
        duplicate_geoids=duplicate_geoids,
        conflicting_duplicate_geoids=conflicting,
    )


def read_bef(path: Path) -> tuple[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, skipinitialspace=True)
        if not reader.fieldnames or len(reader.fieldnames) < 2:
            raise ValueError(f"BEF has no assignment column: {path}")
        geoid_field, district_field = reader.fieldnames[:2]
        assignments = {
            str(row[geoid_field]).strip(): str(row[district_field]).strip()
            for row in reader
            if str(row.get(geoid_field) or "").strip()
        }
    return district_field.strip(), assignments


def write_district_crosswalk(path: Path, inventory: BlockInventory, bef_path: Path) -> dict:
    district_field, assignments = read_bef(bef_path)
    totals = defaultdict(float)
    block_counts = Counter()
    vtd_totals = defaultdict(float)
    missing_bef = 0
    for block, vtd_geoid in inventory.block_to_vtd.items():
        district = assignments.get(block)
        if not district:
            missing_bef += 1
            continue
        area = inventory.block_area.get(block, 0.0)
        if area <= 0:
            area = 1.0
        totals[(vtd_geoid, district)] += area
        block_counts[(vtd_geoid, district)] += 1
        vtd_totals[vtd_geoid] += area

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as target:
        fields = [
            "precinct_key", "vtd_geoid20", "county_fips", "vtd_code20", "vtd_name20",
            "district_num", "district_field", "area_weight", "block_count",
        ]
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for (vtd_geoid, district), area in sorted(totals.items()):
            vtd = inventory.vtds[vtd_geoid]
            writer.writerow({
                "precinct_key": vtd_geoid,
                "vtd_geoid20": vtd_geoid,
                "county_fips": vtd.county_fips,
                "vtd_code20": vtd.code,
                "vtd_name20": vtd.name,
                "district_num": district,
                "district_field": district_field,
                "area_weight": f"{area / vtd_totals[vtd_geoid]:.12f}",
                "block_count": block_counts[(vtd_geoid, district)],
            })

    sums = defaultdict(float)
    for (vtd_geoid, _district), area in totals.items():
        sums[vtd_geoid] += area / vtd_totals[vtd_geoid]
    return {
        "output": str(path),
        "rows": len(totals),
        "vtds": len(sums),
        "districts": len({district for _, district in totals}),
        "blocks_missing_bef_assignment": missing_bef,
        "max_weight_sum_error": max((abs(value - 1.0) for value in sums.values()), default=0.0),
    }


def nhgis_rows(path: Path):
    with zipfile.ZipFile(path) as archive:
        csv_name = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        import io
        with io.TextIOWrapper(archive.open(csv_name), encoding="utf-8-sig", newline="") as source:
            yield from csv.DictReader(source)


def build_vintage_weights(
    source: BlockInventory,
    target: BlockInventory,
    nhgis_path: Path,
) -> tuple[dict[tuple[str, str], float], dict]:
    src_key = f"blk{source.vintage}ge"
    dst_key = f"blk{target.vintage}ge"
    totals = defaultdict(float)
    source_totals = defaultdict(float)
    rows = used = 0
    skip_source = skip_target = skip_area = 0
    for row in nhgis_rows(nhgis_path):
        rows += 1
        source_block = str(row.get(src_key) or "").strip()
        target_block = str(row.get(dst_key) or "").strip()
        source_vtd = source.block_to_vtd.get(source_block)
        if not source_vtd:
            skip_source += 1
            continue
        target_vtd = target.block_to_vtd.get(target_block)
        if not target_vtd:
            skip_target += 1
            continue
        proportion = float(row.get("parea") or 0)
        area = source.block_area.get(source_block, 0.0) * proportion
        if not math.isfinite(area) or area <= 0:
            skip_area += 1
            continue
        totals[(source_vtd, target_vtd)] += area
        source_totals[source_vtd] += area
        used += 1

    weights = {
        pair: area / source_totals[pair[0]]
        for pair, area in totals.items()
        if source_totals[pair[0]] > 0
    }
    return weights, {
        "nhgis_rows": rows,
        "used_rows": used,
        "rows_without_source_wv_block": skip_source,
        "rows_without_target_wv_block": skip_target,
        "zero_area_rows": skip_area,
        "source_vtds": len(source_totals),
        "pairs": len(weights),
    }


def compose_weights(
    first: dict[tuple[str, str], float],
    second: dict[tuple[str, str], float],
) -> dict[tuple[str, str], float]:
    second_by_source = defaultdict(list)
    for (source, target), weight in second.items():
        second_by_source[source].append((target, weight))
    combined = defaultdict(float)
    for (source, middle), first_weight in first.items():
        for target, second_weight in second_by_source.get(middle, []):
            combined[(source, target)] += first_weight * second_weight
    totals = defaultdict(float)
    for (source, _), weight in combined.items():
        totals[source] += weight
    return {
        pair: weight / totals[pair[0]]
        for pair, weight in combined.items()
        if totals[pair[0]] > 0
    }


def write_vintage_crosswalk(
    path: Path,
    source: BlockInventory,
    target: BlockInventory,
    weights: dict[tuple[str, str], float],
    method: str,
) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "source_vintage", "source_vtd_geoid", "source_county_fips", "source_vtd_code", "source_vtd_name",
        "target_vintage", "target_vtd_geoid", "target_county_fips", "target_vtd_code", "target_vtd_name",
        "area_weight", "method",
    ]
    with path.open("w", encoding="utf-8", newline="") as target_file:
        writer = csv.DictWriter(target_file, fieldnames=fields)
        writer.writeheader()
        for (source_geoid, target_geoid), weight in sorted(weights.items()):
            source_vtd = source.vtds[source_geoid]
            target_vtd = target.vtds[target_geoid]
            writer.writerow({
                "source_vintage": source.vintage,
                "source_vtd_geoid": source_geoid,
                "source_county_fips": source_vtd.county_fips,
                "source_vtd_code": source_vtd.code,
                "source_vtd_name": source_vtd.name,
                "target_vintage": target.vintage,
                "target_vtd_geoid": target_geoid,
                "target_county_fips": target_vtd.county_fips,
                "target_vtd_code": target_vtd.code,
                "target_vtd_name": target_vtd.name,
                "area_weight": f"{weight:.12f}",
                "method": method,
            })
    sums = defaultdict(float)
    for (source_geoid, _), weight in weights.items():
        sums[source_geoid] += weight
    return {
        "output": str(path),
        "rows": len(weights),
        "source_vtds": len(sums),
        "target_vtds": len({target for _, target in weights}),
        "max_weight_sum_error": max((abs(value - 1.0) for value in sums.values()), default=0.0),
    }


def inventory_report(inventory: BlockInventory) -> dict:
    return {
        "vintage": inventory.vintage,
        "vtds": len(inventory.vtds),
        "block_features": inventory.total_features,
        "matched_block_geoids": len(inventory.block_to_vtd),
        "unmatched_block_features": inventory.unmatched_features,
        "unmatched_blocks_by_county_fips": inventory.unmatched_by_county_fips,
        "nearest_same_county_block_fallbacks": inventory.nearest_same_county_fallbacks,
        "duplicate_block_geoids": inventory.duplicate_geoids,
        "conflicting_duplicate_block_geoids": inventory.conflicting_duplicate_geoids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--district-only", action="store_true", help="Build only 2020 VTD-to-district BEF outputs")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    bef_out = data_dir / "crosswalks_bef"
    nhgis_out = data_dir / "crosswalks_nhgis"

    print("Building 2020 block-to-VTD inventory...", flush=True)
    inv20 = build_block_inventory(data_dir, 2020)
    report = {"inventories": {"2020": inventory_report(inv20)}, "district_crosswalks": {}, "vintage_crosswalks": {}}

    bef_specs = [
        ("54_WV_CD118.txt", "precinct_to_congressional_2022_enacted.csv"),
        ("54_WV_SLDL22.txt", "precinct_to_state_house_2022.csv"),
        ("54_WV_SLDU22.txt", "precinct_to_state_senate_2022.csv"),
    ]
    for input_name, output_name in bef_specs:
        print(f"Building {output_name}...", flush=True)
        report["district_crosswalks"][output_name] = write_district_crosswalk(
            bef_out / output_name, inv20, data_dir / input_name
        )

    if not args.district_only:
        print("Building 2010 block-to-VTD inventory...", flush=True)
        inv10 = build_block_inventory(data_dir, 2010)
        print("Building 2000 block-to-VTD inventory...", flush=True)
        inv00 = build_block_inventory(data_dir, 2000)
        report["inventories"]["2010"] = inventory_report(inv10)
        report["inventories"]["2000"] = inventory_report(inv00)

        print("Aggregating NHGIS 2000-to-2010 block relationships...", flush=True)
        weights_00_10, qa_00_10 = build_vintage_weights(inv00, inv10, data_dir / "nhgis_blk2000_blk2010_54.zip")
        print("Aggregating NHGIS 2010-to-2020 block relationships...", flush=True)
        weights_10_20, qa_10_20 = build_vintage_weights(inv10, inv20, data_dir / "nhgis_blk2010_blk2020_54.zip")
        weights_00_20 = compose_weights(weights_00_10, weights_10_20)

        outputs = [
            ("vtd2000_to_vtd2010.csv", inv00, inv10, weights_00_10, "nhgis_block_area_2000_to_2010", qa_00_10),
            ("vtd2010_to_vtd2020.csv", inv10, inv20, weights_10_20, "nhgis_block_area_2010_to_2020", qa_10_20),
            ("vtd2000_to_vtd2020.csv", inv00, inv20, weights_00_20, "composed_vtd_2000_to_2010_to_2020", {}),
        ]
        for output_name, source, target, weights, method, qa in outputs:
            output_report = write_vintage_crosswalk(nhgis_out / output_name, source, target, weights, method)
            output_report.update(qa)
            report["vintage_crosswalks"][output_name] = output_report

    input_names = [name for name, _ in bef_specs]
    if not args.district_only:
        input_names += ["nhgis_blk2000_blk2010_54.zip", "nhgis_blk2010_blk2020_54.zip"]
    report["input_sha256"] = {name: sha256(data_dir / name) for name in input_names}
    report_path = data_dir / "crosswalk_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote QA report: {report_path}")

    errors = []
    for group in ("district_crosswalks", "vintage_crosswalks"):
        for name, item in report[group].items():
            if item.get("max_weight_sum_error", 0) > 1e-9:
                errors.append(f"{name}: weights do not sum to 1")
    if inv20.unmatched_features:
        errors.append(f"2020: {inv20.unmatched_features} blocks did not match a VTD")
    if errors:
        print("QA warnings:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
