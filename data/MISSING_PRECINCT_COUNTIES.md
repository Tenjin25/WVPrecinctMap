# West Virginia precinct-result coverage

This audit covers the general-election CSV files consumed by `index.html`. A county
listed as missing has no precinct-level rows in the available source; it must not be
interpreted as having zero votes.

## Coverage

| Year | Counties present | Missing counties | Source |
|---|---:|---|---|
| 2008 | 52 of 55 | Brooke, Doddridge, Mineral | OpenElections files plus recovered county reports |
| 2010 | 44 of 55 | Brooke, Clay, Gilmer, Grant, Greenbrier, Hardy, Harrison, McDowell, Pleasants, Preston, Ritchie | OpenElections files plus recovered county reports |
| 2012 | 55 of 55 | None | Harvard Election Data Archive `WV_2012.tab` |
| 2016 | 55 of 55 | None | MIT MEDSL official precinct returns |

## Normalization applied

Known source-label errors were corrected while consolidating the files:

- `GLIMER` to `GILMER`
- `POCOHONTAS` to `POCAHONTAS`
- `MC DOWELL` to `MCDOWELL`

The apparent 2008 Gilmer gap was therefore a spelling error, not a missing county.

## Recovered county reports

The raw county-document archive in `data/openelections-sources-wv` supplied additional
precinct tables that had not yet been converted by OpenElections. The importer now
recreates normalized county CSVs under `data/supplemental_county_returns`.

- 2008: Hancock and Lincoln presidential results; Morgan presidential, U.S. Senate,
  and gubernatorial results.
- 2010 U.S. Senate: Calhoun, Hancock, Lincoln, Monroe, Pocahontas, Raleigh, Roane,
  Upshur, Wetzel, Wirt, and Wyoming.

Coverage is contest-specific. In 2008, President is present for 51 counties, U.S.
Senate and Governor for 50, and Attorney General for 47. The machine-readable report
lists the missing counties for each office.

Some scanned reports contain internal discrepancies. Contests remain excluded when
the discrepancy prevents a reliable precinct transcription. Upshur's Jeff Becker row
is retained because all 29 precinct cells are legible: they sum to 103 while the same
report prints a total of 106. The importer records this anomaly and does not invent
three balancing votes.

## Official archive check

The West Virginia Secretary of State download pages for the 2008 and 2010 general
elections expose `StateCountyTotals` in CSV, XML, and TXT formats. They do not expose
a precinct-results download for the missing counties. County totals cannot be safely
split among precincts, so this project leaves those counties explicitly missing.

- 2008: <https://apps.sos.wv.gov/elections/results/download.aspx?eid=4&year=2008>
- 2010: <https://apps.sos.wv.gov/elections/results/download.aspx?eid=6&year=2010>
- OpenElections WV: <https://github.com/openelections/openelections-data-wv>
- OpenElections WV source documents: <https://github.com/openelections/openelections-sources-wv>
- Harvard archive: <https://doi.org/10.7910/DVN/YN4TLR>
- MEDSL official returns: <https://github.com/MEDSL/official-precinct-returns>

The machine-readable version of this audit is `precinct_coverage_report.json`.
Regenerate the normalized CSVs and report with:

```powershell
python scripts/import_wv_precinct_supplements.py
```
