from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined


_TEMPLATE_ENV = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def render_template(template_text: str, context: dict[str, Any]) -> str:
    template = _TEMPLATE_ENV.from_string(template_text)
    return template.render(**context)


def path_within(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
