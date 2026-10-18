"""Rappels persistants stockés dans la base SQLite locale de KAIRO."""

from __future__ import annotations

import calendar
import sqlite3
from datetime import datetime, timedelta, timezone

from local_ia.core.notifications import ensure_schema as ensure_notification_schema


ACTIVE_STATUSES = ("scheduled", "notified")
REPEAT_RULES = {None, "none", "daily", "weekly", "monthly"}
MAX_SNOOZE_MINUTES = 7 * 24 * 60


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_at TEXT NOT NULL,
            repeat_rule TEXT,
            repeat_day INTEGER,
            status TEXT NOT NULL DEFAULT 'scheduled',
            created_at TEXT NOT NULL,
            last_notified_at TEXT
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders(status, due_at)"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(reminders)")}
    if "repeat_day" not in columns:
        connection.execute("ALTER TABLE reminders ADD COLUMN repeat_day INTEGER")
    legacy_monthly = connection.execute(
        "SELECT id, due_at FROM reminders WHERE repeat_rule = 'monthly' AND repeat_day IS NULL"
    ).fetchall()
    for reminder_id, due_at in legacy_monthly:
        connection.execute(
            "UPDATE reminders SET repeat_day = ? WHERE id = ?",
            (datetime.fromisoformat(due_at).day, reminder_id),
        )
    connection.commit()


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc)


def _parse_due_at(value: str) -> datetime:
    try:
        due_at = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("Échéance invalide : utilise une date ISO 8601.") from error
    if due_at.tzinfo is None:
        due_at = due_at.astimezone()
    return due_at.astimezone(timezone.utc)


def _stored_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _local_datetime(value: str) -> str:
    return datetime.fromisoformat(value).astimezone().isoformat(timespec="seconds")


def _next_occurrence(
    value: datetime,
    rule: str,
    now: datetime,
    monthly_day: int | None = None,
) -> datetime:
    occurrence = value
    anchor_day = monthly_day or occurrence.day
    while occurrence <= now:
        if rule == "daily":
            occurrence += timedelta(days=1)
        elif rule == "weekly":
            occurrence += timedelta(weeks=1)
        else:
            month_index = occurrence.year * 12 + occurrence.month
            year, month_zero_based = divmod(month_index, 12)
            month = month_zero_based + 1
            day = min(anchor_day, calendar.monthrange(year, month)[1])
            occurrence = occurrence.replace(year=year, month=month, day=day)
    return occurrence


def _row(connection: sqlite3.Connection, reminder_id: int):
    return connection.execute(
        "SELECT id, title, due_at, repeat_rule, status, created_at, last_notified_at "
        "FROM reminders WHERE id = ?",
        (reminder_id,),
    ).fetchone()


def _serialize(row) -> dict:
    return {
        "id": row[0],
        "title": row[1],
        "due_at": _local_datetime(row[2]),
        "repeat": row[3],
        "status": row[4],
        "created_at": row[5],
        "last_notified_at": _local_datetime(row[6]) if row[6] else None,
    }


def use(
    connection: sqlite3.Connection,
    action: str,
    *,
    title: str | None = None,
    due_at: str | None = None,
    repeat: str | None = None,
    reminder_id: int | str | None = None,
    snooze_minutes: int = 10,
) -> dict:
    ensure_schema(connection)
    action = str(action or "").strip().casefold()
    now = _utc_now()

    if action == "create":
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("Le rappel doit avoir un titre.")
        if len(clean_title) > 500:
            raise ValueError("Le titre du rappel est limité à 500 caractères.")
        rule = str(repeat or "none").strip().casefold()
        if rule not in REPEAT_RULES:
            raise ValueError("Répétition acceptée : aucune, daily, weekly ou monthly.")
        due = _parse_due_at(due_at or "")
        if due <= now:
            raise ValueError("L’échéance du rappel doit être dans le futur.")
        cursor = connection.execute(
            "INSERT INTO reminders (title, due_at, repeat_rule, repeat_day, status, created_at) "
            "VALUES (?, ?, ?, ?, 'scheduled', ?)",
            (
                clean_title,
                _stored_datetime(due),
                None if rule == "none" else rule,
                due.day if rule == "monthly" else None,
                _stored_datetime(now),
            ),
        )
        connection.commit()
        return {"action": action, "reminder": _serialize(_row(connection, cursor.lastrowid))}

    if action == "list":
        rows = connection.execute(
            "SELECT id, title, due_at, repeat_rule, status, created_at, last_notified_at "
            "FROM reminders WHERE status IN (?, ?) ORDER BY due_at, id",
            ACTIVE_STATUSES,
        ).fetchall()
        return {"action": action, "reminders": [_serialize(row) for row in rows]}

    if action in {"complete", "cancel", "snooze"}:
        try:
            selected_id = int(reminder_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Un identifiant de rappel valide est requis.") from error
        current = _row(connection, selected_id)
        if current is None or current[4] not in ACTIVE_STATUSES:
            raise ValueError(f"Rappel actif introuvable : {selected_id}.")

        if action == "snooze":
            try:
                minutes = int(snooze_minutes)
            except (TypeError, ValueError) as error:
                raise ValueError("La durée du report doit être un nombre de minutes.") from error
            if not 1 <= minutes <= MAX_SNOOZE_MINUTES:
                raise ValueError("Le report doit être compris entre 1 minute et 7 jours.")
            connection.execute(
                "UPDATE reminders SET due_at = ?, status = 'scheduled' WHERE id = ?",
                (_stored_datetime(now + timedelta(minutes=minutes)), selected_id),
            )
        else:
            status = "completed" if action == "complete" else "cancelled"
            connection.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, selected_id))
        connection.commit()
        return {"action": action, "reminder": _serialize(_row(connection, selected_id))}

    raise ValueError("Action rappel inconnue : utilise create, list, complete, cancel ou snooze.")


def dispatch_due(
    connection: sqlite3.Connection,
    notify,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Notifie les rappels échus une fois, puis avance leur prochaine occurrence."""
    ensure_schema(connection)
    ensure_notification_schema(connection)
    current_time = _utc_now(now)
    rows = connection.execute(
        "SELECT id, title, due_at, repeat_rule, repeat_day FROM reminders "
        "WHERE status = 'scheduled' AND due_at <= ? ORDER BY due_at, id",
        (_stored_datetime(current_time),),
    ).fetchall()
    notifications = []
    for reminder_id, title, due_at, rule, repeat_day in rows:
        if rule:
            next_due = _next_occurrence(
                datetime.fromisoformat(due_at), rule, current_time, repeat_day
            )
            connection.execute(
                "UPDATE reminders SET due_at = ?, last_notified_at = ? WHERE id = ?",
                (_stored_datetime(next_due), _stored_datetime(current_time), reminder_id),
            )
        else:
            connection.execute(
                "UPDATE reminders SET status = 'notified', last_notified_at = ? WHERE id = ?",
                (_stored_datetime(current_time), reminder_id),
            )
        notifications.append({"id": reminder_id, "title": title, "repeat": rule})

    notification_created_at = _stored_datetime(current_time)
    for reminder in notifications:
        message = str(reminder["title"])
        if reminder["repeat"]:
            message += "\nRappel récurrent."
        connection.execute(
            "INSERT INTO app_notifications (kind, title, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("reminder", "Rappel KAIRO", message, notification_created_at),
        )
    connection.execute(
        "DELETE FROM app_notifications WHERE created_at < ?",
        (_stored_datetime(current_time - timedelta(days=1)),),
    )
    connection.commit()

    for reminder in notifications:
        notify(reminder)
    return notifications