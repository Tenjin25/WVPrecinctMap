#!/usr/bin/env python3
"""Import supplemental WV precinct returns for incomplete OpenElections years.

Outputs the seven-column CSV schema consumed by index.html:
county,precinct,office,district,candidate,party,votes
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path


HARVARD_2012_URL = "https://dataverse.harvard.edu/api/access/datafile/2456301"
MEDSL_2016_URL = (
    "https://raw.githubusercontent.com/MEDSL/official-precinct-returns/"
    "master/source/2016-wv-precinct.zip"
)
DRA_2008_URL = (
    "https://raw.githubusercontent.com/dra2020/vtd_data/"
    "master/2010_VTD/WV/2010_election_WV.csv"
)
USER_AGENT = "WVPrecinctMap/1.0"
HEADERS = ["county", "precinct", "office", "district", "candidate", "party", "votes"]

COUNTIES = {
    "BARBOUR", "BERKELEY", "BOONE", "BRAXTON", "BROOKE", "CABELL", "CALHOUN",
    "CLAY", "DODDRIDGE", "FAYETTE", "GILMER", "GRANT", "GREENBRIER", "HAMPSHIRE",
    "HANCOCK", "HARDY", "HARRISON", "JACKSON", "JEFFERSON", "KANAWHA", "LEWIS",
    "LINCOLN", "LOGAN", "MARION", "MARSHALL", "MASON", "MCDOWELL", "MERCER",
    "MINERAL", "MINGO", "MONONGALIA", "MONROE", "MORGAN", "NICHOLAS", "OHIO",
    "PENDLETON", "PLEASANTS", "POCAHONTAS", "PRESTON", "PUTNAM", "RALEIGH",
    "RANDOLPH", "RITCHIE", "ROANE", "SUMMERS", "TAYLOR", "TUCKER", "TYLER",
    "UPSHUR", "WAYNE", "WEBSTER", "WETZEL", "WIRT", "WOOD", "WYOMING",
}
COUNTY_ALIASES = {
    "GLIMER": "GILMER",
    "POCOHONTAS": "POCAHONTAS",
    "MC DOWELL": "MCDOWELL",
}

HARVARD_OFFICES = {
    "AGR": "Commissioner of Agriculture",
    "ATG": "Attorney General",
    "AUD": "Auditor",
    "GOV": "Governor",
    "SOS": "Secretary of State",
    "TRE": "State Treasurer",
    "USP": "President",
    "USS": "U.S. Senate",
    "USH": "U.S. House",
    "STS": "State Senate",
}
MEDSL_OFFICES = {
    "US President": "President",
    "US House": "U.S. House",
    "State House": "State House",
    "State Senate": "State Senate",
    "Governor": "Governor",
    "Attorney General": "Attorney General",
    "Secretary of State": "Secretary of State",
    "Auditor": "Auditor",
    "Commissioner of Agriculture": "Commissioner of Agriculture",
    "State Treasurer": "State Treasurer",
}
PARTIES = {
    "democratic": "DEM",
    "democrat": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "mountain": "MTN",
    "constitution": "CST",
    "independent": "IND",
    "no affiliation": "IND",
    "non partisan": "",
    "socialist equality party": "SEP",
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def save_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_county(raw: str) -> str:
    value = " ".join(str(raw or "").strip().upper().replace(" COUNTY", "").split())
    value = COUNTY_ALIASES.get(value, value)
    return value.title().replace("Mcdowell", "McDowell") if value in COUNTIES else ""


def integer(raw: object) -> int:
    try:
        return int(float(str(raw or "0").replace(",", "").strip() or 0))
    except ValueError:
        return 0


def write_rows(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    os.replace(temporary, path)


def consolidate_local_year(
    source_root: Path,
    supplemental_root: Path,
    year: int,
    output: Path,
) -> dict[str, object]:
    rows: list[list[object]] = []
    rejected_counties: set[str] = set()
    source_paths = list((source_root / str(year)).rglob("*__general__*precinct*.csv"))
    source_paths += list((supplemental_root / str(year)).rglob("*__general__*precinct*.csv"))
    for path in sorted(source_paths):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                county = canonical_county(row.get("county", ""))
                if not county:
                    rejected_counties.add(str(row.get("county", "")).strip())
                    continue
                rows.append([county] + [row.get(key, "") for key in HEADERS[1:]])
    write_rows(output, rows)
    return coverage(
        year,
        "OpenElections local files plus recovered county sources",
        rows,
        rejected_counties,
    )


def supplement_dra_2008_president(raw_path: Path, output: Path) -> dict[str, object]:
    """Fill counties lacking 2008 presidential rows from the DRA VTD archive.

    Dave's Redistricting republishes the Stanford/Harvard election-atlas vote
    data aggregated to 2010 Census VTDs. The file has Democratic, Republican,
    and total presidential votes but no minor-candidate breakdown, so the
    residual is retained as a single ``Other candidates`` row. Existing county
    returns always win; this is only a gap-filler.
    """
    if raw_path.exists():
        payload = raw_path.read_bytes()
    else:
        payload = fetch(DRA_2008_URL)
        save_atomic(raw_path, payload)

    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = [[row.get(key, "") for key in HEADERS] for row in csv.DictReader(handle)]

    president_aliases = {"PRESIDENT", "US PRESIDENT", "U S PRESIDENT"}
    present = set()
    for row in rows:
        office = " ".join(
            "".join(ch if ch.isalnum() else " " for ch in str(row[2]).upper()).split()
        )
        if office in president_aliases:
            present.add(str(row[0]).upper())

    county_by_fips = {
        "001": "Barbour", "003": "Berkeley", "005": "Boone", "007": "Braxton",
        "009": "Brooke", "011": "Cabell", "013": "Calhoun", "015": "Clay",
        "017": "Doddridge", "019": "Fayette", "021": "Gilmer", "023": "Grant",
        "025": "Greenbrier", "027": "Hampshire", "029": "Hancock", "031": "Hardy",
        "033": "Harrison", "035": "Jackson", "037": "Jefferson", "039": "Kanawha",
        "041": "Lewis", "043": "Lincoln", "045": "Logan", "047": "McDowell",
        "049": "Marion", "051": "Marshall", "053": "Mason", "055": "Mercer",
        "057": "Mineral", "059": "Mingo", "061": "Monongalia", "063": "Monroe",
        "065": "Morgan", "067": "Nicholas", "069": "Ohio", "071": "Pendleton",
        "073": "Pleasants", "075": "Pocahontas", "077": "Preston", "079": "Putnam",
        "081": "Raleigh", "083": "Randolph", "085": "Ritchie", "087": "Roane",
        "089": "Summers", "091": "Taylor", "093": "Tucker", "095": "Tyler",
        "097": "Upshur", "099": "Wayne", "101": "Webster", "103": "Wetzel",
        "105": "Wirt", "107": "Wood", "109": "Wyoming",
    }
    filled: set[str] = set()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    for source in reader:
        geoid = str(source.get("GEOID10", "")).strip()
        if len(geoid) < 6 or not geoid.startswith("54"):
            continue
        county = county_by_fips.get(geoid[2:5], "")
        if not county or county.upper() in present:
            continue
        precinct = geoid[5:].lstrip("0") or "0"
        dem = integer(source.get("Dem_2008_pres"))
        rep = integer(source.get("Rep_2008_pres"))
        total = integer(source.get("Tot_2008_pres"))
        if dem:
            rows.append([county, precinct, "President", "", "Barack Obama", "DEM", dem])
        if rep:
            rows.append([county, precinct, "President", "", "John McCain", "REP", rep])
        other = max(0, total - dem - rep)
        if other:
            rows.append([county, precinct, "President", "", "Other candidates", "OTH", other])
        filled.add(county)

    write_rows(output, rows)
    report = coverage(
        2008,
        "OpenElections/recovered county reports plus DRA 2010-VTD presidential fallback",
        rows,
    )
    report["dra_2008_president_filled_counties"] = sorted(filled)
    report["dra_2008_source_url"] = DRA_2008_URL
    report["dra_2008_method"] = "Stanford/Harvard election-atlas votes aggregated to 2010 Census VTDs"
    return report


def recovered_county_rows(output_root: Path) -> None:
    """Convert visually verified raw county documents into the atlas schema.

    Candidate vectors are checked against their source-cell sums. They normally also
    match the total printed in the source document. The documented exception is 2010
    Upshur/Jeff Becker: its 29 printed precinct cells sum to 103 while the source total
    says 106. The 2010 Preston report has two more source anomalies: its precinct rows
    sum to 5,444 Raese and 4,093 Manchin while its footer and the certified county totals
    say 5,466 and 4,071 (the combined two-candidate vote is unchanged), and its Jesse
    Johnson cells sum to 256 while the footer says 257. The 2008 Morgan attorney-general
    table is deliberately excluded because its precinct cells sum to 20 more votes than
    both its printed and certified total.
    """

    def expand(
        county: str,
        precincts: list[object],
        contests: list[tuple[str, str, str, list[int], int]],
    ) -> list[list[object]]:
        rows: list[list[object]] = []
        for office, candidate, party, votes, expected_total in contests:
            if len(votes) != len(precincts):
                raise ValueError(f"{county} {candidate}: precinct vector length mismatch")
            if sum(votes) != expected_total:
                raise ValueError(
                    f"{county} {candidate}: precinct sum {sum(votes)} != {expected_total}"
                )
            rows.extend(
                [county, precinct, office, "", candidate, party, vote]
                for precinct, vote in zip(precincts, votes)
            )
        return rows

    hancock_2008 = expand(
        "Hancock",
        list(range(1, 29)),
        [
            ("President", "John McCain", "REP", [307,217,172,149,217,417,153,432,354,259,295,407,340,213,36,132,296,266,241,368,321,294,364,202,273,215,314,264], 7518),
            ("President", "Barack Obama", "DEM", [202,195,130,138,165,217,111,247,203,202,148,198,179,218,97,195,145,189,220,353,245,228,233,167,243,175,233,228], 5504),
            ("President", "Cynthia McKinney", "MTN", [0,1,1,3,0,6,0,1,4,1,0,2,3,0,0,3,1,1,0,0,1,4,2,1,1,0,2,0], 38),
            ("President", "Ralph Nader", "IND", [4,4,5,6,9,6,2,6,4,5,3,3,3,4,1,4,3,2,9,5,6,6,7,1,1,4,6,2], 121),
            ("President", "Chuck Baldwin", "CST", [3,1,1,3,3,4,1,1,2,0,0,1,0,1,1,1,1,1,2,1,3,1,1,0,0,2,2,2], 39),
        ],
    )
    write_rows(
        output_root / "2008" / "20081104__wv__general__hancock__precinct.csv",
        hancock_2008,
    )

    morgan_precincts = [1, 2, 4, 5, 6, 7, 8, 13, 18, 21, 23, 24, 25]
    morgan_2008 = expand(
        "Morgan",
        morgan_precincts,
        [
            ("President", "John McCain", "REP", [484,545,212,189,254,155,338,390,213,361,487,484,316], 4428),
            ("President", "Barack Obama", "DEM", [289,271,103,111,171,136,243,217,148,257,257,312,206], 2721),
            ("President", "Cynthia McKinney", "MTN", [3,1,1,0,1,0,2,0,0,2,2,4,1], 17),
            ("President", "Ralph Nader", "IND", [13,9,1,7,6,4,11,4,4,5,6,10,5], 85),
            ("President", "Chuck Baldwin", "CST", [2,4,0,0,3,1,4,5,3,1,0,0,2], 25),
            ("U.S. Senate", "Jay Wolfe", "REP", [329,372,134,105,186,104,235,286,133,254,398,334,239], 3109),
            ("U.S. Senate", "Jay Rockefeller", "DEM", [419,420,176,185,229,186,345,300,209,353,325,451,270], 3868),
            ("Governor", "Russ Weeks", "REP", [286,294,101,75,139,72,173,222,91,208,308,281,182], 2432),
            ("Governor", "Joe Manchin III", "DEM", [438,478,203,197,276,197,399,355,247,375,394,445,314], 4318),
            ("Governor", "Jesse Johnson", "MTN", [30,32,11,17,13,28,22,25,17,22,32,57,17], 323),
        ],
    )
    write_rows(
        output_root / "2008" / "20081104__wv__general__morgan__precinct.csv",
        morgan_2008,
    )

    lincoln_2008_precincts = ["2", "3", "4", "5A", "5B", "8", "30", "31", "32", "33", "6", "7", "9", "10", "17", "18", "24A", "24B", "25A", "25B", "27", "28", "29", "12", "20", "19", "21", "22", "23", "26", "13", "14A", "14B", "15", "16"]
    lincoln_2008 = expand(
        "Lincoln",
        lincoln_2008_precincts,
        [
            ("President", "John McCain", "REP", [137,121,122,116,127,101,266,272,104,119,131,113,105,157,40,40,125,124,112,6,94,125,69,34,71,57,99,36,27,131,99,74,44,89,69], 3556),
            ("President", "Barack Obama", "DEM", [101,149,131,94,112,85,160,149,99,55,95,103,74,100,62,44,105,71,81,17,75,85,53,56,41,83,81,38,32,71,97,68,61,122,122], 2972),
            ("President", "Cynthia McKinney", "MTN", [1,2,1,1,1,1,1,1,1,2,4,2,1,0,1,0,1,0,1,0,1,1,1,0,1,2,0,1,0,3,0,0,1,5,0], 38),
            ("President", "Ralph Nader", "IND", [2,7,5,1,5,2,6,4,0,3,6,4,2,4,3,3,4,3,2,0,2,3,2,2,3,2,2,1,1,0,8,3,0,3,4], 102),
            ("President", "Chuck Baldwin", "CST", [0,0,1,1,0,3,2,1,1,1,2,1,0,0,0,0,2,0,0,0,1,0,0,1,1,0,1,2,1,0,1,2,0,1,0], 26),
        ],
    )
    write_rows(
        output_root / "2008" / "20081104__wv__general__lincoln__precinct.csv",
        lincoln_2008,
    )

    hancock_2010 = expand(
        "Hancock",
        list(range(1, 29)),
        [
            ("U.S. Senate", "John R. Raese", "REP", [175,104,69,78,110,235,85,272,207,136,174,232,190,117,13,59,203,154,120,223,173,156,217,121,181,133,184,129], 4250),
            ("U.S. Senate", "Joe Manchin III", "DEM", [216,185,141,144,158,242,114,279,258,222,189,292,190,183,61,138,158,180,234,337,259,253,289,162,195,169,253,203], 5704),
            ("U.S. Senate", "Jeff Becker", "CST", [8,4,6,2,6,13,5,3,8,6,6,11,10,4,0,2,1,5,12,12,10,14,4,5,4,2,11,5], 179),
            ("U.S. Senate", "Jesse Johnson", "MTN", [11,7,4,4,4,11,3,10,9,9,9,6,8,5,2,6,3,0,5,5,9,6,6,8,5,4,2,3], 164),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__hancock__precinct.csv",
        hancock_2010,
    )

    monroe_precincts = [1, 3, 5, 7, 8, 12, 13, 16, 18, 19, 22, 23, 29, 30, 31, 32, 33, 34]
    monroe_2010 = expand(
        "Monroe",
        monroe_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [64,19,53,121,96,111,164,125,25,34,133,99,150,236,100,153,110,36], 1829),
            ("U.S. Senate", "Joe Manchin III", "DEM", [87,30,44,116,92,164,197,153,49,25,221,120,159,221,76,200,108,72], 2134),
            ("U.S. Senate", "Jeff Becker", "CST", [0,2,4,4,7,6,3,5,2,0,5,5,7,4,2,8,2,1], 67),
            ("U.S. Senate", "Jesse Johnson", "MTN", [4,3,1,6,4,6,11,17,1,1,5,2,6,8,0,12,8,1], 96),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__monroe__precinct.csv",
        monroe_2010,
    )

    roane_precincts = [1, 4, 5, 6, 10, 11, 12, 15, 16, 18, 19, 20, 21, 22, 23, 25, 28, 29, 30, 32]
    roane_2010 = expand(
        "Roane",
        roane_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [142,88,95,69,109,124,25,63,64,62,25,105,52,81,106,169,89,111,142,72], 1793),
            ("U.S. Senate", "Joe Manchin III", "DEM", [152,121,155,136,69,143,30,60,92,106,61,108,53,121,209,154,147,117,134,106], 2274),
            ("U.S. Senate", "Jeff Becker", "CST", [1,0,1,0,2,3,0,4,6,0,2,2,1,1,3,4,2,0,0,2], 34),
            ("U.S. Senate", "Jesse Johnson", "MTN", [8,5,8,4,8,9,1,10,8,3,4,5,5,7,9,13,9,7,11,6], 140),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__roane__precinct.csv",
        roane_2010,
    )

    pocahontas_precincts = [1, 2, 3, 4, 6, 10, 12, 13, 15, 18, 21, 23, 26, 27, 29]
    pocahontas_2010 = expand(
        "Pocahontas",
        pocahontas_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [56,92,132,23,55,109,106,80,63,57,65,148,64,97,52], 1199),
            ("U.S. Senate", "Joe Manchin III", "DEM", [71,59,185,34,75,156,126,106,77,68,60,141,56,152,70], 1436),
            ("U.S. Senate", "Jeff Becker", "CST", [5,1,4,0,0,3,3,3,2,3,2,5,2,1,1], 35),
            ("U.S. Senate", "Jesse Johnson", "MTN", [5,5,16,3,4,18,5,4,3,5,6,7,3,11,8], 103),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__pocahontas__precinct.csv",
        pocahontas_2010,
    )

    wetzel_precincts = [4, 5, 10, 15, 16, 18, 21, 24, 27, 29, 33, 36, 38, 39, 40, 42, 43, 44, 45, 46, 48, 50]
    wetzel_2010 = expand(
        "Wetzel",
        wetzel_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [79,41,145,57,78,40,101,28,29,55,100,44,109,136,49,135,201,112,20,72,125,133], 1889),
            ("U.S. Senate", "Joe Manchin III", "DEM", [113,34,197,59,137,38,190,48,55,90,133,90,153,160,100,231,222,153,41,145,201,230], 2820),
            ("U.S. Senate", "Jeff Becker", "CST", [2,0,2,1,5,5,3,4,2,1,6,1,3,6,5,4,5,1,1,2,3,6], 68),
            ("U.S. Senate", "Jesse Johnson", "MTN", [5,3,4,3,1,3,1,0,1,7,5,3,3,8,2,2,4,3,0,10,3,6], 77),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__wetzel__precinct.csv",
        wetzel_2010,
    )

    wirt_precincts = ["1", "2", "7", "7A", "8", "11", "11A", "12", "13"]
    wirt_2010 = expand(
        "Wirt",
        wirt_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [72,16,72,129,109,153,54,57,86], 748),
            ("U.S. Senate", "Joe Manchin III", "DEM", [59,53,153,184,109,194,41,47,77], 917),
            ("U.S. Senate", "Jeff Becker", "CST", [4,2,4,5,5,3,1,0,1], 25),
            ("U.S. Senate", "Jesse Johnson", "MTN", [4,3,12,6,9,8,2,0,0], 44),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__wirt__precinct.csv",
        wirt_2010,
    )

    lincoln_precincts = ["2", "3", "4", "5A", "5B", "8", "30", "31", "32", "33", "6", "7", "9", "10", "17", "18", "24A", "24B", "25A", "25B", "27", "28", "29", "12", "20", "19", "21", "22", "23", "26", "13", "14A", "14B", "15", "16"]
    lincoln_2010 = expand(
        "Lincoln",
        lincoln_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [80,80,73,63,73,66,172,175,47,63,77,67,59,78,27,25,52,53,57,40,39,44,36,27,47,12,35,21,9,87,38,32,23,46,38], 1961),
            ("U.S. Senate", "Joe Manchin III", "DEM", [92,130,122,81,104,107,167,114,95,55,117,90,77,101,53,30,88,82,74,38,73,84,49,54,47,86,105,48,43,95,131,79,61,128,116], 3016),
            ("U.S. Senate", "Jeff Becker", "CST", [3,2,0,1,2,0,3,1,0,1,0,2,0,0,0,0,1,0,0,0,0,0,3,1,0,0,0,1,0,0,1,0,1,0,0], 23),
            ("U.S. Senate", "Jesse Johnson", "MTN", [6,1,4,1,6,1,8,7,2,0,1,4,5,5,2,0,0,4,4,1,5,1,1,0,0,4,3,1,0,2,2,3,0,2,4], 90),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__lincoln__precinct.csv",
        lincoln_2010,
    )

    wyoming_precincts = [
        "Baileysville High", "Brenton", "Basin", "Bud", "Stephenson", "Corinne",
        "Covel", "New Richmond", "Gulf Fork", "Courthouse", "Wolf Pen", "Rock View",
        "Wyoming", "Pineville Grade", "East Pineville", "Sunhill", "Simon",
        "Coal Mountain", "Ikes Fork", "Fanrock", "Hanover", "Matheny", "Oceana A-L",
        "Oceana M-Z", "Kopperston", "Cyclone", "Hatcher", "Lynco", "McGraws", "Maben",
        "Mullens", "South Mullens", "Itmann", "Glen Fork", "Mullens High", "Glen Rogers",
    ]
    wyoming_2010 = expand(
        "Wyoming",
        wyoming_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [57,58,23,54,47,61,41,18,33,17,34,83,43,61,46,93,24,53,32,63,37,100,59,40,95,146,58,38,59,30,64,41,15,60,84,12], 1879),
            ("U.S. Senate", "Joe Manchin III", "DEM", [101,66,22,54,59,68,47,8,48,55,50,65,51,61,64,94,33,22,59,135,75,127,72,59,138,94,96,98,74,23,96,55,51,93,153,62], 2528),
            ("U.S. Senate", "Jeff Becker", "CST", [3,3,0,0,0,2,2,2,1,0,3,1,3,0,1,2,0,1,2,3,2,1,1,0,3,2,2,1,3,1,3,0,1,0,3,0], 52),
            ("U.S. Senate", "Jesse Johnson", "MTN", [0,2,0,2,2,1,3,1,2,2,5,1,3,1,1,3,0,0,1,0,0,9,3,1,4,1,3,3,3,0,4,3,3,1,7,0], 75),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__wyoming__precinct.csv",
        wyoming_2010,
    )

    calhoun_precincts = [1, 4, 5, 6, 7, 8, 10, 11, 15, 19]
    calhoun_2010 = expand(
        "Calhoun",
        calhoun_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [95,79,89,53,111,77,100,58,68,55], 785),
            ("U.S. Senate", "Joe Manchin III", "DEM", [75,101,77,71,113,81,115,77,128,99], 937),
            ("U.S. Senate", "Jeff Becker", "CST", [2,1,1,2,2,3,0,0,3,0], 14),
            ("U.S. Senate", "Jesse Johnson", "MTN", [1,4,6,1,7,3,8,5,13,9], 57),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__calhoun__precinct.csv",
        calhoun_2010,
    )

    raleigh_precincts = [
        "1", "2", "3", "5", "5A", "6", "7", "8", "10", "11", "12", "15",
        "17", "18", "19", "20", "21", "23", "25", "27", "30", "31", "32",
        "33", "34", "35", "36", "37", "38", "40", "41", "44", "45", "46",
        "47", "48", "49", "50", "51", "52", "53", "54", "55", "56", "57",
        "60", "61", "62", "63", "64", "65", "66", "70", "71", "72", "73",
        "74", "75", "76", "77", "80", "81", "85",
    ]
    raleigh_2010 = expand(
        "Raleigh",
        raleigh_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [73,58,71,220,16,295,200,126,42,161,132,191,4,77,118,283,218,25,10,165,151,245,258,208,363,126,124,71,217,33,29,109,213,153,92,14,340,51,146,192,322,167,136,321,176,245,29,38,23,60,36,6,186,168,321,418,202,221,583,281,114,21,230], 9924),
            ("U.S. Senate", "Joe Manchin III", "DEM", [78,213,97,250,34,309,231,137,155,242,150,223,216,213,229,320,222,61,34,188,166,244,340,224,289,182,145,89,302,88,45,122,215,129,139,17,278,67,156,267,293,123,148,325,178,190,59,91,48,112,75,16,249,150,263,276,196,210,369,169,70,30,176], 10922),
            ("U.S. Senate", "Jeff Becker", "CST", [2,4,7,3,2,5,2,4,4,1,4,6,1,1,2,3,7,0,3,6,3,2,9,10,11,5,4,1,7,1,0,8,9,2,1,3,6,4,4,6,6,4,3,3,2,5,1,0,0,1,0,1,3,1,9,10,4,2,11,7,1,1,9], 247),
            ("U.S. Senate", "Jesse Johnson", "MTN", [3,5,3,5,1,5,4,5,4,8,10,7,0,2,4,7,3,2,1,8,5,6,8,11,12,5,4,7,8,3,0,7,2,7,6,1,14,4,5,13,9,2,5,9,7,20,3,6,6,7,1,0,6,8,15,19,15,3,10,3,3,1,7], 380),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__raleigh__precinct.csv",
        raleigh_2010,
    )

    upshur_precincts = ["4", "6", "7", "8", "9", "12", "13", "14", "15", "16", "18A", "18L", "19", "20A", "20L", "25", "27A", "27L", "33", "35", "37A", "37L", "38", "39A", "39L", "44A", "44L", "47A", "47L"]
    upshur_2010 = expand(
        "Upshur",
        upshur_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [102,175,24,135,128,63,95,125,59,145,104,75,130,144,142,77,121,105,177,127,99,112,120,90,125,137,128,96,110], 3270),
            ("U.S. Senate", "Joe Manchin III", "DEM", [87,144,16,219,142,118,93,147,77,153,77,81,118,113,121,73,127,102,157,124,98,110,110,86,83,139,137,81,126], 3259),
            # Source anomaly: these printed cells sum to 103; the report's total is 106.
            ("U.S. Senate", "Jeff Becker", "CST", [3,4,0,3,1,8,3,2,1,5,3,2,3,6,4,5,4,6,7,2,4,7,6,2,1,2,4,2,3], 103),
            ("U.S. Senate", "Jesse Johnson", "MTN", [10,8,0,4,3,1,2,5,2,7,4,5,4,3,3,6,4,5,8,5,1,3,4,4,6,5,5,4,8], 129),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__upshur__precinct.csv",
        upshur_2010,
    )

    preston_precincts = [
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "11A",
        "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22",
        "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
    ]
    preston_2010 = expand(
        "Preston",
        preston_precincts,
        [
            # Source anomaly: the printed cells preserve the combined major-party vote,
            # but allocate 22 fewer votes to Raese and 22 more to Manchin than the footer.
            ("U.S. Senate", "John R. Raese", "REP", [250,260,217,224,211,229,156,227,70,135,159,55,167,332,140,262,62,165,236,130,153,180,89,117,202,125,122,114,94,164,80,97,132,88], 5444),
            ("U.S. Senate", "Joe Manchin III", "DEM", [146,151,137,172,85,132,152,173,85,133,155,56,180,270,107,232,40,137,177,43,121,100,92,68,170,136,166,112,59,53,45,50,97,61], 4093),
            ("U.S. Senate", "Jeff Becker", "CST", [6,3,4,6,20,4,3,4,0,5,6,2,6,10,3,16,2,6,6,3,7,8,3,3,10,2,12,3,4,2,1,4,6,5], 185),
            # Source anomaly: the printed cells sum to 256; the report footer says 257.
            ("U.S. Senate", "Jesse Johnson", "MTN", [13,9,10,10,6,7,8,11,2,10,12,2,6,11,5,9,4,12,14,3,5,11,16,3,13,5,9,9,6,1,4,5,3,2], 256),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__preston__precinct.csv",
        preston_2010,
    )

    pleasants_precincts = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]
    pleasants_2010 = expand(
        "Pleasants",
        pleasants_precincts,
        [
            ("U.S. Senate", "John R. Raese", "REP", [108,123,39,53,95,217,62,48,100,155,42], 1042),
            ("U.S. Senate", "Joe Manchin III", "DEM", [124,194,86,66,96,215,58,67,154,207,138], 1405),
            ("U.S. Senate", "Jeff Becker", "CST", [2,2,3,0,3,4,4,4,3,4,2], 31),
            ("U.S. Senate", "Jesse Johnson", "MTN", [6,5,1,2,7,7,7,1,5,11,5], 57),
        ],
    )
    write_rows(
        output_root / "2010" / "20101102__wv__general__pleasants__precinct.csv",
        pleasants_2010,
    )


def import_harvard_2012(raw_path: Path, output: Path) -> dict[str, object]:
    if raw_path.exists():
        payload = raw_path.read_bytes()
    else:
        payload = fetch(HARVARD_2012_URL)
        save_atomic(raw_path, payload)
    rows: list[list[object]] = []
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")), delimiter="\t")
    for source in reader:
        county = canonical_county(source.get("county", ""))
        if not county:
            continue
        precinct = source.get("precinct", "").strip()
        for code, office in HARVARD_OFFICES.items():
            dem = integer(source.get(f"g2012_{code}_dv"))
            rep = integer(source.get(f"g2012_{code}_rv"))
            total = integer(source.get(f"g2012_{code}_tv"))
            if not total and not dem and not rep:
                continue
            district = source.get("cd", "").strip() if code == "USH" else (
                source.get("sd", "").strip() if code == "STS" else ""
            )
            if dem:
                rows.append([county, precinct, office, district, "Democratic candidate", "DEM", dem])
            if rep:
                rows.append([county, precinct, office, district, "Republican candidate", "REP", rep])
            other = max(0, total - dem - rep)
            if other:
                rows.append([county, precinct, office, district, "Other candidates", "OTH", other])
    write_rows(output, rows)
    return coverage(2012, "Harvard Election Data Archive WV_2012.tab", rows)


def import_medsl_2016(raw_path: Path, output: Path) -> dict[str, object]:
    if raw_path.exists():
        payload = raw_path.read_bytes()
    else:
        payload = fetch(MEDSL_2016_URL)
        save_atomic(raw_path, payload)
    archive = zipfile.ZipFile(io.BytesIO(payload))
    member = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
    rows: list[list[object]] = []
    with io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", newline="") as handle:
        for source in csv.DictReader(handle):
            if source.get("stage", "").strip().lower() != "gen":
                continue
            if source.get("special", "").strip().upper() == "TRUE":
                continue
            office = MEDSL_OFFICES.get(source.get("office", "").strip())
            if not office:
                continue
            county = canonical_county(source.get("county_name", ""))
            if not county:
                continue
            party_raw = source.get("party", "").strip().lower()
            party = PARTIES.get(party_raw, party_raw.upper()[:3])
            rows.append([
                county,
                source.get("precinct", "").strip(),
                office,
                source.get("district", "").strip(),
                source.get("candidate", "").strip(),
                party,
                integer(source.get("votes")),
            ])
    write_rows(output, rows)
    return coverage(2016, "MIT MEDSL official-precinct-returns", rows)


def coverage(
    year: int,
    source: str,
    rows: list[list[object]],
    rejected: set[str] | None = None,
) -> dict[str, object]:
    present = {str(row[0]).upper() for row in rows}
    office_aliases = {
        "president": {"PRESIDENT", "US PRESIDENT", "U S PRESIDENT"},
        "us_senate": {"US SENATE", "U S SENATE", "US SENATOR", "U S SENATOR"},
        "governor": {"GOVERNOR"},
        "attorney_general": {"ATTORNEY GENERAL"},
    }
    office_present: dict[str, set[str]] = {key: set() for key in office_aliases}
    for row in rows:
        office = " ".join(
            "".join(ch if ch.isalnum() else " " for ch in str(row[2]).upper()).split()
        )
        for key, aliases in office_aliases.items():
            if office in aliases:
                office_present[key].add(str(row[0]).upper())
    office_coverage = {
        key: {
            "counties_found": len(found),
            "missing_counties": sorted(
                name.title().replace("Mcdowell", "McDowell") for name in COUNTIES - found
            ),
        }
        for key, found in office_present.items()
    }
    return {
        "year": year,
        "source": source,
        "rows": len(rows),
        "counties_found": len(present),
        "missing_counties": sorted(name.title().replace("Mcdowell", "McDowell") for name in COUNTIES - present),
        "office_coverage": office_coverage,
        "rejected_county_labels": sorted(rejected or set()),
    }


def main() -> int:
    data = Path("data")
    source_root = data / "openelections-data-wv"
    output_root = data / "openelections" / "wv_sos"
    supplemental = data / "supplemental_sources"
    recovered_root = data / "supplemental_county_returns"

    recovered_county_rows(recovered_root)

    output_2008 = output_root / "20081104__wv__general__precinct.csv"
    consolidate_local_year(source_root, recovered_root, 2008, output_2008)
    report_2008 = supplement_dra_2008_president(
        supplemental / "dra" / "2010_election_WV.csv",
        output_2008,
    )

    reports = [
        report_2008,
        consolidate_local_year(source_root, recovered_root, 2010, output_root / "20101102__wv__general__precinct.csv"),
        import_harvard_2012(
            supplemental / "harvard" / "WV_2012.tab",
            output_root / "20121106__wv__general__precinct.csv",
        ),
        consolidate_local_year(
            source_root,
            recovered_root,
            2014,
            output_root / "20141104__wv__general__precinct.csv",
        ),
        import_medsl_2016(
            supplemental / "medsl" / "2016-wv-precinct.zip",
            output_root / "20161108__wv__general__precinct.csv",
        ),
    ]
    reports[0]["source_anomalies"] = [
        {
            "county": "Morgan",
            "office": "Attorney General",
            "action": "excluded",
            "detail": "Printed precinct cells sum to 20 more votes than the report and certified county total.",
        },
        {
            "county": "Lincoln",
            "office": "U.S. Senate and Governor",
            "action": "excluded",
            "detail": "Printed precinct cells do not reconcile to the report totals.",
        },
    ]
    reports[1]["source_anomalies"] = [
        {
            "county": "Upshur",
            "office": "U.S. Senate",
            "candidate": "Jeff Becker",
            "action": "imported source cells",
            "detail": "Printed precinct cells sum to 103; the report total is 106.",
        }
    ]

    report_path = data / "precinct_coverage_report.json"
    report_path.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    for report in reports:
        print(
            f"{report['year']}: {report['counties_found']}/55 counties, "
            f"{report['rows']} rows; missing: "
            f"{', '.join(report['missing_counties']) or 'none'}"
        )
    print(f"Coverage report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
