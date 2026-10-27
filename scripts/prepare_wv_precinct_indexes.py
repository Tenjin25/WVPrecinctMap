#!/usr/bin/env python3
"""Build lightweight precinct centroids and display-name indexes."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from shapely.geometry import mapping, shape


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = DATA / "wv_vtd_2020.geojson"


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    centroids = []
    friendly: defaultdict[str, dict[str, str]] = defaultdict(dict)
    aliases: defaultdict[str, dict[str, list[str]]] = defaultdict(dict)

    for feature in source.get("features", []):
        props = feature.get("properties") or {}
        county = str(props.get("county_nam") or "").strip()
        code = str(props.get("prec_id") or props.get("VTDST20") or "").strip()
        full_name = str(
            props.get("precinct_full_name") or props.get("NAME20") or props.get("precinct_name") or code
        ).strip()
        if not county or not code or not feature.get("geometry"):
            continue
        county_key = county.upper()
        code_key = code.upper()
        friendly[county][code_key] = full_name
        aliases[county_key][code_key] = [code_key]
        if full_name:
            aliases[county_key][full_name.upper()] = [code_key]

        point = shape(feature["geometry"]).representative_point()
        centroid_props = {
            "county_nam": county,
            "county_norm": str(props.get("county_norm") or county_key),
            "prec_id": code,
            "precinct_name": str(props.get("precinct_name") or f"{county} - {code}"),
            "precinct_norm": str(props.get("precinct_norm") or f"{county_key} - {code_key}"),
            "precinct_full_name": full_name,
        }
        centroids.append(
            {"type": "Feature", "properties": centroid_props, "geometry": mapping(point)}
        )

    (DATA / "wv_vtd_2020_centroids.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": centroids}, separators=(",", ":")),
        encoding="utf-8",
    )
    (DATA / "precinct_friendly_names.json").write_text(
        json.dumps({"counties": dict(sorted(friendly.items()))}, indent=2) + "\n",
        encoding="utf-8",
    )
    (DATA / "precinct_alias_index.json").write_text(
        json.dumps({"counties": dict(sorted(aliases.items()))}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "centroids": len(centroids),
                "friendly_name_counties": len(friendly),
                "alias_counties": len(aliases),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
