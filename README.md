# Project Zero — Phase 1 (working foundation)

A private, local, $0 opportunity-tracking agent. **Phase 1 is the machine, not the money**: it stores
opportunities, scores them transparently, queues authorized work, keeps an auditable ledger, enforces a
zero-spend budget, and runs a background worker with a local dashboard. It does **not** yet discover
opportunities by itself (no connectors until Phase 2) and it earns nothing on its own.

## Run it on Windows

1. Install Python 3.10 or newer (free): https://www.python.org/downloads/ — tick **"Add python.exe to PATH"**.
2. Put this `projectzero` folder anywhere (e.g. your Documents).
3. Double-click **`start.bat`**. A browser opens at http://127.0.0.1:8765/ .
   No `pip install` is needed: there are no third-party dependencies.
4. First run loads clearly labelled **SAMPLE** data. Remove it with `python run.py clear-sample`.
5. Stop: close the window or press Ctrl+C (graceful), or double-click `stop.bat`.

Other scripts: `run_tests.bat` (self-test + full test suite), `install_autostart.bat` /
`remove_autostart.bat` (start at login via Windows Task Scheduler).

## What "24/7" really means here

The worker runs only while this program is running on a powered-on, awake, online computer. If the
machine is off, asleep or offline, nothing runs; on the next start it resumes from the saved database
(interrupted tasks are recovered safely, see below). Autostart makes it start at login, not stay alive
through sleep. Keep Windows from sleeping if you want it running overnight.

## Architecture (all standard library)

| Component | File |
|---|---|
| Config + secrets from env/.env | `pzero/config.py` |
| SQLite + migrations (`PRAGMA user_version`) | `pzero/db.py` |
| Runtime settings (validated; spend limits default 0) | `pzero/settings.py` |
| Normalizer, deduplication, sightings | `pzero/opportunities.py` |
| Eligibility + transparent scoring | `pzero/scoring.py` |
| AI interface (works with none; strict schema validation) | `pzero/brain.py` |
| Task queue + lifecycle state machine | `pzero/tasks.py` |
| Execution adapters (`prepare_brief`, `selftest`) + verification | `pzero/executors.py` |
| Budget manager | `pzero/budget.py` |
| Revenue/expense ledger | `pzero/ledger.py` |
| Connector framework (no real connectors yet) | `pzero/connectors.py` |
| Worker/scheduler/recovery | `pzero/worker.py`, `pzero/control.py` |
| Untrusted-content handling, log redaction | `pzero/security.py`, `pzero/activity.py` |
| Dashboard | `pzero/dashboard.py` |

## Rules the code enforces (and tests check)

- Spending: unknown cost is denied; any cost above the limits is denied; limits default to $0.
- Revenue counts only when entered in state `received` with evidence and a verification method.
  Advertised rewards, pending, invoiced, and submitted work are never income. Duplicate references are ignored.
- Non-USD amounts need an explicit rate and its source; none is ever guessed.
- A task runs only if it is approved by you, authorized, and not sample data. Sample data cannot be approved.
- Listing text is data: it is cleaned, scanned for instruction-like text (flagged, capped score, cannot be approved),
  HTML-escaped on display, and cannot change settings.
- After a crash, interrupted tasks are made safe: repeatable ones are re-queued; anything else goes to your
  action queue and is never silently repeated.
- Emergency stop persists across restarts until you clear it.
- Dashboard: loopback only, Host-header check, per-run CSRF token on every action.

## Phase 2 (in progress): first real source

`github_bounties` reads open, unassigned GitHub issues labelled "bounty" through GitHub's official search API
(free; 10 requests/min without a token, this uses ~6). **Try it first without saving anything:** double-click
`check_source.bat` (or `python run.py check-source github_bounties`). Then `start.bat` runs it hourly.
Honest limits: a bounty label does not prove anyone will pay. Rewards are filled only when exactly one dollar
amount appears; everything else shows as unknown and the listing is marked `unclear`/`investigate`.
I could not reach GitHub from my sandbox, so this connector is tested against a synthetic fixture only.
Live behaviour is unverified until you run the check. Optional: put `GITHUB_TOKEN=...` (a free token, no scopes)
in `.env` for higher limits.

## Current limits (not hidden)

- **No real discovery yet.** Opportunities come from manual entry until Phase 2 connectors are built and each
  source's terms are checked.
- The only real adapter writes an **action brief for you**. It does not register, log in, or submit anything.
  Registration, identity checks and human judgment stay with you by design.
- Scores are ranking aids built from recorded data; unknown inputs are shown as "assumed".
- Tested on Linux with Python 3.13. The Windows scripts (`.bat`, Task Scheduler) have **not** been run on Windows
  by me; if one misbehaves, send me the exact message.
- Phases 3–6 features (automated micro-task execution, business engine, learning from outcomes, backup
  rotation tests) are not built. A snapshot backup is taken on every start (`data/backups`, newest 14 kept).

## Where things are

`data/pzero.sqlite3` (all state), `data/logs/pzero.log`, `data/deliverables/` (briefs), `data/backups/`.
To restore: stop the app, copy a file from `data/backups/` over `data/pzero.sqlite3`, start again.
