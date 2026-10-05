import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from nixkeeper.sources.nixpkgs_update import PARSER

from nixkeeper_updates import cli, digest, site

# 2026-10-05 14:20:53 UTC, and a day before.
NOW = 1791210053
DAY = 86400
FAILED_LOG = "UPDATE_INFO: wesnoth 1.18.7 -> 1.18.8 https://x\nerror: build failed\n"
PR_LOG = (
    "UPDATE_INFO: unciv 4.22.1 -> 4.22.6 https://x\n"
    "https://api.github.com/repos/NixOS/nixpkgs/pulls/123456\n"
)


def state_db(path, rows):
    """A state database like the bot's: its log table, with rows of (attr,
    started, finished, exit code)."""
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE log (attr_path text PRIMARY KEY, started integer NOT NULL,"
            " finished integer, exit_code integer)"
        )
        db.executemany("INSERT INTO log VALUES (?, ?, ?, ?)", rows)


class Site(unittest.TestCase):
    def test_latest(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.db")
            state_db(path, [("wesnoth", NOW, NOW + 60, 1), ("unciv", NOW, None, None)])
            self.assertEqual(
                site.latest(path),
                {
                    "wesnoth": {"started": NOW, "finished": NOW + 60, "exit": 1},
                    "unciv": {"started": NOW, "finished": None, "exit": None},
                },
            )

    def test_day_and_log_url(self):
        self.assertEqual(site.day(NOW), "2026-10-05")
        self.assertEqual(
            site.log_url("python3Packages.foo", "2026-10-05"),
            "https://nixpkgs-update-logs.nixos.org/python3Packages.foo/2026-10-05.log",
        )


def run(started, finished=True):
    return {"started": started, "finished": started + 60 if finished else None}


class ToRead(unittest.TestCase):
    def test_new_changed_and_older_rules_newest_first(self):
        found = {
            "same": {"attempt": {"started": NOW - DAY, "parser": PARSER}},
            "newer": {"attempt": {"started": NOW - 2 * DAY, "parser": PARSER}},
            "rules": {"attempt": {"started": NOW - DAY, "parser": PARSER - 1}},
            "nolog": {"noLog": NOW - DAY},
        }
        latest = {
            "same": run(NOW - DAY),
            "newer": run(NOW),
            "rules": run(NOW - DAY),
            "new": run(NOW - 3 * DAY),
            "running": run(NOW, finished=False),
            "nolog": run(NOW - DAY),
        }
        self.assertEqual(cli.to_read(found, latest), ["newer", "rules", "new"])

    def test_entries_say_whats_pending(self):
        attempt = {"started": NOW - DAY, "parser": PARSER}
        found = {"read": {"attempt": attempt}, "behind": {"attempt": attempt}}
        latest = {
            "read": run(NOW - DAY),
            "behind": run(NOW),
            "never": run(NOW),
        }
        self.assertEqual(
            cli.entries(found, latest),
            {
                "read": {"attempt": attempt},
                "behind": {"attempt": attempt, "pending": "2026-10-05"},
                "never": {"pending": "2026-10-05"},
            },
        )  # and packages no longer in the bot's state are dropped


class ReadAttempt(unittest.TestCase):
    def test_the_log_of_its_day(self):
        with mock.patch.object(site, "get", return_value=FAILED_LOG.encode()) as get:
            attempt = cli.read_attempt("wesnoth", NOW)
        get.assert_called_once_with(
            "https://nixpkgs-update-logs.nixos.org/wesnoth/2026-10-05.log"
        )
        self.assertEqual(attempt["outcome"], "failed")
        self.assertEqual(attempt["date"], "2026-10-05")
        self.assertEqual(attempt["started"], NOW)
        self.assertEqual(attempt["parser"], PARSER)
        self.assertEqual((attempt["from"], attempt["to"]), ("1.18.7", "1.18.8"))

    def test_else_the_newest_in_its_folder(self):
        listing = b'<a href="2026-10-04.log">x</a> <a href="2026-10-06.log">y</a>'
        answers = {
            site.log_url("unciv", "2026-10-05"): None,
            f"{site.SITE}/unciv/": listing,
            site.log_url("unciv", "2026-10-06"): PR_LOG.encode(),
        }
        with mock.patch.object(site, "get", side_effect=answers.get):
            attempt = cli.read_attempt("unciv", NOW)
        self.assertEqual(
            (attempt["date"], attempt["outcome"]), ("2026-10-06", "prOpened")
        )
        self.assertEqual(attempt["pr"], 123456)

    def test_none_without_a_log(self):
        with mock.patch.object(site, "get", return_value=None):
            self.assertIsNone(cli.read_attempt("gone", NOW))


class Main(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = os.path.join(self.dir.name, "data")
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def sync(self, rows, logs, *args):
        db = os.path.join(self.dir.name, "state.db")
        if os.path.exists(db):
            os.remove(db)
        state_db(db, rows)
        with open(db, "rb") as f:
            body = f.read()

        def get(url):
            if url == site.STATE:
                return body
            text = logs.get(url.rsplit("/", 2)[-2])
            return text.encode() if text is not None else None

        with (
            mock.patch.object(cli, "MIN_PACKAGES", 1),
            mock.patch.object(site, "get", side_effect=get) as fetched,
        ):
            self.assertEqual(cli.main([self.data, *args]), 0)
        return digest.read(self.data), fetched

    def test_reads_whats_new_and_keeps_the_rest(self):
        rows = [("wesnoth", NOW - DAY, NOW - DAY + 60, 1), ("unciv", NOW, NOW + 60, 0)]
        logs = {"wesnoth": FAILED_LOG, "unciv": PR_LOG}
        (found, meta), _ = self.sync(rows, logs, "--max", "1")
        self.assertEqual(found["unciv"]["attempt"]["outcome"], "prOpened")  # newest
        self.assertEqual(found["wesnoth"], {"pending": "2026-10-04"})
        self.assertEqual((meta["read"], meta["pending"], meta["attempts"]), (1, 1, 1))
        # The next run reads the rest, and nothing again.
        (found, meta), fetched = self.sync(rows, logs)
        self.assertEqual(found["wesnoth"]["attempt"]["outcome"], "failed")
        self.assertEqual((meta["read"], meta["pending"]), (1, 0))
        self.assertEqual(fetched.call_count, 2)  # the state, and wesnoth's log
        # Nothing new: the same bytes.
        with open(os.path.join(self.data, digest.ATTEMPTS), "rb") as f:
            before = f.read()
        (_, meta), _ = self.sync(rows, logs)
        with open(os.path.join(self.data, digest.ATTEMPTS), "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(meta["read"], 0)

    def test_a_missing_log_isnt_asked_again(self):
        rows = [("gone", NOW, NOW + 60, 1)]
        (found, meta), _ = self.sync(rows, {})
        self.assertEqual(found["gone"], {"noLog": NOW})
        self.assertEqual((meta["missing"], meta["pending"]), (1, 0))
        (_, meta), fetched = self.sync(rows, {})
        self.assertEqual(fetched.call_count, 1)  # the state only

    def test_too_few_packages_writes_nothing(self):
        db = os.path.join(self.dir.name, "state.db")
        state_db(db, [("wesnoth", NOW, NOW + 60, 1)])
        with open(db, "rb") as f:
            body = f.read()
        with mock.patch.object(site, "get", return_value=body):
            self.assertEqual(cli.main([self.data]), 1)
        self.assertFalse(os.path.exists(self.data))
