"""The digest nixkeeper reads (data/): attempts.jsonl.gz, nixpkgs-update's
latest attempt at every package it has tried, read as nixkeeper reads it;
and meta.json, about the run that made it.

attempts.jsonl.gz has one package per line, sorted by attribute (the bot's
attribute path: python3Packages.requests, not python313Packages):

    {"attr": "wesnoth",
     "attempt": {"attr": "wesnoth", "date": "2026-10-05", "started": 1791210053,
                 "log": "https://nixpkgs-update-logs.nixos.org/wesnoth/2026-10-05.log",
                 "parser": 2, "outcome": "noChange", "from": "1.18.7", ...}}

"attempt" is the latest attempt whose log was read: as nixkeeper's own
reading of a log gives it (nixkeeper.sources.nixpkgs_update: parse, with
"attr", "date", "log", "parser"), and when it started. "pending", when
there is one, is the day of a newer attempt not read yet (still running, or
its log not reached yet): a reader can then read that log itself, or take
the attempt as it is. A package the bot has tried but whose log hasn't been
read yet has only "pending". "noLog" is the start of a latest attempt that
left no log (none to read: not pending)."""

import gzip
import json
import os

FORMAT = 1
ATTEMPTS = "attempts.jsonl.gz"
META = "meta.json"


def write(directory, found, meta):
    """Write attempts.jsonl.gz ({attr: entry}) and meta.json to directory.
    The same data gives the same bytes (sorted, mtime 0)."""
    os.makedirs(directory, exist_ok=True)
    lines = (
        json.dumps({"attr": attr, **found[attr]}, separators=(",", ":"), sort_keys=True)
        + "\n"
        for attr in sorted(found)
    )
    data = "".join(lines).encode()
    with open(os.path.join(directory, ATTEMPTS), "wb") as f:
        f.write(gzip.compress(data, compresslevel=9, mtime=0))
    with open(os.path.join(directory, META), "w") as f:
        json.dump({"format": FORMAT, **meta}, f, indent=2, sort_keys=True)
        f.write("\n")


def read(directory):
    """({attr: entry}, meta) in directory, or ({}, {}) if none yet."""
    try:
        with open(os.path.join(directory, META)) as f:
            meta = json.load(f)
        found = {}
        with gzip.open(os.path.join(directory, ATTEMPTS), "rt") as f:
            for line in f:
                entry = json.loads(line)
                found[entry.pop("attr")] = entry
        return found, meta
    except FileNotFoundError:
        return {}, {}
