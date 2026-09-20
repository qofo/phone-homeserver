<h1 align="center">phone-homeserver</h1>

<p align="center">
  2017년에 나온 안드로이드 폰 하나로, 루팅도 클라우드도 없이<br>
  공개 블로그와 비공개 문서 뷰어와 브라우저 IDE를 24시간 돌린다.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <img alt="Platform: Android 9+" src="https://img.shields.io/badge/platform-Android%209%2B-3ddc84.svg">
  <img alt="No root required" src="https://img.shields.io/badge/root-not%20required-2da44e.svg">
  <img alt="Ubuntu 26.04 via proot-distro" src="https://img.shields.io/badge/Ubuntu-26.04%20(proot--distro)-E95420.svg">
  <img alt="Python standard library only" src="https://img.shields.io/badge/Python-stdlib%20only-3776AB.svg">
</p>

<p align="center">
  <a href="README.md">English</a> · <b>한국어</b>
</p>

---

기억으로 쓴 튜토리얼이 아니라, 실제로 돌아가고 있는 폰 한 대의 설정이다. 여기 있는
명령은 모두 갤럭시 노트 FE(`SM-N935L`)에서 실행됐고, 그 폰은 2026년 9월 17일부터
[qofo.github.io](https://qofo.github.io/)를 서비스하고 있다. 문서에 나오는 수치는
모두 그 폰의 로그에서 가져왔다.

![폰 서버의 계층 구조](docs/images/architecture.svg)

## 왜 서랍 속 폰인가

이미 갖고 있는 폰은 첫 서버로 싱글보드 컴퓨터보다 낫다. 이유는 네 가지다. 돈이 들지
않고, 소비 전력이 5W 미만이고, 배터리가 곧 무정전 전원 장치이고, 네트워크가 끊겼을
때 볼 화면이 달려 있다. 갤럭시 노트 FE는 CPU와 램에서 라즈베리파이 3을 앞선다.

대가는 평범한 리눅스를 포기하는 것이다. root가 없고, `systemd`가 없고, 도커가 없고,
방화벽이 없고, `/proc`은 거짓을 말한다. 이 제약이 이 저장소의 모든 스크립트를
결정했다. 하나씩은 [`docs/04-always-on.ko.md`](docs/04-always-on.ko.md)에 있다.

![2017년에 나온 폰이 실제로 내주는 자원](docs/images/term-specs.svg)

## 무엇이 돌아가는가

| 서비스 | 주소 | 접근 범위 | 구현 |
|:---|:---|:---|:---|
| **블로그** — Hugo 사이트 + 실시간 하드웨어 대시보드 | ngrok 도메인 뒤의 `:8080` | 공개 인터넷 | `serve_blog.py`, 파이썬 표준 라이브러리 |
| **비공개 문서** — 허용 목록 기반 마크다운 뷰어 | `:8081` | 내 tailnet 안에서만 | `private_docs_server.py`, 파이썬 표준 라이브러리 |
| **code-server** — 브라우저에서 쓰는 VS Code, HTTPS | `:8443` | 내 tailnet 안에서만 | code-server + 개인 CA |

세 서비스는 각자 감독자를 갖는다. 감독자는 10초 안에 프로세스를 되살리고, 재부팅을
견디고, 터미널을 닫아도 계속 돈다.

## 준비물

**하드웨어**

- arm64(`aarch64`) 안드로이드 폰, 안드로이드 7 이상. 루팅은 필요 없다.
- 블로그만 돌린다면 램 **2GB**로 충분하고, code-server까지 쓰려면 **3GB 이상**이 좋다.
- Ubuntu rootfs와 Hugo, code-server를 합쳐 여유 공간 **8GB**.
- 계속 꽂아 둘 충전기. 케이스를 벗겨 두면 좋다. 팬 없는 폰은 부하가 걸리면 뜨거워진다.

**앱** — 전부 무료다. Tailscale만 플레이스토어에서 받는다.

| 앱 | 받는 곳 | 용도 |
|:---|:---|:---|
| **Termux** | [F-Droid](https://f-droid.org/en/packages/com.termux/) — 플레이스토어 버전은 관리가 끊겼으니 **쓰지 않는다** | 모든 것이 돌아가는 리눅스 셸 |
| **Termux:Boot** | [F-Droid](https://f-droid.org/en/packages/com.termux.boot/) | 재부팅 뒤 서버를 다시 띄운다 |
| **Termux:API** | [F-Droid](https://f-droid.org/en/packages/com.termux.api/) | 배터리·온도 조회와 알림 |
| **Tailscale** | [플레이스토어](https://play.google.com/store/apps/details?id=com.tailscale.ipn) | `:8081`과 `:8443`을 위한 사설망 |
| **ngrok 계정** | [ngrok.com](https://ngrok.com) (무료) | 바뀌지 않는 공개 HTTPS 주소 하나 |

Termux 계열 세 앱은 반드시 F-Droid에서 한꺼번에 받는다. F-Droid 빌드와 플레이스토어
빌드를 섞으면 부가 앱이 동작하지 않는다. 안드로이드는 서명 키가 다른 앱끼리 대화하는
것을 막기 때문이다.

## 빠른 시작

여섯 단계다. 각 단계의 배경은 [문서](#문서)에 있다.

### 1. 리눅스 셸 확보

```bash
pkg update && pkg upgrade -y
pkg install proot-distro termux-api openssh
proot-distro install ubuntu
proot-distro login ubuntu
```

우분투에 들어가면 다른 일보다 먼저 인증서 번들을 고친다. 최소 rootfs에는 쓸 만한
CA 번들이 없어서, 이걸 하기 전까지는 모든 HTTPS 호출이 실패한다.

```bash
apt-get update && apt-get install --reinstall ca-certificates
apt-get install -y python3 git curl hugo
```

![Termux — 빈 앱에서 우분투 셸까지](docs/images/term-install.svg)

### 2. 파일을 폰에 올리기

```bash
cd /root
git clone https://github.com/qofo/phone-homeserver.git
cp phone-homeserver/*.py phone-homeserver/*.sh /root/
cp -r phone-homeserver/tests phone-homeserver/private_docs_static /root/
mkdir -p /root/termux && cp phone-homeserver/termux/*.sh /root/termux/
chmod +x /root/*.sh /root/termux/*.sh /root/*.py
```

모든 스크립트는 자기가 `/root`에 있다고 가정한다. 옮기려면 [설정](#설정)을 본다.

### 3. 무언가를 서비스하기

```bash
./start_services.sh start
curl -sI http://127.0.0.1:8080/ | head -1
```

### 4. 바뀌지 않는 공개 주소 얻기

토큰을 `~/.config/ngrok/ngrok.yml`에 넣고, `start_services.sh` 맨 위의
`NGROK_DOMAIN`을 ngrok이 내준 무료 고정 도메인으로 바꾼다.

```yaml
version: "3"
agent:
  authtoken: <발급받은 토큰>
```

도메인을 사지 않고 고정 주소를 얻는 방법은 세 가지였고, 망을 옮겨 다니는 폰에서
동작한 것은 하나뿐이었다. 세 방식 비교는
[`docs/03-public-address.ko.md`](docs/03-public-address.ko.md)에 있다.

### 5. 재부팅을 견디게 만들기

우분투 안이 아니라 **Termux** 셸에서 실행한다.

```bash
ROOTFS=$PREFIX/var/lib/proot-distro/containers/ubuntu/rootfs
mkdir -p ~/.termux/boot
ln -s $ROOTFS/root/termux/ensure-daemon.sh ~/.termux/boot/start-server.sh
termux-job-scheduler --job-id 4241 --period-ms 900000 --persisted true \
    --script $ROOTFS/root/termux/ensure-daemon.sh
```

일반 서버에는 대응물이 없는 단계이고, 제대로 만들기까지 두 번을 다시 쓴 단계다.
`proot`는 `--kill-on-exit`로 실행되므로 로그인 세션 안에서 띄운 프로세스는 세션이
끝날 때 함께 죽는다. 런처는 Termux 쪽에 있어야 하고 `setsid`를 써야 한다.

![재부팅·크래시·로그아웃을 서비스가 견디는 방식](docs/images/boot-chain.svg)

### 6. 다른 기기에서 확인하기

```bash
./start_services.sh status
python3 tests/test_serve_blog.py
```

![실제 폰에서 실행한 세 가지 status 명령](docs/images/term-status.svg)

## 저장소 구조

```
.
├── serve_blog.py              공개 블로그 + /api/metrics            :8080
├── start_services.sh          블로그와 ngrok의 감독자
├── publish_blog.sh            폰과 GitHub Pages에 동시 빌드·배포
├── measure_downtime.py        재시작이 만드는 중단 시간을 잰다
├── private_docs_server.py     tailnet 전용 마크다운 뷰어             :8081
├── private_docs.sh            문서 뷰어의 감독자
├── private_docs.list.example  뷰어가 보여 줄 파일의 허용 목록 예시
├── code_server.sh             code-server 감독자, CA·TLS 발급 포함    :8443
├── private_docs_static/       marked, DOMPurify, 뷰어의 CSS와 JS
├── termux/                    proot 밖에서 돌아야 하는 런처들
│   ├── ensure-daemon.sh         블로그와 ngrok
│   ├── ensure-private-docs.sh   문서 뷰어
│   ├── ensure-code-server.sh    code-server
│   ├── battery-watch.sh         충전 알림과 배터리 기록
│   └── claude-session.sh        SSH 연결보다 오래 사는 tmux 세션
├── tests/
│   ├── test_serve_blog.py       블랙박스 테스트 35개
│   └── test_private_docs.py     블랙박스 보안 테스트 47개
└── docs/                      한국어·영어 가이드
```

세 감독자는 모두 같은 다섯 개 명령을 받는다.

```bash
./start_services.sh   {start|stop|restart|status|start-daemon}
./private_docs.sh     {start|stop|restart|status|start-daemon}
./code_server.sh      {start|stop|restart|status|start-daemon}
```

## 문서

README는 서버를 띄우는 경로만 담는다. 나머지는 아래에 있고, 모든 문서는 두 언어로
존재한다.

| | 문서 | 내용 |
|:--|:---|:---|
| 1 | [설치](docs/01-install.ko.md) · [English](docs/01-install.md) | Termux, `proot-distro`, CA 번들, SSH, 그리고 이 모든 것을 강제한 바이너리 호환성의 벽 |
| 2 | [웹 서버](docs/02-web-server.ko.md) · [English](docs/02-web-server.md) | 표준 라이브러리만으로 만든 정적 서버, 폰에서 돌리는 Hugo, 폰과 GitHub Pages 동시 배포 |
| 3 | [공개 주소](docs/03-public-address.ko.md) · [English](docs/03-public-address.md) | Cloudflare Tunnel과 DuckDNS+포트포워딩과 ngrok 무료 도메인 비교, 그리고 CGNAT |
| 4 | [계속 떠 있게](docs/04-always-on.ko.md) · [English](docs/04-always-on.md) | `--kill-on-exit`, `setsid`, Termux:Boot, 15분 감시 작업, 멈춘 프로세스를 잡는 헬스체크 |
| 5 | [비공개 접근](docs/05-private-access.ko.md) · [English](docs/05-private-access.md) | Tailscale, 방화벽 역할을 하는 바인딩, 문서 뷰어의 5개 방어 계층, HTTPS code-server |
| 6 | [운영](docs/06-operations.ko.md) · [English](docs/06-operations.md) | 배터리와 열, 메트릭 API, 다운타임 측정, 부하 시험, 테스트 실행 |
| 7 | [문제 해결](docs/07-troubleshooting.ko.md) · [English](docs/07-troubleshooting.md) | 이 폰이 실제로 낸 모든 장애를, 눈에 보이는 증상으로 찾게 정리 |

[`docs/reference/`](docs/reference)에는 더 긴 작업 문서 네 편이 있다. 서버 환경 상세
명세서, code-server 사용 안내, Hugo 이전 계획, 부하 시험 규격이다. 가이드의 일부가
아니라 내부 기록이므로 **한국어만 있다.**

## 설정

경로는 `/root` 기준으로 고정돼 있다. 다른 곳에서 쓰려면 다음을 바꾼다.

| 항목 | 위치 |
|:---|:---|
| 내 ngrok 도메인 | `start_services.sh`의 `NGROK_DOMAIN`, `measure_downtime.py`의 `DEFAULT_PUBLIC_URL` |
| 블로그 원본과 빌드 위치 | `publish_blog.sh`의 `SRC`, `serve_blog.py`의 `BLOG_SITE_DIR`(환경변수로도 바꿀 수 있다) |
| 뷰어가 보여 줄 문서 | `cp private_docs.list.example private_docs.list` 후 한 줄에 한 경로 |
| 문서 뷰어의 바인딩과 포트 | `PRIVATE_DOCS_BIND`, `PRIVATE_DOCS_PORT`, `PRIVATE_DOCS_ALLOW`, `PRIVATE_DOCS_LIST`, `PRIVATE_DOCS_STATE` |
| TLS 인증서에 넣을 MagicDNS 이름 | `code_server.sh`의 `MAGIC_DNS` (이 사본에서는 일부러 비워 뒀다) |
| 4241–4246이 이미 쓰이는 경우의 작업 번호 | 각 감독자의 `LAUNCH_JOB_ID` |

ngrok 토큰은 `~/.config/ngrok/ngrok.yml`에 둔다. 저장소에는 절대 넣지 않는다.

## 보안 메모

- **비공개 서비스를 `0.0.0.0`에 바인딩하지 않는다.** `proot` 안에는 방화벽이 없고
  방화벽을 넣을 root도 없다. 그래서 바인딩 주소가 곧 방화벽이다. `:8081`과 `:8443`은
  Tailscale 주소에만 바인딩한다.
- 비공개 서비스 둘은 공개 서비스와 감독자를 공유하지 않는다. 블로그를 잘못 재시작해도
  둘은 끌려가지 않고, 그 반대도 마찬가지다.
- 토큰, 키, 실제 공인 IP는 여기에 넣지 않는다. `docs/`의 주소는 예시 값이다.
  `192.168.0.42`, `100.x.y.z`, `203.0.113.10`.
- `tests/test_private_docs.py`는 블랙박스 보안 시험이다. 경로 조작, 심볼릭 링크 탈출,
  `Host` 헤더, DNS 리바인딩, 허용 목록 우회를 확인한다. 뷰어를 고치면 반드시 돌린다.

![공개 경로와 tailnet 전용 경로](docs/images/network-paths.svg)

## 연재 글

여기의 설계 판단은 그때그때 글로 남겼다. 문서가 요약만 한 실패와 로그가 글에는 그대로
있다. [qofo.github.io](https://qofo.github.io/)에 있고, 원본은
[`qofo/qofo.github.io`](https://github.com/qofo/qofo.github.io)다.

## 다른 언어

영어: **[English documentation](README.md)**. 번역을 환영한다.
`README.<lang>.md`와 그에 맞는 `docs/*.<lang>.md`를 추가하는 풀 리퀘스트를 보내면
여기에 링크한다.

## 라이선스

코드와 문서는 [MIT](LICENSE)다. `private_docs_static/`의 서드파티 파일은 각자의
라이선스를 따른다.

| 파일 | 라이선스 |
|:---|:---|
| `marked.umd.min.js` (marked 18.0.13) | MIT |
| `purify.min.js` (DOMPurify 3.4.15) | Apache-2.0 또는 MPL-2.0 |
