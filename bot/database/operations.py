"""
CRUD operations — group chat model.
Each function opens/closes its own connection for simplicity.
"""
import logging

from bot.database.models import get_db

logger = logging.getLogger(__name__)


# ─── Users ───────────────────────────────────────────────

async def upsert_user(
    telegram_id: int,
    username: str | None = None,
    full_name: str = "",
) -> None:
    """Insert or update a user (auto-registered from poll vote)."""
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO users (telegram_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                is_active = 1
            """,
            (telegram_id, username, full_name),
        )
        await db.commit()
    finally:
        await db.close()


async def get_user(telegram_id: int) -> dict | None:
    """Get user by telegram_id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_user_count() -> int:
    """Total active users."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE is_active = 1"
        )
        row = await cursor.fetchone()
        return row["cnt"]
    finally:
        await db.close()


# ─── Rounds ──────────────────────────────────────────────

async def create_round(
    month_start: str,
    month_end: str,
    chat_id: int | None = None,
) -> int:
    """Create a new round, return its id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO rounds (month_start, month_end, chat_id) VALUES (?, ?, ?)",
            (month_start, month_end, chat_id),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_current_round() -> dict | None:
    """Get the latest active or planned round."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM rounds WHERE status IN ('planned', 'active') "
            "ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_round_poll(
    round_id: int,
    poll_id: str,
    poll_message_id: int,
) -> None:
    """Save poll_id and message_id after sending poll to chat."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE rounds SET poll_id = ?, poll_message_id = ? WHERE id = ?",
            (poll_id, poll_message_id, round_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_round_by_poll_id(poll_id: str) -> dict | None:
    """Find round by its Telegram poll_id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM rounds WHERE poll_id = ?", (poll_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_round_status(round_id: int, status: str) -> None:
    """Update round status."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE rounds SET status = ? WHERE id = ?", (status, round_id)
        )
        await db.commit()
    finally:
        await db.close()


async def get_round_stats() -> dict:
    """Aggregate stats across all rounds."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed "
            "FROM rounds"
        )
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


async def delete_round(round_id: int) -> None:
    """Delete a round and all its participations/matches/feedback."""
    db = await get_db()
    try:
        # Delete feedback for matches in this round
        await db.execute(
            "DELETE FROM feedback WHERE match_id IN "
            "(SELECT id FROM matches WHERE round_id = ?)",
            (round_id,),
        )
        await db.execute("DELETE FROM matches WHERE round_id = ?", (round_id,))
        await db.execute("DELETE FROM participations WHERE round_id = ?", (round_id,))
        await db.execute("DELETE FROM rounds WHERE id = ?", (round_id,))
        await db.commit()
    finally:
        await db.close()


# ─── Participations ──────────────────────────────────────

async def set_participation(user_id: int, round_id: int, opted_in: bool) -> None:
    """Record user's opt-in/out decision from poll vote."""
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO participations (user_id, round_id, opted_in)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, round_id) DO UPDATE SET
                opted_in = excluded.opted_in,
                decided_at = datetime('now')
            """,
            (user_id, round_id, int(opted_in)),
        )
        await db.commit()
    finally:
        await db.close()


async def get_opted_in_users(round_id: int) -> list[dict]:
    """Get all users who opted in for a specific round."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT u.* FROM users u
            JOIN participations p ON u.telegram_id = p.user_id
            WHERE p.round_id = ? AND p.opted_in = 1 AND u.is_active = 1
            """,
            (round_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


# ─── Matches ─────────────────────────────────────────────

async def create_match(
    round_id: int,
    user1_id: int,
    user2_id: int,
    user3_id: int | None = None,
) -> int:
    """Create a match, return its id."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO matches (round_id, user1_id, user2_id, user3_id)
            VALUES (?, ?, ?, ?)
            """,
            (round_id, user1_id, user2_id, user3_id),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_recent_pairs(lookback: int = 4) -> set[tuple[int, int]]:
    """Get all pairs from the last N rounds to avoid repeats."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT m.user1_id, m.user2_id, m.user3_id FROM matches m
            JOIN rounds r ON m.round_id = r.id
            WHERE r.id >= (
                SELECT COALESCE(MAX(id) - ? + 1, 1) FROM rounds
            )
            """,
            (lookback,),
        )
        pairs = set()
        for row in await cursor.fetchall():
            u1, u2, u3 = row["user1_id"], row["user2_id"], row["user3_id"]
            pairs.add(tuple(sorted((u1, u2))))
            if u3:
                pairs.add(tuple(sorted((u1, u3))))
                pairs.add(tuple(sorted((u2, u3))))
        return pairs
    finally:
        await db.close()


async def get_match_count() -> int:
    """Total matches ever created."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM matches")
        row = await cursor.fetchone()
        return row["cnt"]
    finally:
        await db.close()


# ─── Settings ────────────────────────────────────────────

async def set_setting(key: str, value: str) -> None:
    """Save a setting to the DB."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def get_setting(key: str) -> str | None:
    """Get a setting from the DB."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None
    finally:
        await db.close()


async def get_group_chat_id() -> int | None:
    """
    Get group chat ID. Priority:
    1. DB settings (auto-saved when bot is added to chat)
    2. Config (.env)
    """
    from bot.config import config

    # Try DB first
    val = await get_setting("group_chat_id")
    if val:
        return int(val)

    # Fallback to config
    if config.group_chat_id and config.group_chat_id != 0:
        return config.group_chat_id

    return None
