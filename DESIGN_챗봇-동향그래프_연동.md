# 설계안 — ⑤ 챗봇 ↔ ⑥ 동향 인사이트 양방향 연동

> v0.2 (리뷰 반영) · 2026-08-03
> v0.1 대비 변경: 카운트 3종 분리, 질문 원문 미저장, 결정적 노드 ID + 별칭 사전,
> 엣지에 relation_type·confidence·extraction_method·근거 기사, 최상위 articles 컬렉션,
> 시드="예시 데이터" 명시, 답변+추출 LLM 통합 호출(2차), 표시 상한(저장은 무제한)

## 1. 컨셉

**사용자의 조사 질문과 공개 근거를 구조화하여, 팀의 조사 과정 자체를
누적·재탐색 가능한 지식맵으로 만든다.**

- **챗봇 → 그래프**: 지식·동향 모드로 질문할 때마다 수집된 공개 뉴스에서 기업·기술
  엔티티를 추출해 그래프에 누적. 팀이 조사할수록 그래프가 자란다.
- **그래프 → 챗봇**: 노드 클릭 → 챗봇으로 이동, 유형별 질문 템플릿 자동 입력
  (전송은 항상 사용자가 확정).

그래프는 "사실 관계도"가 아니라 "조사 이력 지식맵"이다. 관계의 추출 방식과 신뢰도를
화면에 그대로 드러내 과장하지 않는다.

## 2. 데이터 설계 — `data/insight_graph.json`

```json
{
  "articles": {
    "<article_hash>": { "title": "...", "url": "...", "date": "...", "source": "..." }
  },
  "nodes": [
    {
      "id": "company:삼성sdi",
      "label": "삼성SDI",
      "type": "company",
      "desc": "전고체 파일럿 S라인 운영",
      "article_count": 3,
      "query_count": 2,
      "touch_count": 5,
      "first_seen": "2026-08-03",
      "last_seen": "2026-08-03",
      "search_queries": ["삼성 전고체"],
      "seed": false
    }
  ],
  "edges": [
    {
      "id": "company:삼성sdi|tech:전고체배터리",
      "a": "company:삼성sdi",
      "b": "tech:전고체배터리",
      "label": "함께 언급",
      "relation_type": "co_occurrence",
      "extraction_method": "offline",
      "confidence": 0.6,
      "weight": 2,
      "article_ids": ["<article_hash>"],
      "evidence": null
    }
  ]
}
```

핵심 규칙:

- **노드 ID는 결정적** — `f"{type}:{normalize(label)}"`. normalize = 별칭 사전 적용 →
  소문자 → 공백·특수문자 제거. 랜덤 ID 금지(동시 유입 시 중복 방지).
- **별칭 사전** (`entity.py`의 `ALIASES`): "삼성 sdi"/"samsung sdi"→"삼성SDI",
  "전고체전지"→"전고체 배터리" 등. 데모 도메인(배터리) 중심으로 수록, 확장은 2차.
- **카운트 3종 분리**:
  `article_count` = URL(없으면 정규화 제목+날짜 해시) 기준 중복 제거한 관련 기사 수.
  `query_count` = 이 노드를 발견한 고유 검색어 수.
  `touch_count` = 조사 과정에서 등장한 총횟수.
  노드 크기는 컨셉(조사 이력 강조)에 맞춰 **query_count·touch_count** 반영.
- **질문 원문은 저장하지 않는다.** `search_queries`에 정제된 검색어만 저장.
- **기사는 최상위 `articles`에 해시 키로 1회만 저장**, 엣지는 `article_ids`로 참조.
- **엣지 메타데이터 필수**: `relation_type`(`co_occurrence`|`extracted`|`seed`),
  `extraction_method`(`offline`|`llm`|`seed`), `confidence`, 근거(`article_ids`,
  LLM 추출 시 `evidence` 문장). LLM 추출 관계도 반드시 기사 근거(article_index)를 동반해야 채택.
- **시드**: 기존 더미 8노드를 `seed: true`로 유지하되 화면에 **"예시 데이터"** 로 명시
  ("사전 수집 결과" 표현 금지). 실제 조사로 재발견되면 seed 플래그는 유지, 활성 스타일로 전환.
- **저장 상한 없음** — 표시만 제한(§4).

## 3. 백엔드

### 3-1. `services/graph_store.py` (신규)

`load_graph()` / `merge(extraction, query) -> delta` / seed 초기화.
`merge`가 반환하는 delta:

```json
{
  "added_node_ids": ["company:quantumscape"],
  "updated_node_ids": ["tech:전고체배터리"],
  "added_edge_ids": ["..."],
  "article_count": 4,
  "warnings": []
}
```

### 3-2. `services/entity.py` (신규) — 1차는 오프라인 추출만

- 정제된 검색어 → tech(또는 사전에 있으면 company) 노드.
- 기사 제목·요약에서 내장 기업명 사전 매칭 → company 노드.
- 같은 기사에 등장한 노드 쌍 → `co_occurrence` 엣지, 라벨 "함께 언급" 고정
  (오프라인 규칙으로 의미 관계를 추정하지 않는다).
- 이메일·전화번호 등 명확한 개인정보 패턴은 검색어에서 제거.
- **2차**: 답변 생성과 엔티티 추출을 **한 번의 LLM 호출로 통합**
  (`{"answer", "entities", "relations"}` JSON 응답, 파싱 실패 시 텍스트 답변 + 오프라인 추출 폴백).
  별도 추출 호출 2회 방식은 응답 지연 때문에 채택하지 않음.

### 3-3. `routers/chat.py`

`_answer_from_context()` 답변 생성 후 try/except로 그래프 갱신, 응답에 `graph_delta` 포함.
추출 실패 시 답변은 정상 반환하고 `graph_delta.warnings`에 사유 —
UI는 "답변은 생성했지만 이번 결과는 그래프에 반영하지 못했습니다" 안내.

### 3-4. `routers/insight.py`

| 메서드 | 경로 | 비고 |
|--------|------|------|
| GET | `/api/insight/graph` | 전체 그래프 |
| GET | `/api/insight/articles` | 최상위 articles를 최신순으로 (2차) |
| POST | `/api/insight/reset` | `{"confirm": true, "mode": "seed"}` 필수, 삭제 수 응답 (2차) |

## 4. 프론트

### 4-1. `screen-insight.js`

- `/api/insight/graph` 렌더. 동심원 배치: biz 중앙, tech 안쪽 링, company 바깥 링.
- 노드 반지름 `min + sqrt(touch_count) * scale` (상한 34px).
- **표시 정책**: 기본 중요도 상위 20개 + 선택 노드의 이웃은 순위 무관 표시,
  나머지는 "관련 노드 N개 더 보기". 저장은 전체 유지.
- **선 스타일로 신뢰도 구분**: `extracted` 실선 / `co_occurrence` 점선 / `seed` 흐린 선.
  범례에 명시.
- 시드 노드: 낮은 투명도 + "예시" 배지. 카드 상단에 "예시 데이터 8개 포함" 문구.
- `focus(ids)`: 화면 미로딩 시를 대비해 `pendingFocusIds` 보류 후 로딩 완료 시 적용.
  펄스 강조는 `prefers-reduced-motion` 시 정적 테두리로 대체.
- 긴 라벨은 축약, 툴팁에 전체 + article/query_count + 유래 검색어 표시.

### 4-2. 챗봇 → 그래프 (`screen-chat.js`)

delta를 구체적으로: "동향 그래프에 **QuantumScape** 추가, **전고체 배터리** 관계 갱신
· [그래프에서 보기]" → `goTo('s6')` + `Screens.s6.focus(ids)`.

### 4-3. 그래프 → 챗봇

노드 유형별 질문 템플릿:

- company: `{기업명}의 최근 기술 개발과 사업 동향을 알려줘`
- tech: `{기술명}의 최근 산업 동향과 주요 기업을 알려줘`
- biz: `{사업명}과 연관된 최근 외부 동향을 알려줘`

`Screens.s5.ask(q)` — scope를 context로 전환, 입력창 채움, **자동 전송 안 함**.

## 5. 보안 원칙 정합성

- **보고서 본문은 저장·전송하지 않는다.** 그래프 재료는 정제된 검색어와 공개 뉴스뿐.
- 다만 **사용자가 입력한 질문에는 사내 정보가 포함될 수 있다.** 따라서:
  질문 원문은 그래프에 저장하지 않고 정제된 검색어만 저장 / 외부 전송 직전 전송 문자열을
  화면에 표시(기존 disclosure 유지) / 명확한 개인정보 패턴은 검색어에서 제거 /
  개별 조사 기록 삭제 기능은 고도화 단계에서 검토.
- 2차 LLM 통합 호출 시 추가 전송분은 공개 뉴스 텍스트뿐 — disclosure에 표기.
- LLM 미설정 시 전 기능 오프라인 동작(기존 원칙 준수).

## 6. 구현 순서

**1차 MVP**: graph_store → 오프라인 entity → insight 라우터 + chat 연결 →
screen-insight API 연동 → screen-chat delta·ask() → 통합 검증

**2차**: LLM 통합 호출(답변+추출), evidence·confidence 고도화, articles·reset API, 별칭 사전 확장

**고도화**: 군집화, 기간 필터, 질문별 조사 경로, 미반영 동향 알림, 보고서↔외부동향 로컬 매칭

## 7. 데모 시나리오

1. ⑥ 진입 — 예시 데이터 8개 포함 그래프 표시
2. ⑤ 지식·동향 모드 "QuantumScape 최근 동향" → 답변 + "그래프에 QuantumScape 추가"
3. [그래프에서 보기] → 새 노드 강조 — *그래프가 조사로 자란다*
4. 다른 노드 클릭 → "챗봇에 물어보기" → 질문 프리필 — *순환 구조*
5. 보안 질문 대응: disclosure 영역 + "질문 원문도 그래프에 저장하지 않습니다"
