"""보고서 업로드·목록·상세·삭제 + 양식 검증 결과 + 대시보드 집계."""
from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import config
from app.services import store, validator
from app.services.ingest import extract_presentation, safe_stem

router = APIRouter(prefix="/api", tags=["reports"])


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
    """업로드 시 수행한 양식 검증 결과."""
    payload = store.report_payload(report_id)
    return payload.get("validation", {"total": 0, "by_category": [], "issues": []})


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
