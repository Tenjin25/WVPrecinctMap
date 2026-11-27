#!/usr/bin/env python3
"""Download available 2026 WV county precinct XML into one normalized CSV."""

import csv
import gzip
import io
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://results.enr.clarityelections.com/WV"
OUTPUT = ROOT / "data/openelections/wv_sos/20261103__wv__general__precinct.csv"
REPORT = ROOT / "data/precinct_2026_import_report.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as response:
        body = response.read()
        return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def office_and_district(text):
    label = text.split(" - ", 1)[0].split(",", 1)[0].strip().upper()
    office = {
        "U.S. SENATOR": "U.S. Senate",
        "U.S. HOUSE OF REPRESENTATIVES": "U.S. House",
        "HOUSE OF DELEGATES": "State House",
        "STATE SENATOR": "State Senate",
    }.get(label, label.title())
    match = re.search(r"(?:District\s+(\d+)|(\d+)(?:st|nd|rd|th)?\s+(?:\w+\s+)?District)", text, re.I)
    return office, (match.group(1) or match.group(2)) if match else ""


def main():
    version = get(f"{BASE}/127496/current_ver.txt").decode().strip()
    settings = json.loads(get(f"{BASE}/127496/{version}/json/en/electionsettings.json"))
    counties = settings["settings"]["electiondetails"]["participatingcounties"]
    rows, missing, timestamps = [], [], {}
    for item in counties:
        county, election, revision, *_ = item.split("|")
        url = f"{BASE}/{county}/{election}/{revision}/reports/detailxml.zip"
        try:
            with zipfile.ZipFile(io.BytesIO(get(url))) as archive:
                root = ET.fromstring(archive.read("detail.xml"))
        except (urllib.error.HTTPError, zipfile.BadZipFile, KeyError) as error:
            missing.append({"county": county, "url": url, "error": str(error)})
            continue
        timestamps[county] = root.findtext("Timestamp")
        for contest in root.findall("Contest"):
            office, district = office_and_district(contest.get("text", ""))
            for choice in contest.findall("Choice"):
                candidate = choice.get("text", "")
                party = choice.get("party", "")
                votes = {}
                for vote_type in choice.findall("VoteType"):
                    for precinct in vote_type.findall("Precinct"):
                        name = precinct.get("name", "")
                        votes[name] = votes.get(name, 0) + int(precinct.get("votes", "0"))
                for precinct, count in votes.items():
                    rows.append((county, precinct, office, district, candidate, party, count))
        print(f"{county}: {sum(row[0] == county for row in rows)} rows", flush=True)
    rows.sort(key=lambda row: (row[0], row[1], row[2], row[3], row[4]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, lineterminator="\n")
        writer.writerow(("county", "precinct", "office", "district", "candidate", "party", "votes"))
        writer.writerows(rows)
    report = {"state_version": version, "counties_available": len(timestamps), "counties_missing": missing,
              "rows": len(rows), "county_timestamps": timestamps, "source": f"{BASE}/127496/web.345435/"}
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("state_version", "counties_available", "counties_missing", "rows")}, indent=2))


if __name__ == "__main__":
    main()
