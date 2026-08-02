# Claude Code 실행 프롬프트

이 레포는 **스캐폴딩이 완료된 상태**입니다. UI 셸·디자인 시스템·라우터·검증기·챗봇은 이미 동작합니다.
남은 것은 PPTX 추출기와 생성기 이식, 그리고 화면별 마감입니다.

## 사전 준비

`_ref/` 를 채웁니다. (레포에는 포함되지 않습니다 — `.gitignore` 처리)

```bash
mkdir -p _ref
# v4 프로토타입 압축 해제본을 _ref/report_ai_prototype/ 에 복사
git clone --depth 1 https://github.com/goyeonwoo/SUNIC_Demo _ref/SUNIC_Demo
cp _ref/SUNIC_Demo/index.html _ref/SUNIC_Demo_index.html
# 표준 양식 스펙 문서를 _ref/보고서양식_스펙.md 로 복사
```

표준 양식 템플릿도 옮깁니다.

```bash
cp "_ref/report_ai_prototype/assets/보고양식_Sample_4팀.pptx" app/assets/
```

동작 확인:

```bash
run.bat          # 또는 ./run.sh
curl http://127.0.0.1:8020/health
```

---

## 붙여넣을 프롬프트

아래 블록 전체를 Claude Code 에 붙여넣으세요.

---

```
이 레포의 남은 작업을 진행합니다. CLAUDE.md 를 먼저 읽고 규칙을 지켜주세요.
각 단계가 끝나면 결과를 요약하고 확인을 받은 뒤 다음으로 넘어가세요.

## 0단계 — 현재 상태 파악

아래를 읽고 파악한 내용을 요약해 주세요.
- CLAUDE.md — 디자인 규칙, 금지 사항
- config/standard_rules.yaml — 표준 양식 기준 (단일 진실 공급원)
- app/services/ingest.py, app/services/builder.py — 상단 TODO 주석
- _ref/report_ai_prototype/ppt_ingest.py, build_prototype.py — 이식 원본
- _ref/보고서양식_스펙.md — 양식 실측 스펙

## 1단계 — PPTX 추출기 이식 (app/services/ingest.py)

_ref/report_ai_prototype/ppt_ingest.py 를 이식합니다.
반환 형식은 ingest.py 의 docstring 에 적힌 v4 호환 구조를 유지하세요.

옮기면서 반드시 고칠 것:

(1) 본문 12줄 절단 제거
    원본의 `if len(body) >= 12: break` 는 내용을 조용히 버립니다.
    제한을 없애고, 한 장에 안 들어가면 페이지를 자동 분할하세요.
    이어지는 장은 standard_rules.yaml 의 continuation 규칙을 적용합니다
    (Lv1 제목 색을 #FFFFFF 로 바꿔 숨기되 번호 체계는 유지).

(2) 표 행·열 강제 절단 제거
    원본의 `_normalize_table(tables[0], 2, 5)` 는 5행 3열로 자릅니다.
    제한을 없애고 병합 셀(gridSpan/rowSpan)도 처리하세요.

(3) 본문 계층 판정 개선
    원본 `_estimate_level()` 은 폰트 크기 차이 + x>2.5in 휴리스틱입니다.
    아래 우선순위로 바꾸세요.
      1. paragraph.level 이 있으면 그대로
      2. marL / indent 를 standard_rules.yaml 의 body_levels 와 매칭
      3. 글머리 기호 종류(buChar / buAutoNum)
      4. 폴백으로 기존 폰트 크기 휴리스틱

(4) 좌표·글꼴·색을 하드코딩하지 말고 services.rules.load_rules() 에서 읽기

완료 후 `_ref/report_ai_prototype/generated/` 의 시연용 PPTX 를 업로드해
20페이지가 손실 없이 추출되는지 확인하고 결과를 보고하세요.

## 2단계 — PPTX 생성기 이식 (app/services/builder.py)

_ref/report_ai_prototype/build_prototype.py 를 이식합니다.

옮기면서 반드시 고칠 것:

(1) 모든 run 에 latin + ea 폰트를 명시
    생략하면 테마 상속으로 Aptos 로 떨어집니다.
(2) 좌표·색·크기를 standard_rules.yaml 에서 읽기
(3) 연속 슬라이드 Lv1 제목 색 처리 (continuation 규칙)
(4) 표 격자 0.75pt #BFBFBF, 헤더 #DCE6F2, 1열 #E8E8E8,
    셀 여백 L/R 0.0787in · T/B 0.0394in 고정
(5) 생성 직후 자기검증 — 만든 PPTX 를 다시 파싱해 규칙과 대조하고
    불일치 목록을 반환값에 포함

## 3단계 — 양식 검증기 확장 (app/services/rules.py)

현재 validate_report() 는 추출 JSON 으로 판정 가능한 항목만 봅니다.
1단계에서 원본 폰트·글머리 기호·marL 정보를 추출하게 되면,
그 정보로 아래 항목을 추가 검사하도록 확장하세요.

- 글꼴: 나눔스퀘어 / Corbel 이외 사용
- 글자 크기: 단계별 14/13/12/11/10pt 위반
- 글머리 기호: 표준 기호 이외 사용
- 들여쓰기: marL 이 기준값과 다름
- 표 규격: x 2.897570in, 너비 7.519097in 벗어남
- 개체: 차트·OLE 개체가 이미지로 변환되지 않음

결과 항목 구조는 기존과 동일하게 유지하세요.
{category, severity, slide_no, line_index, message, detail, auto_fixable}

auto_fixable 이 true 인 항목을 일괄 교정하는
POST /api/reports/{id}/autofix 도 추가하세요.

## 4단계 — ③ 보고서 상세 화면 마감

app/static/js/screen-detail.js 를 다듬습니다.

- 좌측 원본 미리보기: 위반 부분을 .badpt 로 정확히 표시
  (현재는 line_index 기반. 1단계에서 원본 기호·크기 정보가 생기면 더 정밀하게)
- 우측 교정본: 실제 표준 양식 적용 결과를 반영. 교정 부분은 .fixedpt
- 표가 2개인 template_type 3 도 렌더링
- 타임라인이 있으면 하단에 표시
- AI 피드백 체크 상태를 서버에 저장하고,
  /api/generate 시 체크된 항목만 발표자 노트로 삽입

## 5단계 — ② 업로드 화면 마감

- 파이프라인 4단계를 실제 처리 상태와 정확히 연동
  (현재는 대략적인 토글만 되어 있습니다)
- 업로드 실패 시 어떤 파일이 왜 실패했는지 .file-item 안에 표시
- 보고서 삭제 버튼 추가 (DELETE /api/reports/{id})
- 병합 순서를 드래그로 조정하는 UI 추가

## 6단계 — ④ 편집기 정밀도

- 8방향 리사이즈 핸들 (현재 우하단 1개)
- 스냅 가이드: 다른 개체 가장자리 + 양식 기준선에 붙기
- 다중 선택 (Shift+클릭) 후 정렬·균등분배
- 확대 50/100/200% + 화면맞춤
- 캔버스에 실제 텍스트 내용을 렌더링 (현재는 개체 이름만 표시)
  폰트 크기는 서버에서 내려준 값 기준으로 px 환산

## 7단계 — 검증

직접 실행해서 확인하고 결과를 보고하세요.
1. /health 정상 응답, template_exists true
2. 시연용 PPTX 20페이지 업로드 → 추출 → 검증 → 표준 양식 생성 통과
3. 생성된 PPTX 를 다시 파싱해 standard_rules.yaml 과 대조, 불일치 목록 보고
4. 2개 이상 보고서 병합 후 다운로드 확인
5. 브라우저 콘솔 에러 0건
6. 6개 화면 전환·사이드바 접기·Undo/Redo 동작

## 하지 말아야 할 것

- CLAUDE.md 의 디자인 토큰(색·폰트·radius·shadow) 변경
- 프론트 프레임워크 도입 (바닐라 JS 유지)
- DB·로그인 구현
- 외부 LLM API 기본 활성화 (환경변수 있을 때만)
- 원본에 없는 보고서 내용 생성
- _ref/ 하위 파일 수정
```

---

## 이어서 쓸 프롬프트 예시

- `2단계 생성기 이식 진행해줘`
- `④ 편집기에서 개체를 드래그하면 우측 속성 패널 x/y 값이 실시간으로 안 바뀌어. 고쳐줘`
- `standard_rules.yaml 에 타임라인 규칙 검증을 추가하고 validator 에 반영해줘`
- `생성된 PPTX 를 규칙과 대조하는 테스트를 pytest 로 만들어줘`
