"""
积分挑战模块 - 猜拳对决

/challenge [积分] - 发起积分挑战
  · 回复某人消息 → 指定对战；直接发送 → 开放挑战（任何人可接受）
  · 积分参数可选；默认为总分 2%，上限为总分 5%
  · 每天最多发起 3 次（每天 4:00 重置）

积分扣除时机：
  · 发起时：仅扣手续费（赌注暂不扣）
  · 接受时：双方各扣赌注，接受方同时扣手续费

手续费规则（赌注 > 10 时生效）：
  · 发起方 12%，接受方 8%
  · 发起方手续费在发起时扣除，无论是否有人接受均不退还

超时规则：
  · 发起后 30 分钟无人接受 → 自动取消（无需退款，赌注本来就没扣）
  · 接受后 30 分钟未全部出拳 → 未出拳方随机出拳，正常结算
"""
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone

from pyrogram import filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from kmua import database
from kmua.database.db import AsyncSessionFactory
from kmua.database.models import ChallengeRecord
from kmua.logger import logger

_TZ_CST = timezone(timedelta(hours=8))
_DAILY_LIMIT = 3
_DEFAULT_BET_RATIO = 0.02
_MAX_BET_RATIO = 0.05
_COMMISSION_THRESHOLD = 10
_CHALLENGER_COMMISSION_RATIO = 0.12
_CHALLENGEE_COMMISSION_RATIO = 0.08
_PENDING_TIMEOUT_SECS = 1800  # 发起后 30 分钟无人接受则取消
_RPS_TIMEOUT_SECS = 1800      # 接受后 30 分钟未全部出拳则随机

_CHOICE_EMOJI = {"rock": "✊", "scissors": "✌️", "paper": "🖐"}
_CHOICE_LABEL = {"rock": "石头", "scissors": "剪刀", "paper": "布"}
_WINS_AGAINST = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
_ALL_CHOICES = list(_CHOICE_EMOJI.keys())

# 活跃计时器，challenge_id → asyncio.Task
_pending_timers: dict[int, asyncio.Task] = {}
_rps_timers: dict[int, asyncio.Task] = {}


# ─── 工具函数 ──────────────────────────────────────────────


def _calc_commission(bet: int, ratio: float) -> int:
    if bet <= _COMMISSION_THRESHOLD:
        return 0
    return round(bet * ratio)


def _rps_result(choice_a: str, choice_b: str) -> int:
    """1=a赢, -1=b赢, 0=平局"""
    if choice_a == choice_b:
        return 0
    return 1 if _WINS_AGAINST[choice_a] == choice_b else -1


async def _get_name(user_id: int) -> str:
    user = await database.get_user_by_id(user_id)
    return user.full_name if user else str(user_id)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─── 消息文本构造 ──────────────────────────────────────────


def _pending_text(
    challenger_name: str,
    challengee_name: str | None,
    bet: int,
    commission_a: int,
) -> str:
    target = f"<b>{challengee_name}</b>" if challengee_name else "所有人"
    commission_note = (
        f"\n💸 手续费（已扣）：{commission_a} 积分" if commission_a > 0 else ""
    )
    return (
        f"⚔️ <b>{challenger_name}</b> 向 {target} 发起积分猜拳挑战！\n"
        f"💰 赌注：<b>{bet}</b> 积分{commission_note}\n"
        f"⏰ 有效期：30 分钟\n\n"
        f"点击按钮接受挑战喵～"
    )


def _rps_text(
    c_name: str,
    e_name: str,
    bet: int,
    c_choice: str | None,
    e_choice: str | None,
) -> str:
    c_status = "✅ 已出拳" if c_choice else "⏳ 等待出拳..."
    e_status = "✅ 已出拳" if e_choice else "⏳ 等待出拳..."
    return (
        f"⚔️ <b>{c_name}</b> vs <b>{e_name}</b>\n"
        f"💰 赌注：<b>{bet}</b> 积分\n"
        f"⏰ 出拳有效期：30 分钟\n\n"
        f"👤 {c_name}：{c_status}\n"
        f"👤 {e_name}：{e_status}\n\n"
        f"请双方各自出拳 👇"
    )


def _result_text(
    c_name: str,
    e_name: str,
    bet: int,
    c_choice: str,
    e_choice: str,
    result: int,
    timeout_auto: bool = False,
) -> str:
    c_icon = f"{_CHOICE_EMOJI[c_choice]} {_CHOICE_LABEL[c_choice]}"
    e_icon = f"{_CHOICE_EMOJI[e_choice]} {_CHOICE_LABEL[e_choice]}"
    auto_note = "⏰ 超时，随机出拳！\n\n" if timeout_auto else ""
    if result == 0:
        outcome = f"🤝 <b>平局！</b> 双方各取回 {bet} 积分（手续费不退）"
    elif result == 1:
        outcome = f"🏆 <b>{c_name}</b> 获胜！赢得对方 {bet} 积分！"
    else:
        outcome = f"🏆 <b>{e_name}</b> 获胜！赢得对方 {bet} 积分！"
    return (
        f"{auto_note}"
        f"⚔️ <b>{c_name}</b> vs <b>{e_name}</b>\n\n"
        f"👤 {c_name}：{c_icon}\n"
        f"👤 {e_name}：{e_icon}\n\n"
        f"{outcome}"
    )


# ─── 键盘构造 ──────────────────────────────────────────────


def _pending_keyboard(challenge_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✋ 接受挑战", callback_data=f"chal_accept_{challenge_id}")]]
    )


def _rps_keyboard(challenge_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✊ 石头", callback_data=f"chal_rps_{challenge_id}_rock"),
            InlineKeyboardButton("✌️ 剪刀", callback_data=f"chal_rps_{challenge_id}_scissors"),
            InlineKeyboardButton("🖐 布", callback_data=f"chal_rps_{challenge_id}_paper"),
        ]]
    )


# ─── 结算核心逻辑 ──────────────────────────────────────────


async def _do_resolve(
    client: Client,
    record: ChallengeRecord,
    challenger_name: str,
    challengee_name: str,
    timeout_auto: bool = False,
) -> None:
    """结算猜拳对决：判定胜负，发放积分，编辑消息。"""
    challenge_id = record.id
    c_choice = record.challenger_choice
    e_choice = record.challengee_choice
    result = _rps_result(c_choice, e_choice)  # type: ignore[arg-type]

    winner_id = (
        record.challenger_id if result == 1
        else record.challengee_id if result == -1
        else 0
    )

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await database.complete_challenge(challenge_id, winner_id, session=session)
                if result == 0:
                    await database.add_points(
                        record.challenger_id, record.chat_id, record.bet_amount,
                        reason=f"猜拳平局取回赌注 #{challenge_id}", session=session,
                    )
                    await database.add_points(
                        record.challengee_id, record.chat_id, record.bet_amount,
                        reason=f"猜拳平局取回赌注 #{challenge_id}", session=session,
                    )
                else:
                    await database.add_points(
                        winner_id, record.chat_id, record.bet_amount * 2,
                        reason=f"猜拳获胜 #{challenge_id}", session=session,
                    )
    except ValueError:
        return  # 并发情况下已被另一协程结算，忽略

    text = _result_text(
        challenger_name, challengee_name,
        record.bet_amount, c_choice, e_choice, result,  # type: ignore[arg-type]
        timeout_auto=timeout_auto,
    )
    try:
        await client.edit_message_text(
            record.chat_id, record.message_id, text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    logger.info(
        f"挑战结算: id={challenge_id}, result={result}, "
        f"winner={winner_id}, bet={record.bet_amount}, auto={timeout_auto}"
    )


# ─── 超时计时器任务 ────────────────────────────────────────


async def _pending_timeout_task(
    client: Client,
    challenge_id: int,
) -> None:
    """等待 30 分钟，若挑战仍处于 pending 则自动取消"""
    await asyncio.sleep(_PENDING_TIMEOUT_SECS)
    _pending_timers.pop(challenge_id, None)

    record = await database.get_challenge(challenge_id)
    if record is None or record.status != "pending":
        return

    await database.expire_challenge(challenge_id)
    try:
        await client.edit_message_text(
            record.chat_id, record.message_id,
            "⏰ 挑战已超时，自动取消。（手续费不退）",
        )
    except Exception:
        pass
    logger.info(f"挑战超时取消(pending): id={challenge_id}")


async def _rps_timeout_task(
    client: Client,
    challenge_id: int,
) -> None:
    """等待 30 分钟，若仍有人未出拳则随机补全后结算"""
    await asyncio.sleep(_RPS_TIMEOUT_SECS)
    _rps_timers.pop(challenge_id, None)

    record = await database.get_challenge(challenge_id)
    if record is None or record.status != "pending_rps":
        return

    # 为未出拳的一方随机选择
    auto_c = record.challenger_choice is None
    auto_e = record.challengee_choice is None
    if auto_c:
        choice = random.choice(_ALL_CHOICES)
        try:
            record = await database.set_challenge_choice(challenge_id, record.challenger_id, choice)
        except ValueError:
            return
    if auto_e:
        choice = random.choice(_ALL_CHOICES)
        try:
            record = await database.set_challenge_choice(challenge_id, record.challengee_id, choice)
        except ValueError:
            return

    # 重新加载最新记录确保两边选择都已写入
    record = await database.get_challenge(challenge_id)
    if record is None or not (record.challenger_choice and record.challengee_choice):
        return

    challenger_name = await _get_name(record.challenger_id)
    challengee_name = await _get_name(record.challengee_id)
    await _do_resolve(client, record, challenger_name, challengee_name, timeout_auto=True)
    logger.info(f"挑战超时随机出拳结算: id={challenge_id}")


def _start_pending_timer(client: Client, challenge_id: int) -> None:
    task = asyncio.create_task(_pending_timeout_task(client, challenge_id))
    _pending_timers[challenge_id] = task


def _start_rps_timer(client: Client, challenge_id: int) -> None:
    # 取消旧的 pending 计时器
    if challenge_id in _pending_timers:
        _pending_timers.pop(challenge_id).cancel()
    task = asyncio.create_task(_rps_timeout_task(client, challenge_id))
    _rps_timers[challenge_id] = task


# ─── 启动恢复 ──────────────────────────────────────────────


async def recover_challenges_on_startup(client: Client) -> None:
    """Bot 启动时处理历史遗留的超时挑战"""
    # 1. 已超时的 pending 挑战 → 直接取消（不需要编辑消息，已重启）
    expired_pending = await database.get_expired_challenges("pending")
    for record in expired_pending:
        await database.expire_challenge(record.id)
    if expired_pending:
        logger.info(f"启动恢复：清理 {len(expired_pending)} 个超时 pending 挑战")

    # 2. 已超时的 pending_rps 挑战 → 随机出拳并结算
    expired_rps = await database.get_expired_challenges("pending_rps")
    for record in expired_rps:
        if not record.challenger_choice:
            try:
                record = await database.set_challenge_choice(
                    record.id, record.challenger_id, random.choice(_ALL_CHOICES)
                )
            except ValueError:
                continue
        if not record.challengee_choice:
            try:
                record = await database.set_challenge_choice(
                    record.id, record.challengee_id, random.choice(_ALL_CHOICES)
                )
            except ValueError:
                continue
        record = await database.get_challenge(record.id)
        if record and record.challenger_choice and record.challengee_choice:
            c_name = await _get_name(record.challenger_id)
            e_name = await _get_name(record.challengee_id)
            await _do_resolve(client, record, c_name, e_name, timeout_auto=True)
    if expired_rps:
        logger.info(f"启动恢复：结算 {len(expired_rps)} 个超时 pending_rps 挑战")


# ─── 命令处理器 ────────────────────────────────────────────


@Client.on_message(filters.command("challenge") & filters.group, group=0)
async def challenge_handler(client: Client, message: Message) -> None:
    """处理 /challenge [积分] 命令"""
    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    challenger_id = user.id
    challenger_name = user.full_name

    # 确定挑战对象
    # 注意：Forum 话题群组中每条消息的 reply_to_message 会自动指向话题创建消息，
    # 需要排除这种情况，只有用户主动回复他人消息时才视为指定挑战
    challengee_id: int | None = None
    challengee_name: str | None = None
    _reply = message.reply_to_message
    _is_real_reply = (
        _reply is not None
        and _reply.from_user is not None
        # 排除话题服务消息（话题创建/编辑）
        and not getattr(_reply, "forum_topic_created", None)
        and not getattr(_reply, "forum_topic_edited", None)
        # 排除 Forum 话题根消息（reply_to_message_id == message_thread_id 时只是在话题内发言，非主动回复）
        and (
            getattr(message, "message_thread_id", None) is None
            or message.reply_to_message_id != getattr(message, "message_thread_id", None)
        )
    )
    if _is_real_reply:
        target = _reply.from_user  # type: ignore[union-attr]
        if target.id == challenger_id:
            await message.reply_text("⚠️ 不能向自己发起挑战喵～")
            return
        if target.is_bot:
            await message.reply_text("⚠️ 不能向 Bot 发起挑战喵～")
            return
        challengee_id = target.id
        challengee_name = target.full_name

    # 每日发起次数检查
    today_count = await database.get_daily_challenge_count(challenger_id, chat_id)
    if today_count >= _DAILY_LIMIT:
        await message.reply_text(
            f"⚠️ 今日发起挑战次数已达上限（{_DAILY_LIMIT} 次），明天再来喵～"
        )
        return

    # 获取发起者积分
    user_points_obj = await database.get_user_points(challenger_id, chat_id)
    total_points = user_points_obj.points if user_points_obj else 0
    if total_points <= 0:
        await message.reply_text("⚠️ 你没有积分，无法发起挑战喵～")
        return

    # 计算赌注上限与默认值
    max_bet = max(1, round(total_points * _MAX_BET_RATIO))
    default_bet = max(1, round(total_points * _DEFAULT_BET_RATIO))

    # 解析可选赌注参数
    args = message.text.split(maxsplit=1)
    if len(args) >= 2:
        try:
            bet_amount = int(args[1].strip())
            if bet_amount <= 0:
                raise ValueError
        except ValueError:
            await message.reply_text("⚠️ 赌注必须是正整数喵～")
            return
        if bet_amount > max_bet:
            await message.reply_text(
                f"⚠️ 赌注不能超过总积分的 5%（当前上限：<b>{max_bet}</b> 积分）",
                parse_mode=ParseMode.HTML,
            )
            return
    else:
        bet_amount = default_bet

    # 计算手续费
    commission_a = _calc_commission(bet_amount, _CHALLENGER_COMMISSION_RATIO)
    commission_b = _calc_commission(bet_amount, _CHALLENGEE_COMMISSION_RATIO)

    # 验证：余额 ≥ 赌注 + 手续费（接受时才真正扣赌注，但提前验证避免无效挑战）
    need_total = bet_amount + commission_a
    if total_points < need_total:
        await message.reply_text(
            f"⚠️ 积分不足！需要 <b>{need_total}</b> 积分"
            f"（赌注 {bet_amount} + 手续费 {commission_a}），"
            f"当前积分：<b>{total_points}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # 发起时只扣手续费（赌注接受时扣）
    expires_at = _now_utc() + timedelta(seconds=_PENDING_TIMEOUT_SECS)
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                if commission_a > 0:
                    await database.cost_points(
                        challenger_id, chat_id, commission_a,
                        reason=f"发起积分挑战手续费（赌注 {bet_amount}）",
                        session=session,
                    )
                record = await database.create_challenge(
                    chat_id=chat_id,
                    challenger_id=challenger_id,
                    challengee_id=challengee_id,
                    bet_amount=bet_amount,
                    challenger_commission=commission_a,
                    challengee_commission=commission_b,
                    expires_at=expires_at,
                    session=session,
                )
                challenge_id = record.id
    except ValueError as e:
        await message.reply_text(f"⚠️ {e}")
        return

    # 发送挑战消息并回填 message_id
    text = _pending_text(challenger_name, challengee_name, bet_amount, commission_a)
    reply = await message.reply_text(
        text, reply_markup=_pending_keyboard(challenge_id), parse_mode=ParseMode.HTML
    )
    await database.update_challenge_message_id(challenge_id, reply.id)

    # 启动 pending 超时计时器
    _start_pending_timer(client, challenge_id)

    logger.info(
        f"挑战发起: id={challenge_id}, chat={chat_id}, "
        f"challenger={challenger_id}, challengee={challengee_id}, bet={bet_amount}"
    )


# ─── 回调处理器 ────────────────────────────────────────────


@Client.on_callback_query(filters.regex(r"^chal_accept_(\d+)$"))
async def on_accept_challenge(client: Client, callback: CallbackQuery) -> None:
    """处理接受挑战按钮"""
    m = re.match(r"^chal_accept_(\d+)$", callback.data)
    challenge_id = int(m.group(1))  # type: ignore[union-attr]
    accepter_id = callback.from_user.id
    accepter_name = callback.from_user.full_name

    record = await database.get_challenge(challenge_id)
    if record is None:
        await callback.answer("❌ 挑战记录不存在", show_alert=True)
        return
    if record.status != "pending":
        await callback.answer("❌ 该挑战已有人接受、已结束或已超时", show_alert=True)
        return
    if accepter_id == record.challenger_id:
        await callback.answer("⚠️ 不能接受自己的挑战喵～", show_alert=True)
        return
    if record.challengee_id is not None and accepter_id != record.challengee_id:
        await callback.answer("⚠️ 这是指定挑战，只有被指定的人才能接受喵～", show_alert=True)
        return

    # 验证双方余额
    c_points_obj = await database.get_user_points(record.challenger_id, record.chat_id)
    challenger_points = c_points_obj.points if c_points_obj else 0
    if challenger_points < record.bet_amount:
        await callback.answer(
            f"⚠️ 发起者积分不足（需要 {record.bet_amount}，当前 {challenger_points}），挑战无效",
            show_alert=True,
        )
        return

    e_points_obj = await database.get_user_points(accepter_id, record.chat_id)
    accepter_points = e_points_obj.points if e_points_obj else 0
    need_e = record.bet_amount + record.challengee_commission
    if accepter_points < need_e:
        await callback.answer(
            f"⚠️ 积分不足！需要 {need_e} 积分"
            f"（赌注 {record.bet_amount} + 手续费 {record.challengee_commission}），"
            f"当前积分：{accepter_points}",
            show_alert=True,
        )
        return

    # 原子：双方同时扣赌注 + 接受方扣手续费，更新状态
    new_expires_at = _now_utc() + timedelta(seconds=_RPS_TIMEOUT_SECS)
    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await database.cost_points(
                    record.challenger_id, record.chat_id, record.bet_amount,
                    reason=f"积分挑战赌注 #{challenge_id}",
                    session=session,
                )
                await database.cost_points(
                    accepter_id, record.chat_id, need_e,
                    reason=f"接受积分挑战 #{challenge_id}（赌注 {record.bet_amount}，手续费 {record.challengee_commission}）",
                    session=session,
                )
                await database.accept_challenge(
                    challenge_id, accepter_id,
                    new_expires_at=new_expires_at,
                    session=session,
                )
    except ValueError as e:
        await callback.answer(f"⚠️ {e}", show_alert=True)
        return

    # 切换到猜拳界面 + 启动 RPS 计时器
    challenger_name = await _get_name(record.challenger_id)
    text = _rps_text(challenger_name, accepter_name, record.bet_amount, None, None)
    await callback.message.edit_text(
        text, reply_markup=_rps_keyboard(challenge_id), parse_mode=ParseMode.HTML
    )
    await callback.answer("✅ 接受挑战！请出拳喵～")

    _start_rps_timer(client, challenge_id)
    logger.info(f"挑战接受: id={challenge_id}, accepter={accepter_id}")


@Client.on_callback_query(filters.regex(r"^chal_rps_(\d+)_(rock|scissors|paper)$"))
async def on_rps_choice(client: Client, callback: CallbackQuery) -> None:
    """处理出拳选择"""
    m = re.match(r"^chal_rps_(\d+)_(rock|scissors|paper)$", callback.data)
    challenge_id = int(m.group(1))  # type: ignore[union-attr]
    choice = m.group(2)  # type: ignore[union-attr]
    user_id = callback.from_user.id

    try:
        record = await database.set_challenge_choice(challenge_id, user_id, choice)
    except ValueError as e:
        msg = str(e)
        if msg == "already_chosen":
            await callback.answer("⚠️ 你已经出拳了喵～", show_alert=True)
        elif msg == "not_participant":
            await callback.answer("⚠️ 你不是本场挑战的参与者喵～", show_alert=True)
        else:
            await callback.answer(f"⚠️ {e}", show_alert=True)
        return

    await callback.answer(f"已选择 {_CHOICE_EMOJI[choice]} {_CHOICE_LABEL[choice]}！")

    challenger_name = await _get_name(record.challenger_id)
    challengee_name = await _get_name(record.challengee_id)

    if record.challenger_choice and record.challengee_choice:
        # 取消 RPS 计时器，立即结算
        if challenge_id in _rps_timers:
            _rps_timers.pop(challenge_id).cancel()
        await _do_resolve(client, record, challenger_name, challengee_name)
    else:
        # 更新消息显示一方已出拳
        text = _rps_text(
            challenger_name, challengee_name, record.bet_amount,
            record.challenger_choice, record.challengee_choice,
        )
        try:
            await callback.message.edit_text(
                text, reply_markup=_rps_keyboard(challenge_id), parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
