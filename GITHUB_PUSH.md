# 깃허브 비공개 레포로 올리기

## 방법 A — gh CLI (권장)

[GitHub CLI](https://cli.github.com/) 가 설치돼 있으면 명령 한 줄로 끝납니다.

```bash
cd sunic-report-agent

# 최초 1회 로그인
gh auth login

git init
git add .
git commit -m "chore: SUNIC UI 기반 보고서 취합·편집 에이전트 스타터"
git branch -M main

# 비공개 레포 생성 + 푸시 (레포 이름은 원하는 대로)
gh repo create sunic-report-agent --private --source=. --remote=origin --push
```

## 방법 B — 웹에서 레포 먼저 만들기

1. https://github.com/new 접속
2. Repository name: `sunic-report-agent`
3. **Private** 선택
4. README·.gitignore·license는 **체크하지 않음** (이미 있습니다)
5. Create repository

그다음:

```bash
cd sunic-report-agent
git init
git add .
git commit -m "chore: SUNIC UI 기반 보고서 취합·편집 에이전트 스타터"
git branch -M main
git remote add origin https://github.com/<계정>/sunic-report-agent.git
git push -u origin main
```

`<계정>` 을 본인 GitHub 사용자명으로 바꾸세요.

## 푸시 전 확인

```bash
git status --short          # 올라갈 파일 확인
git check-ignore -v _ref/*  # _ref 가 제외되는지 확인
```

`_ref/` 안의 사내 자료(v4 프로토타입, 실제 보고서)는 `.gitignore` 로 제외됩니다.
`_ref/README.md` 만 올라갑니다. **혹시 모르니 푸시 전에 `git status` 로 한 번 더 확인하세요.**

## Claude Code 에서 작업 이어가기

```bash
git clone https://github.com/<계정>/sunic-report-agent.git
cd sunic-report-agent

# _ref 채우기 (레포에는 없습니다)
mkdir -p _ref
# → v4 프로토타입 압축 해제본을 _ref/report_ai_prototype/ 에 복사
git clone --depth 1 https://github.com/goyeonwoo/SUNIC_Demo _ref/SUNIC_Demo
cp _ref/SUNIC_Demo/index.html _ref/SUNIC_Demo_index.html

claude
```

Claude Code 가 `CLAUDE.md` 를 자동으로 읽습니다. 그다음 `PROMPT.md` 의 프롬프트를 붙여넣으세요.

## 브랜치 전략 제안

데모 단계라 단순하게 갑니다.

```
main        시연 가능한 상태만 유지
feat/*      기능 작업 (feat/ingest, feat/builder, feat/editor …)
```

```bash
git switch -c feat/ingest
# 작업 후
git push -u origin feat/ingest
gh pr create --fill
```
