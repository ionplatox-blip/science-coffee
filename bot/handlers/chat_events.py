"""
Chat events handler — detects when bot is added/removed from a group.
Auto-saves group_chat_id to settings.
"""
import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, ADMINISTRATOR

from bot.database.operations import set_setting

logger = logging.getLogger(__name__)
router = Router()


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> (IS_MEMBER | ADMINISTRATOR))
)
async def on_bot_added(event: ChatMemberUpdated):
    """Bot was added to a group — save chat_id and send greeting."""
    chat = event.chat

    # Only handle group/supergroup
    if chat.type not in ("group", "supergroup"):
        return

    # Save chat_id to settings
    await set_setting("group_chat_id", str(chat.id))
    logger.info(f"Bot added to chat: {chat.title} (id={chat.id})")

    # Send greeting
    await event.answer(
        "☕ <b>Научный Кофе подключён!</b>\n\n"
        "Раз в месяц я помогу вам познакомиться ближе — "
        "составлю случайные пары для неформальных встреч.\n\n"
        "📌 <b>Как это работает:</b>\n"
        "1. В чате появится опрос — отметьте, что хотите участвовать\n"
        "2. Я случайным образом составлю пары\n"
        "3. Результаты опубликую сюда\n"
        "4. Напишите своему партнёру и договоритесь о встрече ☕",
    )


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=(IS_MEMBER | ADMINISTRATOR) >> IS_NOT_MEMBER)
)
async def on_bot_removed(event: ChatMemberUpdated):
    """Bot was removed from a group — clear saved chat_id."""
    await set_setting("group_chat_id", "")
    logger.info(f"Bot removed from chat: {event.chat.title} (id={event.chat.id}), chat_id cleared")
