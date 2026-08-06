"""양식 기준 조회·수정 + 기준 양식 PPTX 교체."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import config
from app.services import validator
from app.services.ingest import safe_stem

router = APIRouter(prefix="/api", tags=["rules"])


class RulesSaveRequest(BaseModel):
    rules: dict[str, Any]


@router.get("/rules")
def rules() -> dict[str, Any]:
    return validator.load_rules()


@router.put("/rules")
def update_rules(req: RulesSaveRequest):
    """편집한 양식 기준을 저장한다. 이후 검사·PPT 생성에 즉시 반영된다."""
    if not req.rules:
        raise HTTPException(400, "저장할 양식 기준 내용이 없습니다.")
    fonts = req.rules.get("fonts") or {}
    if not fonts.get("latin") or not fonts.get("korean"):
        raise HTTPException(400, "영문·한글 글꼴은 반드시 지정해야 합니다.")
    levels = req.rules.get("body_levels") or []
    if not levels:
        raise HTTPException(400, "본문 단계 설정이 비어 있습니다.")
    for level in levels:
        try:
            size = float(level.get("size", 0))
        except (TypeError, ValueError):
            raise HTTPException(400, "본문 단계의 글자 크기는 숫자여야 합니다.")
        if not (5 <= size <= 60):
            raise HTTPException(400, f"본문 글자 크기 {size}pt는 허용 범위(5–60pt)를 벗어납니다.")
    saved = validator.save_rules(req.rules)
    config.PROFILE_CACHE.unlink(missing_ok=True)
    return {"ok": True, "rules": saved}


LATIN_OPTIONS = ["Corbel", "Arial", "Calibri", "Segoe UI", "Times New Roman", "Tahoma", "Verdana"]
KOREAN_OPTIONS = ["나눔스퀘어", "나눔스퀘어 ExtraBold", "나눔고딕", "맑은 고딕", "바탕", "굴림", "Pretendard"]


def _installed_fonts() -> set[str] | None:
    """설치된 글꼴 이름. 확인할 수 없는 환경(비 Windows 서버 등)에서는 None.

    '모든 사용자'(HKLM)와 '현재 사용자'(HKCU) 양쪽을 본다. 글꼴을 오른쪽 클릭해
    설치하면 현재 사용자 쪽에만 등록되므로 HKLM만 보면 설치해도 미설치로 나온다.
    """
    if sys.platform != "win32":
        return None
    import winreg

    names: set[str] = set()
    found_any = False
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        found_any = True
        try:
            for i in range(winreg.QueryInfoKey(key)[1]):
                value = winreg.EnumValue(key, i)
                names.add(re.sub(r"\s*\((TrueType|OpenType)\)$", "", value[0]).strip())
                # 등록 이름이 한글이어도 파일명으로 한 번 더 찾을 수 있게 파일명도 넣는다
                file_name = str(value[1] or "")
                if file_name:
                    names.add(Path(file_name).stem)
        finally:
            key.Close()
    return names if found_any else None


# 한글 글꼴은 레지스트리에 영문 이름으로 등록돼 있어 별칭으로 함께 찾는다
FONT_ALIASES = {
    "맑은 고딕": ["Malgun Gothic"],
    "나눔고딕": ["NanumGothic"],
    "나눔스퀘어": ["NanumSquare", "NanumSquareR"],
    "나눔스퀘어 ExtraBold": ["NanumSquareExtraBold", "NanumSquare ExtraBold", "NanumSquareEB"],
    "바탕": ["Batang"],
    "굴림": ["Gulim"],
    "돋움": ["Dotum"],
}


def _is_installed(family: str, installed: set[str]) -> bool:
    candidates = [family.strip()] + FONT_ALIASES.get(family.strip(), [])
    lowered = [n.casefold() for n in installed]
    for candidate in candidates:
        target = candidate.casefold()
        if not target:
            continue
        for name in lowered:
            if target == name or target in name or name.startswith(target):
                return True
    return False


@router.get("/fonts")
def fonts() -> dict[str, Any]:
    """글꼴 선택 목록과 이 PC의 설치 여부. 편집기 드롭다운과 안내에 쓴다."""
    rules_data = validator.load_rules()
    cfg = rules_data.get("fonts") or {}
    latin = [x for x in dict.fromkeys([cfg.get("latin", "")] + LATIN_OPTIONS) if x]
    korean = [x for x in dict.fromkeys([cfg.get("korean", ""), cfg.get("heading_korean", "")] + KOREAN_OPTIONS) if x]
    installed = _installed_fonts()
    status: dict[str, bool | None] = {}
    for family in set(latin + korean):
        status[family] = _is_installed(family, installed) if installed is not None else None
    return {
        "rule": {"latin": cfg.get("latin", ""), "korean": cfg.get("korean", ""), "heading_korean": cfg.get("heading_korean", "")},
        "options": {"latin": latin, "korean": korean},
        "installed": status,
        "checked": installed is not None,
    }


@router.get("/template")
def template_info() -> dict[str, Any]:
    path = config.active_template()
    return {
        "name": path.name,
        "is_default": path == config.DEFAULT_TEMPLATE,
        "size_kb": round(path.stat().st_size / 1024) if path.exists() else 0,
    }


@router.post("/template/upload")
async def upload_template(file: UploadFile = File(...)):
    """새 기준 양식 PPTX를 올려 규칙과 좌표 프로파일을 자동 추출한다."""
    filename = file.filename or "양식.pptx"
    if Path(filename).suffix.lower() != ".pptx":
        raise HTTPException(400, "기준 양식은 .pptx 파일만 지원합니다.")
    target = config.TEMPLATES_DIR / f"{safe_stem(filename)}.pptx"
    try:
        with target.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        derived = validator.derive_rules_from_pptx(target)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(400, f"양식 PPTX를 읽지 못했습니다: {type(exc).__name__}: {exc}") from exc
    finally:
        await file.close()

    validator.save_rules(derived)
    config.TEMPLATE_STATE.write_text(
        json.dumps({"file": target.name, "source": filename}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config.PROFILE_CACHE.unlink(missing_ok=True)
    return {"ok": True, "template": target.name, "rules": derived}


@router.post("/template/reset")
def reset_template():
    """기본 제공 양식(보고양식_Sample_4팀.pptx)으로 되돌린다."""
    config.TEMPLATE_STATE.unlink(missing_ok=True)
    config.PROFILE_CACHE.unlink(missing_ok=True)
    derived = validator.derive_rules_from_pptx(config.DEFAULT_TEMPLATE)
    validator.save_rules(derived)
    return {"ok": True, "template": config.DEFAULT_TEMPLATE.name, "rules": derived}
