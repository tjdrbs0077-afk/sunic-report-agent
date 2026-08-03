"""사내 지식 DB 연결부 — **설계 스텁**. 데모 단계에서는 실제로 조회하지 않는다.

왜 비워 두는가
--------------
1주차 수행계획서에 적어 둔 리스크 그대로다.
사내 사업기획서에는 예산·인사 등 민감정보가 들어가므로, 사내 보안 정책 검토가
끝나기 전에는 어떤 경로로도 밖으로 내보내거나 무단 색인하지 않는다.
그래서 데모는 **인터페이스와 파이프라인만 확정**하고, 어댑터 구현은 비워 둔다.
보안 승인이 나면 `InternalKnowledgeSource` 를 구현한 클래스를 하나 등록하면 된다.

파이프라인 (설계 확정분)
------------------------
    [사내 문서 저장소]           예) 그룹웨어 게시판, 사업계획 아카이브, 공유드라이브
            │  (1) 수집         읽기 전용 계정, 증분 동기화
            ▼
    [정규화·비식별화]            표/첨부 텍스트화, 예산 숫자·인명·연락처 마스킹
            │  (2)
            ▼
    [청크 분할 + 임베딩]         문단 단위 500~800자, 문서 메타(부서·연도·보안등급) 부착
            │  (3)              **사내망 임베딩 모델 사용** — 외부 API 로 본문 전송 금지
            ▼
    [벡터 인덱스]                사내 서버 상주. 외부 반출 없음
            │  (4)
            ▼
    [검색 → 근거 조립]           질문 임베딩으로 top-k 조회, 보안등급 필터 적용
            │  (5)
            ▼
    [답변 생성]                  (6) 두 갈래
                                 · 사내 LLM  : 근거 본문까지 전달 가능
                                 · 외부 LLM  : 근거 본문 전달 불가.
                                               제목·부서·연도 등 메타만 노출하고
                                               "사내 문서 N건에서 확인됨" 형태로 안내

외부 LLM 을 쓰는 동안에는 (6) 의 두 번째 갈래만 허용한다.
즉 사내 문서가 색인되어 있어도 본문은 프롬프트에 실리지 않는다.
"""
from __future__ import annotations

from typing import Any, Protocol


class InternalKnowledgeSource(Protocol):
    """사내 지식 저장소 어댑터가 만족해야 할 계약.

    보안 승인 후 구현체를 만들어 `register_source()` 로 등록한다.
    """

    def search(self, query: str, top_k: int = 5, max_security_level: int = 1) -> list[dict[str, Any]]:
        """근거 후보를 반환한다.

        각 항목: {title, department, year, security_level, snippet, doc_id}
        `security_level` 이 `max_security_level` 을 넘는 문서는 반환하지 않는다.
        """
        ...


_source: InternalKnowledgeSource | None = None


def register_source(source: InternalKnowledgeSource) -> None:
    global _source
    _source = source


def is_connected() -> bool:
    return _source is not None


def search(query: str, top_k: int = 5) -> dict[str, Any]:
    """사내 DB 검색. 미연결 상태에서는 빈 결과와 사유를 반환한다."""
    if _source is None:
        return {
            "connected": False,
            "hits": [],
            "note": "사내 지식 DB 는 보안 검토 완료 후 연결됩니다. 현재 데모는 파이프라인 설계까지만 반영되어 있습니다.",
        }
    return {"connected": True, "hits": _source.search(query, top_k=top_k), "note": None}


def redact_for_external(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """외부 LLM 에 넘기기 전 본문을 제거하고 메타데이터만 남긴다.

    사내 문서가 연결된 뒤에도 외부 경로로는 이 함수를 통과한 값만 나갈 수 있다.
    """
    return [
        {
            "title": hit.get("title", ""),
            "department": hit.get("department", ""),
            "year": hit.get("year", ""),
            "doc_id": hit.get("doc_id", ""),
        }
        for hit in hits
    ]
