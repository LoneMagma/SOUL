"""
SOUL — Pattern Memory Engine
=============================
SQLite-backed behavioral pattern detection.
NEW: Persistent session memory — last N conversation exchanges
     are saved and reloaded on next boot so SOUL remembers context.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

DB_PATH = Path(__file__).parent.parent.parent / "soul_memory.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            value       TEXT,
            metadata    TEXT
        );

        CREATE TABLE IF NOT EXISTS patterns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_event   TEXT NOT NULL,
            trigger_value   TEXT NOT NULL,
            follow_action   TEXT NOT NULL,
            follow_params   TEXT,
            occurrence_count INTEGER DEFAULT 0,
            is_active       INTEGER DEFAULT 0,
            created_at      TEXT,
            last_seen_at    TEXT,
            display_text    TEXT
        );

        CREATE TABLE IF NOT EXISTS memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT UNIQUE NOT NULL,
            value       TEXT,
            updated_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS session_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            session_id  TEXT
        );
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# EVENT LOGGING
# ─────────────────────────────────────────────

def log_event(event_type: str, value: str, metadata: dict = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO events (timestamp, event_type, value, metadata) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), event_type, value, json.dumps(metadata or {}))
    )
    conn.commit()
    conn.close()


def get_recent_events(limit: int = 50) -> List[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# SESSION MEMORY (persistent across restarts)
# ─────────────────────────────────────────────

def save_exchange(role: str, content: str, session_id: str = "default"):
    """Save a single message to persistent history."""
    conn = get_db()
    conn.execute(
        "INSERT INTO session_history (timestamp, role, content, session_id) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), role, content, session_id)
    )
    # Keep last 2000 — enough for full debug sessions
    conn.execute("""
        DELETE FROM session_history WHERE id NOT IN (
            SELECT id FROM session_history ORDER BY id DESC LIMIT 2000
        )
    """)
    conn.commit()
    conn.close()


def load_recent_history(limit: int = 10) -> List[dict]:
    """Load the last N exchanges for injection into new session context."""
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content, timestamp FROM session_history ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    # Return in chronological order
    history = [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
               for r in reversed(rows)]
    return history


def format_memory_for_llm(limit: int = 8) -> str:
    """
    Format recent history as a compact memory summary for LLM injection.
    Scrubs any stale user_name references from old sessions.
    """
    history = load_recent_history(limit)
    if not history:
        return ""

    # Load current config to get correct user_name
    try:
        from config import load_config as _lc
        _cfg = _lc()
        user_name = _cfg["entity"].get("user_name", "") or "User"
        entity_name = _cfg["entity"].get("name", "SOUL") or "SOUL"
    except Exception:
        user_name = "User"
        entity_name = "SOUL"

    lines = ["[Recent context from previous session:]"]
    for h in history:
        ts = h["timestamp"][:16].replace("T", " ")
        role_label = user_name if h["role"] == "user" else entity_name
        content = h["content"][:200] + "..." if len(h["content"]) > 200 else h["content"]
        # Scrub any stale hardcoded names — they should never appear in fresh injections
        # Strip raw context packets that were mistakenly saved as assistant messages
        if content.startswith("[") and "CPU:" in content and "RAM:" in content:
            continue  # skip raw context echoes saved as messages
        lines.append(f"[{ts}] {role_label}: {content}")

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def scrub_stale_names(old_names: list):
    """Remove session_history rows that contain any of the given old names.
    Called on startup to purge stale hardcoded user references from old sessions.
    """
    if not old_names:
        return
    conn = get_db()
    for name in old_names:
        conn.execute(
            "DELETE FROM session_history WHERE content LIKE ?",
            (f"%{name}%",)
        )
    conn.commit()
    conn.close()


def save_key_fact(key: str, value: str):
    """Store a named memory fact that persists indefinitely."""
    conn = get_db()
    conn.execute("""
        INSERT INTO memories (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (key, value, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def recall_fact(key: str) -> Optional[str]:
    conn = get_db()
    row = conn.execute("SELECT value FROM memories WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def get_all_facts() -> dict:
    conn = get_db()
    rows = conn.execute("SELECT key, value, updated_at FROM memories").fetchall()
    conn.close()
    return {r["key"]: {"value": r["value"], "updated": r["updated_at"]} for r in rows}


# ─────────────────────────────────────────────
# PATTERN ENGINE
# ─────────────────────────────────────────────

class PatternEngine:
    def __init__(self, threshold: int = 3, window_minutes: int = 10):
        self.threshold = threshold
        self.window_minutes = window_minutes
        init_db()

    def observe(self, event_type: str, value: str, metadata: dict = None):
        log_event(event_type, value, metadata)
        self._update_patterns(event_type, value)

    def _update_patterns(self, event_type: str, value: str):
        conn = get_db()
        preceding = conn.execute("""
            SELECT e1.event_type, e1.value, COUNT(*) as co_count
            FROM events e1
            JOIN events e2 ON (
                e2.event_type = ? AND e2.value = ?
                AND e2.id > e1.id AND e2.id - e1.id <= 3
            )
            WHERE e1.event_type != ? OR e1.value != ?
            GROUP BY e1.event_type, e1.value
            HAVING co_count >= ?
        """, (event_type, value, event_type, value, self.threshold)).fetchall()

        now = datetime.now().isoformat()
        for row in preceding:
            existing = conn.execute("""
                SELECT id, occurrence_count FROM patterns
                WHERE trigger_event = ? AND trigger_value = ? AND follow_action = 'suggest_action'
            """, (row["event_type"], row["value"])).fetchone()

            if existing:
                new_count = existing["occurrence_count"] + 1
                conn.execute(
                    "UPDATE patterns SET occurrence_count = ?, is_active = ?, last_seen_at = ? WHERE id = ?",
                    (new_count, 1 if new_count >= self.threshold else 0, now, existing["id"])
                )
            else:
                conn.execute("""
                    INSERT INTO patterns
                    (trigger_event, trigger_value, follow_action, occurrence_count, is_active, created_at, last_seen_at, display_text)
                    VALUES (?, ?, 'suggest_action', 1, 0, ?, ?, ?)
                """, (
                    row["event_type"], row["value"], now, now,
                    f"When {row['value']} -> {event_type}: {value}"
                ))
        conn.commit()
        conn.close()

    def get_active_patterns(self) -> List[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM patterns WHERE is_active = 1 ORDER BY occurrence_count DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def check_trigger(self, event_type: str, value: str) -> Optional[dict]:
        conn = get_db()
        pattern = conn.execute("""
            SELECT * FROM patterns
            WHERE trigger_event = ? AND trigger_value = ? AND is_active = 1
            LIMIT 1
        """, (event_type, value)).fetchone()
        conn.close()
        return dict(pattern) if pattern else None

    def summary_for_llm(self) -> str:
        patterns = self.get_active_patterns()
        if not patterns:
            return "No patterns learned yet."
        lines = [f"- {p['display_text']} (seen {p['occurrence_count']}x)" for p in patterns[:5]]
        return "Learned behavioral patterns:\n" + "\n".join(lines)

    def save_memory(self, key: str, value: str):
        save_key_fact(key, value)

    def recall(self, key: str) -> Optional[str]:
        return recall_fact(key)
