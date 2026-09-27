# 7. 문제 해결 — 이 폰이 실제로 낸 장애 전부

[English](07-troubleshooting.md) · <b>한국어</b>

[← 6. 운영](06-operations.ko.md) · [README](../README.ko.md)

---

고장 난 하위 시스템이 아니라, 눈에 보이는 증상으로 찾게 정리했다. 모두 이 기기에서 실제로
일어난 일이고, 가정한 것은 없다.

| 영역 | 이동 |
|:---|:---|
| 설치 | [7.1](#71-설치) |
| 떠 있지 않는 프로세스 | [7.2](#72-떠-있지-않는-프로세스) |
| 공개 주소 | [7.3](#73-공개-주소) |
| 비공개 서비스 | [7.4](#74-비공개-서비스) |
| 사이트와 배포 | [7.5](#75-사이트와-배포) |
| 폰 자체 | [7.6](#76-폰-자체) |

## 7.1 설치

**`CANNOT LINK EXECUTABLE "node": cannot locate symbol ...`**
패키지가 깨진 것이 아니라, 설치된 패키지와 기기에 있는 라이브러리의 버전이 어긋난 것이다.
Termux는 안드로이드의 bionic libc 위에서 빌드되고, 저장소는 모든 것이 최신이라고 가정한다.
`pkg update && pkg upgrade -y`를 실행한 뒤 다시 시도한다. 큰 것을 설치한 뒤가 아니라 그
전에 한다.

**배포처에서 내려받은 바이너리가 멈추거나 링커에서 죽는다**
안드로이드 링커에는 일반 리눅스용 빌드가 충족하지 못하는 요구 조건이 있다.
`termux-elf-cleaner <파일>`은 딱 한 번 시도할 가치가 있다. 그것으로 안 되면 고치기를 멈추고
진짜 glibc가 있는 `proot-distro` 안에서 실행한다. [`01-install.ko.md`](01-install.ko.md)
1.4절.

**우분투 안의 모든 HTTPS 호출이 인증서 검증에 실패한다**
`proot-distro`의 rootfs는 최소 구성이라 CA 번들이 없거나 낡았다. 오류는 상대 서버를
탓하지만 문제는 내 신뢰 저장소다.

```bash
apt-get update && apt-get install --reinstall ca-certificates
```

**`termux-battery-status`(또는 다른 `termux-*` 명령)가 영원히 멈추고 아무것도 돌려주지 않는다**
Termux:API가 설치되지 않았거나, Termux와 다른 스토어에서 받은 것이다. 안드로이드는 서명 키가
다른 앱끼리 통신하지 못하게 하고, 그 실패는 조용하다. Termux, Termux:Boot, Termux:API를 모두
F-Droid에서 받는다. 부가 앱은 한 번씩 열어 둔다. 한 번도 실행되지 않은 부가 앱에는 권한이
부여되지 않는다.

**`sysctl -w fs.inotify.max_user_watches=8192`가 성공하는데 아무것도 바뀌지 않는다**
성공하지 않아야 했다는 것이 단서다. `proot-distro`가 그 경로 위에 일반 파일을 bind mount로
덮어 두었다.

```
$ grep inotify /proc/self/mountinfo
... /proc/sys/fs/inotify/max_user_watches rw,relatime - bind
    .../containers/ubuntu/sysdata/sysctl_inotify_max_user_watches rw,relatime
```

읽으면 4096이 나오고, 쓰면 그 파일만 바뀌고, 커널은 둘 다 모른다. `/proc/stat`과
`/proc/uptime`도 같은 수법이다. 진짜 한도를 알려면 숫자를 읽는 대신 실패할 때까지 감시를
걸어 본다.

## 7.2 떠 있지 않는 프로세스

**어젯밤까지 돌던 것이 아침에는 모두 `STOPPED`다**
`proot` 로그인 세션 안에서 띄운 것이다. `proot-distro`는 `--kill-on-exit`로 실행되어 세션이
끝나면 추적 대상 트리를 전부 데려간다. 감독자는 `termux/`의 런처를 통해서만 띄운다. 그
런처들이 Termux 쪽에서 `setsid`를 쓴다. [`04-always-on.ko.md`](04-always-on.ko.md) 4.3절.

**로그가 `[CRASH DETECTED]`로 가득하고 서비스가 계속 튄다**
감독자가 터미널의 프로세스 그룹을 공유하고 있어서, `Ctrl+C`나 닫히는 SSH 세션이 자식에게
닿는다. 감독자가 되살리고, 또 죽는다. 해결은 `setsid`이고, 교훈은 로그의 재시작 루프가
복구의 증거가 아니라 증상이라는 것이다.

**`status`는 `RUNNING`인데 방문자는 오류 페이지를 본다**
프로세스는 있고 일하기를 멈춘 것이다. `pgrep`은 그 차이를 볼 수 없다. 방문자가 실제로 쓰는
엔드포인트를 찌르고, 연속 3회 실패해야 조치하고, 시작 뒤에는 유예 시간을 준다. 4.4절.

**`SIGSTOP`으로 멈춘 서비스가 되살아나지 않는다**
멈춘 프로세스는 `SIGTERM`을 처리할 수 없으므로, `SIGTERM`을 보내고 기다리는 감독자는 영원히
기다린다. 제한 시간 뒤에 `SIGKILL`로 올린다.

**방금 멈춘 서비스가 저절로 돌아왔다**
15분 주기의 `termux-job-scheduler` 작업이 제 일을 한 것이다. 비활성 플래그를 먼저 만든다.
`touch /root/.services_disabled`(또는 `.private_docs_disabled`, `.code_server_disabled`).

**`termux-job-scheduler --period-ms 60000`인데 여전히 15분마다 돈다**
15분이 주기 작업에 대한 플랫폼의 하한이다. 더 짧은 값은 받아들여진 뒤 무시된다.

**SSH 연결이 끊기면 `tmux`도 죽는다**
`tmux` 서버를 `proot` 안에서 띄운 것이다. 그러면 그것도 다른 모든 것처럼 추적 대상이 된다.
`tmux`는 Termux 셸에서 시작하고, 세션 안에서 우분투로 로그인한다.

## 7.3 공개 주소

**`ERR_NGROK_334`: 엔드포인트가 이미 온라인이다**
엣지가 이전 세션을 정리하기 전에 새 에이전트가 도메인을 요구했다. `--pooling-enabled`를
붙인다. 실패 시 재시작하는 감독자를 쓰면 하루 안에 만난다.

**`ERR_NGROK_3200`: 에이전트는 돌고 있는데 엔드포인트가 오프라인이다**
4.4절의 멈춘 터널 사례다. 에이전트를 재시작하고 능동 헬스체크를 넣어서, 다음번에는 여기서
든 23분이 아니라 몇 초로 끝나게 한다.

**방문자가 사이트 전에 "You are about to visit ..."을 본다**
`ERR_NGROK_6024`, 무료 플랜의 브라우저 경고다. `curl`과 API 클라이언트는 영향을 받지 않는다.
`ngrok-skip-browser-warning`을 보내면 건너뛴다. 완전히 없애려면 유료 플랜이나 내 도메인이
필요하다.

**외부에서 요청하면 내 것이 아닌 웹 서버가 응답한다**
DNS 이름은 집을 가리키고, 그 안에서 어느 기계가 답할지는 공유기가 정한다. 예전에 80번 포트에
걸어 둔 포워딩이 데스크톱 PC를 대신 서비스한다. 폰을 탓하기 전에 포워딩 표를 확인한다.

**포워딩할 포트가 아예 없다**
`curl -s https://api.ipify.org`와 `ip route get 1.1.1.1`을 비교한다. WAN 주소가
`100.64.0.0/10` 안이면 통신사 수준 NAT이고, 터널만이 길이다.

**Cloudflare에서 Public Hostname을 추가할 수 없다**
Named Tunnel에는 내가 소유하고 Cloudflare 네임서버로 위임한 도메인이 필요하다. 무료
서브도메인은 위임할 수 없다. [`03-public-address.ko.md`](03-public-address.ko.md).

## 7.4 비공개 서비스

**`refusing to bind to 0.0.0.0`과 종료 코드 2**
의도된 동작이다. 쓸 수 있는 방화벽이 바인딩 주소뿐이므로, tailnet과 루프백 범위 밖의 주소는
경고가 아니라 시작 실패다.

**문서 뷰어가 `waiting`에 머물고 포트를 열지 않는다**
Tailscale 주소를 찾지 못했다. 앱이 꺼져 있거나 폰이 막 부팅한 것이다. 서버는 5초마다 다시
찾고, 올바른 주소를 얻기 전까지는 일부러 소켓을 열지 않는다.

**문서 뷰어가 종료 코드 3으로 끝난다**
tailnet 주소가 바뀌었다. 바인딩한 소켓은 옮길 수 없으므로 끝내고, 감독자가 새 주소로 다시
띄운다.

**다 돌고 있는데 브라우저가 붙지 못한다**
순서대로 확인한다. Tailscale이 *양쪽* 기기에서 켜져 있는가. `./private_docs.sh status`가
`listening`을 출력하는가. LAN 주소가 아니라 tailnet 주소로 접속하고 있는가. 와이파이 주소에서
연결이 거부되는 것은 설계가 동작하는 것이다.

**파일이 있는데 문서가 404다**
`private_docs.list`에 없다. 요청의 파일 이름은 그 목록을 조회하는 키이고 경로가 아니다. 한
줄 추가하면 되고, 재시작은 필요 없다.

**VS Code Remote-SSH: "This machine does not meet ... prerequisites"**
SSH가 도착하는 곳은 Termux이고 그곳은 bionic이다. glibc도 musl도 아니다. 거기에 VS Code
서버를 설치할 방법은 없다. 컨테이너 안에서 code-server를 돌리고 브라우저로 연다.
[`05-private-access.ko.md`](05-private-access.ko.md) 5.7절.

**code-server가 시작 직후 무한히 재시작한다**
원인이 둘이고 보통 함께 온다. 편집기가 준비되기 전에 헬스체크가 찌르고 있는 것(90초를
준다), 그리고 프로세스 패턴이 실제로 듣고 있는 Node가 아니라 래퍼만 맞히는 것이다. 후자는
멀쩡한 서비스를 감독자가 다시 띄우게 만든다.

**브라우저가 인증서를 신뢰하지 않는다고 한다**
그 기기에 CA를 설치한다. 먼저 `./code_server.sh status`가 출력하는 SHA-256 지문을 대조한다.

**내 CA로 발급한 인증서가 검증에 실패한다**
LAN IP나 공개 도메인용으로 발급했다면 이름 제약이 올바로 동작한 것이다. 이 CA는 tailnet
주소와 `*.ts.net`만 보증할 수 있다.

## 7.5 사이트와 배포

**대시보드에 데이터가 없는데, 같은 URL에 `curl`을 쏘면 200이 온다**
CORS preflight다. 비표준 요청 헤더 때문에 브라우저가 `OPTIONS`를 먼저 보내고, 파이썬의
`BaseHTTPRequestHandler`는 구현되지 않은 메서드에 **501**로 답하고, 본 요청은 일어나지
않는다. `OPTIONS`를 직접 처리한다. [`02-web-server.ko.md`](02-web-server.ko.md) 2.3절.

**배포 직후 몇 초 동안 자산이 404다**
서비스 중인 빌드 디렉터리 위에 덮어썼다. 새 디렉터리에 빌드하고 `mv -T`로 심볼릭 링크를
교체한다. `rename(2)` 한 번이다.

**노트북에서는 빌드되는 `hugo`가 폰에서 실패한다**
흔한 원인이 둘이다. 설정의 `timeZone = "Asia/Seoul"`은 이 최소 구성 우분투에 `tzdata`가
없어서 실패한다. 넣지 않는다. 또는 테마가 `apt`의 Hugo(여기서는 0.154.5)보다 높은
`min_version`을 선언해서 빌드를 거부한다.

**`.github/workflows/` 아래 경로에 대해 `git push`가 거부된다**
`repo` 권한만 가진 classic 토큰은 워크플로 파일을 push할 수 없다. `workflow` 권한을 주거나,
이 저장소처럼 Actions 대신 폰에서 빌드한다.

**`gh-pages`에 push했는데 GitHub Pages가 갱신되지 않는다**
push가 Pages 빌드를 반드시 일으키지는 않는다. 여기서는 한 번 됐고 그 뒤 8분 동안 되지
않았다. API로 요청한다.

```bash
curl -X POST -H "Authorization: token <토큰>" \
     https://api.github.com/repos/<owner>/<repo>/pages/builds
```

**github.com의 사이트와 폰의 사이트가 다르다**
Pages는 브랜치를 서비스하므로 GitHub 웹 편집기에서 고친 글은 폰에 없다.
`./publish_blog.sh status`가 각 사본의 커밋을 보여 주고, `publish`가 다시 맞춘다.

## 7.6 폰 자체

**배터리 알림이 15분마다 온다**
배터리가 임계값에 정확히 걸터앉아 있다. 히스테리시스를 넣어서, 값이 임계값에서 몇 포인트
움직인 뒤에야 정상 상태로 돌아가게 한다.

**Tapo 플러그가 시간 초과로 끝나거나, 두 번째 핸드셰이크에 400으로 답한다**
시간 초과는 플러그가 패킷을 잃어서다(여기서는 15%, 공유기까지는 1%). 요청 수를 줄이고,
타임아웃을 늘리는 대신 전체를 다시 시도하고, 결과는 폰의 충전 상태로 판단한다. 핸드셰이크
2의 400은 세션 쿠키가 돌아가지 않았다는 뜻이다. python-kasa에 aiohttp 세션을 직접 넘긴다면
쿠키 저장소를 `unsafe=True`로 만들어야 한다. 그렇지 않으면 IP 주소에서 온 쿠키를 무시한다. `tapo_plug.py status`가 한 번도 성공하지 않으면
`/root/.config/tapo/credentials`의 계정과 Tapo 앱의 타사 호환성 설정을 확인한다.

**8코어 폰인데 `nproc`이 5라고 하고, 로드 애버리지가 변하지 않는다**
안드로이드가 유휴 코어를 핫플러그로 떼어 내므로 보이는 개수가 바뀐다. 움직이지 않는 로드
애버리지는 `proot`가 `/proc/loadavg`를 흉내 낸 결과다. `sysinfo(2)`를 부르거나 Termux
쪽에서 값을 가져온다.

**폰이 뜨거워지고 전체가 느려진다**
서멀 스로틀링이다. 케이스를 벗기고, 화면은 꺼 두고 밝기를 낮추고, 고속 충전 중에 무거운
빌드를 돌리지 않는다. `battery_watch.log`의 `temp`를 보고, 부하 시험 전에 상한을 정한다.
[`06-operations.ko.md`](06-operations.ko.md).

**화면을 끈 뒤 몇 분 만에 터널이 끊긴다**
Doze다. `termux-wake-lock`을 실행하고, 안드로이드 설정에서 Termux의 배터리 최적화를 끈다.
둘 다 필요하고, 하나만으로는 부족하다.

---

여기 적힌 것이 틀렸거나 목록에 없는 장애를 만났다면, 폰 모델과 안드로이드 버전, 해당
`status` 명령의 출력을 함께 이슈로 올려 주면 좋겠다.
