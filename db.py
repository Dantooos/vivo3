from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Tuple

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
            CREATE TABLE IF NOT EXISTS ads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT UNIQUE,
                country       TEXT,
                category      TEXT,
                title         TEXT,
                price         INTEGER,
                views         INTEGER,
                seller_ads    INTEGER,
                has_field     INTEGER,
                created_at    TEXT,
                seller_name   TEXT,
                first_seen    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status        TEXT DEFAULT 'new',
                profile_id    INTEGER,
                opened_at     TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_ad_if_new(data: dict, db_path: str = "data.db") -> bool:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO ads (
                url, country, category, title, price, views, seller_ads, has_field,
                created_at, seller_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("url"),
                data.get("country"),
                data.get("category"),
                data.get("title"),
                data.get("price"),
                data.get("views"),
                data.get("seller_ads"),
                data.get("has_field"),
                data.get("created_at"),
                data.get("seller_name"),
            ),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] == 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def get_next_ad_for_profile(
    profile_id: int, db_path: str = "data.db"
) -> Optional[Tuple[int, str]]:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute(
            """
            SELECT id, url FROM ads
            WHERE status = 'new'
            ORDER BY first_seen ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        ad_id, url = row
        conn.execute(
            "UPDATE ads SET status = 'in_progress', profile_id = ? WHERE id = ?",
            (profile_id, ad_id),
        )
        conn.execute("COMMIT")
        return ad_id, url
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        return None
    finally:
        conn.close()


def mark_ad_opened(ad_id: int, db_path: str = "data.db") -> None:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute(
            "UPDATE ads SET status = 'opened', opened_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ad_id,),
        )
        conn.commit()
    finally:
        conn.close()


def mark_ad_error(ad_id: int, message: str, db_path: str = "data.db") -> None:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.execute("UPDATE ads SET status = 'error' WHERE id = ?", (ad_id,))
        conn.commit()
    finally:
        conn.close()


def get_counts_by_status(db_path: str = "data.db") -> dict:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM ads GROUP BY status"
        ).fetchall()
        counts = {"total": 0}
        total = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
        counts["total"] = total
        for status, count in rows:
            counts[status] = count
        return counts
    finally:
        conn.close()


def get_recent_ads(db_path: str = "data.db", limit: int = 200) -> list:
    path = _db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        rows = conn.execute(
            """
            SELECT id, url, price, views, seller_ads, country, category, status, first_seen
            FROM ads
            ORDER BY first_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return rows
    finally:
        conn.close()
