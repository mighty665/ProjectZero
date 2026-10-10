"""Project Zero launcher.

  python run.py            start dashboard + worker (same as `start`)
  python run.py start --no-browser
  python run.py stop       ask a running worker to stop gracefully
  python run.py check-source [name]   live dry run of a discovery source (saves nothing)
  python run.py selftest   run an end-to-end check in a throwaway database
  python run.py backup     copy the database to data/backups
  python run.py clear-sample   delete the labelled sample data
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import sqlite3
import sys
import tempfile
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pzero import activity, config, connectors, control, dashboard, db, github_bounties, seed, tasks, workflow  # noqa: E402,F401
from pzero.worker import Worker, WorkerController  # noqa: E402


def backup(cfg) -> str:
    os.makedirs(cfg.backups_dir, exist_ok=True)
    dest = os.path.join(cfg.backups_dir, f"pzero-{db.now().replace(':', '').replace('-', '')}.sqlite3")
    src = sqlite3.connect(cfg.db_path)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)  # consistent snapshot even while the app is running
    src.close()
    dst.close()
    # keep the 14 most recent backups
    files = sorted(f for f in os.listdir(cfg.backups_dir) if f.startswith("pzero-"))
    for old in files[:-14]:
        os.remove(os.path.join(cfg.backups_dir, old))
    return dest


def build_connectors(cfg) -> list:
    unknown = [n for n in cfg.connectors if n not in connectors.REGISTRY]
    if unknown:
        raise ValueError(f"config.json lists unknown connectors {unknown}; available: {sorted(connectors.REGISTRY)}")
    return [connectors.REGISTRY[n](cfg.user_agent) for n in cfg.connectors]


def cmd_check_source(cfg, name: str) -> int:
    """Live dry run: fetch from the real source and show what WOULD be stored. Writes nothing to your database."""
    if name not in connectors.REGISTRY:
        print(f"Unknown source {name!r}. Available: {sorted(connectors.REGISTRY)}")
        return 2
    c = connectors.REGISTRY[name](cfg.user_agent)
    print(f"Fetching from {name} ({c.url}) ...")
    try:
        records = c.fetch()
    except Exception as e:  # noqa: BLE001
        print("FAILED:", type(e).__name__, e)
        return 1
    from pzero import opportunities, scoring
    scratch = db.connect(":memory:")
    new = dup = bad = 0
    for raw in records:
        try:
            oid, created, _ = opportunities.add_opportunity(scratch, raw, name)
        except opportunities.OpportunityError as e:
            bad += 1
            print("  skipped malformed record:", e)
            continue
        if created:
            new += 1
            scoring.evaluate(scratch, oid)
        else:
            dup += 1
    print(f"{len(records)} records fetched: {new} distinct, {dup} duplicates, {bad} malformed. (Nothing was saved.)")
    for r in scratch.execute("SELECT * FROM opportunities ORDER BY COALESCE(score,0) DESC LIMIT 8"):
        reward = "unknown" if r["reward_cents"] is None else f"${r['reward_cents']/100:,.0f}"
        flag = "  [FLAGGED TEXT]" if r["injection_flags"] else ""
        print(f"  score {r['score']:>3} | reward {reward:>8} | {r['title'][:70]}{flag}\n           {r['source_url']}")
    return 0


def cmd_start(cfg, open_browser: bool) -> int:
    activity.setup_logging(cfg.log_dir)
    factory = lambda: db.connect(cfg.db_path)
    conn = factory()
    if control.worker_alive(conn):
        print("Project Zero already appears to be running (a worker heartbeat was seen in the last 30 seconds).")
        print(f"Open http://{cfg.host}:{cfg.port}/ in your browser, or run `python run.py stop` first.")
        return 1
    if not conn.execute("SELECT 1 FROM opportunities LIMIT 1").fetchone():
        seed.seed_sample_data(conn)
        print("First run: loaded clearly labelled SAMPLE data. Remove it any time with: python run.py clear-sample")
    try:
        print("Database backup:", backup(cfg))
    except Exception as e:  # noqa: BLE001
        print("Backup skipped:", e)
    try:
        source_list = build_connectors(cfg)
    except ValueError as e:
        print("Configuration problem:", e)
        return 2
    controller = WorkerController(factory, cfg, source_list)
    try:
        server = dashboard.make_server(cfg, controller, factory)
    except OSError as e:
        print(f"Could not open port {cfg.port}: {e}\nChange dashboard_port in config.json or close the other program using it.")
        return 1
    controller.start()
    threading.Thread(target=server.serve_forever, name="pzero-dashboard", daemon=True).start()
    url = f"http://{cfg.host}:{cfg.port}/"
    print(f"Project Zero is running. Dashboard: {url}\nPress Ctrl+C (or close this window) to stop.")
    if open_browser:
        webbrowser.open(url)
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())
    try:
        while not stop.wait(1.0):
            pass
    finally:
        print("Shutting down gracefully...")
        controller.stop()
        server.shutdown()
        conn.close()
    return 0


def cmd_stop(cfg) -> int:
    conn = db.connect(cfg.db_path)
    control.request_worker_stop(conn, True)
    print("Stop requested. The worker will exit within a few seconds if it is running.")
    return 0


def cmd_selftest() -> int:
    """End-to-end check on a throwaway database; touches none of your real data."""
    with tempfile.TemporaryDirectory() as d:
        cfg = config.Config(d, os.path.join(d, "t.sqlite3"), os.path.join(d, "logs"), os.path.join(d, "out"), os.path.join(d, "bk"),
                            "127.0.0.1", 18765, "selftest")
        conn = db.connect(cfg.db_path)
        from pzero import opportunities, scoring
        oid, _, _ = opportunities.add_opportunity(conn, dict(title="Selftest listing", category="microtask", reward=1, est_hours=0.1, geo_ok=True,
                                                             requires_registration=False, requires_identity=False), "selftest")
        scoring.evaluate(conn, oid)
        tid = workflow.approve_opportunity(conn, oid)
        w = Worker(lambda: conn, cfg)
        w.process_tasks(conn)
        state = tasks.get(conn, tid)["state"]
        ok = state == "awaiting_human" and os.path.isfile(os.path.join(cfg.deliverables_dir, f"task_{tid}_brief.md"))
        print("selftest:", "PASS" if ok else f"FAIL (task state {state})")
        conn.close()
        return 0 if ok else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on unusual characters in a Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="Project Zero")
    p.add_argument("command", nargs="?", default="start", choices=["start", "stop", "selftest", "backup", "clear-sample", "check-source"])
    p.add_argument("source", nargs="?", default="github_bounties", help="source name for check-source")
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()
    base = os.path.dirname(os.path.abspath(__file__))
    config.load_env_file(os.path.join(base, ".env"))
    try:
        cfg = config.load_config(base_dir=base)
    except config.ConfigError as e:
        print("Configuration problem:", e)
        return 2
    if a.command == "selftest":
        return cmd_selftest()
    if a.command == "check-source":
        return cmd_check_source(cfg, a.source)
    if a.command == "start":
        return cmd_start(cfg, not a.no_browser)
    if a.command == "stop":
        return cmd_stop(cfg)
    if a.command == "backup":
        print(backup(cfg))
        return 0
    if a.command == "clear-sample":
        conn = db.connect(cfg.db_path)
        seed.clear_sample_data(conn)
        print("Sample data removed.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
