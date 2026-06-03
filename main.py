"""MNN B-Roll Footage Search Engine — entry point.

Usage:
    python main.py                 Launch the search UI (Phase 3).
    python main.py --validate      Check the SharePoint mapped drive(s) and exit.
    python main.py --init-config   Create config.json from the template.
    python main.py --config PATH   Use an alternate config file.

Phase 1 (config + mapped-drive validation) is fully working from the command
line today. The graphical UI arrives in Phase 3; until then, --validate is the
way to confirm the SharePoint drive is reachable.
"""

from __future__ import annotations

import argparse
import os
import sys

from broll_search import __app_name__, __version__
from broll_search.config import ConfigError, config_exists, init_config, load_config
from broll_search.drive_validator import format_report, validate_config


def _cmd_init_config(args: argparse.Namespace) -> int:
    try:
        path = init_config(overwrite=args.force)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Created {path}")
    print("Next: open it and set 'footage_paths' to your mapped SharePoint folder,")
    print("then run:  python main.py --validate")
    return 0


def _load_or_explain(args: argparse.Namespace):
    """Load config, printing a friendly message if it's missing/broken.

    Returns the Config, or None if loading failed (caller should exit non-zero).
    """
    try:
        return load_config(args.config)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if not config_exists() and not args.config:
            print("\nTip: run 'python main.py --init-config' to create config.json.",
                  file=sys.stderr)
        return None


def _cmd_validate(args: argparse.Namespace) -> int:
    config = _load_or_explain(args)
    if config is None:
        return 1

    report = validate_config(config)
    print(format_report(report))
    sys.stdout.flush()  # keep the report above the stderr summary below

    if report.all_ok:
        return 0
    if report.any_usable:
        print("\nSome paths are usable; see warnings/errors above.", file=sys.stderr)
        return 1
    print("\nNo footage paths are reachable. Indexing cannot run until this is "
          "fixed.", file=sys.stderr)
    return 2


def _cmd_index(args: argparse.Namespace) -> int:
    config = _load_or_explain(args)
    if config is None:
        return 1

    # Make sure at least one root is reachable before scanning.
    report = validate_config(config)
    if not report.any_usable:
        print(format_report(report))
        print("\nNo reachable footage paths — cannot index.", file=sys.stderr)
        return 2

    from broll_search.indexer import run_index

    print(f"Indexing into {config.database_abspath} …")
    result = run_index(config, log=lambda m: print(f"  {m}"), full_rescan=args.full)
    print(result.summary())
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    config = _load_or_explain(args)
    if config is None:
        return 1
    from broll_search import database as db
    from broll_search.scheduler import is_index_due

    if not config.database_abspath.exists():
        print("No index database yet. Run:  python main.py --index")
        return 0

    con = db.connect(config.database_abspath)
    try:
        total = db.file_count(con)
        last = db.get_meta(con, "last_index_completed_at") or "never"
        print(f"Index database : {config.database_abspath}")
        print(f"Total files    : {total}")
        print(f"Last indexed   : {last}")
        print(f"Re-index due   : {'yes' if is_index_due(config) else 'no'}")
        for col, label in [("shooter", "Shooters"), ("extension", "File types"),
                          ("shot_type", "Shot types")]:
            vals = db.distinct_values(con, col)
            if vals:
                print(f"{label:<15}: {', '.join(vals)}")
    finally:
        con.close()
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    config = _load_or_explain(args)
    if config is None:
        return 1
    from broll_search import database as db

    if not config.database_abspath.exists():
        print("No index database yet. Run:  python main.py --index", file=sys.stderr)
        return 1

    con = db.connect(config.database_abspath)
    try:
        rows = db.search(con, args.search, limit=args.limit)
        if not rows:
            print("No matches.")
            return 0
        print(f"{len(rows)} result(s):\n")
        for r in rows:
            bits = [r["filename"]]
            meta = []
            if r["shooter"]:
                meta.append(r["shooter"])
            if r["month_name"]:
                meta.append(r["month_name"])
            if r["shot_type"]:
                meta.append(r["shot_type"])
            if r["duration_sec"]:
                meta.append(f"{r['duration_sec']:.0f}s")
            print(f"  {r['filename']}")
            print(f"      {os.path.dirname(r['path'])}"
                  + (f"   [{', '.join(meta)}]" if meta else ""))
    finally:
        con.close()
    return 0


def _check_drive(config) -> bool:
    """Validate the drive; print the report and return False if unusable."""
    report = validate_config(config)
    if not report.any_usable:
        print(format_report(report))
        print("\nThe footage drive is not reachable — fix the connection above "
              "before launching.", file=sys.stderr)
        return False
    return True


def _cmd_launch_web(args: argparse.Namespace) -> int:
    config = _load_or_explain(args)
    if config is None:
        return 1
    if not _check_drive(config):
        return 2
    try:
        from broll_search.web.app import run_web
    except ImportError as exc:
        print(f"ERROR: Could not load the web app (is Flask installed?): {exc}",
              file=sys.stderr)
        print("Install dependencies with:  python -m pip install -r requirements.txt",
              file=sys.stderr)
        return 1
    return run_web(config, share=args.share, port=args.port,
                   open_browser=not args.no_browser)


def _cmd_launch_desktop(args: argparse.Namespace) -> int:
    config = _load_or_explain(args)
    if config is None:
        return 1
    if not _check_drive(config):
        return 2
    try:
        from broll_search.ui.main_window import launch
    except ImportError as exc:
        print(f"ERROR: Could not load the desktop UI (is PyQt5 installed?): {exc}",
              file=sys.stderr)
        return 1
    report = validate_config(config)
    return int(launch(config, report) or 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=f"{__app_name__} (v{__version__})",
    )
    parser.add_argument("--config", metavar="PATH", default=None,
                        help="Path to a config file (defaults to config.json).")
    parser.add_argument("--validate", action="store_true",
                        help="Check the mapped SharePoint drive(s) and exit.")
    parser.add_argument("--init-config", action="store_true",
                        help="Create config.json from the example template.")
    parser.add_argument("--force", action="store_true",
                        help="With --init-config, overwrite config.json. With "
                             "--index, force a full re-scan (see --full).")
    parser.add_argument("--index", action="store_true",
                        help="Scan the footage folder(s) and update the index, then exit.")
    parser.add_argument("--full", action="store_true",
                        help="With --index, re-read every file instead of only changed ones.")
    parser.add_argument("--stats", action="store_true",
                        help="Show index statistics (file count, last run) and exit.")
    parser.add_argument("--search", metavar="QUERY",
                        help="Search the index for QUERY and print matches, then exit.")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max results for --search (default 50).")
    parser.add_argument("--desktop", action="store_true",
                        help="Launch the simple desktop (PyQt5) UI instead of the web gallery.")
    parser.add_argument("--port", type=int, default=None,
                        help="Port for the web gallery (default from config, 8765).")
    parser.add_argument("--share", action="store_true",
                        help="Share on your local network so others (e.g. your manager) "
                             "can open it from their own computer. Prints the link to send them.")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open a browser tab when starting the web gallery.")
    parser.add_argument("--version", action="version",
                        version=f"{__app_name__} {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.init_config:
        return _cmd_init_config(args)
    if args.validate:
        return _cmd_validate(args)
    if args.index:
        return _cmd_index(args)
    if args.stats:
        return _cmd_stats(args)
    if args.search is not None:
        return _cmd_search(args)
    if args.desktop:
        return _cmd_launch_desktop(args)
    return _cmd_launch_web(args)


if __name__ == "__main__":
    raise SystemExit(main())
