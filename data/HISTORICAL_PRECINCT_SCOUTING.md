# Historical precinct source scouting

Last checked: 2026-10-28

## Recovered and integrated

### 2008 President: Dave's Redistricting / Stanford-Harvard atlas

- Source: <https://github.com/dra2020/vtd_data/tree/master/2010_VTD/WV>
- Upstream lineage: <https://sssl.stanford.edu/stanford-election-atlas>
- Raw file: `2010_election_WV.csv`
- Contents: 1,856 West Virginia 2010-VTD rows, with Democratic,
  Republican, and total 2008 presidential votes.
- Statewide audit: 713,325 total; 303,845 Democratic; 397,444 Republican.
- Integrated only where no presidential precinct rows previously existed:
  Barbour (21 VTDs), Brooke (30), Doddridge (12), and Mineral (35).
- Result: 2008 President now has all 55 counties. Minor-candidate votes are
  retained as an `Other candidates` residual because the source does not split
  them by candidate.
- Terms: CC BY-SA 4.0 plus Dave's Redistricting's no-sale condition.

The reproducible importer is `scripts/import_wv_precinct_supplements.py`.

### 2010 U.S. Senate: Preston County election book

- Source document: `data/openelections-sources-wv/2010/Preston WV 2010.11 General.pdf`
- Contest identity: this was the special election for Robert C. Byrd's
  unexpired term. The special primary was held August 28, 2010, while the
  four-candidate general contest was included on the November 2, 2010 ballot.
  Official and archival searches may label it `U.S. Senate - Unexpired Term`,
  `special senatorial election`, or contest code `BU`, rather than simply the
  regular 2010 U.S. Senate election.
- Contents: 34 precinct rows for the four U.S. Senate candidates.
- Integrated result: 2010 overall coverage rises from 44 to 45 counties, leaving
  10 counties with no precinct rows.
- Source anomaly: the precinct cells sum to 5,444 Raese and 4,093 Manchin, while
  the report footer and certified county page report 5,466 and 4,071. The combined
  major-party total is unchanged. Jesse Johnson's cells sum to 256 while the footer
  says 257. The importer retains the cells as printed and does not force the footer.

## Sources checked but not sufficient

### West Virginia Secretary of State legacy results application

- 2008: <https://apps.sos.wv.gov/elections/results/download.aspx?eid=4&year=2008>
- 2010: <https://apps.sos.wv.gov/elections/results/download.aspx?eid=6&year=2010>

The download endpoint exposes `StateCountyTotals` in CSV, XML, and text. On a
missing county's results page (for example, 2010 Brooke), the application reports
`Number of Precincts: None/Not available`; the database is serving county totals,
not hidden precinct rows.

### Harvard Election Data Archive

The public Dataverse dataset at <https://doi.org/10.7910/DVN/YN4TLR> contains
`WV_2012.tab` but no West Virginia 2008 or 2010 tabular file. The independent
DRA/Stanford file above is therefore the usable 2008 recovery.

### DRA mirror and MIT Election Data + Science Lab

The complete `dra2020/vtd_data` mirror was searched beyond the recovered 2008
file. Its West Virginia 2010-VTD file contains only 2008 presidential columns;
the later West Virginia ZIP versions contain presidential and other election
columns from 2008 onward but no 2010 special U.S. Senate contest.

MIT Election Data + Science Lab's public precinct-return collection begins its
nationwide standardized series with 2016. Searches for a separate 2010 West
Virginia precinct file, including `special election`, `unexpired term`, and the
Manchin-Raese candidate names, did not surface one:
<https://electionlab.mit.edu/data>.

### OpenElections

- Data: <https://github.com/openelections/openelections-data-wv>
- Source documents: <https://github.com/openelections/openelections-sources-wv>

Both local mirrors were audited. The previously unconverted Preston general-election
book has now been transcribed for U.S. Senate. Two other 2010 general-election PDFs
were inspected but cannot fill the outstanding contest gaps:

- Ohio's nine pages begin after the federal contests; they contain turnout, straight
  party, judicial, legislative, county, and levy tables, but no U.S. Senate table.
- Ritchie's one-page canvass narrative contains county totals, not precinct rows.

The other remaining 2010 counties have no general-election source document in those
repositories. OpenElections still classifies 2010 precinct results as work in progress.

### Other archive and mirror checks

- Wayback CDX searches for the historical Grant County and Hardy County clerk sites
  did not surface 2010 general-election result files.
- A broader Wayback URL-index sweep found Harrison County's archived `2010 GE`
  election menu. It proves that the county published a dedicated U.S. Senate
  results page at
  `http://www.harrisoncountywv.com/includes/election/2010 GE/US SENATOR.htm`.
  The menu survives, but Wayback did not capture that linked page, the live URL
  now returns 404, and the 2009-2013 Common Crawl indexes do not contain a copy.
  This exact URL is still useful in a targeted request to the county webmaster,
  clerk, or Internet Archive because it identifies the former digital record.
- Wayback URL-index sweeps of the known Brooke, Clay, Gilmer, Greenbrier,
  McDowell, Pleasants, and Ritchie county domains did not reveal additional 2010
  result files. The Greenbrier index retained its 2008 clerk results page and a
  2012 election-total page, but no 2010 result URL.
- WVU's public VTD/SOS report tree was inspected. Its archives contain voter-
  registration precinct summaries from 2022 onward, not historical vote returns:
  <https://data.wvgis.wvu.edu/pub/VTD/SOS/report/Vote/precinct_summary/archive/>.
- West Virginia's county-clerk records-retention schedule identifies the official
  record series as `Precinct Certificates` and describes it as the certificate
  filed by precinct election officials giving the results of their precinct. The
  schedule marks the series `Offer to State Archives`, making county-clerk records
  rooms and the State Archives the strongest offline acquisition route:
  <https://archive.wvculture.org/hiStory/rmpb/rscountyclerk.html>.

## Remaining priority gaps

2010 U.S. Senate has no precinct source for:

- Brooke
- Clay
- Gilmer
- Grant
- Greenbrier
- Hardy
- Harrison
- McDowell
- Ohio (county exists in the normalized file, but this contest is absent)
- Pleasants
- Ritchie

## Records requests

On 2026-10-28, individual electronic-record requests were sent to the current
county-clerk addresses published by the West Virginia Secretary of State for all
11 counties lacking 2010 special U.S. Senate precinct returns: Brooke, Clay,
Gilmer, Grant, Greenbrier, Hardy, Harrison, McDowell, Ohio, Pleasants, and
Ritchie. Each request asked for existing precinct certificates, a statement of
votes cast or canvass with precinct rows, an election-summary detail report, or
the original voting-system export. The requests also asked the clerk to identify
any transfer to the State Archives or another custodian and to give notice before
incurring a copying or research charge.

The State Archives says it does not accept research requests by email; any direct
Archives research request must be submitted by letter with the applicable fee.
County responses identifying a transfer should therefore be used to narrow any
paid postal request to a specific record series and accession.

The best next acquisition route is a Statement of Votes Cast, election-summary
report, or certified precinct canvass from each county clerk/commission. Search
engines did not surface durable public files for these counties. Requests should
ask specifically for the November 2, 2010 **special U.S. Senate election for the
unexpired term (contest code BU)** results **by precinct**, preferably the full
election-summary report in PDF, CSV, or voting-system export format; a county-total
canvass is not sufficient. If no electronic report survives, request the county's
`Precinct Certificates` for that election or ask whether they were transferred to
the West Virginia State Archives.

For 2008, the remaining contest-specific gaps are listed in
`precinct_coverage_report.json`. The West Virginia State Archives' Governor Joe
Manchin collection, Box 99, inventories “County Certificates of Vote, General
Election 2008”: <https://archive.wvculture.org/History/collections/ar/ar2034.html>.
Those records are an official archival lead, but the finding aid does not establish
that they contain precinct tables rather than county totals.

## Validation rule

Do not infer precinct votes from county totals. A recovered source is accepted only
when it provides precinct/VTD rows directly or a documented geographic allocation
from a named precinct dataset. Preserve source anomalies rather than inventing
balancing votes.
