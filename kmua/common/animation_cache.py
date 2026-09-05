"""
卡牌动画缓存管理
单抽动画预生成和加载
"""
from pathlib import Path
from typing import Optional

from kmua.logger import logger


class AnimationCache:
    """单抽动画缓存管理器"""

    def __init__(self, base_path: str = "/kmua/data/cards"):
        self.base_path = Path(base_path)
        self._cache_status: dict[int, dict[int, bool]] = {}  # season_id -> {card_number: exists}

    def get_single_draw_animation(self, season_id: int, card_number: int) -> Optional[bytes]:
        """
        获取单抽动画（预生成的 MP4）

        Args:
            season_id: 赛季 ID
            card_number: 卡片编号

        Returns:
            MP4 字节流，如果不存在则返回 None
        """
        animation_path = self.base_path / f"season_{season_id}" / f"card_{card_number:02d}_single_draw.mp4"

        if not animation_path.exists():
            return None

        try:
            return animation_path.read_bytes()
        except Exception as e:
            logger.warning(f"[AnimationCache] Failed to read {animation_path}: {e}")
            return None

    def check_cache_status(self, season_id: int) -> dict[int, bool]:
        """
        检查指定赛季的缓存状态

        Args:
            season_id: 赛季 ID

        Returns:
            字典：{card_number: exists}
        """
        if season_id in self._cache_status:
            return self._cache_status[season_id]

        status = {}
        season_path = self.base_path / f"season_{season_id}"

        if not season_path.exists():
            self._cache_status[season_id] = status
            return status

        for card_num in range(1, 33):  # 32张卡
            animation_path = season_path / f"card_{card_num:02d}_single_draw.mp4"
            status[card_num] = animation_path.exists()

        self._cache_status[season_id] = status
        missing_count = sum(1 for exists in status.values() if not exists)

        if missing_count > 0:
            logger.warning(f"[AnimationCache] Season {season_id}: {missing_count}/32 animations missing")
        else:
            logger.info(f"[AnimationCache] Season {season_id}: All 32 animations cached")

        return status

    def invalidate_cache(self, season_id: int):
        """使缓存状态失效，强制重新检查"""
        if season_id in self._cache_status:
            del self._cache_status[season_id]


# 全局实例
_animation_cache = AnimationCache()


def get_single_draw_animation(season_id: int, card_number: int) -> Optional[bytes]:
    """获取单抽动画（预生成的 MP4）"""
    return _animation_cache.get_single_draw_animation(season_id, card_number)


def check_animation_cache_status(season_id: int) -> dict[int, bool]:
    """检查指定赛季的动画缓存状态"""
    return _animation_cache.check_cache_status(season_id)
