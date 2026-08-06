"""표준 양식 자동배열·병합. 결과물은 /generated 정적 마운트로 다운로드한다."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config
from app.services import store
from app.services.builder import generate_report, merge_reports

router = APIRouter(prefix="/api", tags=["generate"])


class GenerateRequest(BaseModel):
    report_id: str
    layout_overrides: dict[str, Any] | None = None


class MergeRequest(BaseModel):
    report_ids: list[str]
    title: str = "사업단 통합 보고서"
    include_layout_edits: bool = True


def slug(text: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", text.strip()).strip("_")
    return clean or "통합_보고서"


def has_edits(overrides: dict[str, Any] | None) -> bool:
    if not overrides:
        return False
    return bool(overrides.get("global") or overrides.get("slides"))


@router.post("/generate")
def generate(req: GenerateRequest):
    payload = store.report_payload(req.report_id)
    unit, slides = payload["unit"], payload["slides"]
    if not slides:
        raise HTTPException(400, "자동 배열할 슬라이드 내용이 없습니다.")
    overrides = req.layout_overrides
    if overrides is None:
        overrides = store.load_layouts().get(req.report_id, {})
    suffix = "_편집본" if has_edits(overrides) else "_자동배열본"
    tmp_out = config.GENERATED / f"{slug(unit['name'])}{suffix}.tmp-out.pptx"
    try:
        made = generate_report(config.active_template(), unit, slides, tmp_out, overrides)
    except Exception as exc:
        raise HTTPException(500, f"PPT 자동 배열 중 오류가 발생했습니다: {type(exc).__name__}: {exc}") from exc
    if not tmp_out.exists() or tmp_out.stat().st_size < 1000:
        raise HTTPException(500, "PPT 파일 생성은 완료됐지만 결과 파일이 정상적으로 저장되지 않았습니다.")
    # 본문이 넘쳐 다음 장으로 나뉘면 실제 장수가 늘어난다. 파일명은 실제 장수로 붙인다.
    out = config.GENERATED / f"{slug(unit['name'])}_{made}p{suffix}.pptx"
    tmp_out.replace(out)
    return {"ok": True, "download": f"/generated/{out.name}", "slide_count": made, "source_slide_count": len(slides)}


@router.post("/merge")
def merge(req: MergeRequest):
    available = {x["id"]: x for x in store.load_report_index()}
    ids = [x for x in req.report_ids if x in available]
    if len(ids) < 2:
        raise HTTPException(400, "병합할 보고서를 2개 이상 선택해 주세요.")
    layouts = store.load_layouts()
    paths: list[Path] = []
    total_slides = 0
    try:
        for report_id in ids:
            payload = store.report_payload(report_id)
            unit, slides = payload["unit"], payload["slides"]
            path = config.GENERATED / f"_merge_{report_id}.pptx"
            overrides = layouts.get(report_id, {}) if req.include_layout_edits else {}
            total_slides += generate_report(config.active_template(), unit, slides, path, overrides)
            paths.append(path)
        out = config.GENERATED / f"{slug(req.title)}_{len(ids)}개보고서_{total_slides}p.pptx"
        merge_reports(paths, out)
    except Exception as exc:
        raise HTTPException(500, f"보고서 병합 중 오류가 발생했습니다: {type(exc).__name__}: {exc}") from exc
    return {"ok": True, "download": f"/generated/{out.name}", "report_count": len(ids), "slide_count": total_slides}
