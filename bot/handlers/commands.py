"""
Admin commands for group chat:
  /coffee  — create round + send poll (admin only)
  /match   — run matching + post pairs (admin only)
  /stats   — show statistics (admin only)
  /chatid  — show chat ID (helper)
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import config
from bot.database.operations import (
    get_user_count,
    get_round_stats,
    get_current_round,
    get_opted_in_users,
    get_match_count,
)

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


# ─── /chatid — helper to get chat ID ────────────────────

@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """Show current chat ID — useful for .env setup."""
    await message.reply(
        f"Chat ID: <code>{message.chat.id}</code>\n\n"
        f"Пропиши это значение в <code>GROUP_CHAT_ID</code> в .env",
    )


# ─── /coffee — create round + send poll ─────────────────

@router.message(Command("coffee"))
async def cmd_coffee(message: Message):
    """Create a new round and send opt-in poll to the chat."""
    if not _is_admin(message.from_user.id):
        return

    from bot.services.matcher import create_monthly_round
    from bot.services.notifier import send_optin_poll

    round_data = await create_monthly_round(chat_id=message.chat.id)
    if not round_data:
        await message.reply("❌ Не удалось создать раунд")
        return

    await send_optin_poll(message.bot, message.chat.id, round_data["id"])
    logger.info(f"Round #{round_data['id']} created, poll sent to chat {message.chat.id}")


# ─── /match — run matching + post pairs ──────────────────

@router.message(Command("match"))
async def cmd_match(message: Message):
    """Run matching for the current round and post results."""
    if not _is_admin(message.from_user.id):
        return

    current_round = await get_current_round()
    if not current_round:
        await message.reply("❌ Нет активного раунда. Сначала /coffee")
        return

    from bot.services.matcher import run_matching
    from bot.services.notifier import send_pairs_message

    matches = await run_matching(current_round["id"])

    if not matches:
        await message.reply(
            f"⚠️ Недостаточно участников (минимум {config.min_participants}).\n"
            "Раунд пропущен."
        )
        return

    chat_id = current_round.get("chat_id") or message.chat.id
    await send_pairs_message(message.bot, chat_id, matches)
    logger.info(f"Matching done: {len(matches)} pairs posted to chat {chat_id}")


# ─── /stats — show statistics ────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show bot statistics."""
    if not _is_admin(message.from_user.id):
        return

    user_count = await get_user_count()
    round_stats = await get_round_stats()
    match_count = await get_match_count()
    current_round = await get_current_round()

    round_line = "Нет активного раунда"
    if current_round:
        opted = await get_opted_in_users(current_round["id"])
        round_line = (
            f"#{current_round['id']} ({current_round['status']})\n"
            f"   Период: {current_round['month_start']} — {current_round['month_end']}\n"
            f"   Записались: {len(opted)}"
        )

    await message.reply(
        "📊 <b>Статистика Научного Кофе</b>\n\n"
        f"👥 Пользователей: <b>{user_count}</b>\n"
        f"🔄 Раундов: {round_stats['total']} "
        f"(завершённых: {round_stats['completed']})\n"
        f"☕ Всего пар: {match_count}\n\n"
        f"📋 <b>Текущий раунд:</b>\n{round_line}"
    )
