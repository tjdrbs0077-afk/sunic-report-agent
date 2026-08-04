"""경로 상수 + .env 로딩 — 프로젝트 전체가 이 모듈의 경로만 사용한다.

이 모듈은 app.main 이 가장 먼저 import 하므로, 여기서 .env 를 읽어 두면
llm.py · news.py 가 os.environ 을 볼 때 값이 이미 올라와 있다.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent


def load_env(path: Path | None = None) -> list[str]:
    """프로젝트 루트의 .env 를 읽어 os.environ 에 올린다.

    외부 패키지(python-dotenv) 없이 동작한다 — 데모 당일 설치 실패 위험을 없애기 위함.
    **이미 설정된 환경변수는 덮어쓰지 않는다.** 배포 환경(Render 등)의 값이 우선한다.

    반환: 읽어들인 키 이름 목록 (값은 반환하지 않는다)
    """
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return []

    loaded: list[str] = []
    # utf-8-sig — 메모장으로 저장하면 BOM 이 붙어 첫 키 이름이 깨진다
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("﻿")
        if key.startswith("export "):          # `export KEY=값` 형태도 허용
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]                # 따옴표로 감쌌으면 벗겨 준다
        if not key:
            continue
        os.environ.setdefault(key, value)
        loaded.append(key)
    return loaded


ENV_KEYS_LOADED = load_env()

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
INSIGHT_GRAPH = DATA / "insight_graph.json"
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
