"""定时任务管理模块 - 荷官模式自动开关"""
import asyncio
from datetime import datetime, time as dt_time
from typing import Dict, Optional

from loguru import logger
from pyrogram import Client

from kmua.database import (
    get_all_dealer_mode_chats,
    upsert_dealer_mode_config,
    clear_late_players,
)


class DealerModeScheduler:
    """荷官模式定时任务调度器"""

    def __init__(self, client: Client):
        self.client = client
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self._check_interval = 60  # 每60秒检查一次

    async def start(self):
        """启动定时任务"""
        if self.running:
            logger.warning("定时任务已在运行中")
            return

        self.running = True
        self.task = asyncio.create_task(self._scheduler_loop())
        logger.info("🕐 荷官模式定时任务已启动")

    async def stop(self):
        """停止定时任务"""
        if not self.running:
            return

        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("🕐 荷官模式定时任务已停止")

    async def _scheduler_loop(self):
        """定时任务主循环"""
        logger.info("定时任务主循环已启动")

        try:
            while self.running:
                try:
                    await self._check_and_execute()
                except Exception as e:
                    logger.exception(f"定时任务执行出错: {e}")

                # 等待下一次检查
                await asyncio.sleep(self._check_interval)

        except asyncio.CancelledError:
            logger.info("定时任务循环被取消")
            raise

    async def _check_and_execute(self):
        """检查并执行定时任务"""
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        # 获取所有群组的荷官模式配置
        try:
            configs = await get_all_dealer_mode_chats()
        except Exception as e:
            logger.error(f"获取荷官模式配置失败: {e}")
            return

        for config in configs:
            try:
                # 检查是否到达开启时间
                if current_time == config.start_time:
                    if not config.enabled:
                        await upsert_dealer_mode_config(
                            chat_id=config.chat_id,
                            enabled=True,
                        )
                        # 清空之前的迟到记录
                        await clear_late_players(config.chat_id)

                        # 尝试发送通知消息
                        try:
                            await self.client.send_message(
                                config.chat_id,
                                "🎰 <b>荷官模式已自动开启</b>\n\n"
                                "游戏间隙投掷骰子的玩家将被记录为迟到者。",
                                parse_mode="html",
                            )
                        except Exception as e:
                            logger.warning(f"发送荷官模式开启通知失败 (chat_id={config.chat_id}): {e}")

                        logger.info(
                            f"🎰 自动开启荷官模式: chat_id={config.chat_id}, "
                            f"时间={config.start_time}"
                        )

                # 检查是否到达关闭时间
                elif current_time == config.end_time:
                    if config.enabled:
                        await upsert_dealer_mode_config(
                            chat_id=config.chat_id,
                            enabled=False,
                        )
                        # 清空迟到记录
                        await clear_late_players(config.chat_id)

                        # 尝试发送通知消息
                        try:
                            await self.client.send_message(
                                config.chat_id,
                                "🎰 <b>荷官模式已自动关闭</b>\n\n"
                                "迟到记录已清空。",
                                parse_mode="html",
                            )
                        except Exception as e:
                            logger.warning(f"发送荷官模式关闭通知失败 (chat_id={config.chat_id}): {e}")

                        logger.info(
                            f"🎰 自动关闭荷官模式: chat_id={config.chat_id}, "
                            f"时间={config.end_time}"
                        )

            except Exception as e:
                logger.exception(f"处理群组 {config.chat_id} 的定时任务失败: {e}")
                continue


# 全局调度器实例
_scheduler: Optional[DealerModeScheduler] = None


def get_scheduler(client: Client) -> DealerModeScheduler:
    """获取全局调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = DealerModeScheduler(client)
    return _scheduler


async def init_scheduler(client: Client):
    """初始化并启动调度器"""
    scheduler = get_scheduler(client)
    await scheduler.start()


async def stop_scheduler():
    """停止调度器"""
    global _scheduler
    if _scheduler:
        await _scheduler.stop()
        _scheduler = None
