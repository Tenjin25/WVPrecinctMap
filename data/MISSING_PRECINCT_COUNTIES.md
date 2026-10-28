# West Virginia precinct-result coverage

This audit covers the general-election CSV files consumed by `index.html`. A county
listed as missing has no precinct-level rows in the available source; it must not be
interpreted as having zero votes.

## Coverage

| Year | Counties present | Missing counties | Source |
|---|---:|---|---|
| 2008 | 55 of 55 | None overall; see contest-specific gaps below | OpenElections, recovered county reports, and DRA/Stanford-Harvard VTD fallback |
| 2010 | 45 of 55 | Brooke, Clay, Gilmer, Grant, Greenbrier, Hardy, Harrison, McDowell, Pleasants, Ritchie | OpenElections files plus recovered county reports |
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
- 2010 U.S. Senate: Calhoun, Hancock, Lincoln, Monroe, Pocahontas, Preston,
  Raleigh, Roane, Upshur, Wetzel, Wirt, and Wyoming.

Coverage is contest-specific. Before the VTD fallback described below, President
was present for 51 counties. It is now present for all 55; U.S. Senate and Governor
remain at 50, and Attorney General at 47. The machine-readable report lists the
missing counties for each office.

Some scanned reports contain internal discrepancies. Contests remain excluded when
the discrepancy prevents a reliable precinct transcription. Upshur's Jeff Becker row
is retained because all 29 precinct cells are legible: they sum to 103 while the same
report prints a total of 106. Preston is also retained from 34 legible precinct rows.
Those rows sum to 5,444 Raese and 4,093 Manchin, while both the report footer and the
certified county page say 5,466 and 4,071; the combined major-party total is identical.
Preston's Jesse Johnson cells sum to 256 while the footer says 257. The importer
preserves the printed precinct cells and does not invent balancing votes or choose a
precinct in which to shift the 22-vote allocation.

## 2008 presidential VTD fallback

The remaining 2008 presidential gaps (Barbour, Brooke, Doddridge, and Mineral)
are filled from Dave's Redistricting's statewide `2010_election_WV.csv`. That
file republishes the Stanford/Harvard election-atlas returns aggregated to 2010
Census VTDs. It contains Democratic, Republican, and total presidential votes;
minor-candidate votes are therefore retained as one `Other candidates` residual.
Existing OpenElections and county-document rows take precedence, so this source
is used only for counties with no presidential rows at all.

- DRA VTD data: <https://github.com/dra2020/vtd_data/tree/master/2010_VTD/WV>
- Stanford Election Atlas methodology: <https://sssl.stanford.edu/stanford-election-atlas>

Dave's Redistricting packages the data under CC BY-SA 4.0 with an additional
no-sale condition; downstream use must preserve those terms and attribution.

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
