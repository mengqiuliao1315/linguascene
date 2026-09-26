from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "ai" / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise ValueError(f"Prompt 文件不存在：{path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **values: object) -> str:
    template = load_prompt(name)
    safe = {k: ("" if v is None else v) for k, v in values.items()}
    for key, value in safe.items():
        template = template.replace("{" + key + "}", str(value))
    return template
