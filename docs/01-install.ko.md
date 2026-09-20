# 1. 설치 — 빈 폰에서 우분투 셸까지

[English](01-install.md) · <b>한국어</b>

[← README](../README.ko.md) · 다음: [2. 웹 서버](02-web-server.ko.md)

---

이 문서를 끝내면 폰에서 Ubuntu 26.04가 돌고, 파이썬과 Git과 Hugo가 들어가 있고,
노트북에서 SSH로 붙을 수 있다. 루팅은 필요 없다.

![Termux — 빈 앱에서 우분투 셸까지](images/term-install.svg)

## 1.1 폰 자체를 먼저 설정한다

설치를 시작하기 전에 안드로이드 설정에서 처리한다. 하나하나가 안드로이드가 서버를
죽이는 경로다.

| 설정 | 위치 | 이유 |
|:---|:---|:---|
| Termux의 배터리 최적화 → **해제** | 설정 → 앱 → Termux → 배터리 | 최적화 대상 앱은 안드로이드가 정지시키고, 감시 루프가 멈춘다 |
| **절전 중에도 와이파이 켜 두기** | 설정 → Wi-Fi → 고급 | 없으면 화면을 끈 뒤 몇 분 안에 터널이 끊긴다 |
| 화면 시간 초과는 짧게, 밝기는 낮게 | 설정 → 디스플레이 | 화면이 가장 큰 전력 소모원이자 발열원이다 |
| 자동 업데이트 → **끄기** | 플레이스토어 → 설정 | 새벽에 혼자 재부팅되는 것은 원하는 동작이 아니다 |

폰은 꽂아 둔다. 100%에 머무는 것보다 30%에서 80% 사이를 유지하는 쪽이 배터리에
훨씬 낫다. 양쪽 다 알려 주는 스크립트는 [`06-operations.ko.md`](06-operations.ko.md)에
있다.

## 1.2 F-Droid에서 앱을 받는다

**Termux**, **Termux:Boot**, **Termux:API**를
[F-Droid](https://f-droid.org/en/packages/com.termux/)에서 한 번에 받는다.

> **스토어를 섞지 않는다.** 플레이스토어의 Termux는 관리가 끊겼고, 안드로이드는 서명
> 키가 다른 앱끼리 대화하는 것을 막는다. F-Droid Termux에 플레이스토어 Termux:API를
> 붙이면 `termux-battery-status`가 아무 말 없이 영원히 대답하지 않는다.

Termux:Boot는 설치한 뒤 한 번 열어 둔다. 보이는 변화는 없지만, 한 번도 실행되지 않은
부가 앱에는 부팅 권한이 부여되지 않는다.

## 1.3 다른 일보다 Termux를 먼저 갱신한다

```bash
pkg update && pkg upgrade -y
```

나중이 아니라 맨 처음에 실행한다. Termux는 glibc가 아니라 안드로이드의 **bionic**
libc 위에서 빌드되고, 패키지들은 저장소에 지금 있는 라이브러리 버전을 가정한다. 낡은
상태에서 큰 것을 설치하면 동적 링커가 거부한다.

```
CANNOT LINK EXECUTABLE "node": cannot locate symbol "..." referenced by
"/data/data/com.termux/files/usr/bin/node"...
```

이 오류는 패키지가 깨진 것이 아니라 버전이 어긋난 것이다. `pkg upgrade`로 해결된다.

이어서 이 가이드에 필요한 것을 넣고 웨이크 락을 잡는다.

```bash
pkg install proot-distro termux-api openssh tmux
termux-wake-lock
```

`termux-wake-lock`은 화면이 꺼져도 CPU가 잠들지 않게 한다. 이것이 없으면 폰을 내려놓은
지 몇 분 만에 Doze 상태로 들어가고 네트워크가 멈춘다.

## 1.4 Termux만으로는 왜 안 되는가

Termux에도 파이썬, Node, clang을 바로 설치할 수 있으니 계층을 하나 더 얹는 것이
불필요해 보인다. `pkg`로 받지 않은 것을 돌리려면 필요하다.

배포처에서 직접 내려받은 단일 실행 파일은 — 이 판단을 강제한 사례에서는 197MB짜리 CLI
도구였다 — glibc와, 안드로이드 링커가 받아들이는 ELF 구조를 기대한다. 링커 단계에서
멈추거나 죽는다. `termux-elf-cleaner`로 헤더를 고쳐 볼 가치는 있지만, 그 바이너리에
대해 고치고 다시 받기를 네 번 반복해도 결과는 같았다.

싼 길은 바이너리를 환경에 맞추는 대신 바이너리가 기대하는 환경을 주는 것이다.
`proot-distro`는 `ptrace`로 실제 배포판의 루트 파일 시스템을 Termux 안에서 돌린다.
루팅도, 커널 지원도 필요 없다.

```bash
proot-distro install ubuntu
proot-distro login ubuntu
```

프롬프트가 `root@localhost:~#`로 바뀌고 `/etc/os-release`는 Ubuntu 26.04 LTS라고
답한다. 이 `root`는 진짜 root가 아니다. 그 흉내가 무엇을 주고 무엇을 주지 않는지는
[`04-always-on.ko.md`](04-always-on.ko.md)에 있다.

## 1.5 인증서 번들을 가장 먼저 고친다

```bash
apt-get update
apt-get install --reinstall ca-certificates
```

`proot-distro`가 설치하는 rootfs는 최소 구성이라 패키지가 90개 남짓이고, CA 번들이
없거나 낡았다. 재설치하기 전까지는 모든 HTTPS 클라이언트가 인증서 검증에 실패하고,
오류 메시지는 내 신뢰 저장소가 아니라 상대 서버를 탓한다. 폰 리눅스에서 첫 한 시간에
가장 자주 만나는 실패다.

## 1.6 필요한 것만 설치한다

```bash
apt-get install -y python3 git curl hugo
python3 -V          # 이 폰에서는 3.14.6
hugo version        # apt가 준 0.154.5+extended
```

이 저장소의 서버들은 **파이썬 표준 라이브러리만** 쓴다. `pip install` 단계가 없고
갱신할 의존성도 없다. Hugo를 `apt`에서 받는 것도 의도다. 폰이 네트워크 없이도 사이트를
빌드할 수 있어야 하고, 배포판이 고정한 버전은 움직이는 부품을 하나 줄여 준다. Hugo
테마를 쓸 계획이라면 고르기 전에 테마의 `min_version`과 `apt` 버전을 맞춰 본다.

## 1.7 노트북에서 폰에 접속한다

폰 화면으로 셸 명령을 치는 일은 한 시간을 못 버틴다. **Termux** 쪽에서 `sshd`를
띄운다. 22번은 root가 필요하므로 포트는 8022다.

```bash
# 우분투 안이 아니라 Termux에서
passwd              # SSH용 비밀번호 설정
sshd
whoami              # 사용자 이름, 예: u0_a283
ip addr show wlan0 | grep 'inet '
```

노트북에서는 이렇게 붙는다.

```bash
ssh u0_a283@192.168.0.42 -p 8022
```

그다음 `proot-distro login ubuntu`로 우분투에 들어간다. SSH로 들어가는 곳은 항상
Termux이고 컨테이너가 아니다. 기억해 둘 만한데, VS Code의 Remote-SSH가 실패하는 이유가
정확히 이것이다([`05-private-access.ko.md`](05-private-access.ko.md)).

## 1.8 연결이 끊겨도 작업이 살아남게 한다

모바일 SSH 연결은 끊긴다. 오래 걸리는 작업은 `tmux` 안에서 시작하고, `tmux`는 컨테이너
안이 아니라 **Termux**에서 시작한다.

```bash
tmux new -s work
# ctrl-b d 로 분리, tmux attach -t work 로 복귀
```

`proot` 안에서 띄운 `tmux` 서버는 그 자체가 `proot`의 추적 대상이므로 로그인 세션과
함께 죽는다. 이 저장소의 `termux/claude-session.sh`가 그 규칙을 코드로 적어 둔 것이다.
자기가 추적당하고 있음을 감지하면 실행을 거부하고, Termux 쪽에서 세션을 만든 뒤 거기서
우분투로 로그인한다.

## 1.9 다음으로 넘어가기 전에 확인한다

| 확인 | 기대값 |
|:---|:---|
| 우분투에서 `uname -m` | `aarch64` |
| `cat /etc/os-release \| head -1` | `PRETTY_NAME="Ubuntu 26.04.1 LTS"` |
| `curl -sI https://github.com \| head -1` | `HTTP/2 200` — 실패하면 1.5를 다시 한다 |
| 노트북에서 `ssh u0_a283@<폰-IP> -p 8022` | Termux 프롬프트 |
| `free -h` | 총 3.7GiB 안팎, 스왑이 얼마간 쓰이고 있음 |

다음: HTTP로 무언가를 서비스한다 → [2. 웹 서버](02-web-server.ko.md)
