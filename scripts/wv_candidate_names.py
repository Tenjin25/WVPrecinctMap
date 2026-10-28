"""Canonical candidate-name formatting shared by WV aggregation scripts."""

from __future__ import annotations

import re


ALIASES = {
    "JOHN JB MCCUSKEY": 'John "JB" McCuskey',
    "JOHN PAUL HOTT II": "John Paul Hott II",
    "CHARLES S TRUMP IV": "Charles S. Trump IV",
    "MICHAEL MOSTELLER II": "Michael Mosteller II",
    "KAYLA M MCCOY": "Kayla M. McCoy",
    "JAMES W JIM MCNEELY": 'James W. "Jim" McNeely',
    "POLLA MCCLELLAN RUMBERG": "Polla McClellan Rumberg",
    "DAVID MCCORMICK": "David McCormick",
    "PAT MCGEEHAN": "Pat McGeehan",
    "JB AKERS": "JB Akers",
    "FRANKIE DELAPAS": "Frankie DeLapas",
    "MICHAEL E DEVAULT": "Michael E. DeVault",
    "JOSEPH MANCHIN III": "Joe Manchin III",
    "JOE MANCHIN III": "Joe Manchin III",
}


def name_key(value: str) -> str:
    value = str(value or "").replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def normalize_candidate_name(value: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        return ""
    name = name.replace("“", '"').replace("”", '"').replace("’", "'")
    if name.upper() == name and re.search(r"[A-Z]", name):
        name = name.title()
    name = re.sub(r",?\s+Jr\.?$", " Jr.", name, flags=re.IGNORECASE)
    name = re.sub(r",?\s+Sr\.?$", " Sr.", name, flags=re.IGNORECASE)
    name = re.sub(r"\bIi\b", "II", name)
    name = re.sub(r"\bIii\b", "III", name)
    name = re.sub(r"\bIv\b", "IV", name)
    return ALIASES.get(name_key(name), name)
