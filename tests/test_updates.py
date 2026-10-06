import io
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from nixkeeper.sources.nixpkgs_update import PARSER

from nixkeeper_updates import cli, digest, queue, site

# 2026-10-05 14:20:53 UTC, and a day before.
NOW = 1791210053
DAY = 86400
FAILED_LOG = "UPDATE_INFO: wesnoth 1.18.7 -> 1.18.8 https://x\nerror: build failed\n"
PR_LOG = (
    "UPDATE_INFO: unciv 4.22.1 -> 4.22.6 https://x\n"
    "https://api.github.com/repos/NixOS/nixpkgs/pulls/123456\n"
)


# The bot's queue page, trimmed (2026-10-06).
QUEUE_PAGE = """
    <h1>nixpkgs-update queue</h1>
<h3>this page is updated every 15 minutes, last updated: 2026-10-06 21:18:38 UTC</h3>
    <h3>cycle time: 10.3 days</h3>
<table><thead><tr><th>number</th><th>attribute path</th><th>payload</th></tr></thead>
    <tbody>
        <tr>
            <td>1</td>
            <td>proxyman</td>
            <td>3.16.1 3.21.0 https://github.com/ProxymanApp/proxyman-windows-linux/releases</td>
        </tr>
        <tr>
            <td>1</td>
            <td>proxyman</td>
            <td>0 1</td>
        </tr>
        <tr>
            <td>1</td>
            <td>proxyman</td>
            <td>3.16.1 26.0.1 https://repology.org/project/proxyman/versions</td>
        </tr>
        <tr>
            <td>2</td>
            <td>ipbt</td>
            <td>20210215 20260527 https://repology.org/project/ipbt/versions</td>
        </tr>
        <tr>
            <td>24662</td>
            <td>vym</td>
            <td>2.9.26 3.0.0 https://github.com/insilmaril/vym/releases</td>
        </tr>
        <tr>
            <td>24662</td>
            <td>vym</td>
            <td>2.9.26 3.0.0 https://github.com/insilmaril/vym/releases</td>
        </tr>
    </tbody></table>
"""


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


class Deadline(unittest.TestCase):
    """A whole answer has its deadline to arrive, however steadily it
    trickles in: a real server on this machine sending a byte at a time."""

    BODY = b"x" * 60

    def setUp(self):
        body = self.BODY

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for i in range(len(body)):
                        self.wfile.write(body[i : i + 1])
                        self.wfile.flush()
                        if self.path == "/slow":
                            time.sleep(0.02)
                except OSError:
                    pass  # the client gave up

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        for patcher in (
            mock.patch.object(site, "RETRY_DELAYS", ()),
            mock.patch.object(site, "PAUSE", 0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_trickle_is_given_up(self):
        # 60 bytes at 20 ms each: 1.2 s, against 0.3 s.
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            site.get(self.base + "/slow", 0.3)
        self.assertLess(time.monotonic() - started, 1)

    def test_a_steady_answer_arrives(self):
        self.assertEqual(site.get(self.base + "/fast", 0.3), self.BODY)
        self.assertEqual(site.get(self.base + "/slow", 10), self.BODY)


class ToRead(unittest.TestCase):
    def test_new_changed_and_older_rules_newest_first(self):
        found = {
            "same": {
                "attempt": {
                    "started": NOW - DAY,
                    "parser": PARSER,
                    "date": "2026-10-04",
                }
            },
            "newer": {"attempt": {"started": NOW - 2 * DAY, "parser": PARSER}},
            "rules": {"attempt": {"started": NOW - DAY, "parser": PARSER - 1}},
            "nolog": {"noLog": NOW - DAY},
            "olderlog": {
                "attempt": {
                    "started": NOW - DAY,
                    "parser": PARSER,
                    "date": "2026-04-06",
                }
            },
        }
        latest = {
            "same": run(NOW - DAY),
            "newer": run(NOW),
            "rules": run(NOW - DAY),
            "new": run(NOW - 3 * DAY),
            "running": run(NOW, finished=False),
            "nolog": run(NOW - DAY),
            "olderlog": run(NOW - DAY),
        }
        self.assertEqual(
            cli.to_read(found, latest), ["newer", "olderlog", "rules", "new"]
        )

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

    def test_not_an_older_attempts_log(self):
        listing = b'<a href="2026-04-06.log">x</a>'
        answers = {f"{site.SITE}/old/": listing}
        with mock.patch.object(site, "get", side_effect=answers.get):
            self.assertIsNone(cli.read_attempt("old", NOW))

    def test_none_without_a_log(self):
        with mock.patch.object(site, "get", return_value=None):
            self.assertIsNone(cli.read_attempt("gone", NOW))


class Queue(unittest.TestCase):
    def test_parse(self):
        found = queue.parse(QUEUE_PAGE)
        self.assertEqual(
            {k: found[k] for k in ("updatedAt", "cycleDays", "positions")},
            {
                "updatedAt": "2026-10-06T21:18:38+00:00",
                "cycleDays": 10.3,
                "positions": 24662,
            },
        )
        self.assertEqual(
            found["queue"]["proxyman"],
            {
                "position": 1,
                "script": True,  # "0 1"
                "candidates": [
                    [
                        "3.16.1",
                        "3.21.0",
                        "https://github.com/ProxymanApp/proxyman-windows-linux/releases",
                    ],
                    [
                        "3.16.1",
                        "26.0.1",
                        "https://repology.org/project/proxyman/versions",
                    ],
                ],
            },
        )
        # The same source twice: once.
        self.assertEqual(len(found["queue"]["vym"]["candidates"]), 1)
        self.assertNotIn("script", found["queue"]["ipbt"])

    def test_odd_payloads(self):
        # As the page has them: nothing for the version nixpkgs has
        # (ocamlPackages.labltk), or one with spaces (nerd-fonts.ubuntu-sans).
        self.assertEqual(
            queue.candidate_of(
                ["8.06.16", "https://github.com/garrigue/labltk/releases"]
            ),
            ["", "8.06.16", "https://github.com/garrigue/labltk/releases"],
        )
        self.assertEqual(
            queue.candidate_of(
                [
                    "3.5.0+1.006",
                    "/",
                    "1.100",
                    "3.5.1",
                    "https://github.com/ryanoasis/nerd-fonts/releases",
                ]
            ),
            [
                "3.5.0+1.006 / 1.100",
                "3.5.1",
                "https://github.com/ryanoasis/nerd-fonts/releases",
            ],
        )
        self.assertEqual(queue.candidate_of(["1.0", "1.1"]), ["1.0", "1.1", ""])
        self.assertIsNone(queue.candidate_of(["https://x"]))

    def test_not_the_page(self):
        self.assertIsNone(queue.parse("<html>Bad gateway</html>"))


class Main(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = os.path.join(self.dir.name, "data")
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def sync(self, rows, logs, *args, queue_page=QUEUE_PAGE):
        db = os.path.join(self.dir.name, "state.db")
        if os.path.exists(db):
            os.remove(db)
        state_db(db, rows)
        with open(db, "rb") as f:
            body = f.read()

        def get(url, allowed=site.DEADLINE, compressed=False):
            if url == site.STATE:
                self.assertEqual(allowed, site.STATE_DEADLINE)  # longer
                return body
            if url == site.QUEUE:
                self.assertTrue(compressed)
                if isinstance(queue_page, Exception):
                    raise queue_page
                return queue_page.encode() if queue_page is not None else None
            text = logs.get(url.rsplit("/", 2)[-2])
            return text.encode() if text is not None else None

        with (
            mock.patch.object(cli, "MIN_PACKAGES", 1),
            mock.patch.object(cli, "MIN_QUEUE", 1),
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
        # The state, wesnoth's log and the queue.
        self.assertEqual(fetched.call_count, 3)
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
        self.assertEqual(fetched.call_count, 2)  # the state and the queue only

    def test_the_queue_and_the_last_one_when_it_cant_be_read(self):
        rows = [("vym", NOW, NOW + 60, 1)]
        (_, meta), _ = self.sync(rows, {"vym": FAILED_LOG})
        self.assertEqual(
            meta["queue"],
            {
                "updatedAt": "2026-10-06T21:18:38+00:00",
                "cycleDays": 10.3,
                "positions": 24662,
                "packages": 3,
            },
        )
        self.assertEqual(
            digest.read_queue(self.data)["queue"]["vym"]["position"], 24662
        )
        for failing in (OSError("down"), "<html>Bad gateway</html>", None):
            with self.subTest(failing=str(failing)[:20]):
                (_, again), _ = self.sync(rows, {"vym": FAILED_LOG}, queue_page=failing)
                self.assertEqual(again["queue"], meta["queue"])  # the last one
                self.assertEqual(digest.read_queue(self.data)["positions"], 24662)

    def test_too_few_packages_writes_nothing(self):
        db = os.path.join(self.dir.name, "state.db")
        state_db(db, [("wesnoth", NOW, NOW + 60, 1)])
        with open(db, "rb") as f:
            body = f.read()
        with mock.patch.object(site, "get", return_value=body):
            self.assertEqual(cli.main([self.data]), 1)
        self.assertFalse(os.path.exists(self.data))
