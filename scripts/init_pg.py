"""
一次性脚本：在 PostgreSQL 中创建所有表（用 create_all 而非 alembic migrate）
完全独立运行，不依赖 kmua.config
"""
import asyncio
import sys
import os

# 不加载 kmua 配置，直接设置环境
PG_URL = "postgresql+asyncpg://kmua_user:1Azm7fVJxdW9ALr8yx_YiTgT1NoMCxqT@127.0.0.1:5432/bot_platform"


async def create_tables():
    from sqlalchemy.ext.asyncio import create_async_engine

    # 直接导入 Base（models.py 不依赖 config）
    sys.path.insert(0, "/kmua")
    # 注入假 config 让 models 正常 import
    os.environ.setdefault("KMUA_TOKEN", "dummy")
    os.environ.setdefault("KMUA_OWNERS", "[0]")

    from kmua.database.models import Base

    engine = create_async_engine(PG_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("✅ 所有表创建完成")

    # 列出已创建的表
    from sqlalchemy.ext.asyncio import create_async_engine as cae
    from sqlalchemy import text
    e2 = cae(PG_URL)
    async with e2.connect() as conn:
        result = await conn.execute(text(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname IN ('shared','kmua','hktrpg') "
            "ORDER BY schemaname, tablename"
        ))
        print("\n已创建的表：")
        for row in result:
            print(f"  {row[0]}.{row[1]}")
    await e2.dispose()


if __name__ == "__main__":
    asyncio.run(create_tables())
