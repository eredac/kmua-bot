#!/usr/bin/env python3
"""删除指定的 Telegram 消息"""

import asyncio
from kmua.bot.client import client


async def delete_specific_message():
    """删除群 -1002434265967 中的消息 6205681"""
    chat_id = -1002434265967
    message_id = 6205681

    async with client:
        try:
            await client.delete_messages(chat_id=chat_id, message_ids=message_id)
            print(f"✅ 成功删除消息 {message_id} (群 {chat_id})")
        except Exception as e:
            print(f"❌ 删除失败: {e}")


if __name__ == "__main__":
    asyncio.run(delete_specific_message())
