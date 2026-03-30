from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


@dataclass
class UserConfig:
    lang: str = "zh-CN"
    coins: int = 144 * 16

    @classmethod
    def from_dict(cls, data: dict | None) -> "UserConfig":
        if data is None:
            return cls()
        return cls(lang=data.get("lang", "zh-CN"), coins=data.get("coins", 144 * 16))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChatConfig:
    waifu_enabled: bool = True
    delete_events_enabled: bool = False
    unpin_channel_pin_enabled: bool = False
    message_search_enabled: bool = False
    quote_probability: float = 0.001
    quote_pin_message: bool = True
    title_permissions: dict | None = None
    greeting: str | None = None
    ai_reply: bool = True
    setu_enabled: bool = True
    convert_b23_enabled: bool = True
    parse_artwork_enabled: bool = True
    pick_bottle_enabled: bool = True
    slash_enabled: bool = True
    divination_enabled: bool = True
    checkin_enabled: bool = True
    lang: str = "zh-CN"

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChatConfig":
        if data is None:
            return cls()
        return cls(
            waifu_enabled=data.get("waifu_enabled", True),
            delete_events_enabled=data.get("delete_events_enabled", False),
            unpin_channel_pin_enabled=data.get("unpin_channel_pin_enabled", False),
            message_search_enabled=data.get("message_search_enabled", False),
            quote_probability=data.get("quote_probability", 0.001),
            quote_pin_message=data.get("quote_pin_message", False),
            title_permissions=data.get("title_permissions", {}),
            greeting=data.get("greeting", None),
            ai_reply=data.get("ai_reply", True),
            setu_enabled=data.get("setu_enabled", True),
            convert_b23_enabled=data.get("convert_b23_enabled", False),
            parse_artwork_enabled=data.get("parse_artwork_enabled", True),
            pick_bottle_enabled=data.get("pick_bottle_enabled", True),
            slash_enabled=data.get("slash_enabled", True),
            divination_enabled=data.get("divination_enabled", True),
            checkin_enabled=data.get("checkin_enabled", True),
            lang=data.get("lang", "zh-CN"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class UserChatAssociation(Base):
    __tablename__ = "user_chat_association"
    __table_args__ = {"schema": "shared"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    waifu_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_bot_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserData(Base):
    __tablename__ = "user_data"
    __table_args__ = {"schema": "shared"}

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)

    avatar_big_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    config: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: asdict(UserConfig()),
    )
    is_married: Mapped[bool] = mapped_column(Boolean, default=False)
    married_waifu_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    waifu_mention: Mapped[bool] = mapped_column(Boolean, default=False)

    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_real_user: Mapped[bool] = mapped_column(Boolean, default=True)
    is_bot_global_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    update_avatar_at: Mapped[datetime | None] = mapped_column(
        DateTime(),
        nullable=True,
        default=None,
    )

    chats: Mapped[List["ChatData"]] = relationship(
        "ChatData",
        secondary="shared.user_chat_association",
        back_populates="members",
        primaryjoin="UserData.id == UserChatAssociation.user_id",
        secondaryjoin="ChatData.id == UserChatAssociation.chat_id",
        lazy="noload",
    )

    quotes: Mapped[List["Quote"]] = relationship(
        "Quote",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    married_waifu: Mapped["UserData | None"] = relationship(
        "UserData",
        remote_side=[id],
        post_update=True,
    )

    @property
    def user_config(self) -> UserConfig:
        return UserConfig.from_dict(self.config)

    @user_config.setter
    def user_config(self, config: UserConfig) -> None:
        self.config = config.to_dict()

    def __repr__(self) -> str:
        return f"<UserData(id={self.id}, username='{self.username}', full_name='{self.full_name}')>"


class ChatData(Base):
    __tablename__ = "chat_data"
    __table_args__ = {"schema": "shared"}

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    config: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: asdict(ChatConfig()),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    members: Mapped[List["UserData"]] = relationship(
        "UserData",
        secondary="shared.user_chat_association",
        back_populates="chats",
        primaryjoin="ChatData.id == UserChatAssociation.chat_id",
        secondaryjoin="UserData.id == UserChatAssociation.user_id",
        lazy="noload",
    )

    quotes: Mapped[List["Quote"]] = relationship(
        "Quote",
        back_populates="chat",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    @property
    def chat_config(self) -> ChatConfig:
        return ChatConfig.from_dict(self.config)

    @chat_config.setter
    def chat_config(self, config: ChatConfig) -> None:
        self.config = config.to_dict()

    def __repr__(self) -> str:
        return f"<ChatData(id={self.id}, title='{self.title}', username='{self.username}')>"


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = {"schema": "kmua"}

    link: Mapped[str] = mapped_column(String(256), primary_key=True)

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qer_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )

    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    img: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["UserData"] = relationship(
        foreign_keys=[user_id],
        back_populates="quotes",
        lazy="noload",
    )
    chat: Mapped["ChatData"] = relationship(
        "ChatData",
        back_populates="quotes",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<Quote(link='{self.link}', chat_id={self.chat_id}, user_id={self.user_id})>"


class Bottle(Base):
    __tablename__ = "bottles"
    __table_args__ = {"schema": "kmua"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )

    sender_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(4096), nullable=True)
    picks: Mapped[int] = mapped_column(BigInteger, default=0)
    reports: Mapped[int] = mapped_column(BigInteger, default=0)
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_picked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    def __repr__(self) -> str:
        return f"<Bottle(id={self.id}, sender_id={self.sender_id})>"


class ImageGenDailyUsage(Base):
    __tablename__ = "image_gen_daily_usage"
    __table_args__ = {"schema": "kmua"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    usage_date: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<ImageGenDailyUsage(user_id={self.user_id}, usage_count={self.usage_count}, usage_date='{self.usage_date}')>"


class UserImageGenConfig(Base):
    __tablename__ = "user_image_gen_config"
    __table_args__ = {"schema": "kmua"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    model: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<UserImageGenConfig(user_id={self.user_id}, model='{self.model}')>"


class DealerModeConfig(Base):
    """荷官模式配置表"""
    __tablename__ = "dealer_mode_config"
    __table_args__ = {"schema": "kmua"}

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    start_time: Mapped[str] = mapped_column(
        String(5),
        default="20:00",
        nullable=False,
    )

    end_time: Mapped[str] = mapped_column(
        String(5),
        default="22:00",
        nullable=False,
    )

    late_players: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<DealerModeConfig(chat_id={self.chat_id}, enabled={self.enabled})>"


class QuestionReference(Base):
    """参考提问表"""
    __tablename__ = "question_reference"
    __table_args__ = {"schema": "kmua"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    question_text: Mapped[str] = mapped_column(
        String(4096),
        nullable=False,
    )

    embedding_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    winner_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    loser_ids: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    used_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<QuestionReference(id={self.id}, chat_id={self.chat_id}, used_count={self.used_count})>"


class UserPoints(Base):
    """用户积分余额表，以 (user_id, chat_id) 为复合主键"""

    __tablename__ = "user_points"
    __table_args__ = {"schema": "shared"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    points: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<UserPoints(user_id={self.user_id}, chat_id={self.chat_id}, points={self.points})>"


class DailyCheckIn(Base):
    """每日签到记录表"""

    __tablename__ = "daily_checkin"
    __table_args__ = {"schema": "shared"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checkin_date: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )
    checkin_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    points_earned: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<DailyCheckIn(user_id={self.user_id}, chat_id={self.chat_id}, date='{self.checkin_date}', type='{self.checkin_type}')>"


class PointsTransaction(Base):
    """积分流水表，记录每笔积分变动"""

    __tablename__ = "points_transaction"
    __table_args__ = {"schema": "shared"}

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<PointsTransaction(id={self.id}, user_id={self.user_id}, chat_id={self.chat_id}, amount={self.amount})>"


class PendingQuestionState(Base):
    """待提问状态持久化表（重启恢复用，5分钟 TTL）"""

    __tablename__ = "pending_question_state"
    __table_args__ = {"schema": "kmua"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
    )
    state: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<PendingQuestionState(user_id={self.user_id}, expires_at={self.expires_at})>"


class UserTag(Base):
    """用户自定义群组标签，以 (user_id, chat_id) 为复合主键"""

    __tablename__ = "user_tag"
    __table_args__ = {"schema": "shared"}

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_text: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<UserTag(user_id={self.user_id}, chat_id={self.chat_id}, tag='{self.tag_text}', expires_at={self.expires_at})>"


class ChallengeRecord(Base):
    """积分挑战记录表（猜拳对决）"""

    __tablename__ = "challenge_record"
    __table_args__ = {"schema": "shared"}

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.chat_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    challenger_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # None 表示开放挑战，有值表示指定挑战对象
    challengee_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("shared.user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    bet_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 发起方手续费（发起时即扣，不可退）
    challenger_commission: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    # 接受方手续费（接受时扣）
    challengee_commission: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    # pending / pending_rps / completed / cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # rock / paper / scissors / None
    challenger_choice: Mapped[str | None] = mapped_column(String(10), nullable=True)
    challengee_choice: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 胜者 user_id；0 表示平局；None 表示未结算
    winner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # pending 状态下为接受截止时间；pending_rps 状态下为出拳截止时间
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<ChallengeRecord(id={self.id}, chat={self.chat_id}, "
            f"challenger={self.challenger_id}, status='{self.status}')>"
        )
