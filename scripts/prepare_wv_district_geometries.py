#!/usr/bin/env python3
"""Create enacted WV congressional and legislative district GeoJSON files."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import shapefile


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LAYERS = {
    "tl_2022_54_cd118.zip": ("wv_congress_enacted.geojson", "CD118FP", 2),
    "tl_2022_54_sldl.zip": ("wv_state_house_enacted.geojson", "SLDLST", 100),
    "tl_2022_54_sldu.zip": ("wv_state_senate_enacted.geojson", "SLDUST", 17),
}


def convert(source_name: str, output_name: str, district_field: str, expected: int) -> dict:
    source = DATA / source_name
    stem = source.stem
    features = []
    with zipfile.ZipFile(source) as archive:
        reader = shapefile.Reader(
            shp=archive.open(f"{stem}.shp"),
            shx=archive.open(f"{stem}.shx"),
            dbf=archive.open(f"{stem}.dbf"),
        )
        for item in reader.iterShapeRecords():
            properties = {
                key: value
                for key, value in item.record.as_dict().items()
                if value is not None
            }
            district = str(properties.get(district_field) or "").strip()
            properties["district"] = district
            properties["DISTRICT"] = district
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": item.shape.__geo_interface__,
                }
            )

    districts = {feature["properties"]["district"] for feature in features}
    if len(features) != expected or len(districts) != expected:
        raise ValueError(
            f"{source_name}: expected {expected} districts, found "
            f"{len(features)} features / {len(districts)} district codes"
        )
    output = DATA / output_name
    output.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
        encoding="utf-8",
    )
    return {"source": source_name, "output": output_name, "districts": len(districts)}


def main() -> None:
    results = [
        convert(source, output, district_field, expected)
        for source, (output, district_field, expected) in LAYERS.items()
    ]
    print(json.dumps({"layers": results}, indent=2))


if __name__ == "__main__":
    main()
