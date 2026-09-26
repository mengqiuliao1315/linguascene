"""Prompt 加载器。

Prompt 模板统一放在仓库根目录的 ai/prompts/，业务代码不内联 Prompt 文本。
"""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "ai" / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        # 抛 ValueError 而不是 FileNotFoundError：各 Agent 捕获的是
        # (AIProviderError, ValueError)，据此降级到规则引擎。缺文件是部署问题，
        # 应该退化成离线分析，不该让整个请求 500。
        raise ValueError(f"Prompt 文件不存在：{path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **values: object) -> str:
    template = load_prompt(name)
    safe = {k: ("" if v is None else v) for k, v in values.items()}
    for key, value in safe.items():
        template = template.replace("{" + key + "}", str(value))
    return template
