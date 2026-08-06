"""시연용 가상 보고서 생성 — 업로드할 PPT 없이 화면을 채워 시연할 수 있게 한다."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import demo_data, store, validator

router = APIRouter(prefix="/api", tags=["demo"])


class DemoRequest(BaseModel):
    unit_ids: list[str] = []
    messy: bool = False
    all_units: bool = False


@router.get("/demo/units")
def demo_units() -> dict[str, Any]:
    existing = {x["id"] for x in store.load_report_index()}
    return {
        "units": [
            {
                "id": u["id"],
                "name": u["name"],
                "topic": u["topic"],
                "slide_count": len(demo_data.SLIDE_TOPICS),
                "created": f"demo_{u['id']}" in existing,
                "created_messy": f"demo_{u['id']}_messy" in existing,
            }
            for u in demo_data.BUSINESS_UNITS
        ]
    }


@router.post("/demo/generate")
def demo_generate(req: DemoRequest):
    unit_ids = [u["id"] for u in demo_data.BUSINESS_UNITS] if req.all_units else req.unit_ids
    if not unit_ids:
        raise HTTPException(400, "생성할 사업단을 선택해 주세요.")

    created: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for unit_id in unit_ids:
        try:
            payload = demo_data.build_payload(unit_id, req.messy)
            # 시연용은 원본 PPTX가 없으므로 추출 데이터 기준으로 검사한다.
            payload["validation"] = validator.validate_slides(payload)
            store.save_report_payload(payload["unit"]["id"], payload)
            created.append(store.upsert_report_index(payload))
        except ValueError as exc:
            errors.append({"unit": unit_id, "error": str(exc)})
    if not created:
        raise HTTPException(400, {"message": "생성된 시연 보고서가 없습니다.", "errors": errors})
    return {"ok": True, "created": created, "errors": errors}
