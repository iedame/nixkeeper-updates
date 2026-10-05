# nixkeeper-updates

A digest of [nixpkgs-update](https://github.com/nix-community/nixpkgs-update)'s
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
               "parser": 2, "outcome": "noChange", "from": "1.18.7", "to": "1.18.8"}}
  ```

  `attempt` is the latest attempt whose log was read, as nixkeeper reads
  it: its `outcome` (`prOpened`, `prExists`, `noChange`, `cantUpdate`,
  `failed`, `other`), the versions, the PR, a few lines of the log when it
  failed, and the version of the rules it was read with (`parser`).
  `pending` is the day of a newer attempt not read yet (running, or not
  reached yet); `noLog`, the start of a latest attempt that left no log.

- [`data/meta.json`](https://raw.githubusercontent.com/iedame/nixkeeper-updates/data/data/meta.json):
  when the run was (`fetchedAt`), the newest attempt in the bot's state
  (`stateAt`), the rules' version (`parser`), how many packages, attempts
  read and pending there are, and how many logs and requests the run read
  and made.

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
   again, over the following runs.

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
