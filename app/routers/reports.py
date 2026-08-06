"""보고서 업로드·목록·상세·삭제 + 양식 검증 결과 + 대시보드 집계."""
from __future__ import annotations

import copy
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import config
from app.services import store, validator
from app.services.ingest import extract_presentation, safe_stem

router = APIRouter(prefix="/api", tags=["reports"])


class SlidePatch(BaseModel):
    page_title: str | None = None
    sidebar: str | None = None
    footnote: str | None = None
    body: list[dict[str, Any]] | None = None
    table1: dict[str, Any] | None = None
    table2: dict[str, Any] | None = None
    timeline: list[str] | None = None
    timeline_note: list[str] | None = None


@router.get("/reports")
def reports() -> list[dict[str, Any]]:
    return store.load_report_index()


@router.get("/reports/{report_id}")
def report(report_id: str) -> dict[str, Any]:
    return store.report_payload(report_id)


@router.post("/reports/upload")
async def upload_ppts(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "업로드할 PPTX 파일을 선택해 주세요.")
    created: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for upload in files:
        filename = upload.filename or "업로드.pptx"
        if Path(filename).suffix.lower() != ".pptx":
            errors.append({"file": filename, "error": "현재는 .pptx 형식만 지원합니다."})
            continue
        report_id = f"upload_{uuid4().hex[:10]}"
        target = config.UPLOADS / f"{report_id}_{safe_stem(filename)}.pptx"
        try:
            started = time.perf_counter()
            with target.open("wb") as out:
                shutil.copyfileobj(upload.file, out)
            payload = extract_presentation(target, report_id=report_id, display_name=safe_stem(filename))
            payload["unit"]["source_file"] = filename
            payload["validation"] = validator.validate_pptx(target)
            # 원문 스냅샷 — 페이지 편집의 '원문 복원' 기준
            payload["original_slides"] = copy.deepcopy(payload["slides"])
            payload["uploaded_at"] = datetime.now().isoformat(timespec="seconds")
            payload["processing_seconds"] = round(time.perf_counter() - started, 2)
            store.save_report_payload(report_id, payload)
            item = store.upsert_report_index(payload)
            created.append(item)
        except Exception as exc:
            target.unlink(missing_ok=True)
            errors.append({"file": filename, "error": str(exc)})
        finally:
            await upload.close()
    if not created:
        raise HTTPException(400, {"message": "처리 가능한 PPT가 없습니다.", "errors": errors})
    return {"ok": True, "created": created, "errors": errors}


@router.delete("/reports/{report_id}")
def delete_report(report_id: str):
    if not (config.DATA / f"{report_id}.json").exists():
        raise HTTPException(404, "보고서를 찾을 수 없습니다.")
    store.delete_report_payload(report_id)
    store.remove_from_report_index(report_id)
    layouts = store.load_layouts()
    if layouts.pop(report_id, None) is not None:
        store.save_layouts(layouts)
    for file in config.UPLOADS.glob(f"{report_id}_*.pptx"):
        file.unlink(missing_ok=True)
    return {"ok": True}


@router.get("/reports/{report_id}/rules")
def report_rules(report_id: str) -> dict[str, Any]:
    """업로드 시 수행한 양식 검증 결과(업로드 원본 기준)."""
    payload = store.report_payload(report_id)
    return payload.get("validation", {"total": 0, "by_category": [], "issues": []})


@router.get("/reports/{report_id}/issues")
def report_issues(report_id: str) -> dict[str, Any]:
    """편집기에서 실제로 고칠 수 있는 위반 목록(추출 데이터 기준)."""
    return validator.validate_slides(store.report_payload(report_id))


@router.patch("/reports/{report_id}/slides/{slide_no}")
def patch_slide(report_id: str, slide_no: int, patch: SlidePatch):
    """슬라이드의 제목·본문·표 등 내용을 수정한다 (페이지 편집기의 텍스트 편집)."""
    payload = store.report_payload(report_id)
    slides = payload["slides"]
    target = next((s for s in slides if s["slide_number"] == slide_no), None)
    if target is None:
        raise HTTPException(404, f"{slide_no}페이지를 찾을 수 없습니다.")
    changes = patch.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(400, "수정할 내용이 없습니다.")
    if "body" in changes:
        cleaned = []
        for item in changes["body"]:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            entry = {
                "text": text,
                "level": max(0, min(4, int(item.get("level", 0) or 0))),
                "bold": item.get("bold"),
            }
            # 글머리 지정 — 비우면 양식의 자동번호를 따른다.
            # 자동번호와 같은 꼴("3." / "3)")이면 시작 번호로 해석해 이후 항목이
            # 이어서 매겨지게 한다. 그 외 문자는 고정 글머리로 쓴다.
            bullet = str(item.get("bullet") or "").strip()
            start = item.get("bullet_start")
            auto = re.fullmatch(r"(\d+)\.", bullet) if entry["level"] == 0 else \
                re.fullmatch(r"(\d+)\)", bullet) if entry["level"] == 1 else None
            if auto:
                start, bullet = auto.group(1), ""
            if bullet:
                entry["bullet"] = bullet[:8]
            if start not in (None, ""):
                try:
                    entry["bullet_start"] = max(1, int(start))
                except (TypeError, ValueError):
                    pass
            cleaned.append(entry)
        if not cleaned:
            raise HTTPException(400, "본문은 최소 한 줄이 있어야 합니다.")
        changes["body"] = cleaned
    target.update(changes)
    target["edited"] = True
    store.save_report_payload(report_id, payload)
    return {"ok": True, "slide": target}


@router.get("/reports/{report_id}/autofix/preview")
def autofix_preview(report_id: str, slide_no: int | None = None):
    """자동 수정이 바꿀 내용을 미리 보여준다 (적용하지 않음)."""
    payload = store.report_payload(report_id)
    changes = validator.preview_autofix(payload, slide_no)
    return {"ok": True, "changes": changes, "count": len(changes)}


class SlidesReplace(BaseModel):
    slides: list[dict[str, Any]]


@router.put("/reports/{report_id}/slides")
def replace_slides(report_id: str, req: SlidesReplace):
    """슬라이드 전체를 한 번에 교체한다 (편집기의 Ctrl+Z 되돌리기용)."""
    payload = store.report_payload(report_id)
    if len(req.slides) != len(payload["slides"]):
        raise HTTPException(400, "슬라이드 수가 맞지 않습니다.")
    payload["slides"] = req.slides
    store.save_report_payload(report_id, payload)
    return {"ok": True, "issues": validator.validate_slides(payload)}


@router.post("/reports/{report_id}/autofix")
def autofix(report_id: str, slide_no: int | None = None):
    """자동 수정 가능한 위반을 일괄 적용한다. slide_no를 주면 해당 페이지만."""
    payload = store.report_payload(report_id)
    fixed = validator.autofix_slides(payload, slide_no)
    if fixed:
        store.save_report_payload(report_id, payload)
    return {"ok": True, "fixed": fixed, "issues": validator.validate_slides(payload)}


@router.post("/reports/{report_id}/restore")
def restore(report_id: str, slide_no: int | None = None):
    """업로드 직후의 원문으로 내용을 되돌린다. 레이아웃 편집값은 그대로 둔다."""
    payload = store.report_payload(report_id)
    original = payload.get("original_slides")
    if not original:
        raise HTTPException(400, "이 보고서에는 원문 스냅샷이 없습니다. 다시 업로드하면 복원 기능을 쓸 수 있습니다.")
    originals = {s["slide_number"]: s for s in original}
    restored = 0
    for i, slide in enumerate(payload["slides"]):
        no = slide["slide_number"]
        if slide_no is not None and no != slide_no:
            continue
        source = originals.get(no)
        if source is None:
            continue
        import copy

        if slide != source:
            payload["slides"][i] = copy.deepcopy(source)
            restored += 1
    if restored:
        store.save_report_payload(report_id, payload)
    return {
        "ok": True,
        "restored": restored,
        "issues": validator.validate_slides(payload),
        "slides": payload["slides"],
    }


@router.get("/stats")
def stats() -> dict[str, Any]:
    """대시보드 집계 — 보고서 수·처리 완료·양식 오류 총계·유형별 집계·평균 처리 시간."""
    index = store.load_report_index()
    by_category: dict[str, int] = {}
    issue_total = 0
    durations: list[float] = []
    for item in index:
        try:
            payload = store.report_payload(item["id"])
        except HTTPException:
            continue
        validation = payload.get("validation", {})
        issue_total += int(validation.get("total", 0))
        for entry in validation.get("by_category", []):
            by_category[entry["category"]] = by_category.get(entry["category"], 0) + int(entry["count"])
        if payload.get("processing_seconds") is not None:
            durations.append(float(payload["processing_seconds"]))
    generated = [f for f in config.GENERATED.glob("*.pptx") if not f.name.startswith("_merge_")]
    return {
        "report_count": len(index),
        "done_count": sum(1 for x in index if x.get("status", "done") == "done"),
        "issue_total": issue_total,
        "issues_by_category": [
            {"category": category, "count": count}
            for category, count in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "avg_processing_seconds": round(sum(durations) / len(durations), 2) if durations else 0,
        "generated_count": len(generated),
    }
