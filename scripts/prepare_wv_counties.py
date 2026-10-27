#!/usr/bin/env python3
"""Create the county boundary GeoJSON consumed by the web atlas."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import shapefile


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = DATA / "tl_2020_54_county20.zip"
OUTPUT = DATA / "wv_counties.geojson"


def main() -> None:
    features = []
    with zipfile.ZipFile(SOURCE) as archive:
        stem = "tl_2020_54_county20"
        reader = shapefile.Reader(
            shp=archive.open(f"{stem}.shp"),
            shx=archive.open(f"{stem}.shx"),
            dbf=archive.open(f"{stem}.dbf"),
        )
        for item in reader.iterShapeRecords():
            raw = item.record.as_dict()
            name = str(raw.get("NAME20") or "").strip()
            county_fips = str(raw.get("COUNTYFP20") or "").strip()
            properties = {
                "STATEFP20": str(raw.get("STATEFP20") or "54"),
                "COUNTYFP20": county_fips,
                "GEOID20": str(raw.get("GEOID20") or f"54{county_fips}"),
                "NAME20": name,
                "NAMELSAD20": str(raw.get("NAMELSAD20") or f"{name} County"),
                "county_nam": name,
            }
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": item.shape.__geo_interface__,
                }
            )

    county_fips = {feature["properties"]["COUNTYFP20"] for feature in features}
    if len(features) != 55 or len(county_fips) != 55:
        raise ValueError(
            f"Expected 55 West Virginia counties, found {len(features)} features / "
            f"{len(county_fips)} unique county FIPS codes"
        )

    collection = {"type": "FeatureCollection", "features": features}
    OUTPUT.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(features)} counties")


if __name__ == "__main__":
    main()
