"""nixpkgs-update's public site (https://nixpkgs-update-logs.nixos.org/):
the bot's state database and its logs, one request at a time, at most one a
second, with a User-Agent linking this repository (and so its issue
tracker).

The state database (~supervisor/state.db, SQLite, about 14 MB) has the
bot's latest attempt at every package in its `log` table: when it started
and finished, and its exit code (0 when it opened a PR; 1 for everything
else, a failure as much as "nothing to update", so the log is still read).
An attempt's log is <attr>/<the UTC day it started>.log."""

import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

SITE = "https://nixpkgs-update-logs.nixos.org"
STATE = f"{SITE}/~supervisor/state.db"
USER_AGENT = "nixkeeper-updates (+https://github.com/iedame/nixkeeper-updates)"
# Seconds from one request's start to the next's.
PAUSE = 1.0
# Retries of a failed request, and how long to wait before each.
RETRY_DELAYS = (10, 60)

requests_made = 0
_last = 0.0


def _wait():
    global _last
    pause = _last + PAUSE - time.monotonic()
    if pause > 0:
        time.sleep(pause)
    _last = time.monotonic()


def get(url):
    """The body at url (bytes), or None on 404. A failed request is retried
    after RETRY_DELAYS; raises once every try failed."""
    global requests_made
    for attempt in range(len(RETRY_DELAYS) + 1):
        _wait()
        requests_made += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == len(RETRY_DELAYS):
                raise
        except (urllib.error.URLError, OSError):
            if attempt == len(RETRY_DELAYS):
                raise
        time.sleep(RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")


def latest(path):
    """{attr: {"started": unix time, "finished": unix time or None, "exit":
    exit code or None}} from a state database at path: the bot's latest
    attempt at each package (unfinished ones too)."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        rows = db.execute("SELECT attr_path, started, finished, exit_code FROM log")
        return {
            attr: {"started": started, "finished": finished, "exit": exit_code}
            for attr, started, finished, exit_code in rows
        }


def day(started):
    """The UTC day an attempt started (unix time), as its log is named."""
    return datetime.fromtimestamp(started, UTC).date().isoformat()


def log_url(attr, on_day):
    return f"{SITE}/{urllib.parse.quote(attr)}/{on_day}.log"
