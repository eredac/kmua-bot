"""OpenAI Embeddings 辅助模块 - 用于提问语义去重"""
import hashlib
import httpx
from typing import Optional, Tuple

from dynaconf import Dynaconf
from loguru import logger


# 加载配置
_settings = Dynaconf(
    envvar_prefix="KMUA",
    settings_files=[
        "settings.toml",
        "settings.dev.toml",
    ],
    environments=False,
)


class EmbeddingService:
    """Embedding 服务"""

    def __init__(self):
        # 优先使用独立的 embedding 配置，如果没有则回退到 image_gen 配置
        self.api_url = _settings.get("embedding_api_url") or _settings.get("image_gen_url", "https://api.openai.com/v1")
        self.api_key = _settings.get("embedding_api_key") or _settings.get("image_gen_api_key", "")
        self.model = _settings.get("embedding_model", "text-embedding-3-small")
        self.similarity_threshold = _settings.get("embedding_similarity_threshold", 0.85)

        if not self.api_key:
            logger.warning("未配置 Embedding API Key，语义去重功能将不可用")
        else:
            logger.info(f"Embedding 服务已配置: {self.api_url} | 模型: {self.model}")

    async def get_embedding(self, text: str) -> Optional[list[float]]:
        """
        获取文本的 embedding 向量

        Args:
            text: 输入文本

        Returns:
            embedding 向量，失败返回 None
        """
        if not self.api_key:
            logger.warning("未配置 API Key，无法获取 embedding")
            return None

        try:
            url = f"{self.api_url.rstrip('/')}/embeddings"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            data = {
                "model": self.model,
                "input": text,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()

                result = response.json()
                embedding = result["data"][0]["embedding"]

                logger.debug(f"成功获取 embedding，维度: {len(embedding)}")
                return embedding

        except httpx.HTTPStatusError as e:
            logger.error(f"获取 embedding 失败 (HTTP {e.response.status_code}): {e.response.text}")
            return None
        except Exception as e:
            logger.exception(f"获取 embedding 失败: {e}")
            return None

    def compute_embedding_hash(self, embedding: list[float]) -> str:
        """
        计算 embedding 的哈希值（用于快速去重）

        为了快速查找相似文本，我们对 embedding 进行量化后计算哈希。
        这不是完美的去重，但可以大幅减少需要计算相似度的次数。

        Args:
            embedding: embedding 向量

        Returns:
            哈希值（16进制字符串）
        """
        # 简单量化：将浮点数转换为整数（保留3位小数）
        quantized = [int(x * 1000) for x in embedding[:32]]  # 只取前32维

        # 计算哈希
        hash_input = ",".join(map(str, quantized)).encode()
        return hashlib.md5(hash_input).hexdigest()

    def cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """
        计算余弦相似度

        Args:
            vec1: 向量1
            vec2: 向量2

        Returns:
            相似度 (0-1)
        """
        if len(vec1) != len(vec2):
            logger.error(f"向量维度不匹配: {len(vec1)} vs {len(vec2)}")
            return 0.0

        # 计算点积
        dot_product = sum(a * b for a, b in zip(vec1, vec2))

        # 计算模长
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        # 避免除零
        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    async def check_duplicate(
        self, text: str, existing_texts: list[Tuple[str, str]]
    ) -> Tuple[bool, Optional[str], float]:
        """
        检查文本是否与已有文本重复

        Args:
            text: 待检查的文本
            existing_texts: 已有文本列表 [(text, embedding_hash), ...]

        Returns:
            (是否重复, 重复的文本, 相似度)
        """
        if not self.api_key or not existing_texts:
            return False, None, 0.0

        # 获取新文本的 embedding
        new_embedding = await self.get_embedding(text)
        if not new_embedding:
            logger.warning("无法获取 embedding，跳过去重检查")
            return False, None, 0.0

        # 计算新文本的哈希
        new_hash = self.compute_embedding_hash(new_embedding)

        # 检查是否有相同哈希（快速初筛）
        same_hash_texts = [t for t, h in existing_texts if h == new_hash]

        if same_hash_texts:
            # 有相同哈希，计算精确相似度
            for existing_text in same_hash_texts:
                existing_embedding = await self.get_embedding(existing_text)
                if existing_embedding:
                    similarity = self.cosine_similarity(new_embedding, existing_embedding)

                    if similarity >= self.similarity_threshold:
                        logger.info(
                            f"检测到重复提问（相似度: {similarity:.2f}）: "
                            f"新='{text[:50]}...' vs 旧='{existing_text[:50]}...'"
                        )
                        return True, existing_text, similarity

        return False, None, 0.0


# 全局服务实例
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取全局 embedding 服务实例"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
