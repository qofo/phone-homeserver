# Hugo 도입 & GitHub Pages 동시 운영 계획

> **작성일**: 2026년 9월 18일  
> **대상**: 이 서버에서 작업할 사람과 후속 AI 에이전트  
> **전제 문서**: [`SERVER_ENVIRONMENT_SPEC.md`](SERVER_ENVIRONMENT_SPEC.md) (v2.0.0)  
> **상태**: 실행 완료 (2026-09-19). 폰과 `https://qofo.github.io/` 모두 Hugo 빌드를 서비스 중

---

## 실행 결과 (2026-09-19)

폰 서버와 GitHub Pages가 같은 커밋의 Hugo 빌드를 서비스하고 있습니다. 운영 방법은 `SERVER_ENVIRONMENT_SPEC.md` 5장(관련 파일)과 9장(치트시트)에 있습니다. 아래는 이 계획서와 **다르게 한 것**과 그 이유입니다.

| 항목 | 계획 | 실제 | 이유 |
|:---|:---|:---|:---|
| 저장소 | `/root/site` 새로 생성 | `/root/qofo.github.io` | 이미 공개용으로 정리한 저장소가 있었음 |
| 테마 | PaperMod 서브모듈 | 저장소 안의 자체 레이아웃 (`layouts/`, `assets/`) | 옛 SPA의 디자인·홈 텔레메트리·대시보드를 그대로 옮기려면 PaperMod도 결국 템플릿을 덮어써야 함. 서브모듈과 테마 버전 호환 문제도 없앰 |
| 글 주소 | 영문 슬러그 | `/posts/<slug>/`, 파일은 `NN-<slug>.md` | 권장안 그대로 |
| 글 사이 링크 | `relref` 단축코드 | `[2편](02-stdlib-python-blog.md)` + 링크 render hook | GitHub에서 파일을 읽을 때도 링크가 열림. 대상이 없으면 빌드 실패 |
| 폰 빌드 위치 | `/root/site/public` | `/root/blog_builds/<시각>` + 심볼릭 링크 `/root/blog_public` | 빌드 도중의 반쯤 쓴 파일을 서비스하지 않도록 링크를 rename으로 교체 |
| 배포 명령 | `start_services.sh publish` | `/root/publish_blog.sh` (`phone`/`pages`/`publish`/`status`) | 실행 중인 감시 데몬 스크립트를 고치면 데몬을 껐다 켜야 함. 배포는 감시와 별개 |
| 대시보드 CORS | `Access-Control-Allow-Origin: *`면 충분 | **OPTIONS preflight 응답을 추가** | `ngrok-skip-browser-warning`은 비표준 헤더라 브라우저가 preflight를 먼저 보냄. ngrok은 이를 통과시켰고 옛 서버는 **501**로 답했음(2026-09-19 실측). 7장의 curl 확인은 preflight를 보내지 않아서 이 문제를 놓쳤음 |
| 폴링 주기 | 2초 | Pages 홈 30초·대시보드 5초, 폰 10초·3초. 탭이 숨으면 정지, 실패 시 최대 60초까지 간격 증가 | ngrok 무료 플랜은 요청 수를 셈 |
| GitHub 인증 | 배포용 SSH 키 | 사용자가 설정한 HTTPS 자격 증명(classic 토큰, `repo` 권한) | 이미 준비돼 있었음 |
| **Pages 빌드** | **GitHub Actions** | **폰에서 빌드해 `gh-pages` 브랜치로 push** (`publish_blog.sh publish`). Pages 소스는 `gh-pages` 브랜치 루트, `.nojekyll` 포함 | 토큰에 `workflow` 권한이 없어 워크플로 파일을 push할 수 없음. `gh` 로그인 토큰은 Pages 설정 변경이 403. 빌드는 1초 이내라 폰 부담이 없고, 두 사본이 같은 커밋·같은 Hugo 바이너리로 만들어짐. 대신 GitHub 웹에서 고친 글은 폰에서 `publish`해야 반영됨 |
| `timeZone` | — | 넣지 않음 | 폰 Ubuntu에 tzdata가 없어 `Asia/Seoul`이면 폰 빌드가 실패함 |

검증 (2026-09-19):
- `python3 /root/tests/test_serve_blog.py` 35/35. 경로 검사를 일부러 끈 사본에서는 6개가 실패함(시험이 실제로 방어 코드를 확인함).
- 폰 빌드를 크롤링해 내부 링크 89개 모두 200.
- 브라우저 쪽(jsdom) 27/27: Pages에서의 교차 출처 요청과 헤더, ngrok 경고 HTML 수신 시 "응답 없음" 표시, 복구, 폰 빌드의 같은 출처 요청, 옛 `#post=` 링크 이동, 복사 버튼, 테마 전환. 이 시험은 `npm i jsdom`이 필요해 저장소에 넣지 않았음.
- 전환 재시작 중단 12초. ngrok 주소에서 preflight 204, `/api/metrics` 200, 글·태그·RSS 200.
- GitHub Pages: 소스를 `gh-pages`로 바꾼 뒤 빌드 요청(API)으로 첫 배포. 사이트를 크롤링해 내부 링크 89개 모두 200.
- 소스 전환만으로는 Pages가 다시 빌드하지 않았음. 전환 전에 push한 `gh-pages`와 전환 뒤 push한 `main`은 둘 다 빌드를 일으키지 않아, `POST /repos/qofo/qofo.github.io/pages/builds`로 요청했음.
- 옛 SPA로 돌아가려면: `git -C /root checkout pre-hugo -- serve_blog.py && /root/start_services.sh restart` (옛 SPA는 `/posts`를 읽음).

---

## 0. 목표와 현재 상태

**목표**: 글을 Hugo로 관리하고, 같은 콘텐츠를 **폰 서버와 `github.io` 두 곳에서 동시에** 서비스합니다.

**현재**: `serve_blog.py` 한 파일이 전부를 담당합니다.

| 역할 | 현재 방식 | Hugo 도입 후 |
|:---|:---|:---|
| 글 저장 | `/posts/*.md` (독자 형식) | `site/content/posts/*.md` (front matter) |
| 렌더링 | 브라우저에서 `marked.js` | Hugo가 빌드 시 HTML 생성 |
| 목록·태그·요약 | 파이썬이 파일을 파싱 | Hugo가 처리 |
| 테마·레이아웃 | 파이썬 문자열 안의 HTML | Hugo 테마 |
| 실시간 대시보드 | `/api/metrics` + 내장 JS | **그대로 유지** (폰에만 있는 기능) |
| 서빙 | 파이썬이 HTML 생성해 응답 | 파이썬이 정적 파일 + API 응답 |

**핵심 제약**: GitHub Pages는 정적 파일만 서비스합니다. 대시보드의 실시간 데이터는 폰에서만 나옵니다. 그래서 "똑같은 사이트 두 벌"이 아니라, **같은 글 + 폰에서만 살아 있는 대시보드**라는 구조로 갑니다.

---

## 1. 목표 구조

```
        site/content/posts/*.md   ← 원본 하나 (git)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
   hugo --baseURL           hugo (GitHub Actions)
   <ngrok 주소>              --baseURL <user>.github.io
        │                        │
        ▼                        ▼
  /root/site/public         GitHub Pages
        │                        │
  serve_blog.py                  │
   ├ 정적 파일                    │
   └ /api/metrics ◀──── 대시보드 페이지가 CORS로 호출 ────┘
        │
     ngrok 터널
```

- **글**은 두 곳에서 똑같이 보입니다.
- **대시보드**는 어느 쪽에서 열어도 폰의 `/api/metrics`를 호출합니다. 폰이 꺼져 있으면 "응답 없음"으로 표시됩니다.
- **폰이 꺼져도 글은 GitHub Pages에서 계속 열립니다.** 이게 이번 작업의 가장 큰 실익입니다.

---

## 2. 선택과 근거

### 2.1 `serve_blog.py`를 버리지 않고 역할을 바꿉니다
Hugo가 HTML을 만들면 파이썬의 렌더링 역할은 사라집니다. 하지만 `/api/metrics`는 **이 폰에서만 얻을 수 있는 데이터**이고, 코어별 사용률 수집(cpuidle)·배터리(Termux:API) 로직이 들어 있습니다. 그래서 파이썬 서버는 "정적 파일 서버 + 텔레메트리 API"로 축소해서 남깁니다.

부수 효과가 하나 있습니다. 지금은 글을 고치면 서버 재시작이 필요 없지만 렌더링을 매 요청 처리합니다. 앞으로는 **빌드할 때 한 번만** 렌더링하고, 글을 고치면 `hugo` 빌드만 다시 돌리면 됩니다. 서버 재시작도 필요 없습니다.

### 2.2 빌드는 GitHub Actions에서, 폰에서도 병행
| 방식 | 장점 | 단점 | 결정 |
|:---|:---|:---|:---|
| GitHub Actions 빌드 | 폰 자원 0, 안정적 | 푸시해야 반영 | **Pages용으로 채택** |
| 폰에서 빌드 후 푸시 | 오프라인에서도 결과 확인 | 폰 CPU·배터리 소모 | 폰 서빙용으로만 사용 |

폰은 자기가 서비스할 `public/`만 만들고, GitHub는 자기 것을 따로 빌드합니다. 빌드 결과물(`public/`)은 저장소에 넣지 않습니다.

### 2.3 저장소는 하나로 새로 만듭니다
현재 `/root`(서버 파일)와 `/posts`(글) 두 저장소가 있습니다. Hugo 사이트는 **세 번째 저장소 `/root/site`**로 만들고, 이것만 GitHub에 올립니다. `/root`에는 ngrok 토큰·자격 증명이 있으므로 절대 올리지 않습니다.

### 2.4 baseURL은 두 개
같은 소스로 두 주소를 서비스하므로 빌드할 때 주소를 지정합니다.

```bash
hugo --baseURL https://daringly-marrow-penny.ngrok-free.dev/   # 폰용
hugo --baseURL https://<user>.github.io/                       # Actions용
```

검색엔진 중복 색인을 피하려고 **canonical은 GitHub Pages 주소로 고정**합니다(폰 주소는 언제든 바뀔 수 있고, ngrok 경고 페이지 때문에 방문자 경험도 나쁩니다).

---

## 3. 사전에 확인한 사실 (2026-09-18 실측)

| 항목 | 값 | 의미 |
|:---|:---|:---|
| `apt-cache policy hugo` | 0.154.5-1 (arm64) | 우분투 저장소에서 바로 설치 가능 |
| hugo 패키지 의존성 | `libsass1`, `libwebp7` | **extended 빌드** → SCSS 테마 사용 가능 |
| glibc | 2.43 | 공식 `hugo_extended_linux-arm64` 바이너리도 실행 가능 (대안) |
| 디스크 여유 | 42GB | 테마·빌드 여유 충분 |
| github.com | HTTP 200 | 네트워크 문제 없음 |
| `/root/.ssh` | **없음** | GitHub 인증 수단을 새로 만들어야 함 |
| git remote | **없음** | 원격 저장소 미연결 |
| inotify 감시 한도 | proot가 가짜 파일로 제한 | **`hugo server --watch`를 상시 서비스로 쓰지 말 것** (1회성 빌드 사용) |

---

## 4. 먼저 결정해야 할 것 (사용자 입력 필요)

| # | 결정 | 선택지 | 권장 |
|:--|:---|:---|:---|
| 1 | GitHub 사용자명 | — | 필요 |
| 2 | 저장소 이름 | `<user>.github.io` (주소가 루트) / 일반 저장소(주소에 `/repo` 붙음) | **`<user>.github.io`** |
| 3 | 저장소 공개 여부 | public / private | public (Actions 무제한, Pages 무료) |
| 4 | 테마 | PaperMod / Congo / Blowfish 등 | **PaperMod** (한국어 무난, 가볍고 문서 많음) |
| 5 | 글 주소 형식 | 한글 슬러그 / 영문 슬러그 | **영문 슬러그** (URL 깨짐·공유 문제 없음) |
| 6 | **공개 IP 마스킹** | 그대로 / 가림 | **가릴 것** (아래 참고) |

> ⚠️ **6번은 그냥 넘기지 마세요.** 초기 원고에는 집 공인 IP와 그 IP를 가리키는 DuckDNS 주소가 적혀 있었습니다. 공개 GitHub 저장소는 검색 색인과 아카이브가 남고, 집 공유기를 향한 스캔을 부르는 정보이므로 예시 값으로 바꿔야 합니다. 커밋 이력에도 남기 때문에 **첫 푸시 전에** 정리해야 하고, 이 저장소는 정리를 마친 새 히스토리에서 시작했습니다.

---

## 5. 단계별 실행 계획

### Phase 0. 준비 (10분, 사람이 결정)
1. 4장의 6개 항목 결정
2. GitHub에서 저장소 생성 (빈 저장소, README 없이)
3. 4편의 공개 IP 관련 문장 수정 후 `/posts`에 커밋

### Phase 1. 폰에서 Hugo로 전환 (1~2시간)

```bash
# 1) 설치와 확인
apt-get update && apt-get install -y hugo
hugo version                      # extended 표기 확인

# 2) 사이트 생성
mkdir -p /root/site && cd /root/site
hugo new site . --force
git init -b main
git submodule add --depth 1 https://github.com/adityatelange/hugo-PaperMod themes/PaperMod

# 3) 설정 (hugo.toml) — baseURL은 폰용으로 두고, Actions에서는 --baseURL로 덮어씀
#    languageCode = 'ko-kr', theme = 'PaperMod', title, params.canonifyURLs 등

# 4) 글 변환 (6장 규칙에 따라 스크립트 1회 실행)
#    /posts/*.md → /root/site/content/posts/*.md

# 5) 빌드와 확인
hugo --minify --baseURL https://daringly-marrow-penny.ngrok-free.dev/
ls -la public/index.html
```

```bash
# 6) 파이썬 서버를 정적 서빙으로 전환
#    - SITE_DIR = "/root/site/public" 추가
#    - "/" 및 하위 경로 → public 아래 파일 응답 (디렉터리는 index.html, 경로 이탈 차단)
#    - /api/metrics 유지, /api/posts·/api/post 제거
#    - 실패 시 404 페이지
/root/start_services.sh restart
curl -sI http://localhost:8080/ | head -1
curl -s http://localhost:8080/api/metrics | head -c 80
```

**검증**: 폰 로컬 200, 글 6편 열림, 대시보드 데이터 표시, 외부 ngrok 주소에서 동일.  
**롤백**: `git -C /root revert <커밋>` 후 `start_services.sh restart` (이전 SPA로 즉시 복귀).

### Phase 2. GitHub Pages 연동 (1시간)

```bash
# 1) 배포용 SSH 키 생성 (폰에서 푸시할 때 사용)
mkdir -p /root/.ssh && chmod 700 /root/.ssh
ssh-keygen -t ed25519 -C "you@example.com" -f /root/.ssh/id_ed25519 -N ""
cat /root/.ssh/id_ed25519.pub     # → GitHub 저장소 Settings > Deploy keys (쓰기 허용)에 등록

# 2) 원격 연결과 첫 푸시
cd /root/site
git remote add origin git@github.com:<user>/<user>.github.io.git
echo "public/" > .gitignore
echo ".hugo_build.lock" >> .gitignore
git add -A && git commit -m "Hugo site with six posts"
git push -u origin main

# 3) GitHub 저장소 설정
#    Settings > Pages > Source: GitHub Actions
```

`.github/workflows/pages.yml` (요지):

```yaml
name: Deploy Hugo site to Pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      HUGO_VERSION: 0.154.5
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
          fetch-depth: 0
      - name: Install Hugo
        run: |
          curl -sL https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-amd64.tar.gz | tar -xz hugo
          sudo mv hugo /usr/local/bin/
      - uses: actions/configure-pages@v5
        id: pages
      - run: hugo --minify --baseURL "${{ steps.pages.outputs.base_url }}/"
      - uses: actions/upload-pages-artifact@v3
        with:
          path: ./public
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

**검증**: Actions 성공 → `https://<user>.github.io/` 200, 글 6편, **폰을 껐을 때도 열림**.

### Phase 3. 자동화와 정리 (선택, 30분)

1. `start_services.sh publish` 추가: `hugo --minify --baseURL <ngrok>` 실행 후 결과 요약 출력. 글을 고친 뒤 이 명령 하나면 폰 쪽 반영 완료(재시작 불필요).
2. 대시보드 페이지를 Hugo 레이아웃으로 이식 (7장).
3. canonical을 Pages 주소로 고정.
4. 옛 `#post=...` 해시 링크로 들어온 방문자를 새 경로로 보내는 리다이렉트 스크립트 1개(선택).
5. `/posts`는 이전 기록으로 남기되, 원본은 `site/content/posts`로 일원화.

---

## 6. 콘텐츠 변환 규칙

현재 형식(머리말 인용 블록) → Hugo front matter 매핑입니다. 6편 모두 규칙이 같으므로 스크립트 1회 실행으로 변환합니다.

| 현재 | Hugo front matter |
|:---|:---|
| `# 1편. 제목` (본문 첫 줄) | `title: "1편. 제목"` (본문에서는 H1 제거) |
| `> **작성일**: 2026년 9월 17일` | `date: 2026-09-17` |
| `> **개정**: 2026년 9월 18일` | `lastmod: 2026-09-18` |
| `> **시리즈**: 스마트폰으로 서버 만들기 (1편)` | `series: ["스마트폰으로 서버 만들기"]`, `weight: 1` |
| `> **태그**: \`A\`, \`B\`` | `tags: ["A", "B"]` |
| 첫 문단 | `summary: "..."` |
| 파일명 `01_agy_setup_and_troubleshooting.md` | `slug: "termux-proot-ubuntu-setup"` 등 영문 슬러그 |
| 본문의 `[5편](#post=05_...)` | `[5편]({{< relref "05-...md" >}})` |

주의할 점:
- Hugo는 front matter 뒤의 첫 `#`를 그대로 본문 제목으로 렌더링하므로, 테마가 제목을 출력한다면 본문의 H1은 지웁니다.
- 코드 블록 안의 `{{`는 Hugo 템플릿으로 해석될 수 있습니다. 현재 글에는 없지만, 앞으로 Actions YAML 등을 붙여 넣을 때 주의해야 합니다(`{{</* */>}}` 이스케이프).
- 표·코드 블록은 Hugo 기본 마크다운(goldmark)에서 그대로 동작합니다.

---

## 7. 대시보드를 두 곳에서 살리는 방법

대시보드 페이지는 Hugo 레이아웃 하나로 만들고, 데이터는 항상 폰에서 가져옵니다.

```js
const API = location.hostname.endsWith('github.io')
  ? 'https://daringly-marrow-penny.ngrok-free.dev/api/metrics'
  : '/api/metrics';

const res = await fetch(API, {
  headers: { 'ngrok-skip-browser-warning': 'true' }   // 무료 플랜 경고 페이지 우회
});
```

이 방식이 실제로 되는지 2026-09-18에 확인했습니다.

```
브라우저 UA, 헤더 없음        → HTTP 200, 2902 bytes  (ngrok 경고 페이지)
브라우저 UA + skip 헤더        → HTTP 200, 1770 bytes  (실제 JSON)
Origin: https://example.github.io → access-control-allow-origin: *
```

- `/api/metrics`는 이미 `Access-Control-Allow-Origin: *`이므로 GitHub Pages에서 호출해도 막히지 않습니다.
- ngrok 무료 플랜의 경고 페이지는 **헤더를 붙인 요청에는 나오지 않습니다.** 브라우저 주소창으로 직접 들어갈 때만 뜹니다.
- 폰이 꺼져 있거나 터널이 끊기면 요청이 실패합니다. 이때는 숫자 대신 "폰이 응답하지 않습니다"와 마지막 갱신 시각을 표시합니다. **이 상태 표시 자체가 서버 감시 역할**을 합니다.

---

## 8. 검증 체크리스트

Phase 1 완료 시
- [ ] `hugo version`에 extended 표기
- [ ] `curl -sI http://localhost:8080/` → 200
- [ ] 글 6편 각각 열림, 표·코드 블록·글 사이 링크 정상
- [ ] `/api/metrics` JSON 정상, 대시보드 숫자 표시
- [ ] ngrok 주소에서 동일하게 동작
- [ ] `start_services.sh status` 정상, 재시작 후에도 유지

Phase 2 완료 시
- [ ] Actions 워크플로 성공
- [ ] `https://<user>.github.io/` 200, 글 6편
- [ ] Pages의 대시보드가 폰 데이터를 표시
- [ ] **폰 전원을 끈 상태에서 Pages가 여전히 열림**
- [ ] 저장소에 토큰·키·개인정보가 없음 (`git log -p | grep -iE "authtoken|BEGIN .*PRIVATE KEY"`)

---

## 9. 위험과 대응

| 위험 | 가능성 | 영향 | 대응 |
|:---|:---:|:---|:---|
| 공개 저장소에 집 공인 IP 노출 | 높음 | 큼 | **첫 푸시 전에 4편 수정** (4장 6번) |
| 테마가 새 Hugo 문법 요구 | 중 | 중 | apt 버전과 Actions 버전을 **같은 번호로 고정** |
| 폰 빌드가 느리거나 발열 | 중 | 작음 | 글 수정 시에만 1회 빌드, 감시(watch) 모드 사용 안 함 |
| proot inotify 제한 | 확정 | 작음 | `hugo server` 상시 구동 금지 |
| 대시보드가 Pages에서 깨짐 | 중 | 작음 | 실패 시 안내 문구로 대체(7장) |
| ngrok 주소 변경 | 낮음 | 중 | 대시보드 API 주소를 설정 파일 한 곳에서 관리 |
| SSH 키 유출 | 낮음 | 큼 | 계정 키 대신 **저장소 배포 키**만 사용, `/root/.ssh` 권한 700 |

---

## 10. 롤백 계획

- Phase 1은 `/root` 저장소의 커밋 하나로 묶습니다. 문제가 생기면 `git revert` 후 `start_services.sh restart`로 **1분 안에** 이전 SPA로 돌아옵니다.
- 전환 직전 상태에 태그를 남깁니다: `git -C /root tag pre-hugo`
- Hugo 사이트는 별도 디렉터리이므로, 실패해도 기존 `/posts`와 파이썬 서버는 그대로 남아 있습니다.
- Phase 2는 폰 서비스에 영향을 주지 않습니다. Pages만 끄면 됩니다.

---

## 11. 이 작업이 함께 해결하는 것

- **기기 밖 백업이 없다**는 기존 숙제가 해결됩니다. GitHub가 글의 원격 사본이 됩니다.
- **ngrok 경고 페이지** 문제가 완화됩니다. 사람에게 공유하는 링크는 `github.io`를 쓰고, 폰 주소는 실시간 대시보드용으로 둡니다.
- **폰이 꺼져도 글은 살아 있습니다.** 배터리가 빠진 채로 방치되어도 블로그 자체는 계속 열립니다.

---

## 부록: 예상 소요와 순서 요약

| 단계 | 내용 | 예상 시간 | 폰 서비스 중단 |
|:---|:---|:---:|:---:|
| Phase 0 | 결정·저장소 생성·IP 문장 정리 | 10분 | 없음 |
| Phase 1 | Hugo 설치·변환·정적 서빙 전환 | 1~2시간 | 재시작 시 10초 내외 |
| Phase 2 | GitHub 연동·Actions·Pages | 1시간 | 없음 |
| Phase 3 | publish 명령·대시보드 이식·정리 | 30분 | 없음 |

**다음 행동**: 4장의 6개 항목을 정해 주시면 Phase 1부터 실행합니다.
