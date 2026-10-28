# West Virginia Precinct Map

An interactive West Virginia election atlas with county, precinct, and
legislative/congressional district views. The project includes normalized
precinct returns, Census geography crosswalks, and reproducible aggregation
scripts.

## Election data

Normalized statewide precinct CSVs live in `data/openelections/wv_sos/`.
Complete 55-county coverage is currently available for the 2012, 2014, 2016, 2018,
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

Historical county maps for 2000–2012 are normalized from OpenElections and the
West Virginia Secretary of State before rebuilding the contest slices:

```powershell
python scripts/import_wv_historical_county_results.py
python scripts/build_wv_county_contests.py
```

District contest slices are generated separately from block-level election
estimates and Census block equivalency files:

```powershell
python scripts/aggregate_openelections_crosswalks.py
python scripts/build_wv_native_district_contests.py
python scripts/aggregate_wv_2022_precinct_geometry.py
python scripts/aggregate_wv_block_contests.py
```

The resulting JSON slices and manifest are written to
`data/district_contests/`. The production build prefers exact block or
district-native totals, then adds only validated historical precinct/VTD
crosswalk slices with at least 97% matched vote coverage.

## Sources

- West Virginia Secretary of State historical election results
- OpenElections West Virginia standardized election returns
- U.S. Census Bureau TIGER/Line geography
- NHGIS block crosswalks
- [WV GIS Technical Center 2022 voting-district/precinct boundaries](https://data.wvgis.wvu.edu/pub/Clearinghouse/boundaries/WV_Voting_Districts_Precincts/Archive/WV_Precinct_2022_103122_UTM83.zip)

Raw source repositories and downloaded ZIP archives are intentionally ignored
by Git. Normalized inputs, derived web assets, scripts, and validation reports
are versioned here.

Regenerate the county boundary file from the Census TIGER/Line archive with:

```powershell
python scripts/prepare_wv_counties.py
```

Generate West Virginia's enacted congressional, House of Delegates, and State
Senate boundary files with:

```powershell
python scripts/prepare_wv_district_geometries.py
```

Build the precinct centroid and display-name indexes used by the low-zoom and
search interfaces with:

```powershell
python scripts/prepare_wv_precinct_indexes.py
```
