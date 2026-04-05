"""
profile.py - SQLite CRUD for student profiles.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _db_path() -> Path:
    from app.config import STUDENTS_DB
    return STUDENTS_DB


@contextmanager
def _conn():
    db = _db_path()
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS students (
                student_id  TEXT PRIMARY KEY,
                name        TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT,
                question    TEXT,
                topic       TEXT,
                key_concepts TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            );

            CREATE TABLE IF NOT EXISTS struggles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT,
                concept     TEXT,
                details     TEXT,
                resolved    BOOLEAN DEFAULT 0,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            );
        """)
    logger.info("Student database initialised at %s", _db_path())


def create_or_update_student(student_id: str, name: str) -> dict:
    """Create a new student or update their name."""
    with _conn() as con:
        con.execute(
            """
            INSERT INTO students (student_id, name)
            VALUES (?, ?)
            ON CONFLICT(student_id) DO UPDATE SET name = excluded.name
            """,
            (student_id, name),
        )
    return get_student_profile(student_id)


def get_student_profile(student_id: str) -> dict:
    """
    Return a dict with student info and interaction history.
    Creates a minimal record if the student doesn't exist yet.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()

        if row is None:
            # Auto-create on first access
            con.execute(
                "INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)",
                (student_id, student_id),
            )
            name = student_id
        else:
            name = row["name"]

        interactions = con.execute(
            """
            SELECT topic, key_concepts, timestamp
            FROM interactions
            WHERE student_id = ?
            ORDER BY timestamp DESC
            LIMIT 20
            """,
            (student_id,),
        ).fetchall()

        struggles = con.execute(
            """
            SELECT concept, details, resolved
            FROM struggles
            WHERE student_id = ? AND resolved = 0
            ORDER BY timestamp DESC
            """,
            (student_id,),
        ).fetchall()

        total = con.execute(
            "SELECT COUNT(*) as cnt FROM interactions WHERE student_id = ?",
            (student_id,),
        ).fetchone()["cnt"]

    # Build unique past topics list (most recent first, deduped)
    seen = set()
    past_topics = []
    for row in interactions:
        topic = row["topic"]
        if topic and topic not in seen:
            seen.add(topic)
            past_topics.append(topic)

    return {
        "student_id": student_id,
        "name": name,
        "past_topics": past_topics,
        "struggles": [
            {"concept": s["concept"], "details": s["details"]} for s in struggles
        ],
        "total_interactions": total,
    }


def update_student_profile(
    student_id: str,
    question: str,
    topic: str,
    key_concepts: list,
) -> None:
    """Log an interaction for the student."""
    with _conn() as con:
        # Ensure student record exists
        con.execute(
            "INSERT OR IGNORE INTO students (student_id, name) VALUES (?, ?)",
            (student_id, student_id),
        )
        con.execute(
            """
            INSERT INTO interactions (student_id, question, topic, key_concepts)
            VALUES (?, ?, ?, ?)
            """,
            (student_id, question, topic, ", ".join(key_concepts)),
        )
    logger.debug("Logged interaction for student '%s', topic='%s'", student_id, topic)


def add_struggle(student_id: str, concept: str, details: str) -> None:
    """Log a known struggle / misconception for a student."""
    with _conn() as con:
        con.execute(
            """
            INSERT INTO struggles (student_id, concept, details)
            VALUES (?, ?, ?)
            """,
            (student_id, concept, details),
        )
    logger.debug("Logged struggle for student '%s': %s", student_id, concept)


def resolve_struggle(student_id: str, concept: str) -> None:
    """Mark a struggle as resolved."""
    with _conn() as con:
        con.execute(
            """
            UPDATE struggles SET resolved = 1
            WHERE student_id = ? AND concept = ?
            """,
            (student_id, concept),
        )
