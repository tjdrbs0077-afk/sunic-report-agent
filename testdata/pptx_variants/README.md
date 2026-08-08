# PPTX 오류 변형 데이터

이 폴더는 실제 보고 양식을 복제한 뒤 오류를 하나씩 의도적으로 주입한 회귀 테스트 입력을 담습니다. 기준 양식 자체는 하나여도 괜찮지만, 다양한 입력 오류와 그 기대 결과가 있어야 검증·자동 수정 기능을 안정적으로 개선할 수 있습니다.

## 포함 오류

- 불릿과 연속 공백
- 제목 글꼴과 크기
- 본문 글꼴과 크기
- 제목 위치
- 표 위치와 너비
- 위 오류의 복합 사례

`manifest.json`은 파일별 기대 오류 범주와 현재 알려진 검증 공백을 기록합니다. `validator-baseline.json`은 현재 검증기의 실제 탐지 결과를 기록하는 기준선입니다.

## 재생성

프레젠테이션 런타임이 준비된 환경에서 다음 명령을 실행합니다.

```powershell
node scripts/generate_pptx_variants.mjs
python scripts/evaluate_pptx_variants.py
```

렌더링 이미지는 저장소에 포함하지 않고 `.tmp/ppt-variant-renders`에 생성합니다.
