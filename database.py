"""Small SQLite persistence layer for UPI Shield.

Only scan metadata and one-way hashes are stored. Uploaded screenshots and
full OCR text are never written to disk by this application.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("UPI_SHIELD_DB", str(BASE_DIR / "data" / "upi_shield.sqlite3")))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db() -> None:
    """Create the scan-history table and indexes when the app starts."""
    with closing(_connect()) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_sha256 TEXT NOT NULL,
                transaction_hash TEXT,
                upi_app TEXT NOT NULL,
                verdict TEXT NOT NULL,
                risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_scans_image_hash
                ON scans(image_sha256);

            CREATE INDEX IF NOT EXISTS idx_scans_transaction_hash
                ON scans(transaction_hash);

            CREATE INDEX IF NOT EXISTS idx_scans_created_at
                ON scans(created_at DESC);
            """
        )


def save_scan_and_check_duplicates(
    *,
    image_sha256: str,
    transaction_hash: str | None,
    upi_app: str,
    verdict: str,
    risk_score: int,
) -> dict[str, Any]:
    """Atomically check for earlier hashes and save this scan.

    BEGIN IMMEDIATE serializes the read/check/write sequence so two concurrent
    uploads cannot both be treated as the first occurrence of the same hash.
    """
    created_at = datetime.now(timezone.utc).isoformat()

    connection = _connect()
    try:
        connection.execute("BEGIN IMMEDIATE")

        duplicate_image = connection.execute(
            "SELECT COUNT(*) AS total FROM scans WHERE image_sha256 = ?",
            (image_sha256,),
        ).fetchone()["total"] > 0

        duplicate_transaction = False
        if transaction_hash:
            duplicate_transaction = connection.execute(
                "SELECT COUNT(*) AS total FROM scans WHERE transaction_hash = ?",
                (transaction_hash,),
            ).fetchone()["total"] > 0

        cursor = connection.execute(
            """
            INSERT INTO scans (
                image_sha256, transaction_hash, upi_app, verdict, risk_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                image_sha256,
                transaction_hash,
                upi_app,
                verdict,
                risk_score,
                created_at,
            ),
        )
        scan_id = cursor.lastrowid
        connection.execute("COMMIT")

        return {
            "scan_id": scan_id,
            "duplicate_image": duplicate_image,
            "duplicate_transaction": duplicate_transaction,
            "created_at": created_at,
        }
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def get_history(limit: int = 20) -> list[dict[str, Any]]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT id, upi_app, verdict, risk_score, created_at
            FROM scans
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_stats() -> dict[str, int]:
    with closing(_connect()) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN verdict = 'SUSPICIOUS' THEN 1 ELSE 0 END) AS suspicious
            FROM scans
            """
        ).fetchone()
        return {
            "total_scans": int(row["total"] or 0),
            "suspicious_scans": int(row["suspicious"] or 0),
        }
