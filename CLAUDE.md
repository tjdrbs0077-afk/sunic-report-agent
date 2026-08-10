# 사내 보고서 편집·다운로드 에이전트 (데모)

## 이 프로젝트가 하는 일

사업단에서 제출한 제각각인 PPT 보고서를 표준 양식으로 통일하고, 페이지 단위로 수정하고,
근거를 붙여 질의응답하고, 하나로 병합하는 사내 도구입니다.

현재 **데모 단계**입니다. DB·인증·다중 사용자는 만들지 않습니다.

## 스택

- 백엔드: FastAPI + python-pptx + 자체 하이브리드 TF-IDF 검색 (순수 파이썬, services/retrieve.py)
- 프론트: 바닐라 JS + CSS. **프레임워크 금지** (React/Vue/Tailwind/Bootstrap 전부 안 씀)
- 저장: JSON 파일 (`data/`)
- 폰트: Pretendard Variable (CDN)

## 화면 구성

| # | id | 화면 | 주요 API |
|---|----|------|----------|
| ⌂ | home | 홈 | — |
| 1 | s1 | 현황 대시보드 | `/api/stats`, `/api/reports/{id}/archive`, `/api/reports/{id}/unarchive` |
| 2 | s2 · s7 | 업로드 · 다운로드 | `/api/reports/upload`, `/api/generate`, `/api/merge` |
| 3 | s3 | 보고서 상세 | `/api/reports/{id}`, `/api/reports/{id}/rules` |
| 4 | s4 | 페이지 편집 | `/api/layouts`, `/api/generate` |
| 5 | s5 | 챗봇 | `/api/chat` — 단일 통합 챗봇 (보고서 전문 + 뉴스, LLM 키 없으면 오프라인 폴백) |
| 6 | s6 | 동향 인사이트 | `/api/reports/{id}/news` — 보고서 키워드 뉴스 + 기사 기반 기업·기술 지식맵. 기사 목록과 지식맵은 서로 하이라이트된다 (챗봇과는 미연동) |

## 디자인 규칙 — 반드시 지킬 것

UI는 `_ref/SUNIC_Demo_index.html` 에서 그대로 가져왔습니다. **디자인 토큰을 임의로 바꾸지 마세요.**

```css
--page:          #f6f4f2;   /* 배경 */
--surface-1:     #ffffff;   /* 카드 */
--text-primary:  #191216;
--text-secondary:#6d6367;
--text-muted:    #a29699;
--grid:          #eee9e7;   /* 표 구분선 */
--baseline:      #d8d0cd;   /* 입력 테두리 */
--border:        rgba(25,18,22,.07);
--accent:        #ea002c;   /* SK 레드 */
--accent-deep:   #c00026;
--accent-soft:   #fdedf0;
--orange:        #f47725;
--grad:          linear-gradient(135deg, #ea002c 0%, #f5551f 55%, #f47725 100%);
```

- 사이드바: `linear-gradient(180deg, #250610 0%, #150308 100%)`, 폭 236px (접으면 70px)
- 카드: `border-radius: 18px`, `padding: 22px 24px`, `--shadow-sm`
- 버튼: `border-radius: 12px`, primary 는 `--grad` + 그림자
- 폰트: Pretendard Variable, 본문 14px / line-height 1.6

새 컴포넌트가 필요하면 **기존 클래스를 조합**하세요. 새 색이나 새 radius 값을 만들지 마세요.

### 재사용 가능한 클래스

| 클래스 | 용도 |
|---|---|
| `.card` | 모든 패널의 기본 컨테이너 |
| `.tile` | 상단 KPI 숫자 타일 (`.label` `.value` `.delta`) |
| `.chip.ok/.run/.wait/.err` | 상태 배지 |
| `.btn.primary` / `.btn.ghost` / `.disabled` | 버튼 |
| `.dropzone` | 파일 업로드 영역 |
| `.file-item` + `.mini-track` `.mini-fill` | 업로드 진행 목록 |
| `.steps` `.step.done` `.step.now` | 파이프라인 단계 표시 |
| `.bigprog` `.f` | 큰 진행 바 |
| `.rulelist` | 양식 기준 목록 |
| `.slide-mock` | 슬라이드 미리보기 프레임 |
| `.badpt` / `.fixedpt` | 오류(빨강) / 교정(초록) 인라인 강조 |
| `.fixlist` + `.fico` `.cnt` | 수정 내역 목록 |
| `.fb-item` `.sev.high/mid/low` | 체크박스형 피드백 카드 |
| `.bar-row` `.bar-fill` | 가로 바 차트 |
| `.art` `.pill.news/.pat` `.relbar` | 목록 아이템 + 관련도 게이지 |
| `.note` | 회색 안내 박스 |
| `.demo-badge` | 우상단 DEMO 표시 |

## 표준 보고 양식 스펙

`config/standard_rules.yaml` 이 단일 진실 공급원입니다. 하드코딩하지 말고 여기서 읽으세요.

핵심 값:
- 슬라이드 10.833333 × 7.5 in (A4 가로)
- 영문 `Corbel` / 한글 `나눔스퀘어` / 제목 `나눔스퀘어 ExtraBold`
- 제목 24pt Bold
- 본문 5단계: 14 / 13 / 12 / 11 / 10 pt, 각 단계 marL·indent·글머리 기호 고정
- 표: x 2.897570in, 너비 7.519097in 고정. 헤더 `#DCE6F2`, 1열 `#E8E8E8`, 격자 0.75pt `#BFBFBF`
  - **세로 위치(y)는 쓰지 않는다.** 양식 실측 y 는 샘플의 짧은 본문을 전제로 한
    값이라, 그대로 두면 본문이 길 때 글자와 겹치고 짧을 때 글 끝과 표 사이가 텅 빈다.
    표는 **본문의 다음 문단처럼** 글이 끝나는 자리 바로 아래에 문단 간격
    (`body_line_gap()` = 본문 spc_before 10pt ≒ 0.139in) 만큼만 띄워 붙인다.
    표가 둘이면 그 사이는 `TABLE_GAP`(0.26in).
  - 유형 1 은 하단 타임라인 띠가 고정이므로 표는 그 위(`stack_floor()`)에서 멈춘다.
  - 미리보기(`screen-editor.js` 의 `flowBodyAndTables`)가 같은 규칙을 쓴다.
    간격 상수를 바꿀 때는 `builder.py` 와 양쪽을 함께 고칠 것.
- 외곽 프레임 헤더 `#B7D3EE`, 테두리 `#7F7F7F`
- 각주 8pt
- **연속 슬라이드 규칙**: 같은 대주제가 다음 장으로 이어지면 Lv1 제목 색을 `#FFFFFF` 로
  바꿔 시각적으로 숨기되 번호 체계는 유지

## 디렉터리

```
app/
  main.py              FastAPI 진입점
  routers/             reports · generate · layout · chat · rules
  services/
    ingest.py          PPTX → 구조화 JSON
    builder.py         구조화 JSON → 표준 양식 PPTX
    validator.py       standard_rules.yaml 대조 검사
    retrieve.py        하이브리드 TF-IDF 검색 (콘텐츠 가중치·동의어·중복 제거)
    intent.py          질문 의도 분류 (사실/위치/요약/비교/분석/외부)
    lexicon.py         불용어·조사·동의어 사전 (config/synonyms.yaml 로드)
    news.py            ⑥ 동향 인사이트용 RSS 뉴스 수집·채점·지식맵 생성
    news_chat.py       ⑤ 챗봇용 근거 기사 수집 (네이버 API → RSS 폴백)
  static/              index.html, css/theme.css, js/*
  assets/              보고양식_Sample_4팀.pptx
config/standard_rules.yaml
data/  uploads/  generated/
_ref/                  참고용 원본. 여기 파일은 수정하지 마세요.
```

## 알려진 제약 (데모 단계에서는 그대로 둠)

- 이미지·SmartArt·차트의 의미 해석 안 함
- 표 병합 셀 미처리
- 미리보기(CSS)와 실제 PPT 출력의 폰트 축소 알고리즘이 달라 미세하게 어긋남
- 동시 편집 충돌 처리 없음
- ⑥ 동향 인사이트는 보고서 키워드 뉴스 그래프만 사용한다. 챗봇 질문은 그래프에
  저장·연동하지 않는다 (팀 결정으로 연동 제거 — DESIGN_챗봇-동향그래프_연동.md 는 폐기된 설계)
- 기업 추출은 사전 + 접미사 + 문장 주체 규칙이라 낯선 회사명은 놓칠 수 있다

## ⑥ 정렬·지식맵 연동 규칙 (건드릴 때 주의)

- **검색어 하나를 한 번만 요청하지 말 것.** 구글 뉴스는 기간을 지정하지 않으면
  최근 며칠치만 돌려준다. `SEARCH_WINDOWS` 로 기간을 나눠(최근 1주 / 1~2주 /
  2~4주) 세 번 요청해 합친다. 수집 범위는 `LOOKBACK_DAYS`(30일) 이며
  API 의 `days` 파라미터로 조정할 수 있다.
- **정확도 점수에 RSS 순위를 넣지 말 것.** 구글 뉴스 RSS는 사실상 최신순이라
  순위를 점수에 섞으면 '정확순'이 '최신순'의 복사본이 된다 (`relevance_score`).
- **후보군을 한쪽 정렬로만 잘라 캐시에 담지 말 것.** `balanced_pool` 이
  최신순 몫 + **경과일 구간별**(`AGE_BUCKETS`) 정확순 몫을 남긴다. 그냥 정확순
  상위로 자르면 동점이 시각으로 갈리면서 후보군 전체가 최근 며칠로 쪼그라들고,
  한 달 전 기사가 캐시까지 살아남지 못한다.
- **정확순 표시에는 `spread_by_day` 로 하루 상한을 건다.** 점수 순서는 그대로
  두되 같은 날짜가 목록을 독점하지 못하게 한다.
- **정확순 동점은 시간으로 풀지 말 것.** 관련도 → 걸린 검색어 수 → 제목 길이
  순으로 먼저 푼다 (`sort_articles`). 곧장 시간으로 넘어가면 오늘 기사만 남는다.
- **정렬은 서버가 끝낸다.** `screen-insight.js` 는 받은 순서를 그대로 그린다.
  화면에서 다시 정렬하면 날짜 표기 형식이 바뀔 때마다 서버 결과를 뒤엎는다.
- **기사 ↔ 지식맵 연동은 `build_graph` 가 만드는 양방향 색인으로 돈다.**
  노드에 `articles_idx`, 기사에 `node_ids`. 색인은 화면에 보이는 기사 목록
  순서 기준이라, 정렬을 바꾸면 그래프를 반드시 다시 만들어야 한다.
- **지식맵 재료는 상위 `GRAPH_ARTICLES`(10) 건의 제목 + 요약.** 화면 목록도 같은
  10건을 보여 줘야 색인이 어긋나지 않는다 (`screen-insight.js` 의 `GRAPH_ARTICLES`).
- **기술 노드를 보고서 검색어로만 만들지 말 것.** 그러면 가지가 3~4개뿐인
  앙상한 별 모양이 된다. `TECH_PATTERNS` 사전 + `TECH_SUFFIX` 자동 추출 +
  검색어를 합쳐 쓴다. 기관은 `ORG_PATTERNS` + 접미사 + 문장 주체.
- **사전 정규식에 `\b` 를 쓰지 말 것.** 파이썬은 한글도 낱말 문자로 보기 때문에
  `\bAI\b` 가 "AI가" 의 AI 를 놓친다. 패턴은 `_relax_boundaries` 를 거쳐
  컴파일되며(`_ORG_RE`·`_TECH_RE`), 새 패턴을 추가할 때도 이 목록에 넣으면 된다.
- **동시 등장 선(기술↔기술, 기관↔기관)은 근거 2건부터.** 1건이면 한 기사에서
  우연히 겹친 것이라 선이 폭발한다.

이 항목들은 고도화 단계에서 다룹니다. 데모에서는 건드리지 마세요.

## 금지 사항

- 디자인 토큰(색·폰트·radius·shadow) 임의 변경
- 프론트 프레임워크 도입
- DB·로그인 구현
- 외부 LLM API 를 기본 활성화 (환경변수 있을 때만 사용, 없으면 TF-IDF 폴백)
- 전송 내역을 disclosure 없이 외부로 보내는 코드 (v2 전송 정책: 허용하되 전부 공개)
- 원본 보고서에 없는 내용 생성
- `_ref/` 하위 파일 수정

## 실행

```bash
# Windows
run.bat

# macOS / Linux
./run.sh
```

→ http://127.0.0.1:8120
