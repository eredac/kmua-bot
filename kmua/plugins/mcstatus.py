import asyncio
import time
from typing import Dict

from dynaconf import Dynaconf
from loguru import logger
from pyrogram import Client, filters
from pyrogram.types import Message

# 加载配置
_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)


async def check_mc_server_connectivity(
    host: str, port: int = 25565, timeout: float = 3.0
) -> tuple[bool, float]:
    """
    检测 Minecraft 服务器连通性

    Args:
        host: 服务器地址
        port: 服务器端口,默认 25565
        timeout: 超时时间(秒),默认 3.0

    Returns:
        (是否连通, 延迟时间ms)
    """
    try:
        start_time = time.time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        latency = (time.time() - start_time) * 1000  # 转换为毫秒
        writer.close()
        await writer.wait_closed()
        return True, latency
    except asyncio.TimeoutError:
        logger.debug(f"连接超时: {host}:{port}")
        return False, 0.0
    except Exception as e:
        logger.debug(f"连接失败 {host}:{port}: {e}")
        return False, 0.0


async def check_multiple_times(
    host: str, port: int = 25565, times: int = 3
) -> tuple[int, list[float]]:
    """
    多次检测服务器连通性

    Args:
        host: 服务器地址
        port: 服务器端口
        times: 检测次数

    Returns:
        (成功次数, 延迟列表)
    """
    success_count = 0
    latencies = []

    for i in range(times):
        is_connected, latency = await check_mc_server_connectivity(host, port)
        if is_connected:
            success_count += 1
            latencies.append(latency)
        # 添加小延迟避免过于频繁的连接
        if i < times - 1:
            await asyncio.sleep(0.5)

    return success_count, latencies


def parse_server_address(address: str) -> tuple[str, int]:
    """
    解析服务器地址

    Args:
        address: 服务器地址,格式为 "host" 或 "host:port"

    Returns:
        (host, port)
    """
    if ":" in address:
        host, port_str = address.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = 25565
    else:
        host = address
        port = 25565

    return host, port


@Client.on_message(filters.command("mcstatus"), group=0)
async def mcstatus_command(client: Client, message: Message):
    """处理 /mcstatus 指令"""
    # 获取配置的服务器列表
    mc_servers: Dict[str, str] = _settings.get("mc_servers", {})

    if not mc_servers:
        await message.reply_text("❌ 未配置 Minecraft 服务器列表")
        return

    # 发送处理中消息
    status_msg = await message.reply_text("🔍 正在检测服务器连通性,请稍候...")

    # 检测所有服务器
    results = []

    for name, address in mc_servers.items():
        host, port = parse_server_address(address)
        logger.info(f"检测服务器: {name} ({host}:{port})")

        # 进行3次连接测试
        success_count, latencies = await check_multiple_times(host, port, times=3)

        # 计算平均延迟
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            min_latency = min(latencies)
            max_latency = max(latencies)
        else:
            avg_latency = 0
            min_latency = 0
            max_latency = 0

        results.append({
            "name": name,
            "address": address,
            "host": host,
            "port": port,
            "success_count": success_count,
            "total_count": 3,
            "avg_latency": avg_latency,
            "min_latency": min_latency,
            "max_latency": max_latency,
        })

    # 构建回复消息（使用 Telegram markdown 引用格式）
    reply_lines = ["🎮 **HK 服务器 MC 连通测试 (TCP)**\n"]

    for result in results:
        name = result["name"]
        address = result["address"]
        success_count = result["success_count"]
        total_count = result["total_count"]
        avg_latency = result["avg_latency"]

        # 根据成功率选择状态图标
        if success_count == total_count:
            status_icon = "✅"
        elif success_count > 0:
            status_icon = "⚠️"
        else:
            status_icon = "❌"

        # 延迟显示
        latency_str = f"{avg_latency:.0f}ms" if success_count > 0 else "N/A"

        # 构建服务器状态行（使用引用格式）
        reply_lines.append(f">{status_icon} **{name}**")
        reply_lines.append(f">地址: `{address}`")
        reply_lines.append(f">连通: {success_count}/{total_count} | 延迟: {latency_str}")
        reply_lines.append("")  # 空行分隔引用块

    reply_text = "\n".join(reply_lines)

    # 更新状态消息
    await status_msg.edit_text(reply_text)
    logger.info(f"服务器状态检测完成,共检测 {len(results)} 个服务器")
