# phone-homeserver

서랍 속 갤럭시 노트 FE(Android 9)에 우분투를 올리고, 그 위에서 블로그와 대시보드를 24시간 돌리는 개인 서버의 코드와 운영 문서다. 앱 하나 없이 파이썬 표준 라이브러리와 셸 스크립트만 쓴다.

이 저장소는 기술 블로그 연재의 실물이다. 글은 [`qofo/qofo.github.io`](https://github.com/qofo/qofo.github.io)에 있다.

## 구조

```
Android 9
└─ Termux (앱)
   ├─ Termux:Boot / termux-job-scheduler   ← 부팅 때와 15분마다 감독 스크립트를 되살림
   └─ proot-distro: Ubuntu 26.04 (aarch64)
      ├─ start_services.sh      공개 서비스의 감독자 (블로그 + ngrok)
      │   ├─ serve_blog.py      Hugo로 빌드한 블로그 + 실시간 대시보드 API (:8080)
      │   └─ ngrok              고정 도메인으로 공개
      └─ private_docs.sh        내부 문서 서버의 감독자 (별도)
          └─ private_docs_server.py   Tailscale 안에서만 열리는 마크다운 뷰어 (:8081)
```

블로그 글과 Hugo 사이트는 [`qofo/qofo.github.io`](https://github.com/qofo/qofo.github.io)에 있다. 같은 원본을 GitHub Pages와 이 폰이 각각 빌드해서 서비스하고, 대시보드 수치는 어느 쪽에서 열어도 폰의 `/api/metrics`에서 온다.

proot는 `--kill-on-exit`로 실행되므로 로그인 세션에서 띄운 프로세스는 세션이 끝나면 함께 죽는다. 그래서 감독자는 항상 Termux 쪽 런처(`termux/`)가 `setsid`로 proot 바깥에서 낳는다. 이 제약과 나머지 함정은 블로그 3편과 5편에 있다.

## 파일

| 경로 | 역할 |
|---|---|
| `serve_blog.py` | `/root/blog_public`의 Hugo 빌드를 정적으로 보내고, `/api/metrics`를 제공한다(CORS preflight 포함) |
| `publish_blog.sh` | 블로그 원본(`qofo.github.io`)을 폰용으로 빌드해 무중단 교체하고, `publish`면 GitHub에도 push한다 |
| `start_services.sh` | 공개 서비스 감독자. `start` `stop` `restart` `status` `start-daemon` |
| `measure_downtime.py` | 재시작 중 공개 주소의 중단 시간을 0.2초 간격으로 잰다 |
| `private_docs_server.py` | Tailscale 전용 문서 뷰어. 허용 목록에 있는 마크다운만 서빙한다 |
| `private_docs.sh` | 문서 서버 감독자. 같은 다섯 개 명령 |
| `private_docs.list.example` | 문서 허용 목록의 예시 |
| `private_docs_static/` | 뷰어의 정적 파일 (marked, DOMPurify 포함) |
| `termux/` | Termux 쪽 런처. proot 바깥에서 감독자를 낳는다 |
| `tests/test_private_docs.py` | 문서 서버의 블랙박스 보안 테스트 47개 |
| `tests/test_serve_blog.py` | 블로그 서버의 블랙박스 테스트 35개 (경로 조작, 리디렉트, 캐시, CORS, 빌드 교체) |
| `docs/` | 서버 환경 명세, 부하 시험 기록, Hugo 이전 계획 (IP는 예시 값으로 바꿈) |

## 설정

경로는 `/root` 기준으로 고정돼 있다. 옮겨 쓰려면 다음을 바꾼다.

- `start_services.sh`의 `NGROK_DOMAIN`, `measure_downtime.py`의 `DEFAULT_PUBLIC_URL`: 본인의 ngrok 고정 도메인
- `publish_blog.sh`의 `SRC`(블로그 저장소 경로)와 저장소 이름, `serve_blog.py`의 `BLOG_SITE_DIR`(환경변수로도 바꿀 수 있다)
- ngrok authtoken은 `~/.config/ngrok/ngrok.yml`에 둔다. **저장소에 넣지 않는다.**
- 문서 서버: `cp private_docs.list.example private_docs.list` 후 보여 줄 파일을 한 줄에 하나씩 적는다. 목록에 없는 파일은 URL을 알아도 열리지 않는다.
- 문서 서버는 Tailscale 인터페이스의 주소에만 바인딩한다. 환경변수는 `PRIVATE_DOCS_BIND`, `PRIVATE_DOCS_PORT`, `PRIVATE_DOCS_ALLOW`, `PRIVATE_DOCS_LIST`, `PRIVATE_DOCS_STATE`.

## 실행과 시험

```bash
./start_services.sh status        # 공개 서비스
./private_docs.sh status          # 내부 문서 서버
python3 tests/test_private_docs.py
python3 tests/test_serve_blog.py
./publish_blog.sh status          # 폰 사본과 Pages가 어느 커밋을 서비스하는지
```

테스트는 임시 디렉터리와 자체 포트만 쓰므로 실행 중인 서비스에 영향을 주지 않는다.

## 보안 메모

- 문서 서버를 `0.0.0.0`에 바인딩하지 않는다. 바인딩 주소가 곧 방화벽이다. 자세한 방어 계층은 8편에 있다.
- 이 저장소에는 토큰, 키, 실제 공인 IP를 넣지 않는다. `docs/`의 IP는 예시 값(`192.168.0.42`, `100.x.y.z`)이다.

## 라이선스

이 저장소의 코드와 문서는 [MIT](LICENSE)다. `private_docs_static/`에 들어 있는 서드파티 파일은 각자의 라이선스를 따른다.

| 파일 | 라이선스 |
|---|---|
| `marked.umd.min.js` (marked 18.0.13) | MIT |
| `purify.min.js` (DOMPurify 3.4.15) | Apache-2.0 또는 MPL-2.0 |
