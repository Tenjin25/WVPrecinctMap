#!/usr/bin/env python3
"""Download and merge Census TIGER/Line 2008 West Virginia VTDs.

The 2008 Census archive stores VTD00 shapefiles in one ZIP per county. This
script downloads all 55 county archives, preserves them under data/tiger2008,
and builds the statewide GeoJSON consumed by index.html.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import shapefile


BASE_URL = "https://www2.census.gov/geo/tiger/TIGER2008/54_WEST_VIRGINIA/"
COUNTY_DIR_RE = re.compile(r'href="(54\d{3}_[^"/]+_County/)"', re.IGNORECASE)


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "WVPrecinctMap/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def discover_counties() -> list[tuple[str, str]]:
    listing = fetch_bytes(BASE_URL).decode("utf-8", errors="replace")
    directories = sorted(set(COUNTY_DIR_RE.findall(listing)))
    counties = [(directory[:5], directory) for directory in directories]
    if len(counties) != 55:
        raise RuntimeError(f"Expected 55 West Virginia county directories; found {len(counties)}")
    return counties


def download_archive(county_fips: str, directory: str, raw_dir: Path, force: bool) -> Path:
    filename = f"tl_2008_{county_fips}_vtd00.zip"
    destination = raw_dir / filename
    if destination.exists() and destination.stat().st_size > 0 and not force:
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is None:
                return destination

    payload = fetch_bytes(f"{BASE_URL}{directory}{filename}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        with zipfile.ZipFile(temporary) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Corrupt member {bad_member} in {filename}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def field_value(properties: dict[str, object], *names: str) -> str:
    for name in names:
        value = properties.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def county_display_name(directory: str) -> str:
    return directory.rstrip("/").split("_", 1)[1].removesuffix("_County").replace("_", " ")


def archive_features(archive_path: Path, county_fips: str, directory: str) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix=f"wv_vtd_{county_fips}_") as temp_name:
        temp_dir = Path(temp_name)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp_dir)
        shapefiles = list(temp_dir.glob("*.shp"))
        if len(shapefiles) != 1:
            raise RuntimeError(f"Expected one shapefile in {archive_path.name}; found {len(shapefiles)}")

        county_name = county_display_name(directory)
        features: list[dict[str, object]] = []
        with shapefile.Reader(str(shapefiles[0]), encoding="latin1") as reader:
            field_names = [field[0] for field in reader.fields[1:]]
            for shape_record in reader.iterShapeRecords():
                original = dict(zip(field_names, shape_record.record))
                precinct_id = field_value(original, "VTDST00", "VTDST", "VTD")
                precinct_name = field_value(original, "NAME00", "NAMELSAD00", "NAME")
                county_norm = county_name.upper()
                precinct_norm = f"{county_norm} - {precinct_id}" if precinct_id else county_norm
                properties = {
                    **original,
                    "STATEFP00": field_value(original, "STATEFP00", "STATEFP") or "54",
                    "COUNTYFP00": field_value(original, "COUNTYFP00", "COUNTYFP") or county_fips[-3:],
                    "county_nam": county_name,
                    "county_norm": county_norm,
                    "prec_id": precinct_id,
                    "precinct_name": f"{county_name} - {precinct_id}" if precinct_id else county_name,
                    "precinct_norm": precinct_norm,
                    "precinct_full_name": precinct_name,
                }
                features.append(
                    {
                        "type": "Feature",
                        "properties": properties,
                        "geometry": shape_record.shape.__geo_interface__,
                    }
                )
        return features


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redownload existing county archives")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/wv_vtd_2000.geojson"),
        help="statewide output GeoJSON path",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/tiger2008_vtd00"),
        help="directory in which county ZIP archives are retained",
    )
    args = parser.parse_args()

    counties = discover_counties()
    all_features: list[dict[str, object]] = []
    for index, (county_fips, directory) in enumerate(counties, start=1):
        archive = download_archive(county_fips, directory, args.raw_dir, args.force)
        features = archive_features(archive, county_fips, directory)
        all_features.extend(features)
        print(f"[{index:02d}/55] {county_display_name(directory)}: {len(features)} VTDs", flush=True)

    collection = {
        "type": "FeatureCollection",
        "name": "West Virginia 2008 TIGER VTD00",
        "source": BASE_URL,
        "features": all_features,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(collection, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporary, args.output)
    print(f"Wrote {len(all_features)} VTD features to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise
