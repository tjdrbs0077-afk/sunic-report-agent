# 사내 보고서 취합·편집 에이전트 (데모)

## 이 프로젝트가 하는 일

사업단에서 제출한 제각각인 PPT 보고서를 표준 양식으로 통일하고, 페이지 단위로 수정하고,
근거를 붙여 질의응답하고, 하나로 병합하는 사내 도구입니다.

현재 **데모 단계**입니다. DB·인증·다중 사용자는 만들지 않습니다.

## 스택

- 백엔드: FastAPI + python-pptx + scikit-learn (TF-IDF)
- 프론트: 바닐라 JS + CSS. **프레임워크 금지** (React/Vue/Tailwind/Bootstrap 전부 안 씀)
- 저장: JSON 파일 (`data/`)
- 폰트: Pretendard Variable (CDN)

## 화면 구성

| # | id | 화면 | 주요 API |
|---|----|------|----------|
| ⌂ | home | 홈 | — |
| 1 | s1 | 현황 대시보드 | `/api/stats` |
| 2 | s2 | 업로드 · 취합 | `/api/reports/upload`, `/api/merge` |
| 3 | s3 | 보고서 상세 | `/api/reports/{id}`, `/api/reports/{id}/rules` |
| 4 | s4 | 페이지 편집 | `/api/layouts`, `/api/generate` |
| 5 | s5 | 근거형 챗봇 | `/api/chat` |
| 6 | s6 | 동향 인사이트 | 더미 (연동 예정) |

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
    retrieve.py        TF-IDF 검색
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
- ⑥ 동향 인사이트는 전부 더미

이 항목들은 고도화 단계에서 다룹니다. 데모에서는 건드리지 마세요.

## 금지 사항

- 디자인 토큰(색·폰트·radius·shadow) 임의 변경
- 프론트 프레임워크 도입
- DB·로그인 구현
- 외부 LLM API 를 기본 활성화 (환경변수 있을 때만 사용, 없으면 TF-IDF 폴백)
- 원본 보고서에 없는 내용 생성
- `_ref/` 하위 파일 수정

## 실행

```bash
# Windows
run.bat

# macOS / Linux
./run.sh
```

→ http://127.0.0.1:8020
