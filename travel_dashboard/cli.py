"""Command line: python -m travel_dashboard [build|check|serve]."""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import sys
import time
import tomllib
from pathlib import Path

from . import export
from .profiles import Profiles
from .tables import read_all

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def load_settings() -> dict:
    return tomllib.loads((ROOT / "config" / "settings.toml").read_text(encoding="utf-8"))


def _print_issues(issues) -> None:
    for i in issues:
        print(f"  [{i.level}] {i.table} {i.id}: {i.message}")


def cmd_build(args) -> int:
    settings = load_settings()
    em = settings.get("emissions", {})
    data_dir = Path(args.data) if args.data else ROOT / "data"
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    draws = args.draws or em.get("draws", 2000)
    out = Path(args.out) if args.out else SITE / "data"
    t0 = time.perf_counter()
    tables = read_all(data_dir)
    profiles = Profiles.load(ROOT / "config" / "emissions.toml")
    defaults = em.get("defaults", {"level": "destination", "alloc": "iso", "occ": "observed", "nonco2": "full",
                                   "scope": "all"})
    em_json = export.emissions_json(tables, profiles, today, draws, em.get("seed", 20261018), defaults)
    sizes = {
        "emissions.json": export.write(out / "emissions.json", em_json),
        "costs.json": export.write(out / "costs.json", export.costs_json(tables, today)),
        "meta.json": export.write(out / "meta.json", export.meta_json(settings, profiles)),
    }
    print(f"built {', '.join(f'{k} ({v // 1024} KB)' for k, v in sizes.items())} from {data_dir} "
          f"in {time.perf_counter() - t0:.1f} s")
    print(f"  {len(tables.costs)} costs, {em_json['meta']['counts']}")
    if tables.issues:
        print(f"{len(tables.issues)} data issue(s):")
        _print_issues(tables.issues)
    return 0


def cmd_check(args) -> int:
    from . import trip as trip_mod

    data_dir = Path(args.data) if args.data else ROOT / "data"
    tables = read_all(data_dir)
    trip_mod.build(tables.waypoints, tables.travel, tables.issues)
    print(f"{len(tables.costs)} costs, {len(tables.waypoints)} waypoints, {len(tables.travel)} travel rows")
    _print_issues(tables.issues)
    errors = sum(i.level == "error" for i in tables.issues)
    print(f"{len(tables.issues)} issue(s), {errors} error(s)")
    return 1 if errors else 0


def cmd_serve(args) -> int:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"serving {SITE} at http://localhost:{args.port}/  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m travel_dashboard")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="read data/*.csv and write site/data/*.json")
    b.add_argument("--data", help="data directory (default: data/)")
    b.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    b.add_argument("--draws", type=int, help="Monte Carlo draws (default from config/settings.toml)")
    b.add_argument("--out", help="output directory (default: site/data/)")
    c = sub.add_parser("check", help="validate the data and list issues")
    c.add_argument("--data")
    s = sub.add_parser("serve", help="preview the site locally")
    s.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    if args.cmd in (None, "build"):
        if args.cmd is None:
            args = ap.parse_args(["build", *(argv or sys.argv[1:])])
        return cmd_build(args)
    return {"check": cmd_check, "serve": cmd_serve}[args.cmd](args)
