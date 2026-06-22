"""
Хранилище диалогов на SQLite — лёгкое, без отдельного сервера БД,
переживает рестарт процесса (в отличие от хранения в памяти).
Каждый клиент идентифицируется по номеру WhatsApp (from_number).
"""
import sqlite3
import json
import time
from contextlib import contextmanager
from typing import List, Dict, Optional

from app.config import CONVERSATIONS_DB_PATH, MAX_HISTORY_MESSAGES


def _init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_state (
                phone TEXT PRIMARY KEY,
                escalated INTEGER NOT NULL DEFAULT 0,
                escalated_at REAL,
                lead_data TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()


@contextmanager
def _connect():
    conn = sqlite3.connect(CONVERSATIONS_DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


_init_db()


def add_message(phone: str, role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (phone, role, content, created_at) VALUES (?, ?, ?, ?)",
            (phone, role, content, time.time()),
        )
        conn.commit()


def get_history(phone: str, limit: int = MAX_HISTORY_MESSAGES) -> List[Dict[str, str]]:
    """Возвращает последние N сообщений в хронологическом порядке для передачи в Claude."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT role, content FROM messages WHERE phone = ? ORDER BY id DESC LIMIT ?",
            (phone, limit),
        )
        rows = cur.fetchall()
    rows.reverse()
    return [{"role": r, "content": c} for r, c in rows]


def is_escalated(phone: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("SELECT escalated FROM client_state WHERE phone = ?", (phone,))
        row = cur.fetchone()
    return bool(row and row[0])


def set_escalated(phone: str, value: bool = True) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO client_state (phone, escalated, escalated_at, lead_data, updated_at)
            VALUES (?, ?, ?, '{}', ?)
            ON CONFLICT(phone) DO UPDATE SET escalated = ?, escalated_at = ?, updated_at = ?
        """, (phone, int(value), now, now, int(value), now, now))
        conn.commit()


def get_lead_data(phone: str) -> Dict:
    with _connect() as conn:
        cur = conn.execute("SELECT lead_data FROM client_state WHERE phone = ?", (phone,))
        row = cur.fetchone()
    if not row:
        return {}
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {}


def update_lead_data(phone: str, patch: Dict) -> Dict:
    """Сливает patch в текущие данные лида по клиенту и сохраняет."""
    current = get_lead_data(phone)
    current.update({k: v for k, v in patch.items() if v is not None})
    now = time.time()
    with _connect() as conn:
        conn.execute("""
            INSERT INTO client_state (phone, escalated, escalated_at, lead_data, updated_at)
            VALUES (?, 0, NULL, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET lead_data = ?, updated_at = ?
        """, (phone, json.dumps(current, ensure_ascii=False), now, json.dumps(current, ensure_ascii=False), now))
        conn.commit()
    return current


def reset_conversation(phone: str) -> None:
    """Используется командой сброса /reset для тестирования."""
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))
        conn.execute("DELETE FROM client_state WHERE phone = ?", (phone,))
        conn.commit()
