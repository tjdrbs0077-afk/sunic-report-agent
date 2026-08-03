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

## 환경변수 (전부 선택 사항)

설정하지 않으면 외부 호출이 **전혀 일어나지 않고** 오프라인(TF-IDF) 동작으로 폴백합니다.

| 변수 | 용도 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude API 키. 설정 시 ⑤ 챗봇이 보고서 전문 근거의 통합 답변을 생성합니다 |
| `ANTHROPIC_MODEL` | 기본 `claude-sonnet-5` |
| `ANTHROPIC_BASE_URL` | 기본 `https://api.anthropic.com` |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 네이버 검색 오픈 API. 없으면 구글 뉴스 RSS로 폴백 |
| `LLM_API_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI 호환 엔드포인트를 쓸 때 |

```bash
# Windows
set ANTHROPIC_API_KEY=sk-ant-...
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-...
```

### 전송 정책 — 투명한 전송 통제 (v2)

사업기획보고서에는 예산·인사 등 민감정보가 포함될 수 있습니다.
v1은 "본문 절대 비전송"이었으나 답변 품질 한계로, **v2부터는 전송을 허용하되
전송 내역을 전부 공개**하는 방식으로 팀 합의하에 변경했습니다.

- 외부로 나가는 것 — 사용자 질문, 질문에서 뽑은 뉴스 검색어,
  그리고 **API 키 설정 시** 선택한 보고서 전문(답변 생성 목적에 한함)
- Anthropic API는 기본적으로 입력을 모델 학습에 사용하지 않습니다
- ⑤ 화면은 답변마다 **무엇이 전송되었는지 그대로 표시**합니다 (disclosure)
- ⑥ 동향 그래프에 저장되는 것은 정제된 검색어와 공개 기사뿐 —
  보고서 본문·질문 원문은 저장하지 않습니다
- API 키가 없으면 외부 LLM 호출이 전혀 없는 오프라인 발췌 답변으로 폴백합니다

사내 지식 DB 연동은 `app/services/knowledge.py` 에 파이프라인 설계와 인터페이스만 있고,
보안 검토 완료 전까지 실제 조회는 하지 않습니다.

## 화면별 기능

| # | 화면 | 기능 |
|---|------|------|
| 1 | 현황 대시보드 | 등록 보고서·처리 완료·양식 오류·평균 처리 시간 집계, 오류 유형별 차트, 처리 완료 도넛 |
| 2 | 업로드 · 취합 | PPTX 드래그앤드롭 업로드(진행률 표시) → 추출 + 양식 검사, 전체 보고서 통합 PPT 생성·다운로드 |
| 3 | 보고서 상세 | 원본 ↔ 표준 양식 적용본 비교(실제 양식 비율), 양식 위반 수정 내역, 보고서 내용 기반 AI 피드백 |
| 4 | 페이지 편집 | 캔버스에서 개체 드래그 이동·크기 조절, 좌표·글꼴·색 편집, 페이지/전체 적용, Undo/Redo(Ctrl+Z) |
| 5 | 근거형 챗봇 | 단일 통합 챗봇 — 선택한 보고서 전문 + 공개 뉴스를 근거로 한 번에 답변. 보고서 인용 [p.N] 클릭 시 해당 페이지로 이동, 뉴스 인용은 [기사 N]. 매 답변에 전송 내역(disclosure) 표시. 키 미설정 시 오프라인 발췌로 폴백 |
| 6 | 동향 인사이트 | ⑤ 지식·동향 모드의 조사(검색어·공개 기사)가 누적되는 팀 조사 지식맵. 챗봇 답변에서 [그래프에서 보기]로 이동, 노드 클릭 시 챗봇 질문 프리필. 예시 데이터 8개 포함 |

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
- 동향 인사이트의 관계는 오프라인 동시등장(점선) 중심입니다. 그래프에는 질문 원문이 아닌
  정제된 검색어만 저장되며, 시드 8개는 예시 데이터로 표시됩니다.
- 양식 검증은 텍스트·표 중심이며 이미지 개체 규격은 검사하지 않습니다.
