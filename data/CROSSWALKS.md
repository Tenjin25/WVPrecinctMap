# Crosswalk generation

Run the generator from the project root:

```powershell
python scripts/prepare_wv_precinct_geometries.py
python scripts/build_wv_crosswalks.py
python scripts/aggregate_wv_block_contests.py
python scripts/aggregate_openelections_crosswalks.py
```

The geometry preparation step uses the West Virginia GIS Technical Center's
archived 2020 precinct service export and its statewide 2024 precinct shapefile.
The archived 2020 service is a composite: Census 2020 VTDs where available,
Census 2010 VTD fallback geometry, and county-supplied precincts. The script
restores missing fallback labels from the Census 2010 VTD layer, dissolves
duplicate precinct parts, and removes two county-cover placeholders plus one
microscopic topology sliver. `precinct_geometry_report.json` audits those changes.

The script creates two groups of derived files:

- `crosswalks_bef/`: 2020 Census VTD-to-congressional, state House, and state Senate area weights based on the official block equivalency files.
- `crosswalks_nhgis/`: 2000-to-2010, 2010-to-2020, and composed 2000-to-2020 VTD area weights based on NHGIS block crosswalks.

`crosswalk_report.json` records input hashes, row counts, coverage, and the maximum error in each source VTD's weight sum. Raw ZIP and BEF inputs remain unchanged.

## Weight interpretation

Each output is source-normalized: the `area_weight` rows for a source VTD sum to 1. District weights use 2020 Census block land area (water area only for water-only blocks). Vintage weights multiply each NHGIS `parea` value by the source block's area before aggregating, preventing small blocks from being weighted the same as large blocks.

For the archived statewide 2020 composite, 22 block internal points fall in tiny
source edge gaps. They are assigned to the nearest precinct within the same
county and counted in `crosswalk_report.json`; no block is assigned across a
county boundary.

The composed 2000-to-2020 file multiplies VTD-level 2000-to-2010 and 2010-to-2020 weights. Use the direct vintage files when an intermediate 2010 allocation is useful for auditing.

The contest aggregation step joins the RDH 2016, 2018, 2020, and 2024
block-level vote estimates directly to the official BEFs. It writes pretty-
printed nested slices under `district_contests/`, a combined
`wv_district_results.json`, and conservation checks in
`district_aggregation_report.json`.

Both contest aggregators write vote counts as JSON integers. Fractional
crosswalk allocations are converted with deterministic largest-remainder
rounding, applied separately to each candidate across districts, so the
rounded candidate and contest totals are preserved exactly. Margins and
coverage percentages remain decimal values. The OpenElections test slices are
written under `district_contests_openelections/`, with match and conservation
checks in `openelections_crosswalk_report.json`.
