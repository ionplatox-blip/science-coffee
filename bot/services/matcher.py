"""
Matching service — pairs participants for coffee meetings.
Random matching only.
"""
import logging
import random
from datetime import datetime

from bot.config import config
from bot.database.operations import (
    get_opted_in_users,
    get_recent_pairs,
    create_match,
    create_round,
    update_round_status,
    get_current_round,
)

logger = logging.getLogger(__name__)


async def run_matching(round_id: int) -> list[dict]:
    """
    Main matching function.
    1. Get opted-in users
    2. Load recent pairs to avoid repeats
    3. Form random pairs
    4. Save to DB
    Returns list of created matches with user info.
    """
    users = await get_opted_in_users(round_id)

    if len(users) < config.min_participants:
        logger.warning(
            f"Only {len(users)} participants — need at least {config.min_participants}. "
            "Skipping this round."
        )
        return []

    recent_pairs = await get_recent_pairs(config.history_lookback)
    logger.info(f"Loaded {len(recent_pairs)} recent pairs to avoid")

    pairs = _form_pairs(users, recent_pairs)
    logger.info(f"Formed {len(pairs)} pairs from {len(users)} participants")

    # Save matches to DB
    matches = []
    for pair in pairs:
        if len(pair) == 2:
            match_id = await create_match(
                round_id=round_id,
                user1_id=pair[0]["telegram_id"],
                user2_id=pair[1]["telegram_id"],
            )
            matches.append({"id": match_id, "users": pair, "is_trio": False})
        elif len(pair) == 3:
            match_id = await create_match(
                round_id=round_id,
                user1_id=pair[0]["telegram_id"],
                user2_id=pair[1]["telegram_id"],
                user3_id=pair[2]["telegram_id"],
            )
            matches.append({"id": match_id, "users": pair, "is_trio": True})

    await update_round_status(round_id, "active")
    return matches


def _form_pairs(
    users: list[dict],
    recent_pairs: set[tuple[int, int]],
) -> list[list[dict]]:
    """
    Form pairs avoiding recent matches.
    If odd number — last group becomes a trio.
    """
    shuffled = users.copy()
    random.shuffle(shuffled)

    pairs = []
    used = set()

    for i in range(len(shuffled)):
        if i in used:
            continue

        user_a = shuffled[i]
        best_j = None

        for j in range(i + 1, len(shuffled)):
            if j in used:
                continue
            pair_key = tuple(sorted((
                user_a["telegram_id"],
                shuffled[j]["telegram_id"],
            )))
            if pair_key not in recent_pairs:
                best_j = j
                break

        # Fallback: take any available partner
        if best_j is None:
            for j in range(i + 1, len(shuffled)):
                if j not in used:
                    best_j = j
                    break

        if best_j is None:
            # Last person — attach to last pair as trio
            if pairs:
                pairs[-1].append(user_a)
            used.add(i)
            continue

        used.add(i)
        used.add(best_j)
        pairs.append([user_a, shuffled[best_j]])

    return pairs


async def create_monthly_round(chat_id: int | None = None) -> dict | None:
    """
    Create a new round for the current month.
    Returns the round dict or None if one already exists.
    """
    import calendar

    existing = await get_current_round()
    if existing:
        logger.info(f"Round already exists: {existing['id']}")
        return existing

    today = datetime.now()
    first_day = today.replace(day=1)
    last_day_num = calendar.monthrange(today.year, today.month)[1]
    last_day = today.replace(day=last_day_num)

    round_id = await create_round(
        month_start=first_day.strftime("%Y-%m-%d"),
        month_end=last_day.strftime("%Y-%m-%d"),
        chat_id=chat_id,
    )

    logger.info(f"Created monthly round {round_id}: {first_day.date()} — {last_day.date()}")
    return {
        "id": round_id,
        "month_start": first_day.strftime("%Y-%m-%d"),
        "month_end": last_day.strftime("%Y-%m-%d"),
        "chat_id": chat_id,
        "status": "planned",
    }
