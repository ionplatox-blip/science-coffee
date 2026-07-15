"""
Poll answer handler — captures votes from the opt-in poll.
Auto-registers users and records their participation.
"""
import logging

from aiogram import Router
from aiogram.types import PollAnswer

from bot.database.operations import (
    upsert_user,
    set_participation,
    get_round_by_poll_id,
)

logger = logging.getLogger(__name__)
router = Router()


@router.poll_answer()
async def on_poll_answer(poll_answer: PollAnswer):
    """
    Handle poll votes.
    Option 0 = "Да!" → opt in
    Option 1 = "Не в этот раз" → opt out
    Empty option_ids = retracted vote → opt out
    """
    user = poll_answer.user
    poll_id = poll_answer.poll_id
    option_ids = poll_answer.option_ids

    # Find the round for this poll
    round_data = await get_round_by_poll_id(poll_id)
    if not round_data:
        logger.debug(f"Poll {poll_id} not found in rounds — ignoring")
        return

    # Auto-register user from poll vote
    full_name = user.first_name or ""
    if user.last_name:
        full_name += f" {user.last_name}"

    await upsert_user(
        telegram_id=user.id,
        username=user.username,
        full_name=full_name.strip() or "—",
    )

    # Determine opt-in/out
    if not option_ids:
        # Vote retracted
        opted_in = False
    else:
        opted_in = 0 in option_ids  # Option 0 = "Да!"

    await set_participation(user.id, round_data["id"], opted_in)

    action = "IN" if opted_in else "OUT"
    logger.info(
        f"Poll vote: {user.id} (@{user.username}) opted {action} "
        f"for round #{round_data['id']}"
    )
