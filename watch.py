"""Local watch list. The morning script prints a line only when a saved status changes."""
from __future__ import annotations

import json
import stat
from pathlib import Path

if __package__:
    from . import errors
    from .safe_write import WriteRefused, directory_is_real, write_bytes
    from .service import fail, lei_ok, lookup_lei
else:
    import errors
    from safe_write import WriteRefused, directory_is_real, write_bytes
    from service import fail, lei_ok, lookup_lei

PLUGIN_REL = "plugin-data/gleif/watch.json"
STATE_NAME = "watch.json"
MAX_LEIS = 10
_DATA_DIR: Path | None = None


def set_data_dir(path: Path | None) -> None:
    global _DATA_DIR
    _DATA_DIR = path


def _empty() -> dict:
    return {"version": 1, "leis": {}}


def _root_and_rel(directory: Path | None) -> tuple[Path, str]:
    if directory is not None:
        return directory, STATE_NAME
    if _DATA_DIR is not None:
        return _DATA_DIR, STATE_NAME
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()), PLUGIN_REL


def _state_path(directory: Path | None) -> tuple[Path, Path, str]:
    root, relative = _root_and_rel(directory)
    return root.joinpath(*Path(relative).parts), root, relative


def load_state(directory: Path | None = None) -> dict:
    path, _root, _relative = _state_path(directory)
    try:
        directory_is_real(path.parent)
    except WriteRefused as exc:
        raise WatchFileError("watch_unreadable") from exc
    try:
        info = path.lstat()
    except FileNotFoundError:
        return _empty()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise WatchFileError("watch_unreadable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WatchFileError("watch_unreadable") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("leis"), dict):
        raise WatchFileError("watch_unreadable")
    return payload


def save_state(payload: dict, directory: Path | None = None) -> None:
    _path, root, relative = _state_path(directory)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    try:
        write_bytes(root, relative, raw, create=True)
    except WriteRefused as exc:
        raise WatchFileError("watch_refused") from exc
    except (OSError, RuntimeError) as exc:
        raise WatchFileError("watch_refused") from exc


class WatchFileError(Exception):
    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


def _file_error(exc: WatchFileError) -> dict:
    if exc.error_type == "watch_full":
        return fail(errors.WATCH_FULL)
    if exc.error_type == "watch_refused":
        return fail(errors.WATCH_REFUSED)
    return fail(errors.WATCH_UNREADABLE)


def _leis(payload: dict) -> dict:
    leis = payload.get("leis")
    return leis if isinstance(leis, dict) else {}


def _code(value: object) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def add_lei(lei: object, directory: Path | None = None) -> dict:
    code = _code(lei)
    if not lei_ok(code):
        return fail(errors.LEI_INVALID)
    try:
        state = load_state(directory)
    except WatchFileError as exc:
        return _file_error(exc)
    except (OSError, RuntimeError):
        return fail(errors.WATCH_UNREADABLE)
    leis = _leis(state)
    if code in leis:
        return {
            "ok": True,
            "message": f"{code} is already on the watch list.",
            "leis": sorted(leis),
            "next_step": "Run the morning job, or add a different LEI.",
        }
    if len(leis) >= MAX_LEIS:
        return fail(errors.WATCH_FULL)
    leis[code] = None
    state["leis"] = leis
    state["version"] = 1
    try:
        save_state(state, directory)
    except WatchFileError as exc:
        return _file_error(exc)
    return {
        "ok": True,
        "message": f"Added {code}. The first successful read stores a baseline and prints no line.",
        "leis": sorted(leis),
        "next_step": "Run schedule when the list, the 08:00 job, and local delivery are what you want.",
    }


def remove_lei(lei: object, directory: Path | None = None) -> dict:
    code = _code(lei)
    if not lei_ok(code):
        return fail(errors.LEI_INVALID)
    try:
        state = load_state(directory)
    except WatchFileError as exc:
        return _file_error(exc)
    except (OSError, RuntimeError):
        return fail(errors.WATCH_UNREADABLE)
    leis = _leis(state)
    if code not in leis:
        return {
            "ok": True,
            "message": f"{code} was not on the watch list.",
            "leis": sorted(leis),
            "next_step": "List the watched LEIs before adding one.",
        }
    leis.pop(code, None)
    state["leis"] = leis
    try:
        save_state(state, directory)
    except WatchFileError as exc:
        return _file_error(exc)
    return {
        "ok": True,
        "message": f"Removed {code} from the watch list.",
        "leis": sorted(leis),
        "next_step": "The morning job keeps running until you unschedule it.",
    }


def list_leis(directory: Path | None = None) -> dict:
    try:
        state = load_state(directory)
    except WatchFileError as exc:
        return _file_error(exc)
    except (OSError, RuntimeError):
        return fail(errors.WATCH_UNREADABLE)
    rows = []
    for code in sorted(_leis(state)):
        snap = state["leis"][code]
        rows.append({"lei": code, "baseline": isinstance(snap, dict)})
    return {
        "ok": True,
        "message": f"{len(rows)} LEIs are on the watch list.",
        "leis": rows,
        "next_step": "Show this list before schedule. Delivery is local only.",
    }


def _snapshot(record: dict) -> dict:
    return {
        "registration_status": record.get("registration_status"),
        "entity_status": record.get("entity_status"),
        "golden_copy": record.get("golden_copy"),
    }


def _change_line(lei: str, previous: dict, current: dict) -> str | None:
    parts = []
    if previous.get("registration_status") != current.get("registration_status"):
        parts.append(
            f"registration.status {previous.get('registration_status')} -> {current.get('registration_status')}"
        )
    if previous.get("entity_status") != current.get("entity_status"):
        parts.append(f"entity.status {previous.get('entity_status')} -> {current.get('entity_status')}")
    if not parts:
        return None
    text = f"{lei} " + ". ".join(parts) + f". Golden copy {current.get('golden_copy') or 'absent'}."
    caution = current.get("caution") or ""
    if caution:
        text += " " + caution
    return text


def run_watch(directory: Path | None = None, transport=None) -> str:
    """Stdout for the morning job. An empty string sends no message."""
    try:
        state = load_state(directory)
    except WatchFileError:
        return "The watch file was not read. Saved statuses were kept.\n"
    except (OSError, RuntimeError):
        return "The watch file was not read. Saved statuses were kept.\n"
    leis = _leis(state)
    lines: list[str] = []
    dirty = False
    for code in sorted(leis):
        if not lei_ok(code):
            lines.append(f"{code} was not read. The saved status was kept.")
            continue
        try:
            record = lookup_lei(code, transport)
        except Exception:
            lines.append(f"{code} was not read. The saved status was kept.")
            continue
        if not record.get("ok"):
            lines.append(f"{code} was not read. The saved status was kept.")
            continue
        current = _snapshot(record)
        current["caution"] = record.get("caution") or ""
        previous = leis.get(code)
        if not isinstance(previous, dict):
            stored = _snapshot(record)
            leis[code] = stored
            dirty = True
            continue
        line = _change_line(code, previous, current)
        stored = _snapshot(record)
        if stored != {key: previous.get(key) for key in stored}:
            leis[code] = stored
            dirty = True
        if line:
            lines.append(line)
    if dirty:
        state["leis"] = leis
        state["version"] = 1
        try:
            save_state(state, directory)
        except WatchFileError:
            lines.append("The new status was not saved. The previous file was kept.")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def watch_stdout() -> str:
    return run_watch()
