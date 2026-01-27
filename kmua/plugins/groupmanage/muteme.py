"""
/muteme 命令 - 让用户主动禁言自己
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import ChatPermissions, Message

from kmua.i18n import i18n


def parse_time_string(time_str: str) -> timedelta | None:
    """
    解析时间字符串，支持格式：
    - 4m = 4 分钟
    - 3h = 3 小时
    - 6d = 6 天
    - 5w = 5 周

    Args:
        time_str: 时间字符串

    Returns:
        timedelta 对象，如果解析失败则返回 None
    """
    pattern = r"^(\d+)([mhdw])$"
    match = re.match(pattern, time_str.lower().strip())

    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)

    if value <= 0:
        return None

    # 转换为 timedelta
    if unit == "m":  # 分钟
        return timedelta(minutes=value)
    elif unit == "h":  # 小时
        return timedelta(hours=value)
    elif unit == "d":  # 天
        return timedelta(days=value)
    elif unit == "w":  # 周
        return timedelta(weeks=value)

    return None


def format_duration(duration: timedelta) -> str:
    """
    格式化时间间隔为中文描述

    Args:
        duration: 时间间隔

    Returns:
        中文描述字符串，例如 "30分钟"、"2小时"、"7天"
    """
    total_seconds = int(duration.total_seconds())

    # 计算各个时间单位
    weeks = total_seconds // (7 * 24 * 3600)
    days = (total_seconds % (7 * 24 * 3600)) // (24 * 3600)
    hours = (total_seconds % (24 * 3600)) // 3600
    minutes = (total_seconds % 3600) // 60

    # 构建描述
    parts = []
    if weeks > 0:
        parts.append(f"{weeks}周")
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分钟")

    return "".join(parts) if parts else "0分钟"


@Client.on_message(filters.command("muteme") & filters.group, group=0)
async def muteme_command(client: Client, message: Message):
    """
    /muteme 命令处理器
    让用户主动禁言自己
    """
    # 获取用户和群组信息
    user = message.from_user
    chat = message.chat

    if not user:
        await message.reply_text(i18n.t("bot.msg.muteme.errors.no_user"))
        return

    # 检查用户是否是管理员
    try:
        member = await client.get_chat_member(chat.id, user.id)
        if member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):
            # 用户是管理员，发送错误消息
            reply_msg = await message.reply_text(
                i18n.t("bot.msg.muteme.errors.admin")
            )
            # 5分钟后删除消息
            asyncio.create_task(_delete_messages_after_delay(message, reply_msg))
            return
    except Exception:
        pass  # 如果获取成员信息失败，继续执行

    # 检查是否提供了时间参数
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text(i18n.t("bot.msg.muteme.errors.no_time"))
        return

    time_str = args[1].strip()

    # 解析时间
    duration = parse_time_string(time_str)
    if duration is None:
        await message.reply_text(i18n.t("bot.msg.muteme.errors.invalid_format"))
        return

    # 检查时间是否超过 365 天
    max_duration = timedelta(days=365)
    if duration > max_duration:
        await message.reply_text(
            i18n.t("bot.msg.muteme.errors.too_long", max_days=365)
        )
        return

    # 计算禁言结束时间（使用 UTC 时间）
    until_date = datetime.now(timezone.utc) + duration

    try:
        # 创建完全禁言的权限对象（所有权限都设为 False）
        restricted_permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
        )

        # 禁言用户
        await client.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=restricted_permissions,
            until_date=until_date,
        )

        # 格式化时间描述
        time_desc = format_duration(duration)

        # 获取用户显示名称（优先使用用户名，否则使用全名）
        display_name = user.username if user.username else user.full_name

        # 发送成功消息
        reply_msg = await message.reply_text(
            i18n.t(
                "bot.msg.muteme.success",
                username=display_name,
                duration=time_desc,
            )
        )

        # 5分钟后删除消息
        asyncio.create_task(_delete_messages_after_delay(message, reply_msg))

    except Exception as e:
        # 处理错误（例如：bot 没有管理员权限）
        error_msg = str(e)
        if "CHAT_ADMIN_REQUIRED" in error_msg or "not enough rights" in error_msg:
            await message.reply_text(i18n.t("bot.msg.muteme.errors.bot_no_permission"))
        else:
            await message.reply_text(
                i18n.t("bot.msg.muteme.errors.generic", error=error_msg)
            )


async def _delete_messages_after_delay(
    command_message: Message, reply_message: Message
):
    """
    在5分钟后删除命令消息和回复消息

    Args:
        command_message: 用户发送的命令消息
        reply_message: bot 的回复消息
    """
    await asyncio.sleep(300)  # 等待5分钟（300秒）
    try:
        await command_message.delete()
    except Exception:
        pass  # 忽略删除失败的错误

    try:
        await reply_message.delete()
    except Exception:
        pass  # 忽略删除失败的错误
