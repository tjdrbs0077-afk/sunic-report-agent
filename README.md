# 사내 보고서 취합·편집 에이전트 (데모)

사업단이 제각각 만든 PPT 보고서를 **표준 양식으로 통일**하고, 페이지 단위로 수정하고,
근거를 붙여 질의응답하고, 하나로 병합하는 사내 도구입니다. 현재 데모 단계이며
DB·인증 없이 JSON 파일로 저장합니다.

## 실행 방법

```
run.bat        (Windows)
./run.sh       (macOS / Linux)
```

가상환경(.venv) 생성 → 의존성 설치 → uvicorn 실행까지 자동으로 진행되고,
브라우저에서 **http://127.0.0.1:8020** 을 엽니다.

수동 실행:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8020
```

## 화면별 기능

| # | 화면 | 기능 |
|---|------|------|
| 1 | 현황 대시보드 | 등록 보고서·처리 완료·양식 오류·평균 처리 시간 집계, 오류 유형별 차트, 처리 완료 도넛 |
| 2 | 업로드 · 취합 | PPTX 드래그앤드롭 업로드(진행률 표시) → 추출 + 양식 검사, 전체 보고서 통합 PPT 생성·다운로드 |
| 3 | 보고서 상세 | 원본 ↔ 표준 양식 적용본 비교(실제 양식 비율), 양식 위반 수정 내역, 보고서 내용 기반 AI 피드백 |
| 4 | 페이지 편집 | 캔버스에서 개체 드래그 이동·크기 조절, 좌표·글꼴·색 편집, 페이지/전체 적용, Undo/Redo(Ctrl+Z) |
| 5 | 근거형 챗봇 | 업로드된 보고서 내용만 근거로 답변, [p.N] 출처 클릭 시 해당 페이지로 이동 |
| 6 | 동향 인사이트 | 키워드·기사·관계 그래프 (더미 데이터, 연동 예정) |

## 구조

```
app/
  main.py               FastAPI 진입점
  config.py             경로 상수
  routers/              reports · generate · layout · chat · rules
  services/             ingest(추출) · builder(PPTX 생성) · validator(양식 검사) · store · retrieve
  static/               SUNIC 디자인 UI (바닐라 JS)
  assets/               보고양식_Sample_4팀.pptx (표준 템플릿)
config/standard_rules.yaml   표준 양식 규칙 (실측 스펙 기반)
data/ uploads/ generated/    JSON 저장소 · 업로드 원본 · 생성 결과
```

## 알려진 제약 (데모 단계)

- 저장은 JSON 파일 — 다중 사용자 동시 편집은 지원하지 않습니다.
- 원본 PPT의 이미지·차트 개체는 추출하지 않습니다(텍스트·표·타임라인만 이관).
- AI 피드백·챗봇은 기본적으로 TF-IDF + 규칙 기반 오프라인 응답입니다.
  환경변수 `LLM_API_URL` / `LLM_API_KEY` / `LLM_MODEL` 을 설정한 경우에만 외부 LLM을 호출합니다.
- 표준 양식 렌더링에는 나눔스퀘어(`NanumSquareR/EB.ttf`) 글꼴 설치가 필요합니다.
  미설치 시 PPT에서 대체 글꼴로 표시됩니다.
- 동향 인사이트 화면은 더미 데이터입니다(뉴스·특허 수집 연동 예정).
- 양식 검증은 텍스트·표 중심이며 이미지 개체 규격은 검사하지 않습니다.
