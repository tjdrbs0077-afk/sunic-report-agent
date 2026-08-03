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

TEMPLATE = ASSETS / "보고양식_Sample_4팀.pptx"
RULES_FILE = CONFIG_DIR / "standard_rules.yaml"
REPORT_INDEX = DATA / "reports.json"
LAYOUT_STORE = DATA / "layout_overrides.json"
INSIGHT_GRAPH = DATA / "insight_graph.json"
PROFILE_CACHE = DATA / "template_profile.json"

for folder in (DATA, UPLOADS, GENERATED):
    folder.mkdir(parents=True, exist_ok=True)
