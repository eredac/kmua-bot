"""add gacha card system tables

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-08-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "l6m7n8o9p0q1"
down_revision: str = "k5l6m7n8o9p0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 获取数据库检查器
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 创建 card_season 表
    if not insp.has_table("card_season", schema="kmua"):
        op.create_table(
            "card_season",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("total_cards", sa.Integer(), nullable=False, server_default="32"),
        sa.Column("draw_price", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("daily_free_draws", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("pity_legendary", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("pity_dedup", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("redeem_reward", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("trade_fee", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        schema="kmua",
    )

    # 创建索引(带防御检查)
    season_indexes = [idx["name"] for idx in insp.get_indexes("card_season", schema="kmua")]
    if "ix_kmua_card_season_id" not in season_indexes:
        op.create_index("ix_kmua_card_season_id", "card_season", ["id"], schema="kmua")

    # 创建 card_definition 表
    if not insp.has_table("card_definition", schema="kmua"):
        op.create_table(
        "card_definition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("card_number", sa.Integer(), nullable=False),
        sa.Column("rarity", sa.String(20), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("image_file_id", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["season_id"], ["kmua.card_season.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="kmua",
    )

    # 创建索引(带防御检查)
    definition_indexes = [idx["name"] for idx in insp.get_indexes("card_definition", schema="kmua")]
    if "ix_kmua_card_definition_id" not in definition_indexes:
        op.create_index("ix_kmua_card_definition_id", "card_definition", ["id"], schema="kmua")
    if "ix_kmua_card_definition_season_id" not in definition_indexes:
        op.create_index("ix_kmua_card_definition_season_id", "card_definition", ["season_id"], schema="kmua")

    # 创建 user_card 表
    if not insp.has_table("user_card", schema="kmua"):
        op.create_table(
        "user_card",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("card_def_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("obtained_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["shared.user_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["shared.chat_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_def_id"], ["kmua.card_definition.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["kmua.card_season.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="kmua",
    )

    # 创建索引(带防御检查)
    user_card_indexes = [idx["name"] for idx in insp.get_indexes("user_card", schema="kmua")]
    if "ix_kmua_user_card_id" not in user_card_indexes:
        op.create_index("ix_kmua_user_card_id", "user_card", ["id"], schema="kmua")
    if "ix_kmua_user_card_user_id" not in user_card_indexes:
        op.create_index("ix_kmua_user_card_user_id", "user_card", ["user_id"], schema="kmua")
    if "ix_kmua_user_card_chat_id" not in user_card_indexes:
        op.create_index("ix_kmua_user_card_chat_id", "user_card", ["chat_id"], schema="kmua")
    if "ix_kmua_user_card_card_def_id" not in user_card_indexes:
        op.create_index("ix_kmua_user_card_card_def_id", "user_card", ["card_def_id"], schema="kmua")
    if "ix_kmua_user_card_season_id" not in user_card_indexes:
        op.create_index("ix_kmua_user_card_season_id", "user_card", ["season_id"], schema="kmua")

    # 创建 card_draw_record 表
    if not insp.has_table("card_draw_record", schema="kmua"):
        op.create_table(
        "card_draw_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("card_def_id", sa.Integer(), nullable=False),
        sa.Column("is_free", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("pity_triggered", sa.String(20), nullable=True),
        sa.Column("draw_date", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["shared.user_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_id"], ["shared.chat_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["kmua.card_season.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_def_id"], ["kmua.card_definition.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="kmua",
    )
    # 创建索引(带防御检查)
    draw_record_indexes = [idx["name"] for idx in insp.get_indexes("card_draw_record", schema="kmua")]
    if "ix_kmua_card_draw_record_id" not in draw_record_indexes:
        op.create_index("ix_kmua_card_draw_record_id", "card_draw_record", ["id"], schema="kmua")
    if "ix_kmua_card_draw_record_user_id" not in draw_record_indexes:
        op.create_index("ix_kmua_card_draw_record_user_id", "card_draw_record", ["user_id"], schema="kmua")
    if "ix_kmua_card_draw_record_chat_id" not in draw_record_indexes:
        op.create_index("ix_kmua_card_draw_record_chat_id", "card_draw_record", ["chat_id"], schema="kmua")
    if "ix_kmua_card_draw_record_season_id" not in draw_record_indexes:
        op.create_index("ix_kmua_card_draw_record_season_id", "card_draw_record", ["season_id"], schema="kmua")
    if "ix_kmua_card_draw_record_draw_date" not in draw_record_indexes:
        op.create_index("ix_kmua_card_draw_record_draw_date", "card_draw_record", ["draw_date"], schema="kmua")

    # 创建 card_trade_request 表
    if not insp.has_table("card_trade_request", schema="kmua"):
        op.create_table(
        "card_trade_request",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=False),
        sa.Column("receiver_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_card_id", sa.Integer(), nullable=False),
        sa.Column("receiver_card_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["chat_id"], ["shared.chat_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["shared.user_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receiver_id"], ["shared.user_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_card_id"], ["kmua.user_card.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["receiver_card_id"], ["kmua.user_card.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["season_id"], ["kmua.card_season.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="kmua",
    )
    # 创建索引(带防御检查)
    trade_request_indexes = [idx["name"] for idx in insp.get_indexes("card_trade_request", schema="kmua")]
    if "ix_kmua_card_trade_request_id" not in trade_request_indexes:
        op.create_index("ix_kmua_card_trade_request_id", "card_trade_request", ["id"], schema="kmua")
    if "ix_kmua_card_trade_request_chat_id" not in trade_request_indexes:
        op.create_index("ix_kmua_card_trade_request_chat_id", "card_trade_request", ["chat_id"], schema="kmua")
    if "ix_kmua_card_trade_request_sender_id" not in trade_request_indexes:
        op.create_index("ix_kmua_card_trade_request_sender_id", "card_trade_request", ["sender_id"], schema="kmua")
    if "ix_kmua_card_trade_request_receiver_id" not in trade_request_indexes:
        op.create_index("ix_kmua_card_trade_request_receiver_id", "card_trade_request", ["receiver_id"], schema="kmua")

    # 创建 card_album 表
    if not insp.has_table("card_album", schema="kmua"):
        op.create_table(
        "card_album",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("card_def_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("first_obtained_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["shared.user_data.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["card_def_id"], ["kmua.card_definition.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["kmua.card_season.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "card_def_id", name="uq_album_user_card"),
        sa.PrimaryKeyConstraint("id"),
        schema="kmua",
    )
    # 创建索引(带防御检查)
    album_indexes = [idx["name"] for idx in insp.get_indexes("card_album", schema="kmua")]
    if "ix_kmua_card_album_id" not in album_indexes:
        op.create_index("ix_kmua_card_album_id", "card_album", ["id"], schema="kmua")
    if "ix_kmua_card_album_user_id" not in album_indexes:
        op.create_index("ix_kmua_card_album_user_id", "card_album", ["user_id"], schema="kmua")
    if "ix_kmua_card_album_card_def_id" not in album_indexes:
        op.create_index("ix_kmua_card_album_card_def_id", "card_album", ["card_def_id"], schema="kmua")
    if "ix_kmua_card_album_season_id" not in album_indexes:
        op.create_index("ix_kmua_card_album_season_id", "card_album", ["season_id"], schema="kmua")


def downgrade() -> None:
    op.drop_table("card_album", schema="kmua")
    op.drop_table("card_trade_request", schema="kmua")
    op.drop_table("card_draw_record", schema="kmua")
    op.drop_table("user_card", schema="kmua")
    op.drop_table("card_definition", schema="kmua")
    op.drop_table("card_season", schema="kmua")
