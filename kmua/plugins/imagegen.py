import asyncio
import io
import os
import time
from datetime import datetime
from typing import Dict

import httpx
import pyrogram
import sqlalchemy
from pyrogram.types import Message
from dynaconf import Dynaconf
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from kmua import database
from kmua.config import app_config
from kmua.database.db import with_session, with_tx
from kmua.database.models import ImageGenDailyUsage, UserImageGenConfig

# Load settings directly for image_gen config
_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)

# Image generation client
class _ImageGenClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        model: str,
    ):
        self.api_key = api_key
        self.url = url
        self.model = model
        headers = {
            "User-Agent": "KMUA ImageGenClient",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(120, connect=10, read=120),
        )

    async def generate_image(
        self,
        prompt: str,
        model: str | None = None,
        size: str | None = None,
        quality: str | None = None,
        response_format: str | None = None,
    ) -> httpx.Response:
        """Generate an image from a text prompt"""
        if not self.api_key:
            raise ValueError("API key is not set")

        data = {
            "prompt": prompt,
            "model": model or self.model,
            "size": size or _settings.get('image_gen_size', '1024x1024'),
            "quality": quality or _settings.get('image_gen_quality', 'standard'),
            "response_format": response_format or _settings.get('image_gen_response_format', 'url'),
            "n": 1,
        }

        response = await self.client.post(
            f"{self.url}/images/generations",
            json=data,
            timeout=120,
        )
        return response

    async def edit_image(
        self,
        image_bytes: bytes | list[bytes],
        prompt: str,
        model: str | None = None,
        size: str | None = None,
        response_format: str | None = None,
    ) -> httpx.Response:
        """Edit an image using AI"""
        if not self.api_key:
            raise ValueError("API key is not set")

        # Prepare files for upload
        files = []
        if isinstance(image_bytes, list):
            # Multiple images
            for idx, img_bytes in enumerate(image_bytes):
                files.append(("image", (f"image_{idx}.png", img_bytes, "image/png")))
        else:
            # Single image
            files.append(("image", ("image.png", image_bytes, "image/png")))

        # Prepare form data
        data = {
            "prompt": prompt,
            "model": model or self.model,
            "response_format": response_format or _settings.get('image_gen_response_format', 'url'),
        }

        # Add size if provided
        if size:
            data["size"] = size

        # Create a new client without Content-Type header for multipart
        async with httpx.AsyncClient(
            headers={
                "User-Agent": "KMUA ImageGenClient",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=httpx.Timeout(120, connect=10, read=120),
        ) as client:
            response = await client.post(
                f"{self.url}/images/edits",
                data=data,
                files=files,
            )

        return response

    def set_model(self, model: str):
        """Set the current model for image generation"""
        self.model = model


# Initialize client
imagegen_client: _ImageGenClient | None = None
if _settings.get('image_gen', False) and _settings.get('image_gen_api_key'):
    imagegen_client = _ImageGenClient(
        url=_settings.get('image_gen_url', 'https://api.openai.com/v1'),
        api_key=_settings.image_gen_api_key,
        model=_settings.get('image_gen_model', 'dall-e-3'),
    )

# Store last usage time per user for rate limiting
_last_usage: Dict[int, float] = {}
# Track ongoing API requests
_active_requests: int = 0
_max_concurrent_requests: int = 3  # Maximum concurrent API requests


@with_session
async def get_or_create_daily_usage(
    user_id: int,
    today: str,
    session: AsyncSession | None = None
) -> ImageGenDailyUsage:
    """获取或创建今日使用记录"""
    assert session is not None

    usage = await session.get(ImageGenDailyUsage, user_id)

    if usage is None:
        # 创建新记录
        usage = ImageGenDailyUsage(
            user_id=user_id,
            usage_count=0,
            usage_date=today
        )
        session.add(usage)
        await session.flush()
    elif usage.usage_date != today:
        # 日期不是今天，重置计数
        usage.usage_count = 0
        usage.usage_date = today
        await session.flush()

    return usage


@with_tx
async def increment_usage_in_db(
    user_id: int,
    today: str,
    session: AsyncSession | None = None
) -> None:
    """在数据库中递增使用次数"""
    assert session is not None

    usage = await session.get(ImageGenDailyUsage, user_id)

    if usage is None:
        usage = ImageGenDailyUsage(
            user_id=user_id,
            usage_count=1,
            usage_date=today
        )
        session.add(usage)
    elif usage.usage_date != today:
        # 日期不是今天，重置为1
        usage.usage_count = 1
        usage.usage_date = today
    else:
        # 递增计数
        usage.usage_count += 1

    await session.flush()


async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    try:
        db_user = await database.get_user_by_id(user_id)
        return db_user.is_bot_global_admin or user_id in app_config.owners
    except:
        return False


async def check_daily_limit(user_id: int, model: str) -> tuple[bool, int, int]:
    """
    检查用户每日使用次数限制
    返回: (是否允许, 今日已用次数, 每日限额)
    """
    # 只对 nano-banana-pro 系列模型限制(不包括 nano-banana)
    if not model.startswith('nano-banana-pro'):
        return True, 0, 0

    # 检查是否为管理员
    if await is_admin(user_id):
        return True, 0, 0

    # 获取今天的日期字符串
    today = datetime.now().strftime('%Y-%m-%d')

    # 从数据库获取今日使用次数
    usage = await get_or_create_daily_usage(user_id, today)
    used_count = usage.usage_count
    daily_limit = 5

    return used_count < daily_limit, used_count, daily_limit


async def increment_daily_usage(user_id: int, model: str):
    """递增用户今日使用次数"""
    # 只对 nano-banana-pro 系列模型计数(不包括 nano-banana)
    if not model.startswith('nano-banana-pro'):
        return

    # 管理员不计数
    if await is_admin(user_id):
        return

    today = datetime.now().strftime('%Y-%m-%d')

    # 在数据库中递增使用次数
    await increment_usage_in_db(user_id, today)


@with_session
async def get_user_model(
    user_id: int,
    session: AsyncSession | None = None
) -> str:
    """
    获取用户配置的模型
    如果用户没有配置，返回默认模型 nano-banana
    """
    assert session is not None

    config = await session.get(UserImageGenConfig, user_id)

    if config is None:
        # 返回默认模型
        return "nano-banana"

    return config.model


@with_tx
async def set_user_model(
    user_id: int,
    model: str,
    session: AsyncSession | None = None
) -> None:
    """设置用户的模型配置"""
    assert session is not None

    config = await session.get(UserImageGenConfig, user_id)

    if config is None:
        # 创建新配置
        config = UserImageGenConfig(
            user_id=user_id,
            model=model
        )
        session.add(config)
    else:
        # 更新现有配置
        config.model = model

    await session.flush()


async def check_whitelist(chat_id: int) -> bool:
    """Check if chat is in whitelist"""
    whitelist = _settings.get('image_gen_whitelist', [])
    return chat_id in whitelist


async def check_cooldown(user_id: int, is_whitelisted: bool) -> tuple[bool, float]:
    """Check if user is in cooldown period (only for non-whitelisted chats)"""
    if is_whitelisted:
        return True, 0.0

    if user_id in _last_usage:
        elapsed = time.time() - _last_usage[user_id]
        cooldown = _settings.get('image_gen_cd', 5)
        remaining = cooldown - elapsed
        if remaining > 0:
            return False, remaining
    return True, 0.0


async def can_make_request() -> bool:
    """Check if we can make a new API request"""
    global _active_requests
    return _active_requests < _max_concurrent_requests


async def _check_image_edit_permissions(message: Message) -> tuple[bool, str | None, bool, str]:
    """
    检查图片编辑权限
    返回: (是否允许, 错误信息, 是否在白名单, 用户模型)
    """
    if not _settings.get('image_gen', False):
        return False, "图片生成功能未启用", False, "nano-banana"

    if not imagegen_client:
        return False, "图片生成服务未配置", False, "nano-banana"

    user = message.from_user
    chat = message.chat
    if user is None or chat is None:
        return False, None, False, "nano-banana"

    # Get user's model configuration
    user_model = await get_user_model(user.id)

    # Check whitelist status
    is_whitelisted = await check_whitelist(chat.id)

    # Check cooldown (only for non-whitelisted chats)
    can_use, remaining = await check_cooldown(user.id, is_whitelisted)
    if not can_use:
        return False, f"请等待 {remaining:.1f} 秒后再次使用", is_whitelisted, user_model

    # Check daily limit for nano-banana-pro models
    can_use_daily, used_count, daily_limit = await check_daily_limit(user.id, user_model)
    if not can_use_daily:
        return False, f"今日 {user_model} 模型使用次数已达上限 ({used_count}/{daily_limit})，明天再来吧喵～", is_whitelisted, user_model

    # Check concurrent request limit
    if not await can_make_request():
        return False, "当前API请求过多，请稍后再试", is_whitelisted, user_model

    return True, None, is_whitelisted, user_model


async def _download_photo(client: pyrogram.Client, photo) -> bytes:
    """下载图片并返回字节数据"""
    file_id = photo.file_id
    file_path = await client.download_media(file_id)

    with open(file_path, 'rb') as f:
        image_bytes = f.read()

    # Clean up temp file
    if os.path.exists(file_path):
        os.remove(file_path)

    return image_bytes


async def _process_image_edit_response(
    message: Message,
    response: httpx.Response,
    prompt: str,
    status_msg: Message,
    user_model: str,
) -> bool:
    """
    处理图片编辑API响应
    返回: 是否成功
    """
    data = response.json()

    if "data" in data and len(data["data"]) > 0:
        image_data = data["data"][0]

        # Check if response is URL or base64
        if "url" in image_data:
            # Download image from URL
            async with httpx.AsyncClient() as http_client:
                img_response = await http_client.get(image_data["url"])
                img_response.raise_for_status()

                # Send as photo using BytesIO
                await message.reply_photo(
                    photo=io.BytesIO(img_response.content),
                    caption=f"编辑描述: {prompt}\n模型: {user_model}"
                )
        elif "b64_json" in image_data:
            import base64
            # Decode base64 image
            img_bytes = base64.b64decode(image_data["b64_json"])
            await message.reply_photo(
                photo=io.BytesIO(img_bytes),
                caption=f"编辑描述: {prompt}\n模型: {user_model}"
            )
        else:
            await status_msg.edit_text("图片编辑失败: 未知的响应格式")
            return False
    else:
        await status_msg.edit_text("图片编辑失败: 响应数据为空")
        return False

    return True


async def _handle_image_edit_error(e: Exception, status_msg: Message):
    """处理图片编辑错误"""
    if isinstance(e, httpx.HTTPStatusError):
        logger.error(f"Image edit HTTP error: {e.response.status_code} - {e.response.text}")
        error_msg = f"编辑失败: HTTP {e.response.status_code}"
        try:
            error_data = e.response.json()
            if "error" in error_data:
                error_info = error_data["error"]
                if isinstance(error_info, dict) and "message" in error_info:
                    error_msg += f'\n{error_info["message"]}'
                else:
                    error_msg += f'\n{error_info}'
        except:
            pass
        await status_msg.edit_text(error_msg)
    else:
        logger.exception(f"Image edit failed: {e}")
        await status_msg.edit_text(f"编辑失败: {str(e)}")


@pyrogram.Client.on_message(
    pyrogram.filters.photo & pyrogram.filters.regex(r"^/multiedit\s"),
    group=0
)
async def multiedit_from_caption(client: pyrogram.Client, message: Message):
    """从相册 caption 编辑多张图片"""
    global _active_requests

    # 检查权限
    can_proceed, error_msg, is_whitelisted, user_model = await _check_image_edit_permissions(message)
    if not can_proceed:
        if error_msg:
            await message.reply_text(error_msg)
        return

    # 从 caption 提取提示词
    caption = message.caption or ""
    prompt_match = caption.split(maxsplit=1)
    if len(prompt_match) < 2:
        await message.reply_text(
            "请在图片的说明中提供编辑描述\n"
            "用法: 发送相册（1-6张图片）并在说明中写 /multiedit [编辑描述]\n"
            "示例: /multiedit 把这些图片都改成水彩画风格\n"
            "注意: 建议使用3张以内图片效果最佳"
        )
        return

    prompt = prompt_match[1]

    # 收集图片
    photos = []

    # 检查是否为相册（media_group）
    if message.media_group_id:
        # 获取相册中的所有消息
        try:
            media_group = await client.get_media_group(
                message.chat.id,
                message.id
            )

            # 只处理照片
            for msg in media_group:
                if msg.photo:
                    photos.append(msg.photo)

        except Exception as e:
            logger.error(f"Failed to get media group: {e}")
            # 如果获取失败，至少处理当前这张
            photos = [message.photo]
    else:
        # 单张图片
        photos = [message.photo]

    # 限制图片数量
    if len(photos) > 6:
        await message.reply_text(
            f"图片数量过多（{len(photos)}张），最多支持6张图片\n"
            "建议使用3张以内效果最佳"
        )
        return

    # 发送处理中消息
    status_msg = await message.reply_text(
        f"正在下载 {len(photos)} 张图片并进行编辑，请稍候...\n"
        f"{'（建议3张以内效果最佳）' if len(photos) > 3 else ''}"
    )

    try:
        # 增加活动请求计数
        _active_requests += 1

        # 下载所有图片
        image_bytes_list = []
        for idx, photo in enumerate(photos):
            try:
                img_bytes = await _download_photo(client, photo)
                image_bytes_list.append(img_bytes)

                # 更新进度
                if len(photos) > 1:
                    await status_msg.edit_text(
                        f"正在下载图片 {idx + 1}/{len(photos)}...\n"
                        f"{'（建议3张以内效果最佳）' if len(photos) > 3 else ''}"
                    )
            except Exception as e:
                logger.error(f"Failed to download photo {idx + 1}: {e}")
                await status_msg.edit_text(f"下载第 {idx + 1} 张图片失败: {str(e)}")
                return

        await status_msg.edit_text(
            f"已下载 {len(image_bytes_list)} 张图片，正在进行AI编辑..."
        )

        # 调用编辑API（支持多图）
        response = await imagegen_client.edit_image(
            image_bytes=image_bytes_list,  # 传入图片列表
            prompt=prompt,
            model=user_model,
        )
        response.raise_for_status()

        # 处理响应
        success = await _process_image_edit_response(message, response, prompt, status_msg, user_model)

        if success:
            # 更新冷却时间(仅非白名单用户)
            if not is_whitelisted and message.from_user:
                _last_usage[message.from_user.id] = time.time()

            # 递增每日使用次数
            if message.from_user:
                await increment_daily_usage(message.from_user.id, user_model)

            # 删除状态消息
            await status_msg.delete()

    except Exception as e:
        await _handle_image_edit_error(e, status_msg)
    finally:
        # 减少活动请求计数
        _active_requests = max(0, _active_requests - 1)


@pyrogram.Client.on_message(
    pyrogram.filters.photo & pyrogram.filters.regex(r"^/editimg\s"),
    group=0
)
async def editimg_from_caption(client: pyrogram.Client, message: Message):
    """从图片 caption 直接编辑图片 (方式A)"""
    global _active_requests

    # 检查权限
    can_proceed, error_msg, is_whitelisted, user_model = await _check_image_edit_permissions(message)
    if not can_proceed:
        if error_msg:
            await message.reply_text(error_msg)
        return

    # 从 caption 提取提示词
    caption = message.caption or ""
    prompt_match = caption.split(maxsplit=1)
    if len(prompt_match) < 2:
        await message.reply_text(
            "请在图片的说明中提供编辑描述\n"
            "用法: 发送图片并在说明中写 /editimg [编辑描述]\n"
            "示例: /editimg 把天空改成日落"
        )
        return

    prompt = prompt_match[1]

    # 发送处理中消息
    status_msg = await message.reply_text("正在下载图片并进行编辑，请稍候...")

    try:
        # 增加活动请求计数
        _active_requests += 1

        # 下载图片
        image_bytes = await _download_photo(client, message.photo)

        await status_msg.edit_text("图片已下载，正在进行AI编辑...")

        # 调用编辑API
        response = await imagegen_client.edit_image(
            image_bytes=image_bytes,
            prompt=prompt,
            model=user_model,
        )
        response.raise_for_status()

        # 处理响应
        success = await _process_image_edit_response(message, response, prompt, status_msg, user_model)

        if success:
            # 更新冷却时间(仅非白名单用户)
            if not is_whitelisted and message.from_user:
                _last_usage[message.from_user.id] = time.time()

            # 递增每日使用次数
            if message.from_user:
                await increment_daily_usage(message.from_user.id, user_model)

            # 删除状态消息
            await status_msg.delete()

    except Exception as e:
        await _handle_image_edit_error(e, status_msg)
    finally:
        # 减少活动请求计数
        _active_requests = max(0, _active_requests - 1)


@pyrogram.Client.on_message(pyrogram.filters.command("genimg"), group=0)
async def genimg_command(client: pyrogram.Client, message: Message):
    """Generate image from text prompt using AI"""
    global _active_requests

    if not _settings.get('image_gen', False):
        await message.reply_text("图片生成功能未启用")
        return

    if not imagegen_client:
        await message.reply_text("图片生成服务未配置")
        return

    user = message.from_user
    chat = message.chat
    if user is None or chat is None:
        return

    # Get user's model configuration
    user_model = await get_user_model(user.id)

    # Check whitelist status
    is_whitelisted = await check_whitelist(chat.id)

    # Check cooldown (only for non-whitelisted chats)
    can_use, remaining = await check_cooldown(user.id, is_whitelisted)
    if not can_use:
        await message.reply_text(f"请等待 {remaining:.1f} 秒后再次使用")
        return

    # Check daily limit for nano-banana-pro models
    can_use_daily, used_count, daily_limit = await check_daily_limit(user.id, user_model)
    if not can_use_daily:
        await message.reply_text(f"今日 {user_model} 模型使用次数已达上限 ({used_count}/{daily_limit})，明天再来吧喵～")
        return

    # Check concurrent request limit
    if not await can_make_request():
        await message.reply_text(f"当前API请求过多，请稍后再试")
        return

    # Get prompt from command
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.reply_text("请提供图片描述\n用法: /genimg [提示词]")
        return

    prompt = command_parts[1]

    # Send processing message
    status_msg = await message.reply_text("正在生成图片，请稍候...")

    try:
        # Increment active requests counter
        _active_requests += 1

        # Generate image with user's model
        response = await imagegen_client.generate_image(prompt, model=user_model)
        response.raise_for_status()

        data = response.json()

        # Handle different response formats
        if "data" in data and len(data["data"]) > 0:
            image_data = data["data"][0]

            # Check if response is URL or base64
            if "url" in image_data:
                # Download image from URL
                async with httpx.AsyncClient() as http_client:
                    img_response = await http_client.get(image_data["url"])
                    img_response.raise_for_status()

                    # Send as photo using BytesIO
                    await message.reply_photo(
                        photo=io.BytesIO(img_response.content),
                        caption=f"提示词: {prompt}\n模型: {user_model}"
                    )
            elif "b64_json" in image_data:
                import base64
                # Decode base64 image
                img_bytes = base64.b64decode(image_data["b64_json"])
                await message.reply_photo(
                    photo=io.BytesIO(img_bytes),
                    caption=f"提示词: {prompt}\n模型: {user_model}"
                )
            else:
                await status_msg.edit_text("图片生成失败: 未知的响应格式")
                return
        else:
            await status_msg.edit_text("图片生成失败: 响应数据为空")
            return

        # Update cooldown (only for non-whitelisted chats)
        if not is_whitelisted:
            _last_usage[user.id] = time.time()

        # Increment daily usage count for nano-banana-pro models
        await increment_daily_usage(user.id, user_model)

        # Delete status message
        await status_msg.delete()

    except httpx.HTTPStatusError as e:
        logger.error(f"Image generation HTTP error: {e.response.status_code} - {e.response.text}")
        error_msg = f"生成失败: HTTP {e.response.status_code}"
        try:
            error_data = e.response.json()
            if "error" in error_data:
                error_info = error_data["error"]
                if isinstance(error_info, dict) and "message" in error_info:
                    error_msg += f'\n{error_info["message"]}'
                else:
                    error_msg += f'\n{error_info}'
        except:
            pass
        await status_msg.edit_text(error_msg)
    except Exception as e:
        logger.exception(f"Image generation failed: {e}")
        await status_msg.edit_text(f"生成失败: {str(e)}")
    finally:
        # Decrement active requests counter
        _active_requests = max(0, _active_requests - 1)


@pyrogram.Client.on_message(pyrogram.filters.command("editimg"), group=0)
async def editimg_command(client: pyrogram.Client, message: Message):
    """回复图片并编辑 (方式C)"""
    global _active_requests

    # 检查权限
    can_proceed, error_msg, is_whitelisted, user_model = await _check_image_edit_permissions(message)
    if not can_proceed:
        if error_msg:
            await message.reply_text(error_msg)
        return

    # 从命令提取提示词
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        await message.reply_text(
            "请回复一张图片并提供编辑描述\n"
            "用法1: 回复图片 + /editimg [编辑描述]\n"
            "用法2: 发送图片并在说明中写 /editimg [编辑描述]\n"
            "示例: /editimg 把沙发改成红色"
        )
        return

    prompt = command_parts[1]

    # 检查是否回复了包含图片的消息
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply_text(
            "请回复一张图片并使用此命令\n"
            "用法1: 回复图片 + /editimg [编辑描述]\n"
            "用法2: 发送图片并在说明中写 /editimg [编辑描述]"
        )
        return

    # 发送处理中消息
    status_msg = await message.reply_text("正在下载图片并进行编辑，请稍候...")

    try:
        # 增加活动请求计数
        _active_requests += 1

        # 下载图片
        image_bytes = await _download_photo(client, message.reply_to_message.photo)

        await status_msg.edit_text("图片已下载，正在进行AI编辑...")

        # 调用编辑API
        response = await imagegen_client.edit_image(
            image_bytes=image_bytes,
            prompt=prompt,
            model=user_model,
        )
        response.raise_for_status()

        # 处理响应
        success = await _process_image_edit_response(message, response, prompt, status_msg, user_model)

        if success:
            # 更新冷却时间(仅非白名单用户)
            if not is_whitelisted and message.from_user:
                _last_usage[message.from_user.id] = time.time()

            # 递增每日使用次数
            if message.from_user:
                await increment_daily_usage(message.from_user.id, user_model)

            # 删除状态消息
            await status_msg.delete()

    except Exception as e:
        await _handle_image_edit_error(e, status_msg)
    finally:
        # 减少活动请求计数
        _active_requests = max(0, _active_requests - 1)


@pyrogram.Client.on_message(pyrogram.filters.command("imgmodel"), group=0)
async def imgmodel_command(client: pyrogram.Client, message: Message):
    """Change image generation model (per-user configuration)"""
    if not _settings.get('image_gen', False):
        await message.reply_text("图片生成功能未启用")
        return

    if not imagegen_client:
        await message.reply_text("图片生成服务未配置")
        return

    user = message.from_user
    if user is None:
        return

    # Get model name from command
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        # Show current user's model
        current_model = await get_user_model(user.id)
        await message.reply_text(
            f"你当前使用的模型: {current_model}\n"
            f"\n可用模型:\n"
            f"- nano-banana (默认，无限制)\n"
            f"- nano-banana-pro (每日5次)\n"
            f"- nano-banana-pro-2k (每日5次)\n"
            f"- nano-banana-pro-4k (每日5次)\n"
            f"- gemini-2.5-flash-image (无限制)\n"
            f"\n用法: /imgmodel [模型名称]"
        )
        return

    model = command_parts[1].strip()

    # Save user's model configuration
    await set_user_model(user.id, model)
    await message.reply_text(f"✅ 已将你的模型切换为: {model}\n以后生成图片将使用此模型")
