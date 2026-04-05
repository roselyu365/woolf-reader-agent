"""
theme_tagger.py
用 Claude 给每个 chunk 打主题标签（从预定义9个主题中选1-3个）
离线运行，入库前调用
"""

import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")  # 打标签用 Haiku，省钱省时

THEMES = [
    "women_independence",       # 女性独立、空间、经济自由
    "stream_of_consciousness",  # 意识流、内心叙事、感知
    "grief_loss",               # 哀悼、失去、死亡
    "bloomsbury_circle",        # 布卢姆斯伯里圈子、朋友关系
    "writing_process",          # 写作本身、创作过程、语言
    "vita_relationship",        # 与 Vita Sackville-West 的关系
    "mansfield_rivalry",        # 与 Katherine Mansfield 的竞争/欣赏
    "historical_social_context",# 时代背景、社会结构、政治
    "feminist_argument",        # 女权论点、对不平等的批判
]

SYSTEM_PROMPT = f"""你是一个文学研究助手，专门分析弗吉尼亚·伍尔夫的作品。

给定一段文字，从以下主题列表中选择1-3个最相关的主题标签。
只选真正相关的，不要为了凑数而选。

主题列表：
{chr(10).join(f"- {t}" for t in THEMES)}

只输出 JSON 数组，例如：["women_independence", "feminist_argument"]
不要输出任何其他内容。"""


def tag_chunk(text: str) -> list[str]:
    """给单个 chunk 打标签，返回主题列表"""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=100,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text[:800]}],  # 截断避免超长
        )
        raw = response.content[0].text.strip()
        tags = json.loads(raw)
        # 只保留预定义主题中的标签
        return [t for t in tags if t in THEMES]
    except Exception as e:
        print(f"    Warning: tag_chunk failed ({e}), using empty tags")
        return []


def tag_chunks_batch(chunks: list[str], batch_size: int = 20) -> list[list[str]]:
    """批量打标签，显示进度"""
    results = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        if i % batch_size == 0:
            print(f"    Tagging: {i}/{total}...")
        results.append(tag_chunk(chunk))
    print(f"    Tagging: {total}/{total} done")
    return results
