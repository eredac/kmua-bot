"""
数据迁移脚本：从 SQLite 读取数据，写入 PostgreSQL
完全独立运行，不依赖 kmua.config
"""
import asyncio
import sqlite3
import json
import sys
from datetime import datetime, timezone

SQLITE_PATH = "/kmua/data/kmua.db"
PG_URL = "postgresql://kmua_user:1Azm7fVJxdW9ALr8yx_YiTgT1NoMCxqT@127.0.0.1:5432/bot_platform"


def parse_dt(s, with_tz=True):
    """将 SQLite 的 naive datetime 字符串解析为 Python datetime（UTC）"""
    if s is None:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if with_tz:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return s  # fallback: return as-is


def read_sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    data = {}

    # user_data（先不包含 married_waifu_id，最后再更新）
    cur.execute("SELECT * FROM user_data")
    data["user_data"] = [dict(r) for r in cur.fetchall()]

    # chat_data
    cur.execute("SELECT * FROM chat_data")
    data["chat_data"] = [dict(r) for r in cur.fetchall()]

    # user_chat_association
    cur.execute("SELECT * FROM user_chat_association")
    data["user_chat_association"] = [dict(r) for r in cur.fetchall()]

    # user_points
    cur.execute("SELECT * FROM user_points")
    data["user_points"] = [dict(r) for r in cur.fetchall()]

    # daily_checkin
    cur.execute("SELECT * FROM daily_checkin")
    data["daily_checkin"] = [dict(r) for r in cur.fetchall()]

    # points_transaction
    cur.execute("SELECT * FROM points_transaction")
    data["points_transaction"] = [dict(r) for r in cur.fetchall()]

    # quotes
    cur.execute("SELECT * FROM quotes")
    data["quotes"] = [dict(r) for r in cur.fetchall()]

    # bottles
    cur.execute("SELECT * FROM bottles")
    data["bottles"] = [dict(r) for r in cur.fetchall()]

    # image_gen_daily_usage
    cur.execute("SELECT * FROM image_gen_daily_usage")
    data["image_gen_daily_usage"] = [dict(r) for r in cur.fetchall()]

    # user_image_gen_config
    cur.execute("SELECT * FROM user_image_gen_config")
    data["user_image_gen_config"] = [dict(r) for r in cur.fetchall()]

    # dealer_mode_config
    cur.execute("SELECT * FROM dealer_mode_config")
    data["dealer_mode_config"] = [dict(r) for r in cur.fetchall()]

    # question_reference
    cur.execute("SELECT * FROM question_reference")
    data["question_reference"] = [dict(r) for r in cur.fetchall()]

    conn.close()
    return data


async def migrate(data):
    import asyncpg
    conn = await asyncpg.connect(PG_URL)

    try:
        async with conn.transaction():

            # ── 1. shared.user_data（不带 married_waifu_id）──────────────────────
            print(f"  迁移 user_data: {len(data['user_data'])} 行")
            for r in data["user_data"]:
                config = r["config"] if isinstance(r["config"], str) else json.dumps(r["config"])
                await conn.execute("""
                    INSERT INTO shared.user_data
                      (id, username, full_name, avatar_big_id, config,
                       is_married, waifu_mention, is_bot, is_real_user,
                       is_bot_global_admin, created_at, updated_at, update_avatar_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                    ON CONFLICT (id) DO NOTHING
                """,
                    r["id"], r["username"], r["full_name"], r["avatar_big_id"],
                    config,
                    bool(r["is_married"]), bool(r["waifu_mention"]),
                    bool(r["is_bot"]), bool(r["is_real_user"]),
                    bool(r["is_bot_global_admin"]),
                    parse_dt(r["created_at"]), parse_dt(r["updated_at"]),
                    parse_dt(r["update_avatar_at"], with_tz=False),
                )

            # ── 2. shared.chat_data ───────────────────────────────────────────────
            print(f"  迁移 chat_data: {len(data['chat_data'])} 行")
            for r in data["chat_data"]:
                config = r["config"] if isinstance(r["config"], str) else json.dumps(r["config"])
                await conn.execute("""
                    INSERT INTO shared.chat_data
                      (id, title, username, config, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    ON CONFLICT (id) DO NOTHING
                """,
                    r["id"], r["title"], r["username"], config,
                    parse_dt(r["created_at"]), parse_dt(r["updated_at"]),
                )

            # ── 3. shared.user_chat_association ──────────────────────────────────
            print(f"  迁移 user_chat_association: {len(data['user_chat_association'])} 行")
            for r in data["user_chat_association"]:
                await conn.execute("""
                    INSERT INTO shared.user_chat_association
                      (user_id, chat_id, waifu_id, is_bot_admin, promoted_by,
                       created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (user_id, chat_id) DO NOTHING
                """,
                    r["user_id"], r["chat_id"], r["waifu_id"],
                    bool(r["is_bot_admin"]), r["promoted_by"],
                    parse_dt(r["created_at"]), parse_dt(r["updated_at"]),
                )

            # ── 4. shared.user_points ────────────────────────────────────────────
            print(f"  迁移 user_points: {len(data['user_points'])} 行")
            for r in data["user_points"]:
                await conn.execute("""
                    INSERT INTO shared.user_points
                      (user_id, chat_id, points, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5)
                    ON CONFLICT (user_id, chat_id) DO NOTHING
                """,
                    r["user_id"], r["chat_id"], r["points"],
                    parse_dt(r["created_at"]), parse_dt(r["updated_at"]),
                )

            # ── 5. shared.daily_checkin ──────────────────────────────────────────
            print(f"  迁移 daily_checkin: {len(data['daily_checkin'])} 行")
            for r in data["daily_checkin"]:
                await conn.execute("""
                    INSERT INTO shared.daily_checkin
                      (id, user_id, chat_id, checkin_date, checkin_type,
                       points_earned, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (id) DO NOTHING
                """,
                    r["id"], r["user_id"], r["chat_id"],
                    r["checkin_date"], r["checkin_type"], r["points_earned"],
                    parse_dt(r["created_at"]),
                )

            # ── 6. shared.points_transaction ─────────────────────────────────────
            print(f"  迁移 points_transaction: {len(data['points_transaction'])} 行")
            for r in data["points_transaction"]:
                await conn.execute("""
                    INSERT INTO shared.points_transaction
                      (id, user_id, chat_id, amount, reason, operator_id, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (id) DO NOTHING
                """,
                    r["id"], r["user_id"], r["chat_id"],
                    r["amount"], r["reason"], r["operator_id"],
                    parse_dt(r["created_at"]),
                )

            # ── 7. kmua.quotes ───────────────────────────────────────────────────
            print(f"  迁移 quotes: {len(data['quotes'])} 行")
            for r in data["quotes"]:
                await conn.execute("""
                    INSERT INTO kmua.quotes
                      (link, chat_id, user_id, qer_id, message_id,
                       text, img, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (link) DO NOTHING
                """,
                    r["link"], r["chat_id"], r["user_id"], r["qer_id"],
                    r["message_id"], r["text"], r["img"],
                    parse_dt(r["created_at"]), parse_dt(r["updated_at"]),
                )

            # ── 8. kmua.bottles ──────────────────────────────────────────────────
            print(f"  迁移 bottles: {len(data['bottles'])} 行")
            for r in data["bottles"]:
                await conn.execute("""
                    INSERT INTO kmua.bottles
                      (id, sender_id, text, picks, reports, file_id,
                       media_type, created_at, last_picked_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (id) DO NOTHING
                """,
                    r["id"], r["sender_id"], r["text"],
                    r["picks"], r["reports"], r["file_id"], r["media_type"],
                    parse_dt(r["created_at"]), parse_dt(r["last_picked_at"]),
                )

            # ── 9. kmua.image_gen_daily_usage ────────────────────────────────────
            # SQLite 旧表列名：model_tier, usage_count, usage_date（无 updated_at）
            print(f"  迁移 image_gen_daily_usage: {len(data['image_gen_daily_usage'])} 行")
            for r in data["image_gen_daily_usage"]:
                await conn.execute("""
                    INSERT INTO kmua.image_gen_daily_usage
                      (user_id, usage_count, usage_date)
                    VALUES ($1,$2,$3)
                    ON CONFLICT (user_id) DO NOTHING
                """,
                    r["user_id"], r["usage_count"], r.get("usage_date", "1970-01-01"),
                )

            # ── 10. kmua.user_image_gen_config ───────────────────────────────────
            print(f"  迁移 user_image_gen_config: {len(data['user_image_gen_config'])} 行")
            for r in data["user_image_gen_config"]:
                await conn.execute("""
                    INSERT INTO kmua.user_image_gen_config
                      (user_id, model, updated_at)
                    VALUES ($1,$2,$3)
                    ON CONFLICT (user_id) DO NOTHING
                """,
                    r["user_id"], r["model"], parse_dt(r["updated_at"]),
                )

            # ── 11. kmua.dealer_mode_config ──────────────────────────────────────
            print(f"  迁移 dealer_mode_config: {len(data['dealer_mode_config'])} 行")
            for r in data["dealer_mode_config"]:
                late_players = r["late_players"]
                if isinstance(late_players, str):
                    pass  # already JSON string
                else:
                    late_players = json.dumps(late_players)
                await conn.execute("""
                    INSERT INTO kmua.dealer_mode_config
                      (chat_id, enabled, start_time, end_time, late_players,
                       created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (chat_id) DO NOTHING
                """,
                    r["chat_id"], bool(r["enabled"]), r["start_time"],
                    r["end_time"], late_players,
                    parse_dt(r["created_at"]), parse_dt(r["updated_at"]),
                )

            # ── 12. kmua.question_reference ──────────────────────────────────────
            print(f"  迁移 question_reference: {len(data['question_reference'])} 行")
            for r in data["question_reference"]:
                await conn.execute("""
                    INSERT INTO kmua.question_reference
                      (id, chat_id, question_text, embedding_hash,
                       winner_id, loser_ids, used_count, created_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (id) DO NOTHING
                """,
                    r["id"], r["chat_id"], r["question_text"],
                    r["embedding_hash"], r["winner_id"], r["loser_ids"],
                    r["used_count"], parse_dt(r["created_at"]),
                )

            # ── 13. 更新 user_data.married_waifu_id ──────────────────────────────
            married = [(r["id"], r["married_waifu_id"])
                       for r in data["user_data"] if r["married_waifu_id"] is not None]
            print(f"  更新 married_waifu_id: {len(married)} 行")
            for uid, wid in married:
                await conn.execute("""
                    UPDATE shared.user_data SET married_waifu_id=$1 WHERE id=$2
                """, wid, uid)

            # ── 14. 重置序列 ─────────────────────────────────────────────────────
            print("  重置 PG 序列...")
            for schema, table, col in [
                ("shared", "daily_checkin", "id"),
                ("shared", "points_transaction", "id"),
                ("kmua", "bottles", "id"),
                ("kmua", "question_reference", "id"),
            ]:
                await conn.execute(f"""
                    SELECT setval(
                        pg_get_serial_sequence('{schema}.{table}', '{col}'),
                        COALESCE((SELECT MAX({col}) FROM {schema}.{table}), 1)
                    )
                """)

        print("\n✅ 迁移完成！")

        # 验证迁移结果
        print("\n📊 PostgreSQL 数据验证：")
        checks = [
            ("shared.user_data", "user_data"),
            ("shared.chat_data", "chat_data"),
            ("shared.user_chat_association", "user_chat_association"),
            ("shared.user_points", "user_points"),
            ("shared.daily_checkin", "daily_checkin"),
            ("shared.points_transaction", "points_transaction"),
            ("kmua.quotes", "quotes"),
            ("kmua.bottles", "bottles"),
            ("kmua.question_reference", "question_reference"),
        ]
        for pg_table, sqlite_table in checks:
            pg_count = await conn.fetchval(f"SELECT COUNT(*) FROM {pg_table}")
            sqlite_count = len(data[sqlite_table])
            status = "✅" if pg_count == sqlite_count else "⚠️"
            print(f"  {status} {pg_table}: PG={pg_count}, SQLite={sqlite_count}")

    finally:
        await conn.close()


async def main():
    print("📖 读取 SQLite 数据...")
    data = read_sqlite()
    total = sum(len(v) for v in data.values())
    print(f"   共 {total} 行数据\n")

    print("📤 写入 PostgreSQL...")
    await migrate(data)


if __name__ == "__main__":
    asyncio.run(main())
