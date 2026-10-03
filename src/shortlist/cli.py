"""Command line interface: ``shortlist <command> ...``.

Settings are read from ``--settings``, else the SHORTLIST_SETTINGS environment variable, else
``./settings.json`` if it exists, else built-in defaults.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .config import ConfigError, Settings, load_settings
from .letters import DEFAULT_MAX_WORDS, DEFAULT_MIN_WORDS, check_letters
from .normalize import RawJobsError, normalize_file
from .rules import self_check
from .safety import sanitize_text
from .tracker import (
    OPEN_STATUSES,
    TrackerError,
    add_file,
    init_tracker,
    mark_applied,
    prune,
    read_jobs,
    rebuild,
    refresh,
    update_file,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {value!r}") from exc


def _settings_path(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    env = os.environ.get("SHORTLIST_SETTINGS")
    if env:
        return Path(env)
    default = Path.cwd() / "settings.json"
    return default if default.is_file() else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shortlist",
        description="Shortlist: transparent job filtering, ranking and tracking. You review and submit; "
                    "Shortlist never applies, logs in or sends anything.",
    )
    p.add_argument("--version", action="version", version=f"shortlist {__version__}")
    p.add_argument("-s", "--settings", help="settings JSON file (default: $SHORTLIST_SETTINGS or ./settings.json)")
    p.add_argument("-t", "--tracker", help="tracker .xlsx path (overrides tracker_path in settings)")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    c = sub.add_parser("init", help="create a new tracker workbook (refuses to overwrite)")
    c.add_argument("--answers", help="optional JSON file of your standard application answers")
    c.add_argument("--write-settings", action="store_true",
                   help="also write a settings.json with the defaults (if none exists)")

    c = sub.add_parser("normalize", help="filter an agent's raw jobs JSON into tracker rows")
    c.add_argument("raw", help="raw jobs JSON from a search agent")
    c.add_argument("out", help="where to write the kept, normalised jobs")
    c.add_argument("--date", type=_date, help="treat this date as today (YYYY-MM-DD)")

    c = sub.add_parser("add", help="append jobs from JSON file(s), skipping duplicates")
    c.add_argument("json", nargs="+")

    c = sub.add_parser("update", help="set fields on existing rows, matched by 'Job URL'")
    c.add_argument("json")

    sub.add_parser("prune", help="remove stale, crowded or skipped jobs you have not acted on (backs up first)")

    c = sub.add_parser("applied", help="mark job(s) Applied by company, part of 'company role', or job link")
    c.add_argument("names", nargs="+")
    c.add_argument("--date", type=_date, help="date applied (default today)")

    sub.add_parser("dashboard", help="recompute priority/flags and refresh the Dashboard tab")

    c = sub.add_parser("rebuild", help="start a fresh tracker with only these jobs (backs up the old file)")
    c.add_argument("json", nargs="+")

    c = sub.add_parser("top", help="print the top open jobs by priority")
    c.add_argument("-n", type=int, help="how many (default: top_n from settings)")
    c.add_argument("--json", action="store_true", help="print JSON (with the fields a letter writer needs)")
    c.add_argument("--all", action="store_true", help="include every job, not only open ones")

    sub.add_parser("test-rules", help="run the built-in filtering rule checks")

    c = sub.add_parser("check-letters", help="check drafted cover letters (dashes, length, 'Never say' phrases)")
    c.add_argument("files", nargs="+")
    c.add_argument("--fact-sheet", help="fact sheet whose 'Never say' section lists banned phrases")
    c.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS)
    c.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)

    c = sub.add_parser("scan", help="sanitise a text file from a job page and report instruction-like text")
    c.add_argument("file")
    return p


def _print_list(title: str, items: list[str]) -> None:
    if items:
        print(title)
        for item in items:
            print(f"  {item}")


def _run(args: argparse.Namespace, settings: Settings) -> int:
    tracker = Path(args.tracker) if args.tracker else None
    cmd = args.command

    if cmd == "init":
        if args.write_settings:
            target = Path(args.settings) if args.settings else Path.cwd() / "settings.json"
            if target.exists():
                print(f"{target} already exists; left unchanged")
            else:
                target.write_text(json.dumps(Settings(base_dir=target.parent).to_dict(), indent=2), encoding="utf-8")
                print(f"wrote {target}")
                settings = load_settings(target)
        print(f"created {init_tracker(settings, args.answers, tracker)}")
        return 0

    if cmd == "normalize":
        result = normalize_file(args.raw, args.out, args.date or date.today(), settings)
        print(f"kept {len(result.kept)}, dropped {len(result.dropped)} -> {args.out}")
        for d in result.dropped:
            print(f"  dropped: {d.get('Company')} - {d.get('Role Title')} ({d.get('Reason')})")
        for w in result.warnings:
            print(f"  safety: {w.get('Company')} - {w.get('Role Title')}: {'; '.join(w['Warnings'])}")
        print(f"logs: {settings.logs_dir}")
        return 0

    if cmd == "add":
        total = 0
        for path in args.json:
            r = add_file(settings, path, tracker)
            total += r.added
            print(f"{path}: added {r.added}, skipped {len(r.duplicates)} duplicate(s)")
            _print_list("  skipped (rejected there within "
                        f"{settings.reapply_cooldown_days} days):", r.cooldown)
            _print_list("  skipped (invalid):", r.invalid)
        print(f"added {total} job(s) in total")
        return 0

    if cmd == "update":
        updated, missing = update_file(settings, args.json, tracker)
        print(f"updated {updated} row(s)" + (f"; not found: {missing}" if missing else ""))
        return 0

    if cmd == "prune":
        r = prune(settings, tracker)
        where = f"; old file kept as {r.backup}" if r.backup else ""
        print(f"pruned {len(r.dropped)} job(s), kept {len(r.kept)}{where}")
        for j in r.dropped:
            print(f"  removed: {j.get('Company')} - {j.get('Role Title')} (posted {j.get('Date Posted')})")
        return 0

    if cmd == "applied":
        done, problems = mark_applied(settings, args.names, args.date, tracker)
        _print_list("marked Applied:", done)
        _print_list("not changed (be more specific):", problems)
        return 1 if problems else 0

    if cmd == "dashboard":
        refresh(settings, tracker)
        print("dashboard refreshed")
        return 0

    if cmd == "rebuild":
        r, backup = rebuild(settings, args.json, tracker)
        print(f"rebuilt with {r.added} job(s)" + (f"; old file kept as {backup}" if backup else ""))
        return 0

    if cmd == "top":
        path = tracker or settings.tracker_path
        if not path.exists():
            raise TrackerError(f"{path} does not exist; run 'shortlist init' first")
        jobs = [j for j in read_jobs(path)
                if args.all or (j.get("Status") in OPEN_STATUSES and j.get("Status") != "Skipped")]
        jobs.sort(key=lambda j: -(j.get("Priority") or 0))
        n = args.n or (len(jobs) if args.all else settings.top_n)
        keys = ["Priority", "Company", "Role Title", "Date Posted", "Applicants", "Flags", "Status", "Job URL"]
        if args.json:
            keys += ["Location", "Country", "Visa / Sponsorship", "Resume Version", "Why It Fits", "Red Flags",
                     "Notes", "Cover Letter File"]
        rows = [{k: j.get(k) for k in keys} for j in jobs[:n]]
        if args.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False, default=str))
        else:
            for i, j in enumerate(rows, start=1):
                print(f"{i:>2}. [{j['Priority']}] {j['Company']} - {j['Role Title']} "
                      f"(posted {j['Date Posted']}; applicants: {j['Applicants']})")
                if j["Flags"]:
                    print(f"      flags: {j['Flags']}")
                print(f"      {j['Job URL']}")
        return 0

    if cmd == "test-rules":
        results = self_check()
        for name, ok, got, expected in results:
            print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  (got {got!r}, expected {expected!r})"))
        failed = sum(not ok for _, ok, _, _ in results)
        print(f"\n{len(results) - failed}/{len(results)} checks passed")
        return 1 if failed else 0

    if cmd == "check-letters":
        reports = check_letters([Path(f) for f in args.files],
                                Path(args.fact_sheet) if args.fact_sheet else None,
                                args.min_words, args.max_words)
        for r in reports:
            print(f"{'OK  ' if r.ok else 'FAIL'} {r.path} ({r.words} words)")
            for e in r.errors:
                print(f"     error: {e}")
            for w in r.warnings:
                print(f"     warning: {w}")
        return 0 if all(r.ok for r in reports) else 1

    if cmd == "scan":
        clean, warnings = sanitize_text(Path(args.file).read_text(encoding="utf-8-sig"), max_length=0)
        print(f"{len(clean)} characters after cleaning")
        _print_list("warnings:", warnings)
        if not warnings:
            print("no warnings")
        return 2 if any(w.startswith("instruction-like") for w in warnings) else 0

    raise AssertionError(cmd)  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``shortlist`` console script."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    path = _settings_path(args.settings)
    if args.command == "init" and args.write_settings and path is not None and not path.exists():
        path = None  # the file is about to be written with defaults
    try:
        settings = load_settings(path) if args.command != "test-rules" else Settings()
        return _run(args, settings)
    except (ConfigError, TrackerError, RawJobsError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
