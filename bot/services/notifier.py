"""
Notification service — sends poll and match results to group chat.
"""
import logging

from aiogram import Bot

from bot.database.operations import update_round_poll

logger = logging.getLogger(__name__)


async def send_optin_poll(bot: Bot, chat_id: int, round_id: int) -> None:
    """
    Send a non-anonymous poll to the group chat for opt-in.
    Saves poll_id to the round for tracking votes.
    """
    message = await bot.send_poll(
        chat_id=chat_id,
        question="☕ Привет! Будешь участвовать во встречах Научного Кофе в этом месяце?",
        options=["Да! 🤗", "Не в этот раз 🙅"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )

    # Save poll_id for tracking votes in PollAnswer handler
    await update_round_poll(
        round_id=round_id,
        poll_id=message.poll.id,
        poll_message_id=message.message_id,
    )

    logger.info(f"Opt-in poll sent to chat {chat_id}, poll_id={message.poll.id}")


async def send_pairs_message(
    bot: Bot,
    chat_id: int,
    matches: list[dict],
) -> None:
    """
    Post matching results to the group chat.
    Splits into multiple messages if text exceeds Telegram's 4096 char limit.
    """
    header = (
        "☕ <b>Пары для Научного Кофе составлены!</b>\n"
        "Ищи в списке ниже, с кем встречаешься в этом месяце:\n"
    )
    footer = (
        "\nНапиши собеседнику в личку, чтобы договориться "
        "об удобном времени и формате встречи ☕"
    )

    pair_lines = []
    for match in matches:
        users = match["users"]
        mentions = [_mention(u) for u in users]
        pair_lines.append(f"  ☕ {' x '.join(mentions)}")

    # Split into chunks respecting 4096 char limit
    MAX_LEN = 4096
    chunks = []
    current = header

    for line in pair_lines:
        # +1 for newline
        if len(current) + len(line) + 1 + len(footer) > MAX_LEN:
            chunks.append(current)
            current = ""
        current += line + "\n"

    current += footer
    chunks.append(current)

    for chunk in chunks:
        await bot.send_message(chat_id, chunk)

    logger.info(f"Pairs message sent to chat {chat_id}: {len(matches)} pairs ({len(chunks)} msg)")


async def send_meeting_nudge(bot: Bot, chat_id: int) -> None:
    """~18th: nudge in chat to remind about meetings."""
    await bot.send_message(
        chat_id,
        "👋 <b>Напоминание</b>\n\n"
        "Не забудьте встретиться со своим кофе-партнёром!\n"
        "Если ещё не списались — самое время написать ☕",
    )
    logger.info(f"Meeting nudge sent to chat {chat_id}")


async def send_feedback_poll(bot: Bot, chat_id: int) -> None:
    """~30th: ask in chat if people met their partners."""
    await bot.send_poll(
        chat_id=chat_id,
        question="☕ Как прошёл Научный Кофе в этом месяце? Удалось встретиться?",
        options=["Да, встретились! 👍", "Не получилось 😕", "Не участвовал(а)"],
        is_anonymous=True,
    )
    logger.info(f"Feedback poll sent to chat {chat_id}")


def _mention(user: dict) -> str:
    """Format user as @username or linked full_name."""
    if user.get("username"):
        return f"@{user['username']}"
    # Fallback: tg://user link so people can still click
    name = user.get("full_name", "Участник")
    tg_id = user.get("telegram_id", "")
    if tg_id:
        return f'<a href="tg://user?id={tg_id}">{name}</a>'
    return name
