"""양식 기준 조회·수정 + 기준 양식 PPTX 교체."""
from __future__ import annotations

import json
import shutil
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
