# County result aggregation

County result files are generated only for election years with normalized
precinct results covering all 55 West Virginia counties. The current complete
years are 2012, 2016, 2018, 2020, 2022, and 2024. The 2008 and 2010 normalized
files remain partial and are deliberately excluded.

Run:

```powershell
python scripts/aggregate_wv_county_results.py
```

The script groups records by `county`, `office`, `district`, `party`, and
`candidate`, sums `votes`, and writes OpenElections-compatible CSV files to
`data/openelections/wv_sos/county/`. It refuses to process a listed year unless
the source contains exactly 55 distinct counties and verifies that the total
vote count is unchanged by aggregation.

Machine-readable validation results are written to
`data/county_aggregation_report.json`.
