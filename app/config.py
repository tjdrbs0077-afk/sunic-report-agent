"""경로 상수 — 프로젝트 전체가 이 모듈의 경로만 사용한다."""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent

STATIC = APP_DIR / "static"
ASSETS = APP_DIR / "assets"
CONFIG_DIR = ROOT / "config"
DATA = ROOT / "data"
UPLOADS = ROOT / "uploads"
GENERATED = ROOT / "generated"

DEFAULT_TEMPLATE = ASSETS / "보고양식_Sample_4팀.pptx"
TEMPLATE = DEFAULT_TEMPLATE  # 하위 호환 — 실제 사용은 active_template()
RULES_FILE = CONFIG_DIR / "standard_rules.yaml"
REPORT_INDEX = DATA / "reports.json"
LAYOUT_STORE = DATA / "layout_overrides.json"
PROFILE_CACHE = DATA / "template_profile.json"
TEMPLATE_STATE = DATA / "active_template.json"
TEMPLATES_DIR = DATA / "templates"

for folder in (DATA, UPLOADS, GENERATED, TEMPLATES_DIR):
    folder.mkdir(parents=True, exist_ok=True)


def active_template() -> Path:
    """현재 기준 양식 PPTX. 사용자가 다른 PPTX를 올리면 그 파일을 쓴다."""
    import json

    if TEMPLATE_STATE.exists():
        try:
            state = json.loads(TEMPLATE_STATE.read_text(encoding="utf-8"))
            path = TEMPLATES_DIR / state.get("file", "")
            if state.get("file") and path.exists():
                return path
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_TEMPLATE


def active_template_name() -> str:
    return active_template().name
