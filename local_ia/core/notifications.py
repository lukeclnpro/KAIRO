"""Événements courts partagés entre Sleep et l'interface KAIRO."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS app_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS app_notifications_created_idx ON app_notifications(created_at)"
    )
    connection.commit()


def publish(connection: sqlite3.Connection, kind: str, title: str, message: str) -> None:
    ensure_schema(connection)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.execute(
        "INSERT INTO app_notifications (kind, title, message, created_at) VALUES (?, ?, ?, ?)",
        (str(kind), str(title), str(message), created_at),
    )
    connection.execute(
        "DELETE FROM app_notifications WHERE created_at < ?",
        ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds"),),
    )
    connection.commit()


def consume(connection: sqlite3.Connection, limit: int = 20) -> list[dict]:
    ensure_schema(connection)
    selected_limit = max(1, min(int(limit), 100))
    connection.execute("BEGIN IMMEDIATE")
    try:
        rows = connection.execute(
            "SELECT id, kind, title, message, created_at FROM app_notifications "
            "ORDER BY id LIMIT ?",
            (selected_limit,),
        ).fetchall()
        if rows:
            connection.executemany(
                "DELETE FROM app_notifications WHERE id = ?",
                ((row[0],) for row in rows),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return [
        {"id": row[0], "kind": row[1], "title": row[2], "message": row[3], "created_at": row[4]}
        for row in rows
    ]