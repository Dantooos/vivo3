from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Tuple, List

BASE_DIR = Path(__file__).resolve().parent


def _db_path(db_path: str) -> str:
    path = Path(db_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


def init_db(db_path: str = "data.db") -> None:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY,
                first_seen_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                country TEXT,
                category TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ads_queue (
                url TEXT PRIMARY KEY,
                added_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'new',
                last_error TEXT,
                assigned_profile_id TEXT,
                sent_ts TIMESTAMP,
                opened_ts TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_seen_url(
    url: str, country: str, category: str, db_path: str = "data.db"
) -> bool:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO seen_urls (url, country, category) VALUES (?, ?, ?)",
            (url, country, category),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] == 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def enqueue_url(url: str, db_path: str = "data.db") -> bool:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ads_queue (url, status) VALUES (?, 'new')",
            (url,),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] == 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def get_next_queue_item(
    profile_id: str,
    countries: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    db_path: str = "data.db",
) -> Optional[Tuple[str]]:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN EXCLUSIVE")

        filters = ["q.status = 'new'"]
        params: List[str] = []

        if countries:
            placeholders = ",".join(["?"] * len(countries))
            filters.append(f"s.country IN ({placeholders})")
            params.extend(countries)
        if categories:
            placeholders = ",".join(["?"] * len(categories))
            filters.append(f"s.category IN ({placeholders})")
            params.extend(categories)

        where_clause = " AND ".join(filters)

        query = f"""
            SELECT q.url
            FROM ads_queue q
            JOIN seen_urls s ON s.url = q.url
            WHERE {where_clause}
            ORDER BY q.added_ts ASC
            LIMIT 1
        """
        row = conn.execute(query, params).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        (url,) = row
        conn.execute(
            """
            UPDATE ads_queue
            SET status = 'sent', assigned_profile_id = ?, sent_ts = CURRENT_TIMESTAMP
            WHERE url = ?
            """,
            (profile_id, url),
        )
        conn.execute("COMMIT")
        return (url,)
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        return None
    finally:
        conn.close()


def mark_queue_opened(url: str, db_path: str = "data.db") -> None:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            "UPDATE ads_queue SET status = 'opened', opened_ts = CURRENT_TIMESTAMP WHERE url = ?",
            (url,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_queue_error(url: str, message: str, db_path: str = "data.db") -> None:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            "UPDATE ads_queue SET status = 'error', last_error = ? WHERE url = ?",
            (message, url),
        )
        conn.commit()
    finally:
        conn.close()


def get_seen_count(db_path: str = "data.db") -> int:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        return conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
    finally:
        conn.close()


def get_queue_counts(db_path: str = "data.db") -> dict:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM ads_queue GROUP BY status"
        ).fetchall()
        counts = {"total": 0}
        total = conn.execute("SELECT COUNT(*) FROM ads_queue").fetchone()[0]
        counts["total"] = total
        for status, count in rows:
            counts[status] = count
        return counts
    finally:
        conn.close()


def get_recent_queue(db_path: str = "data.db", limit: int = 200) -> list:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        rows = conn.execute(
            """
            SELECT url, status, added_ts, assigned_profile_id, sent_ts, opened_ts
            FROM ads_queue
            ORDER BY added_ts DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return rows
    finally:
        conn.close()


def clear_queue(db_path: str = "data.db") -> None:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute("DELETE FROM ads_queue")
        conn.commit()
    finally:
        conn.close()
