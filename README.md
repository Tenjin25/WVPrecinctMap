# West Virginia Precinct Map

An interactive West Virginia election atlas with county, precinct, and
legislative/congressional district views. The project includes normalized
precinct returns, Census geography crosswalks, and reproducible aggregation
scripts.

## Election data

Normalized statewide precinct CSVs live in `data/openelections/wv_sos/`.
Complete 55-county coverage is currently available for the 2012, 2016, 2018,
2020, 2022, and 2024 general elections. The 2008 and 2010 files are retained as
partial datasets and their missing counties are documented in
`data/MISSING_PRECINCT_COUNTIES.md`.

Generate county totals for the complete years:

```powershell
python scripts/aggregate_wv_county_results.py
```

This writes OpenElections-compatible files to
`data/openelections/wv_sos/county/` and a validation report to
`data/county_aggregation_report.json`.

Build the county-map contest slices and manifest:

```powershell
python scripts/build_wv_county_contests.py
```

These files are written to `data/contests/`.

District contest slices are generated separately from block-level election
estimates and Census block equivalency files:

```powershell
python scripts/aggregate_wv_block_contests.py
```

The resulting JSON slices and manifest are written to
`data/district_contests/`.

## Sources

- West Virginia Secretary of State historical election results
- OpenElections West Virginia standardized election returns
- U.S. Census Bureau TIGER/Line geography
- NHGIS block crosswalks

Raw source repositories and downloaded ZIP archives are intentionally ignored
by Git. Normalized inputs, derived web assets, scripts, and validation reports
are versioned here.

Regenerate the county boundary file from the Census TIGER/Line archive with:

```powershell
python scripts/prepare_wv_counties.py
```
