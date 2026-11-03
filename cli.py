"""Local CLI: hermes gleif watch|schedule|unschedule|status|call."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

if __package__:
    from .prefix import cron_lines
    from .public_cron import CronUnread, Store
    from .safe_write import WriteRefused, remove_file, write_bytes
    from .service import dump, fail, invoke
    from . import errors, watch
else:
    from prefix import cron_lines
    from public_cron import CronUnread, Store
    from safe_write import WriteRefused, remove_file, write_bytes
    from service import dump, fail, invoke
    import errors
    import watch

JOB_NAME = "gleif-watch"
SCRIPT_NAME = "gleif-watch.py"
SCHEDULE = "0 8 * * *"
PROMPT = (
    "Read each watched LEI record. [SILENT] Deliver the script stdout. "
    "The first successful read stores a baseline and prints no line."
)
GONE = "No cron job named gleif-watch was found."
LOCAL_ONLY = "This plugin delivers the morning line to local only, so it is not sent to another chat."
SCHEDULER_NOTE = (
    "The job does not fire until a scheduler is serving this profile. "
    "hermes cron status says the jobs will not fire and, on the default profile, "
    "prints hermes --profile default gateway install. "
    "Local delivery keeps a printed line under cron/output and sends nothing to a chat."
)
_ZONE = re.compile(r"[A-Za-z0-9_+/-]{1,80}\Z")

SCRIPT_TEXT = """#!/usr/bin/env python3
\"\"\"Morning LEI watch. Empty stdout sends no message.\"\"\"
import sys
from pathlib import Path


def main() -> int:
    try:
        from hermes_constants import get_hermes_home
    except Exception:
        sys.stderr.write("gleif is not installed, so the morning watch did not run.\\n")
        return 1
    plugin = Path(get_hermes_home()) / "plugins" / "gleif"
    if not (plugin / "watch.py").is_file():
        sys.stderr.write("gleif is not installed, so the morning watch did not run.\\n")
        return 1
    sys.path.insert(0, str(plugin))
    try:
        import watch
    except Exception:
        sys.stderr.write("gleif is not installed, so the morning watch did not run.\\n")
        return 1
    text = watch.watch_stdout()
    if text:
        sys.stdout.write(text)
        if not text.endswith("\\n"):
            sys.stdout.write("\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def setup_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command", required=True)
    watch_parser = sub.add_parser("watch", help="Add, remove, list, or run watched LEIs")
    watch_sub = watch_parser.add_subparsers(dest="watch_command", required=True)
    add = watch_sub.add_parser("add", help="Save one LEI")
    add.add_argument("lei")
    remove = watch_sub.add_parser("remove", help="Drop one LEI")
    remove.add_argument("lei")
    watch_sub.add_parser("list", help="List watched LEIs")
    watch_sub.add_parser("run", help="Compare today's read with the saved status")
    schedule = sub.add_parser("schedule", help="Create the local morning job")
    schedule.add_argument("--deliver", default="local", help="Only local is accepted")
    sub.add_parser("unschedule", help="Remove the morning job if it exists")
    sub.add_parser("status", help="Show whether the morning job exists")
    call = sub.add_parser("call", help="Call one tool and print JSON")
    call.add_argument("tool")
    call.add_argument("--json", default="{}")


def _home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def _config_timezone(text: str) -> str:
    """Top-level ``timezone`` from a Hermes config file. Nested keys are ignored."""
    for line in text.splitlines():
        if not line or line[0] in " \t#":
            continue
        if not line.startswith("timezone:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if " #" in raw:
            raw = raw.split(" #", 1)[0].rstrip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1].strip()
        if raw in {"", "~", "null", "Null", "NULL"}:
            return ""
        return raw
    return ""


def profile_zone_name() -> str:
    """IANA name from ``HERMES_TIMEZONE`` or the profile ``config.yaml`` ``timezone`` key."""
    reported = os.environ.get("HERMES_TIMEZONE", "").strip()
    if reported:
        return reported
    try:
        from hermes_constants import get_config_path

        text = Path(get_config_path()).read_text(encoding="utf-8")
    except Exception:
        return ""
    if not isinstance(text, str):
        return ""
    return _config_timezone(text)


def when_text() -> str:
    name = ""
    try:
        reported = profile_zone_name()
        if isinstance(reported, str):
            name = reported.strip()
    except Exception:
        name = ""
    if name and _ZONE.fullmatch(name):
        return f"08:00 in the profile timezone {name}."
    return "08:00 in the machine local time."


def write_watch_script(home: Path | None = None) -> str:
    root = home or _home()
    write_bytes(Path(root), f"scripts/{SCRIPT_NAME}", SCRIPT_TEXT.encode("utf-8"), create=True)
    return f"scripts/{SCRIPT_NAME}"


def _lines(job_id: str | None = None) -> str:
    text = "\n".join(cron_lines(job_id))
    if not job_id:
        text += "\nThe cron output had no job id. Read the id from cron list, then run cron remove with that id."
    return text


def _drop_watch_script(home: Path | None) -> str:
    try:
        root = home or _home()
    except Exception:
        return "The watch script was not removed because the Hermes home could not be resolved."
    try:
        kind = remove_file(Path(root), f"scripts/{SCRIPT_NAME}")
    except WriteRefused as exc:
        return f"The watch script was not removed ({exc.kind})."
    except Exception:
        return "The watch script was not removed."
    if kind == "removed":
        return f"Removed scripts/{SCRIPT_NAME}."
    return ""


def schedule_job(store: Store, deliver: str, home: Path | None = None) -> tuple[int, str]:
    if deliver != "local":
        return 1, LOCAL_ONLY
    try:
        write_watch_script(home)
    except WriteRefused as exc:
        return 1, f"The watch script was not written ({exc.kind})."
    except Exception:
        return 1, "The Hermes home could not be resolved, so the morning job was not created."
    try:
        existing = store.job_by_name(JOB_NAME)
    except CronUnread as exc:
        return 1, str(exc) or "hermes cron list failed"
    if existing:
        return 0, f"{JOB_NAME} is already scheduled. {when_text()} {SCHEDULER_NOTE}\n" + _lines(existing.get("id") or None)
    try:
        created = store.create_job(
            prompt=PROMPT,
            schedule=SCHEDULE,
            name=JOB_NAME,
            deliver="local",
            script=SCRIPT_NAME,
        )
    except Exception as exc:
        message = str(exc) or "hermes cron create failed"
        try:
            still_there = store.job_by_name(JOB_NAME)
        except Exception:
            still_there = {"id": ""}
        if not still_there:
            note = _drop_watch_script(home)
            if note:
                message = message + "\n" + note
        return 1, message
    return 0, f"Scheduled {JOB_NAME}. {when_text()} {SCHEDULER_NOTE}\n" + _lines(created.get("id") or None)


def job_status(store: Store) -> tuple[int, str]:
    try:
        job = store.job_by_name(JOB_NAME)
    except CronUnread as exc:
        return 1, str(exc) or "hermes cron list failed"
    if not job:
        return 0, GONE
    ident = job.get("id") or ""
    return 0, f"Cron job {ident} named {JOB_NAME} is scheduled.\n" + _lines(ident or None)


def unschedule_job(store: Store, home: Path | None = None) -> tuple[int, str]:
    try:
        job = store.job_by_name(JOB_NAME)
    except CronUnread as exc:
        return 1, str(exc) or "hermes cron list failed"
    if not job:
        note = _drop_watch_script(home)
        if note:
            return 0, GONE + "\n" + note
        return 0, GONE
    ident = job.get("id") or ""
    if not ident:
        return 1, "The cron job had no id, so it was not removed."
    if not store.remove_job(ident):
        return 1, f"The cron job {ident} was not removed."
    text = f"Removed cron job {ident}.\n" + _lines(ident)
    note = _drop_watch_script(home)
    if note:
        text += "\n" + note
    return 0, text


def _print_watch(payload: dict) -> tuple[int, str]:
    return (0 if payload.get("ok") else 1), dump(payload)


def handle(args: argparse.Namespace, store: Store | None = None) -> int:
    command = getattr(args, "command", None)
    holder = store or Store()
    if command == "schedule":
        code, text = schedule_job(holder, getattr(args, "deliver", "local"))
    elif command == "unschedule":
        code, text = unschedule_job(holder)
    elif command == "status":
        code, text = job_status(holder)
    elif command == "watch":
        action = getattr(args, "watch_command", None)
        if action == "add":
            code, text = _print_watch(watch.add_lei(args.lei))
        elif action == "remove":
            code, text = _print_watch(watch.remove_lei(args.lei))
        elif action == "list":
            code, text = _print_watch(watch.list_leis())
        elif action == "run":
            text = watch.watch_stdout()
            if text:
                print(text, end="" if text.endswith("\n") else "\n")
            return 0
        else:
            print("Use watch add, remove, list, or run.")
            return 1
    elif command == "call":
        raw = getattr(args, "json", "{}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print(dump(fail(errors.ARGS_INVALID)))
            return 1
        if not isinstance(payload, dict):
            print(dump(fail(errors.ARGS_INVALID)))
            return 1
        body = invoke(getattr(args, "tool", ""), payload)
        print(dump(body))
        return 0 if body.get("ok") else 1
    else:
        print("Use watch, schedule, unschedule, status, or call.")
        return 1
    print(text)
    return code
