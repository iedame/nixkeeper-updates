"""The bot's queue (site.QUEUE): which packages nixpkgs-update will try,
in order, and what it would update each to. The page lists, in its order,
a row for each update source of each package:

    <td>1</td> <td>proxyman</td>
    <td>3.16.1 3.21.0 https://github.com/ProxymanApp/proxyman-windows-linux/releases</td>
    <td>1</td> <td>proxyman</td> <td>0 1</td>

("0 1": its updateScript, which decides the version itself), under "last
updated: 2026-10-06 21:18:38 UTC" and "cycle time: 10.3 days", how long
the bot takes to get through all of it. A package's position is how far
it is from being tried: the front holds those tried longest ago, so it's
tried in about position / positions × the cycle time. A package not in it
has nothing the bot could update it to right now (no newer version it
knows of, no updateScript)."""

import re
from datetime import UTC, datetime

ROW = re.compile(r"<tr>\s*<td>(\d+)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*</tr>")
UPDATED = re.compile(r"last updated: (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC")
CYCLE = re.compile(r"cycle time: ([0-9.]+) days")
UPDATE_SCRIPT = ["0", "1"]


def candidate_of(parts):
    """[from, to, source URL] from a payload's words, read from the end: the
    URL, the version before it, and the rest as what nixpkgs has, which can
    be empty (" 8.06.16 https://...") or hold spaces ("3.5.0+1.006 / 1.100
    3.5.1 https://..."); None when there's no version to update to."""
    source = parts.pop() if parts and parts[-1].startswith("http") else ""
    if not parts:
        return None
    to = parts.pop()
    return [" ".join(parts), to, source]


def parse(html):
    """{"updatedAt", "cycleDays", "positions", "queue": {attr: {"position",
    "candidates": [[from, to, source URL], ...], "script": true when it has
    an updateScript}}} from the queue page, or None when it isn't one (no
    time, cycle or rows)."""
    updated = UPDATED.search(html)
    cycle = CYCLE.search(html)
    rows = ROW.findall(html)
    if not (updated and cycle and rows):
        return None
    found = {}
    for position, attr, payload in rows:
        entry = found.setdefault(attr.strip(), {"position": int(position)})
        parts = payload.split()
        if parts == UPDATE_SCRIPT:
            entry["script"] = True
        elif (candidate := candidate_of(parts)) and candidate not in entry.setdefault(
            "candidates", []
        ):
            entry["candidates"].append(candidate)
    at = datetime.strptime(updated.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return {
        "updatedAt": at.isoformat(timespec="seconds"),
        "cycleDays": float(cycle.group(1)),
        "positions": max(int(p) for p, _, _ in rows),
        "queue": found,
    }
