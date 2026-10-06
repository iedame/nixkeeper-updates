"""`python3 -m nixkeeper_updates [DATA_DIR] [--max N] [--minutes M]`: bring
the digest in DATA_DIR (default data/) up to date with nixpkgs-update. Each
run (every 3 hours):

1. downloads the bot's state database (site.py), with its latest attempt at
   every package;
2. reads the logs of the attempts that are new since the digest last read
   that package's (about 2,500 a day), newest first: one request each, at
   most N (default MAX_READ) and for at most M minutes (default
   MAX_MINUTES), the rest left for the next run ("pending");
3. reads each with nixkeeper's own rules (nixkeeper.sources.nixpkgs_update:
   parse), so the digest says what nixkeeper would; when those rules change
   (its PARSER), every log is read again, over the following runs.

The first runs read every package's latest log (about 34,000, newest first).
Nothing is written when the state database can't be read: the last digest
stays."""

import re
import sys
import tempfile
import time
import urllib.parse
from datetime import UTC, datetime

from nixkeeper.sources.nixpkgs_update import PARSER, parse

from . import digest, site

MAX_READ = 3000
MAX_MINUTES = 150
# Fewer packages than this in the state database means it wasn't read right
# (it has about 34,000): nothing is written.
MIN_PACKAGES = 20_000
# This many logs in a row that can't be read: the site is likely down, and
# the run stops (what it read is still written).
MAX_FAILURES_IN_A_ROW = 5
LOG_NAME = re.compile(r'href="(\d{4}-\d{2}-\d{2})\.log"')


def arg(argv, flag, default):
    if flag in argv:
        i = argv.index(flag)
        value = argv[i + 1]
        del argv[i : i + 2]
        return int(value)
    return default


def to_read(found, latest):
    """The packages whose latest finished attempt the digest hasn't read
    (with these rules), newest first; not those whose latest attempt left no
    log ("noLog", its start)."""
    wanted = []
    for attr, run in latest.items():
        entry = found.get(attr) or {}
        if run["finished"] is None or entry.get("noLog") == run["started"]:
            continue  # still running, or nothing to read
        attempt = entry.get("attempt") or {}
        if (
            attempt.get("started") != run["started"]
            or attempt.get("parser") != PARSER
            # From before read_attempt took only logs from its day on.
            or attempt.get("date", "") < site.day(run["started"])
        ):
            wanted.append((-run["started"], attr))
    return [attr for _, attr in sorted(wanted)]


def read_attempt(attr, started):
    """The attempt that started at started (unix time), read: its log, named
    after its day; if that isn't there (an attempt over midnight, say), the
    newest log in the package's folder from that day on (an older one is an
    earlier attempt's). None if there's no log."""
    on_day = site.day(started)
    body = site.get(site.log_url(attr, on_day))
    if body is None:
        listing = site.get(f"{site.SITE}/{urllib.parse.quote(attr)}/")
        days = [
            d
            for d in LOG_NAME.findall((listing or b"").decode(errors="replace"))
            if d >= on_day
        ]
        if not days:
            return None
        on_day = max(days)
        body = site.get(site.log_url(attr, on_day))
        if body is None:
            return None
    return {
        "attr": attr,
        "date": on_day,
        "started": started,
        "log": site.log_url(attr, on_day),
        "parser": PARSER,
        **parse(body.decode(errors="replace")),
    }


def entries(found, latest):
    """The digest's entries for the packages in latest (others are gone from
    the bot's state: dropped), each with "pending" when its latest attempt
    isn't the one read (nor one with no log: "noLog")."""
    out = {}
    for attr, run in latest.items():
        entry = {}
        old = found.get(attr) or {}
        if attempt := old.get("attempt"):
            entry["attempt"] = attempt
        if old.get("noLog") == run["started"]:
            entry["noLog"] = run["started"]
        elif (
            not attempt
            or attempt.get("started") != run["started"]
            or attempt.get("parser") != PARSER
        ):
            entry["pending"] = site.day(run["started"])
        out[attr] = entry
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    most = arg(argv, "--max", MAX_READ)
    minutes = arg(argv, "--minutes", MAX_MINUTES)
    directory = argv[0] if argv else "data"
    started = time.monotonic()
    found, _ = digest.read(directory)

    print("Reading nixpkgs-update's state...", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        body = site.get(site.STATE, site.STATE_DEADLINE)
        if body is None:
            print("::error::No state database: not written.", file=sys.stderr)
            return 1
        f.write(body)
        f.flush()
        latest = site.latest(f.name)
    if len(latest) < MIN_PACKAGES:
        print(
            f"::error::Only {len(latest):,} packages in the state database "
            f"(expected over {MIN_PACKAGES:,}): not written.",
            file=sys.stderr,
        )
        return 1

    wanted = to_read(found, latest)
    print(
        f"  {len(latest):,} packages, {len(wanted):,} attempts to read "
        f"(at most {most:,} now)",
        file=sys.stderr,
    )
    read = missing = in_a_row = 0
    for attr in wanted[:most]:
        if time.monotonic() - started > minutes * 60:
            print(f"  stopping after {minutes} minutes", file=sys.stderr)
            break
        if in_a_row >= MAX_FAILURES_IN_A_ROW:
            print("::warning::The log site stopped answering.", file=sys.stderr)
            break
        try:
            attempt = read_attempt(attr, latest[attr]["started"])
            in_a_row = 0
        except OSError as e:  # urllib's errors are OSErrors
            print(f"  {attr}: {e}", file=sys.stderr)
            in_a_row += 1
            continue
        if attempt is None:
            missing += 1
            found.setdefault(attr, {})["noLog"] = latest[attr]["started"]
            continue
        found.setdefault(attr, {})["attempt"] = attempt
        read += 1

    out = entries(found, latest)
    newest = max(run["started"] for run in latest.values())
    meta = {
        "fetchedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "stateAt": datetime.fromtimestamp(newest, UTC).isoformat(timespec="seconds"),
        "parser": PARSER,
        "packages": len(out),
        "attempts": sum(1 for e in out.values() if "attempt" in e),
        "pending": sum(1 for e in out.values() if "pending" in e),
        "read": read,
        "missing": missing,
        "requests": site.requests_made,
    }
    digest.write(directory, out, meta)
    print(
        f"  read {read:,} logs ({missing:,} missing), {meta['pending']:,} "
        f"attempts pending; {site.requests_made:,} requests in "
        f"{(time.monotonic() - started) / 60:.0f} min",
        file=sys.stderr,
    )
    return 0
