#!/usr/bin/env python3
"""手动给用户添加积分的临时脚本"""
import asyncio
import sys

sys.path.insert(0, "/kmua")

from kmua.database import points as db_points


async def main():
    # 测试群 chat_id（需要主人提供）
    # LunarEclipse user_id（需要主人提供）

    # 示例：给 user_id=123456, chat_id=-100123456 添加 5000 积分
    user_id = int(input("请输入 user_id: "))
    chat_id = int(input("请输入 chat_id (群组通常是负数): "))
    amount = 5000

    result = await db_points.add_points(
        user_id=user_id,
        chat_id=chat_id,
        amount=amount,
        reason="管理员手动发放",
        operator_id=None,
    )

    print(f"✅ 成功给用户 {user_id} 在群组 {chat_id} 添加 {amount} 积分")
    print(f"当前总积分: {result.points}")


if __name__ == "__main__":
    asyncio.run(main())
