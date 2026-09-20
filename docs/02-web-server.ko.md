# 2. 웹 서버 — 표준 라이브러리에서 Hugo까지

[English](02-web-server.md) · <b>한국어</b>

[← 1. 설치](01-install.ko.md) · 다음: [3. 공개 주소](03-public-address.ko.md)

---

폰은 웹 서버를 하나도 설치하지 않고도 웹사이트를 서비스할 수 있다. 이 문서는 그 한 줄
명령에서 시작해, 이 저장소가 실제로 돌리는 구조까지 간다. Hugo가 정적 사이트를 빌드하고,
`serve_blog.py`가 그것을 서비스하고, 같은 커밋이 폰과 GitHub Pages에 동시에 올라간다.

## 2.1 30초 버전

```bash
cd /root/site && python3 -m http.server 8080 --bind 127.0.0.1
curl -sI http://127.0.0.1:8080/ | head -1
```

폰이 HTTP를 서비스할 수 있다는 것을 확인하기에는 충분하다. 그대로 띄워 두기에는
충분하지 않다. `http.server`는 디렉터리 목록을 보여 주고, 심볼릭 링크를 따라 트리
밖으로 나가고, 캐시 헤더를 붙이지 않고, 그 순간 디스크에 있는 것을 그대로 보낸다.
반쯤 쓰인 빌드까지 포함해서다.

## 2.2 요청할 때가 아니라 빌드할 때 렌더한다

이 블로그의 첫 버전은 파이썬 파일 하나였다. 요청마다 마크다운 파일 이름을 파싱하고,
마크다운은 브라우저가 렌더했다. 동작은 했고, 치명적인 성질이 하나 있었다. **폰이 꺼지면
사이트가 없다.** [`04-always-on.ko.md`](04-always-on.ko.md)의 재부팅 장애 때 방문자가
본 것은 느린 페이지가 아니라 터널의 오류 페이지였다.

정적 사이트 생성기로 옮기면 해결된다. 빌드 결과물은 그냥 파일이기 때문이다. 그 파일은
폰보다 가동률이 좋은 곳에 복사할 수 있고, 두 곳에서 동시에 서비스할 수 있다.

```bash
apt-get install -y hugo         # 이 폰에서는 0.154.5+extended
hugo new site blog && cd blog
hugo --gc --minify -d public
```

Hugo는 이 폰에서 글 열 편짜리 사이트를 2초 안에 빌드한다. 테마는 폰이 실제로 빌드할 수
있는 것을 고른다. 먼저 `min_version`을 확인하고, git 서브모듈이나 Hugo 모듈보다
`themes/`에 파일로 복사해 넣는 쪽을 택한다. 그러면 빌드에 네트워크가 필요 없다.

![같은 커밋을 폰과 GitHub Pages에 배포하는 흐름](images/publish-pipeline.svg)

## 2.3 빌드를 안전하게 서비스하기

`serve_blog.py`는 표준 라이브러리의 `ThreadingHTTPServer`다. `http.server`에 더한
것은 전부 방어 코드다.

| 동작 | 이유 |
|:---|:---|
| 모든 경로를 resolve한 뒤 빌드 루트 안인지 확인 | `..`와 심볼릭 링크는 둘 다 단순 결합을 빠져나간다 |
| 디렉터리 목록을 절대 보여 주지 않음 | 목록 하나가 새면 트리 전체의 지도가 된다 |
| 디렉터리 요청에 `index.html`, 슬래시 누락은 리디렉트 | Hugo가 생성하는 구조와 맞춘다 |
| 해시가 붙은 자산은 긴 `Cache-Control`, HTML은 짧게 | 폰의 업링크가 병목이라 캐시가 평소보다 더 중요하다 |
| `/api/metrics`로 배터리·메모리·온도·가동 시간 제공 | 대시보드의 유일한 데이터 출처 |
| `Access-Control-Allow-Origin`만이 아니라 `OPTIONS`를 직접 처리 | 아래를 본다 |

CORS 문제는 따로 적어 둘 만하다. `curl`로는 잡히지 않기 때문이다. 브라우저가 비표준
요청 헤더를 보낼 때 — 여기서는 `ngrok-skip-browser-warning`이었다 — 먼저 `preflight`
`OPTIONS` 요청을 보낸다. 파이썬의 `BaseHTTPRequestHandler`는 구현되지 않은 메서드에
**501**로 답하고, preflight가 실패하고, 대시보드에는 데이터가 나오지 않는다. 그런데 같은
URL에 `curl`을 쏘면 200이 온다. `OPTIONS`를 직접 처리해야 한다.

```bash
BLOG_SITE_DIR=/root/blog_public python3 serve_blog.py
```

## 2.4 빌드 교체는 원자적으로

새 디렉터리에 빌드하고 심볼릭 링크를 옮긴다. 서비스 중인 디렉터리 위에 덮어쓰지 않는다.

```bash
out=/root/blog_builds/$(date +%Y%m%d-%H%M%S)
hugo --gc --minify -d "$out"
ln -sfn "$out" /root/blog_public.new
mv -Tf /root/blog_public.new /root/blog_public     # rename(2): 원자적
```

심볼릭 링크에 대한 `mv -T`는 `rename(2)` 한 번이므로, 요청은 옛 빌드 아니면 새 빌드를
받는다. 이것을 하지 않으면 사이트가 반쯤 쓰인 구간이 생기고, 두 빌드에 모두 있는
자산에 대해 방문자가 404를 받는다.

빌드가 아예 없을 때 `serve_blog.py`는 500이 아니라 짧은 안내와 함께 200으로 답한다.
감시 도구에는 "고장"이 아니라 "살아 있고 비어 있음"으로 보여야 한다.

## 2.5 원본 하나, 서버 둘

`publish_blog.sh`는 네 개의 동작을 받는다.

```bash
./publish_blog.sh phone      # 폰 사본을 빌드하고 교체
./publish_blog.sh pages      # 빌드해서 gh-pages 브랜치로 push
./publish_blog.sh publish    # 같은 커밋으로 둘 다
./publish_blog.sh status     # 각 사본이 어느 커밋을 서비스하는지
```

GitHub Pages 사본까지 폰이 빌드한다. 흔한 방식은 아니다. 이유는 자격 증명이다.
`repo` 권한만 가진 classic 토큰은 `.github/workflows/` 아래 경로를 push할 수 없어서
GitHub Actions 워크플로를 쓸 수 없다. 폰에서 빌드하면 2초가 걸리고, Actions 사용량이
들지 않고, 두 사본이 같은 커밋과 같은 Hugo 바이너리에서 나온다는 것이 보장된다.

이 구조를 따라 쓸 때 알아 둘 것이 두 가지 있다.

- **`gh-pages`에 push해도 Pages 빌드가 반드시 시작되지는 않는다.** 한 번은 됐고 그
  뒤로는 8분 동안 시작되지 않았다. `publish_blog.sh`는 빌드가 잡히는지 지켜보다가,
  없으면 API(`POST /repos/<owner>/<repo>/pages/builds`)로 요청한다.
- **Pages는 브랜치를 서비스하므로, github.com에서 고친 글은 폰에 없다.** 폰에서
  `publish`를 실행해 다시 맞추고, 벌어졌는지는 `status`로 확인한다.

## 2.6 폰 전용 페이지를 공개 빌드에서 뺀다

실시간 대시보드는 폰의 `/api/metrics`를 호출한다. 공개 사이트에서 이 말은 방문자마다
자기 브라우저로 내 폰을 찌른다는 뜻이고, 맞는 구조가 아니다. Hugo의 설정 디렉터리가
이것을 해결한다. 대시보드 콘텐츠는 `content-phone/`에 두고, 폰 설정에서만 마운트한다.

```toml
# config/phone/hugo.toml — 폰 빌드에서만 공용 설정 위에 병합된다
[[module.mounts]]
  source = "content-phone"
  target = "content"
```

함정이 하나 있다. **메뉴는 Hugo 설정 디렉터리 사이에서 병합되지 않는다.** 메뉴 항목
하나를 추가한 `config/phone/hugo.toml`은 메뉴 전체를 대체하므로, 공용 항목까지 다시
적어야 한다.

## 2.7 확인

```bash
python3 tests/test_serve_blog.py     # 블랙박스 테스트 35개
./publish_blog.sh status
curl -sI http://127.0.0.1:8080/ | head -1
curl -s http://127.0.0.1:8080/api/metrics | head -c 200
```

이 테스트는 경로 조작, 심볼릭 링크 탈출, 리디렉트, 캐시 헤더, CORS preflight, 빌드
교체를 확인한다. 임시 디렉터리와 자체 포트만 쓰므로 운영 중인 폰에서 돌려도 안전하다.
테스트 자체를 점검하는 방법도 있다. 서버를 복사한 뒤 사본에서 경로 검사를 지우고,
테스트가 실패하는지 확인하면 된다.

다음: 집 밖에서 닿게 만든다 → [3. 공개 주소](03-public-address.ko.md)
