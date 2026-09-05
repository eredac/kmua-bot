"""
Chat-Level Message Queue
每个 chat 独立的消息操作队列，防止 Telegram API 限流导致超时
"""
import asyncio
from collections import defaultdict
from typing import Callable, Any

from kmua.logger import logger


class ChatMessageQueue:
    """每个 chat 独立的消息队列，控制 API 调用速率"""

    def __init__(self, max_per_second: int = 20):
        """
        初始化消息队列

        Args:
            max_per_second: 每秒最大消息操作数（保守值，低于 Telegram 的 30/s 限制）
        """
        self._queues: dict[int, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._workers: dict[int, asyncio.Task] = {}
        self._max_per_second = max_per_second
        self._interval = 1.0 / max_per_second
        logger.info(f"[MessageQueue] Initialized with max_per_second={max_per_second}, interval={self._interval:.3f}s")

    async def enqueue(self, chat_id: int, coro: Callable, *args, **kwargs) -> Any:
        """
        将消息操作加入队列并等待执行

        Args:
            chat_id: 群组/用户 ID
            coro: 要执行的协程函数
            *args, **kwargs: 传递给协程的参数

        Returns:
            协程的执行结果

        Raises:
            原协程抛出的任何异常
        """
        queue = self._queues[chat_id]
        result_future = asyncio.Future()

        await queue.put((coro, args, kwargs, result_future))

        # 启动 worker（如果未启动）
        if chat_id not in self._workers or self._workers[chat_id].done():
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id))
            logger.debug(f"[MessageQueue] Started worker for chat {chat_id}")

        return await result_future

    async def _worker(self, chat_id: int):
        """处理特定 chat 的消息队列"""
        queue = self._queues[chat_id]
        processed = 0

        while True:
            try:
                # 等待任务（30秒无任务则退出）
                coro, args, kwargs, future = await asyncio.wait_for(
                    queue.get(), timeout=30.0
                )

                try:
                    result = await coro(*args, **kwargs)
                    future.set_result(result)
                    processed += 1
                except Exception as e:
                    logger.warning(f"[MessageQueue] Task failed for chat {chat_id}: {e}")
                    future.set_exception(e)

                # 限速：每次操作后等待
                await asyncio.sleep(self._interval)

            except asyncio.TimeoutError:
                # 30秒无任务，清理 worker
                logger.info(f"[MessageQueue] Worker idle timeout for chat {chat_id}, processed {processed} messages")
                if chat_id in self._workers:
                    del self._workers[chat_id]
                break
            except Exception as e:
                logger.exception(f"[MessageQueue] Worker error for chat {chat_id}: {e}")

    def get_queue_size(self, chat_id: int) -> int:
        """获取指定 chat 的队列大小"""
        return self._queues[chat_id].qsize()

    def get_active_workers(self) -> int:
        """获取活跃 worker 数量"""
        return len([w for w in self._workers.values() if not w.done()])


# 全局实例
_message_queue = ChatMessageQueue(max_per_second=20)


async def enqueue_message_operation(chat_id: int, coro: Callable, *args, **kwargs) -> Any:
    """
    便捷函数：将消息操作加入队列

    使用示例：
        await enqueue_message_operation(
            chat_id,
            callback.message.edit_media,
            InputMediaPhoto(png_io, caption=caption),
            reply_markup=keyboard
        )
    """
    return await _message_queue.enqueue(chat_id, coro, *args, **kwargs)


def get_queue_size(chat_id: int) -> int:
    """获取指定 chat 的队列大小"""
    return _message_queue.get_queue_size(chat_id)
