"""경로 상수 — 프로젝트 전체가 이 모듈의 경로만 사용한다."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
ENV_FILE = ROOT / ".env"


def _load_env() -> None:
    """루트의 .env 를 환경변수로 읽어 온다.

    이미 설정된 환경변수(호스팅 대시보드에서 넣은 값 등)가 우선이며,
    빈 값은 넣지 않아 '설정 안 함'과 구분된다. python-dotenv 가 없어도 동작한다.
    """
    if not ENV_FILE.exists():
        return
    try:
        from dotenv import dotenv_values

        pairs = dotenv_values(ENV_FILE, encoding="utf-8")
    except ImportError:
        pairs = {}
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip().strip("'\"")
    for key, value in pairs.items():
        if value and not os.environ.get(key):
            os.environ[key] = value


_load_env()

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
