"""
audit.py — Structured audit log for Provenance Guard.

Every attribution decision and every appeal is recorded as a newline-delimited
JSON entry in logs/audit.jsonl. The log is append-only; entries are never
deleted or modified in place. Appeals update status by appending a new entry
that references the original content_id.

In-memory index: a dict mapping content_id → list index in the log file
is maintained at runtime so /appeal can look up and update records quickly
without re-reading the whole file on every request.
"""

import os
import json
from datetime import datetime, timezone

LOG_FILE = os.path.join("logs", "audit.jsonl")

# Runtime index: content_id → most recent full entry dict
_index: dict[str, dict] = {}


def _ensure_log_dir() -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def _load_index() -> None:
    """Load existing log into memory index on startup."""
    global _index
    _index = {}
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                cid = entry.get("content_id")
                if cid:
                    _index[cid] = entry
            except json.JSONDecodeError:
                pass


# Load on module import
_ensure_log_dir()
_load_index()


def append_log(entry: dict) -> None:
    """
    Append a structured entry to the audit log and update the in-memory index.
    """
    _ensure_log_dir()
    cid = entry.get("content_id")
    if cid:
        _index[cid] = entry

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Terminal summary
    attr = entry.get("attribution", "?")
    conf = entry.get("confidence", "?")
    status = entry.get("status", "?")
    cid_short = str(cid)[:8] if cid else "?"
    print(f"[AUDIT] {cid_short}... | attr={attr} | conf={conf} | status={status}")


def update_status(content_id: str, new_status: str, appeal_reasoning: str = "") -> bool:
    """
    Update a submission's status and append an appeal entry to the log.

    Returns True if the content_id was found, False otherwise.
    """
    if content_id not in _index:
        return False

    original = _index[content_id].copy()
    original["status"] = new_status
    original["appeal_timestamp"] = datetime.now(timezone.utc).isoformat()
    original["appeal_reasoning"] = appeal_reasoning
    original["event_type"] = "appeal"

    # Update index with new status
    _index[content_id] = original

    # Append appeal event to log
    append_log(original)
    return True


def get_log(limit: int = 20) -> list[dict]:
    """
    Return the most recent `limit` entries from the audit log.
    Reads from file to ensure accuracy (not just the in-memory index).
    """
    if not os.path.exists(LOG_FILE):
        return []

    entries = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    return entries[-limit:]
