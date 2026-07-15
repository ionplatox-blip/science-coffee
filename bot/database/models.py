"""
Database schema — group chat model.
SQLite with WAL mode for concurrent reads.
"""
import aiosqlite
import pathlib
import logging

from bot.config import config

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id   INTEGER PRIMARY KEY,
    username      TEXT,
    full_name     TEXT NOT NULL,
    is_active     INTEGER DEFAULT 1,
    registered_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rounds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    month_start     TEXT NOT NULL,
    month_end       TEXT NOT NULL,
    chat_id         INTEGER,
    poll_id         TEXT,
    poll_message_id INTEGER,
    status          TEXT DEFAULT 'planned' CHECK(status IN ('planned', 'active', 'completed')),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS participations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(telegram_id),
    round_id   INTEGER NOT NULL REFERENCES rounds(id),
    opted_in   INTEGER DEFAULT 0,
    decided_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, round_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id    INTEGER NOT NULL REFERENCES rounds(id),
    user1_id    INTEGER NOT NULL REFERENCES users(telegram_id),
    user2_id    INTEGER NOT NULL REFERENCES users(telegram_id),
    user3_id    INTEGER REFERENCES users(telegram_id),
    status      TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'met', 'skipped')),
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id     INTEGER NOT NULL REFERENCES matches(id),
    from_user_id INTEGER NOT NULL REFERENCES users(telegram_id),
    rating       INTEGER CHECK(rating BETWEEN 1 AND 5),
    met          INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(match_id, from_user_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_participations_round ON participations(round_id);
CREATE INDEX IF NOT EXISTS idx_matches_round ON matches(round_id);
CREATE INDEX IF NOT EXISTS idx_matches_users ON matches(user1_id, user2_id);
"""


async def get_db() -> aiosqlite.Connection:
    """Open a database connection with WAL mode and row factory."""
    db_path = pathlib.Path(config.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Create all tables if they don't exist."""
    db = await get_db()
    try:
        await db.executescript(_SCHEMA)
        await db.commit()
        logger.info(f"Database ready: {config.db_path}")
    finally:
        await db.close()
