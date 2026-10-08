# nixkeeper-updates

A digest of [nixpkgs-update](https://github.com/NixOS/nixpkgs-update)'s
latest attempt at every package, for
[nixkeeper](https://github.com/iedame/nixkeeper): whether the bot opened a
PR, found a PR already open, had nothing to update, couldn't update the
package, or failed, kept up to date every 3 hours by a workflow, so
nixkeeper reads one file instead of each package's logs.

It reads what the bot publishes at
[nixpkgs-update-logs.nixos.org](https://nixpkgs-update-logs.nixos.org/):
its state database (`~supervisor/state.db`), which has the bot's latest
attempt at every package and when it started, and the log of each attempt
that's new since the last run, about 2,500 a day, one request a second,
with a User-Agent linking here. Each log is read with nixkeeper's own rules
(its `nixkeeper/sources/nixpkgs_update.py`, through the flake), so the
digest says what nixkeeper would.

## The digest

On the `data` branch:

- [`data/attempts.jsonl.gz`](https://raw.githubusercontent.com/iedame/nixkeeper-updates/data/data/attempts.jsonl.gz):
  every package the bot has tried (about 34,000), one per line, sorted by
  its attribute as the bot names it (`python3Packages.requests`):

  ```json
  {"attr": "wesnoth",
   "attempt": {"attr": "wesnoth", "date": "2026-10-05", "started": 1791210053,
               "log": "https://nixpkgs-update-logs.nixos.org/wesnoth/2026-10-05.log",
               "parser": 4, "outcome": "noChange", "from": "1.18.7", "to": "1.18.8"}}
  ```

  `attempt` is the latest attempt whose log was read, as nixkeeper reads
  it: its `outcome` (`prOpened`, `prExists`, `branchExists`, `noChange`,
  `cantUpdate`, `skipped`, `failed`, `other`), the versions, the PR, a few
  lines of the log saying why when it has them (a failure's end, the bot's
  reason for skipping), and the version of the rules it was read with
  (`parser`).
  `pending` is the day of a newer attempt not read yet (running, or not
  reached yet); `noLog`, the start of a latest attempt that left no log.

- [`data/queue.json.gz`](https://raw.githubusercontent.com/iedame/nixkeeper-updates/data/data/queue.json.gz):
  the bot's [queue](https://nixpkgs-update-logs.nixos.org/~supervisor/queue.html)
  as the last run read it: when the page was made (`updatedAt`), how many
  days the bot takes to go round it (`cycleDays`), how many positions it
  has, and for each package in it (about 25,000) its position and what it
  would update it to:

  ```json
  {"cycleDays": 10.3, "positions": 24662, "updatedAt": "2026-10-06T21:18:38+00:00",
   "queue": {"unciv": {"position": 10719, "script": true,
                       "candidates": [["4.22.5", "4.22.7", "https://github.com/yairm210/Unciv/releases"], ...]}}}
  ```

  A package at position p is tried about p / positions × `cycleDays`
  after `updatedAt` (the front holds those tried longest ago). Each
  candidate is `[from, to, source URL]` (`from` can be empty, or hold
  spaces, as the bot has it); `script` means it also has an updateScript.
  A package not in the queue has nothing the bot could update it to right
  now.

- [`data/meta.json`](https://raw.githubusercontent.com/iedame/nixkeeper-updates/data/data/meta.json):
  when the run was (`fetchedAt`), the newest attempt in the bot's state
  (`stateAt`), the rules' version (`parser`), how many packages, attempts
  read and pending there are, how many logs and requests the run read and
  made, and the queue's `updatedAt`, `cycleDays`, `positions` and
  `packages` (`queue`).

The `data` branch is `main` plus one commit with the digest: each run replaces
it, so no history piles up.

## How it's kept up to date

The "Digest" workflow runs every 3 hours:

1. the bot's state database (about 14 MB): its latest attempt at every
   package;
2. the logs of the attempts that are new since the digest read that
   package's, newest first, one request each: about 300 a run; at most
   3,000 a run, and for at most 150 minutes, the rest left for the next
   run (pending);
3. each read with nixkeeper's rules. When those change (nixkeeper's
   `PARSER`, through `nix flake update nixkeeper`), every log is read
   again, over the following runs;
4. the bot's queue page (about 0.5 MB compressed), one request. When it
   can't be read, or isn't what it should be, the last one stays.

The first runs read every package's latest log (about 34,000, newest first,
about 3,000 a run). A run that can't read the state database publishes
nothing: the last digest stays.

## Running it

```bash
nix run . -- data
```

brings the digest in `data/` up to date (`-- data --max 100` reads at most
100 logs). `nix flake check` runs the tests and lint, `nix fmt` formats.

## License

MIT
