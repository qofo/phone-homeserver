# [서버 환경 상세 명세서 & 에이전트 인수인계 가이드]
# Server Environment Specification & Agent Handoff Guide

> **최종 갱신일**: 2026년 9월 25일  
> **문서 버전**: v2.5.0 (`/root` 정리: 문서는 `docs/`, 로그는 `logs/`)  
> **대상**: 이 환경에서 작업할 모든 후속 AI 에이전트 (Claude Code, Antigravity CLI 등)  
> **핵심 키워드**: `Samsung Galaxy Note FE`, `Termux`, `PRoot-Distro`, `Ubuntu 26.04 LTS`, `aarch64`, `No-Systemd`, `Tailscale`, `ngrok`, `Supervisor`

---

## 📌 1. 개요 (Executive Summary)

현재 작업 중인 서버는 AWS, GCP 등 일반적인 클라우드 x86 가상머신(VM)이 아닙니다.  
**스마트폰(Android) 공기계의 Termux 앱 내에서 `proot-distro`로 우분투(Ubuntu) 환경을 에뮬레이션하여 24시간 가동 중인 초경량 모바일 워크스테이션**입니다.

이 위에서 **기술 블로그 + 실시간 하드웨어 대시보드**(`serve_blog.py`, 포트 8080)가 돌고, **ngrok 고정 도메인**으로 외부에 공개됩니다. 두 서비스는 Termux 쪽에서 띄운 **감시 데몬**이 관리합니다(5장).

블로그는 Hugo 사이트(`/root/qofo.github.io`)이고, 같은 원본을 **폰과 GitHub Pages(`https://qofo.github.io/`) 두 곳**에서 서비스합니다. 폰은 자기가 빌드한 정적 파일을 보냅니다. **실시간 대시보드는 폰 사본에만 있습니다**(2026-09-20 결정). 공개 사이트를 여는 사람마다 폰을 호출하는 구조가 맞지 않아서, Pages 빌드에서는 대시보드 페이지와 홈의 수치 표시를 뺐습니다. 원본은 `content-phone/`에 있고 폰 빌드에서만 마운트됩니다(5장 관련 파일, 10장).

일반적인 리눅스 서버 상식(systemd, Docker, root 권한, 포트포워딩 등)이 그대로 적용되지 않으므로, **이 문서의 제약사항과 규칙**을 숙지한 상태에서 명령어를 실행해야 합니다.

---

## 📱 2. 하드웨어 및 호스트 스펙 (Hardware Specifications)

| 항목 | 상세 스펙 | 비고 및 에이전트 유의사항 |
|:---|:---|:---|
| **디바이스 모델** | **Samsung Galaxy Note Fan Edition (`SM-N935L`)** | 한국 LGU+ 출시 스마트폰 모델 |
| **모바일 AP (CPU)** | **Samsung Exynos 8890 Octa-Core** | 4x Exynos-M1 + 4x Cortex-A53. 안드로이드 핫플러그로 일부 코어(예: cpu6·7)가 꺼져 있을 수 있음 |
| **CPU 아키텍처** | **`aarch64` (ARM 64-bit)** | **외부 바이너리는 반드시 `arm64` / `aarch64` 빌드 사용** (x86_64 실행 불가) |
| **메모리 (RAM)** | **약 3.7GiB** + zRAM Swap 2GiB | 평소 스왑 사용량 약 1GiB. 대용량 빌드 시 OOM(LMK) 주의 |
| **스토리지 (Disk)** | **내장 UFS 2.0 (총 54GB, 가용 약 32GB)** | Android 데이터 파티션 위에 우분투 rootfs가 위치 |
| **전원 및 쿨링** | **상시 충전 전제, 팬리스(Fanless)** | ⚠️ 2026-09-17 확인 시 충전기 **미연결(방전 중)**. 전원 연결 상태를 확인할 것. 고부하 시 서멀 스로틀링 가능 |

---

## 🧱 3. 가상화 및 OS 레이어 (PRoot Architecture)

이 환경은 커널 레벨 가상화(KVM)나 컨테이너(Docker/LXC)가 아닌 **PRoot (User-space chroot/mount emulation via `ptrace`)** 기술로 구동됩니다.

```
┌───────────────────────────────────────────────────────────┐
│                    Samsung Android OS                     │
│               (Linux Kernel 3.18 / 6.17-PRoot)            │
├───────────────────────────────────────────────────────────┤
│   Termux App (User UID: aid_u0_aNNN)                      │
│   - sshd (포트 8022), Termux:Boot, Termux:API             │
│   - /root/termux/ensure-daemon.sh (서비스 런처)           │
│   ┌───────────────────────────────────────────────────┐   │
│   │         PRoot Engine (ptrace syscall hook)        │   │
│   │   ┌───────────────────────────────────────────┐   │   │
│   │   │      Ubuntu 26.04.1 LTS (Resolute)        │   │   │
│   │   │      - Fake root (uid=0)                  │   │   │
│   │   │      - Claude Code, Antigravity CLI(agy)  │   │   │
│   │   │      - 감시 데몬 (start_services.sh)      │   │   │
│   │   │      - Python 블로그 서버 + ngrok         │   │   │
│   │   └───────────────────────────────────────────┘   │   │
│   └───────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

### ⚠️ PRoot의 구조적 특징과 차이점
1. **Fake Root (가짜 root 권한)**
   - `whoami`는 `root`로 나오지만, 커널 관점에서는 안드로이드 앱 계정(`aid_u0_aNNN`)입니다.
   - 하드웨어 제어나 커널 권한(`CAP_SYS_ADMIN`, iptables, 커널 모듈)은 사용할 수 없습니다.
2. **No Systemd / No Init Daemon**
   - **`systemctl`, `service`, `journalctl`은 동작하지 않습니다.** 서비스 관리는 `/root/start_services.sh`로 합니다.
3. **`--kill-on-exit`: proot 세션이 끝나면 그 안의 프로세스가 모두 죽습니다**
   - `proot-distro login`은 proot를 `--kill-on-exit`로 실행합니다. 대화형 proot 로그인이나 에이전트 세션 안에서 `nohup ... &`로 띄운 프로세스는, 그 로그인 셸이 끝나는 순간 함께 종료됩니다.
   - 2026-09-17에 이 문제로 블로그와 ngrok이 꺼진 채 방치된 적이 있습니다. 상시 서비스는 반드시 Termux 쪽 런처로 띄웁니다(5장).
4. **가짜 `/proc` 파일**
   - `/proc/stat`, `/proc/uptime`, `/proc/loadavg`는 proot-distro가 넣은 **정적 파일**입니다. Android가 진짜 파일 접근을 막기 때문이며, proot 밖에서도 읽을 수 없습니다.
   - 따라서 `uptime`, `top`의 CPU%와 load 값은 의미가 없습니다.
   - 실제 값을 얻는 방법:
     - 가동 시간: `CLOCK_BOOTTIME`
     - 부하: `sysinfo(2)`
     - 코어별 사용률: `/sys/devices/system/cpu/cpu*/cpuidle/state*/time`
   - `serve_blog.py`의 대시보드는 이 방식으로 수집합니다.
5. **실행 파일 출처가 섞여 있음**
   - `python3`(3.14), `node`, `npm`, `curl`, `nano`, `clang`, `make`는 Ubuntu 패키지가 아니라 **Termux 바이너리**(`/data/data/com.termux/files/usr/bin`, PATH 맨 뒤)입니다.
   - Ubuntu 쪽은 패키지 약 90개의 최소 설치입니다. `git`은 2026-09-17에 apt로 설치했습니다.
6. **시간대가 다름**
   - Ubuntu 쪽은 **UTC**, Termux(안드로이드) 쪽은 **KST(UTC+9)**입니다.
   - `/root/logs/daemon.log`는 UTC로, Termux의 `~/boot_services.log`는 KST로 기록됩니다.
7. **`ptrace` 오버헤드**
   - 파일 I/O와 `fork`/`exec`가 네이티브보다 1.5~3배 느립니다. `npm install`처럼 작은 파일이 많은 작업은 특히 느립니다.
8. **Android Doze & 프로세스 수명**
   - 절전(Doze)이나 LMK(Low Memory Killer)로 프로세스가 불시에 종료될 수 있습니다. 부팅 스크립트가 `termux-wake-lock`을 잡고 있고, 서비스는 감시 데몬과 15분 주기 감시 작업으로 복구됩니다.

---

## 🌐 4. 네트워크 토폴로지 및 접속 환경 (Networking)

| 인터페이스 | IP 주소 | 네트워크 성격 | 사용 용도 |
|:---|:---|:---|:---|
| `lo` | `127.0.0.1` | 로컬 루프백 | 블로그 서버(8080), ngrok 관리 API(4040) |
| `wlan0` | `192.168.0.42` | 홈 Wi-Fi 사설망 | 같은 공유기 내 기기에서 접속 |
| `tun1` | `100.x.y.z` | **Tailscale VPN** (안드로이드 앱) | Tailscale 기기 간 암호화 통신, **내부 문서 서버(8081)** |
| `rmnet0~7` | 이동통신사 사설 IP | LTE / 5G | **CGNAT** 적용으로 직접 인바운드 불가 |

* **SSH 접속**: Termux의 `sshd`, 포트 **8022**, 공개키 인증만 허용(비밀번호 로그인 비활성).

### 🚀 외부 공개: ngrok 고정 도메인
* **공개 주소**: `https://daringly-marrow-penny.ngrok-free.dev` → `http://localhost:8080`
* **실행 옵션**: `ngrok http 8080 --url <도메인> --pooling-enabled` (설정: `/root/.config/ngrok/ngrok.yml`)
* **제약**: 무료 플랜이라 **브라우저 방문자에게 ngrok 경고 페이지(ERR_NGROK_6024)가 먼저** 표시됩니다. curl 등 비브라우저 요청은 바로 통과합니다.

### 🗄️ 폐기된 방식: Cloudflare Tunnel
* 처음에는 Cloudflare 임시 터널(`*.trycloudflare.com`)을 썼지만, 주소가 매번 바뀌어 ngrok으로 전환했습니다.
* 토큰 방식 원격 터널(ID는 생략)이 **ngrok 도메인(`blog.daringly-marrow-penny.ngrok-free.dev`)으로 잘못 설정된 채** Cloudflare 대시보드에 남아 있을 수 있습니다. 소유하지 않은 도메인이라 동작하지 않습니다.
* `/usr/local/bin/cloudflared` 바이너리와 `/root/logs/cloudflared.log`가 남아 있지만 실행하지 않습니다.

---

## 🛠️ 5. 서비스 구조 (Supervisor Architecture)

### 실행 경로
```
Termux:Boot (부팅 시) ──────────┐
Termux ~/.bashrc (로그인마다) ──┤
감시 작업 4241 (15분 주기) ─────┼─▶ /root/termux/ensure-daemon.sh   ← Termux 쪽, proot 밖
start_services.sh start ────────┘      PID 파일로 실행 여부 확인
  (작업 4242로 요청)                   없으면 setsid로 터미널과 분리해 실행
                                              │
                                              ▼
                      proot-distro login ubuntu -- /root/start_services.sh start-daemon
                        · flock으로 단일 실행 보장
                        · ngrok 기동 전 네트워크 준비 여부 확인
                        · 10초마다 프로세스 생존 및 능동 헬스체크(포트 8080/4040)
                        · 응답 불가(먹통) 프로세스 자동 감지 및 강제 재기동
                        · 연속 크래시 시 재시작 대기 10초 → 최대 5분
                        · 로그 10MB 초과 시 순환
                                              │
                        ├─▶ python3 -u /root/serve_blog.py   (0.0.0.0:8080)
                        └─▶ ngrok http 8080 --url … --pooling-enabled
```

* 감시 데몬과 두 서비스는 **제어 터미널이 없는 독립 세션**에서 돕니다. 따라서 SSH 터미널의 Ctrl+C나 로그아웃이 전달되지 않습니다.
* `termux-job-scheduler`로 예약한 스크립트는 Termux 앱 프로세스에서 실행됩니다. 그래서 proot 안(에이전트 세션 포함)에서도 세션에 묶이지 않는 데몬을 띄울 수 있습니다. 단, 인터넷 연결이 있어야 작업이 실행됩니다.

### 관련 파일
| 경로 | 역할 |
|:---|:---|
| `/root/start_services.sh` | 서비스 관리 명령 + 감시 데몬 본체 |
| `/root/termux/ensure-daemon.sh` | Termux 쪽 런처. Termux에서 보이는 경로: `/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/termux/ensure-daemon.sh` |
| `/root/termux/claude-session.sh` | Termux 셸의 `claude-session` 별칭. Termux 쪽 tmux(3.7c) 세션에서 Claude Code를 실행해 SSH 종료 후에도 작업 유지 |
| Termux `~/.termux/boot/start-server.sh` | 부팅 시 wake-lock, sshd, 런처 실행, 감시 작업 4241 등록 |
| Termux `~/.bashrc` | Termux 로그인마다 런처 실행 (데몬이 있으면 아무것도 안 함) |
| `/root/.bashrc` | 대화형 proot 로그인 시 `start_services.sh login-check` |
| `/root/serve_blog.py` | `/root/blog_public`의 정적 파일(Hugo 빌드) + `/api/metrics`(CORS 허용, preflight 응답). 멀티스레드, 요청 타임아웃 30초. 빌드가 없으면 `/`에 200 안내 페이지 |
| `/root/publish_blog.sh` | 폰용 빌드와 교체(`phone`), Pages용 빌드를 로컬 `gh-pages`에 커밋(`pages`), 둘 다 빌드하고 `main`·`gh-pages`를 함께 push(`publish`), 상태(`status`) |
| `/root/blog_public` → `/root/blog_builds/<UTC시각>` | 폰이 서비스하는 빌드. 심볼릭 링크를 rename으로 바꿔 무중단 교체, 최근 3개 보관 |
| `/root/qofo.github.io/content/posts/*.md` | 블로그 글 원본 (현재 8편). `/posts`는 Hugo 전환 전 기록으로만 남아 있음 |
| `/root/.start_services.pid`, `.start_services.lock` | 데몬 PID 파일과 단일 실행용 lock |
| `/root/.services_disabled` | `stop` 시 생성. 있으면 어떤 경로로도 자동 시작하지 않음 |
| `/root/.restart_requested` | `restart` 플래그 파일. 데몬이 감시 루프에서 확인 후 서비스 교체 |
| `/root/logs/downtime.log` | 서비스 비가용(다운타임) 시간 영구 누적 로그 |
| `/root/.downtime_start`, `.last_downtime`, `.service_heartbeat` | 다운타임 측정용 상태 파일 및 감시 데몬 하트비트 |
| `/root/measure_downtime.py` | 재부팅/재시작 전후 서브세컨드(0.5초) 정밀 가용성 측정 프로브 도구 |
| `/root/logs/daemon.log` (UTC), `blog_server.log`, `ngrok.log` | 로그 (10MB 초과 시 `.1`로 순환) |
| Termux `~/boot_services.log` (KST) | 런처 실행 기록 |

### 관리 명령 (`/root/start_services.sh <명령>`)
| 명령 | 동작 |
|:---|:---|
| `status` | 감시 데몬·블로그·ngrok 상태, 자동 시작 여부, 최근 다운타임 시간(`Last Downtime`) 및 현재 중단 여부 표시 |
| `downtime` | 누적된 서비스 다운타임(비가용 시간) 전체 이력 및 현재 진행 중인 중단 지속 시간 출력 |
| `restart` | 플래그 파일(`.restart_requested`) 생성 → 감시 데몬이 블로그·ngrok 재시작 (**코드 수정 반영은 이것으로**) |
| `stop` | 데몬·서비스 종료 + 자동 시작 비활성화 (부팅·로그인·감시 작업도 다시 띄우지 않음) |
| `start` | 자동 시작 재개. 데몬이 없으면 Termux에 런처 실행을 요청하고 최대 60초 대기 |
| `start-daemon` | 감시 데몬 본체. **직접 실행하지 말 것** (런처가 실행) |
| `login-check` | `/root/.bashrc`용 확인 명령 |

### 내부 문서 서버 (Tailscale 전용, 포트 8081)
기획·계획 문서를 **Tailscale 망 안에서만** 웹으로 보는 마크다운 뷰어입니다. 공개 블로그와는 **프로세스·감시 데몬·런처·감시 작업을 모두 따로** 둡니다. 그래서 이쪽을 멈추거나 고쳐도 블로그와 ngrok에는 영향이 없습니다.

* **주소**: `http://100.x.y.z:8081/` (Tailscale에 연결된 기기에서만 열림)
* **실행 경로**: Termux:Boot / 감시 작업 **4243**(15분) / `private_docs.sh start`(작업 **4244**) → `/root/termux/ensure-private-docs.sh` → `proot-distro login ubuntu -- /root/private_docs.sh start-daemon` → `python3 -u /root/private_docs_server.py`
* **감시 데몬**: `start_services.sh`와 같은 방식입니다(flock 단일 실행, 10초 주기, 30초 유예 후 `/healthz` 능동 점검 3회 실패 시 강제 재기동, 재시작 대기 10초→최대 5분, 재시작은 플래그 파일). 서버 종료 코드 **3**(Tailscale 주소 변경)은 즉시 재기동하고, **2**(허용되지 않은 주소라 바인딩 거부)는 5분 뒤 재시도합니다.

| 방어 층 | 내용 |
|:---|:---|
| 바인딩 주소 | Tailscale IPv4(100.64.0.0/10)에만 바인딩합니다. `0.0.0.0`·LAN·공인 IP는 실행 자체를 거부(종료 코드 2)합니다. 그래서 LAN, `127.0.0.1`, ngrok(8080만 전달) 경로로는 연결이 거부됩니다. |
| VPN 상태 | 부팅 직후 Tailscale이 아직 없으면 `waiting` 상태로 대기하다가 주소가 생기면 바인딩합니다. VPN이 꺼지면 `offline`으로 표시하고, 주소가 바뀌면 종료 코드 3으로 재바인딩합니다. |
| 접속자 IP | 요청마다 peer IP가 tailnet 대역(100.64.0.0/10, fd7a:115c:a1e0::/48)인지 확인하고, 아니면 403을 돌려줍니다. |
| Host 헤더 | tailnet IP, `*.ts.net`, 점 없는 MagicDNS 이름만 허용합니다(DNS 리바인딩 방어). |
| 문서 허용 목록 | `/root/private_docs.list`에 적힌 `.md` 파일만 보입니다. 경로 조작, 숨김 파일, 목록 밖 파일은 404입니다. 목록 변경은 재시작 없이 반영됩니다. |
| 브라우저 | 엄격한 CSP(`script-src 'self'`, 외부 이미지 불가), `nosniff`, `no-store`, `noindex`를 적용하고 CORS는 허용하지 않습니다. 마크다운은 브라우저에서 marked로 변환한 뒤 DOMPurify로 정화하고 원격 이미지를 제거합니다. 라이브러리는 SRI 해시를 검증해 `private_docs_static/`에 두었습니다. |

| 경로 | 역할 |
|:---|:---|
| `/root/private_docs_server.py` | 서버 본체 (표준 라이브러리만 사용) |
| `/root/private_docs.sh` | 관리 명령 + 감시 데몬 (`start`/`stop`/`restart`/`status`) |
| `/root/termux/ensure-private-docs.sh` | Termux 쪽 런처 (`ensure-daemon.sh`와 별개) |
| `/root/private_docs.list` | 공개할 문서 허용 목록 |
| `/root/private_docs_static/` | 뷰어 JS/CSS, marked 18.0.13, DOMPurify 3.4.15 |
| `/root/tests/test_private_docs.py` | 블랙박스 보안 테스트 47개 (`python3 /root/tests/test_private_docs.py`) |
| `/root/termux/battery-watch.sh` | 배터리 관리(감시 작업 4247, 15분 주기). 충전기가 **Tapo P100 스마트 플러그**에 물려 있어서, 충전 중 80% 이상이면 플러그를 끄고 방전 중 40% 이하면 켭니다(2026-09-27부터). 성공 여부는 플러그의 응답이 아니라 **폰의 충전 상태**로 판단합니다. 플러그로 바꾸지 못했을 때만 예전 알림(80% "빼세요", 30% "꽂으세요"+진동)을 보냅니다. 매 실행마다 `/root/logs/battery_watch.log`에 잔량·상태·온도·전류·전압과 플러그 조작 결과를 기록합니다 |
| `/root/tapo_plug.py` | 플러그 제어(`status`/`on`/`off`). python-kasa 0.10.2(`/root/.local/share/tapo-venv`, 우분투 python3 venv)로 KLAP 통신. 계정은 `/root/.config/tapo/credentials`(600, **출력 금지**), 주소는 `/root/.config/tapo/host`. 플러그가 패킷을 약 15% 잃어서 짧은 타임아웃과 재시도를 쓰고, 연결을 재사용하지 않습니다 |
| `/root/logs/private_docs.log` (KST) | 서버·감시 데몬 로그 (2MB 초과 시 `.1`로 순환). 일반 열람은 기록하지 않고 거부(`[DENY]`)만 남깁니다. |
| `/root/.private_docs.state`, `.private_docs.pid`, `.private_docs.lock` | 서버 상태(`listening`/`waiting`/`offline`), 감시 데몬 PID, lock |
| `/root/.private_docs_disabled`, `.private_docs_restart` | `stop` 시 생성되는 자동 시작 중지 플래그, `restart` 플래그 |


### code-server (브라우저용 VS Code, Tailscale 전용, 포트 8443)
폰의 파일을 브라우저에서 VS Code로 편집하는 환경입니다. 사용 방법과 인증서 등록은 **`/root/docs/CODE_SERVER_GUIDE.md`**(내부 문서 서버에도 있음)를 보십시오. 블로그·문서 서버와 **감시 데몬·런처·감시 작업을 모두 따로** 둡니다.

* **왜 Remote-SSH가 아닌가**: VS Code Remote-SSH는 Termux의 sshd(8022)로 들어가는데, Termux는 bionic libc라 VS Code Server가 요구하는 glibc/libstdc++가 없습니다(`~/.vscode-server/.cli.*.log`: `does not meet Visual Studio Code Server's prerequisites`). code-server는 glibc가 있는 proot 우분투 안에서 돕니다.
* **주소**: `https://<this-device>.<tailnet>.ts.net:8443/` 또는 `https://100.x.y.z:8443/` (Tailscale 전용, 비밀번호 로그인). 서버 인증서에 IP와 MagicDNS 이름이 모두 들어 있습니다.
* **설치**: `/root/.local/lib/code-server-4.137.0-linux-arm64` (심볼릭 링크 `/root/.local/lib/code-server`), GitHub 릴리스 SHA-256 검증 후 설치. 사용자 데이터·확장은 `/root/.local/share/code-server/`
* **실행 경로**: Termux:Boot / 감시 작업 **4245**(15분) / `code_server.sh start`(작업 **4246**) → `/root/termux/ensure-code-server.sh` → `proot-distro login ubuntu -- /root/code_server.sh start-daemon` → `code-server --bind-addr <Tailscale IP>:8443 --cert … /root`
* **감시 데몬**: 15초 주기, 90초 유예 후 `https://<IP>:8443/healthz`를 **우리 CA로 검증하며** 점검, 3회 실패 시 강제 재기동, 재시작 대기 15초→최대 5분, 재시작은 플래그 파일. Tailscale 주소는 감시 데몬이 직접 찾고(SIOCGIFADDR), 없으면 `waiting`, 바뀌면 인증서를 다시 발급해 재기동합니다.
* **메모리**: 대기 중 약 150MB(래퍼 + 서버 두 프로세스). 브라우저가 붙으면 확장 호스트만큼 늘어납니다. 메모리가 필요하면 `code_server.sh stop`.

| 방어 층 | 내용 |
|:---|:---|
| 바인딩 주소 | Tailscale IPv4에만 바인딩합니다. `127.0.0.1`·LAN으로는 연결이 거부되고, ngrok은 8080만 전달하므로 인터넷에 노출되지 않습니다. |
| TLS | 폰에서 만든 개인 CA(`/root/.config/code-server/tls/ca.crt`, 2036년까지)가 서버 인증서(397일, 만료 30일 전 자동 갱신)를 발급합니다. CA에는 **이름 제약**(100.64.0.0/10, fd7a:115c:a1e0::/48, `ts.net`)이 걸려 있어 다른 사이트용 인증서는 검증에 실패합니다. |
| 인증 | code-server 비밀번호(`/root/.config/code-server/config.yaml`, 권한 600). 로그인 시도는 분당 2회·시간당 12회로 제한됩니다. |
| WebSocket | 로그인 없으면 401, 다른 출처(Origin)면 403입니다. |

| 경로 | 역할 |
|:---|:---|
| `/root/code_server.sh` | 관리 명령 + 감시 데몬 (`start`/`stop`/`restart`/`status`) + 인증서 발급·갱신 |
| `/root/termux/ensure-code-server.sh` | Termux 쪽 런처 |
| `/root/.config/code-server/config.yaml` | 비밀번호 등 설정. **내용을 출력하지 말 것** |
| `/root/.config/code-server/tls/` | `ca.key`·`server.key`(600, 비밀), `ca.crt`(사용자 기기에 등록), `server.crt` |
| `/root/.local/share/code-server/User/settings.json` | 캐시·설치 폴더를 파일 감시·검색에서 제외(아래 inotify 항목), 텔레메트리·자동 업데이트 끔 |
| `/root/logs/code_server.log` (KST + code-server 자체 로그) | 2MB 초과 시 `.1`로 순환 |
| `/root/.code_server.state`, `.code_server.pid`, `.code_server.lock` | 상태(`listening`/`waiting`/`offline`), 감시 데몬 PID, lock |
| `/root/.code_server_disabled`, `.code_server_restart` | 자동 시작 중지 플래그, `restart` 플래그 |

---

## ⚠️ 6. 후속 에이전트가 절대 피해야 할 실수 (Agent Don'ts & Gotchas)

1. ❌ **`systemctl` / `service` 사용 금지** → `/root/start_services.sh`를 사용하십시오.
2. ❌ **proot 안에서 `nohup python3 … &`로 서비스를 직접 띄우지 말 것**
   - 세션이 끝나면 함께 죽고, 감시 데몬과 충돌합니다.
   - 대신 `start_services.sh restart`(코드 반영)나 `start`(데몬 기동)를 사용하십시오.
3. ❌ **`pkill -f` / `pgrep -f` 패턴을 느슨하게 쓰지 말 것**
   - `pkill -f serve_blog`처럼 쓰면 그 문자열이 들어간 **자기 셸 명령줄**까지 일치해서 스스로를 종료시키거나 오탐합니다.
   - `'^python3 (-u )?/root/serve_blog\.py'`처럼 `^`로 시작을 고정하십시오.
4. ❌ **`docker` / `podman` 설치 및 구동 금지** (cgroups/namespaces 미지원)
5. ❌ **1024 이하 특권 포트 바인딩 지양** → 8080, 3000 같은 하이 포트를 사용하십시오.
6. ❌ **과도한 병렬 빌드 금지** → `-j2` 이하로 제한하십시오(LMK에 의한 SIGKILL 위험).
7. ❌ **x86_64 바이너리 다운로드 금지** → `aarch64` / `arm64` 빌드만 사용하십시오.
8. ❌ **비밀 파일 내용 출력 금지**
   - `/root/.config/ngrok/ngrok.yml` (authtoken)
   - `~/.gemini/antigravity-cli/antigravity-oauth-token`
   - `~/.claude/.credentials.json`
   - Termux `~/.termux_authinfo`
9. ⚠️ **CA 인증서 문제**: TLS 인증서 오류가 나면 `apt-get install --reinstall ca-certificates`를 실행하십시오.
10. ⚠️ **코드 수정 절차**: 수정 → `git -C /root diff`로 확인 → 커밋 → `start_services.sh restart` 순서를 지키십시오.
11. ❌ **내부 문서 서버나 code-server를 `0.0.0.0`에 바인딩하거나, ngrok에 연결하거나, `serve_blog.py`·`start_services.sh`에 합치지 말 것** (code-server는 폰 전체의 셸입니다)
    - 8080은 ngrok으로 인터넷에 공개됩니다. 비공개 문서는 반드시 별도 프로세스가 Tailscale 주소(8081)에서만 제공해야 합니다.
    - 문서를 추가할 때는 `/root/private_docs.list`에 한 줄을 넣기만 하면 됩니다(블로그 저장소 `qofo.github.io`에 넣으면 공개됩니다).

---

## 🤖 7. 에이전트 도구 설정

### Antigravity CLI (`agy` 1.2.5)
* 설정 파일: `/root/.gemini/antigravity-cli/settings.json`
  * 모든 도구 자동 승인 (`command(*)`, `read_file(*)`, `write_file(*)`, `read_url(*)`, `execute_url(*)`)
  * 신뢰 작업공간: `/`, `/root`
  * 기본 모델: Gemini 3.8 Flash (High)
* 비대화형 실행: `agy -p "<프롬프트>"`. 읽기 전용 작업은 `--mode plan`을 함께 사용합니다.
* ⚠️ URL 읽기·실행까지 자동 승인되므로 프롬프트 인젝션에 취약한 구성입니다. 신뢰할 수 없는 웹 콘텐츠를 다룰 때 주의하십시오.

### Claude Code (2.1.274)
* 실행 파일: `/root/.local/bin/claude`
* 설정: `/root/.claude/settings.json`
* 메모리: `/root/.claude/projects/-root/memory/`

---

## 🗃️ 8. 버전 관리 & 백업

| 대상 | 방식 |
|:---|:---|
| `/root` | git 저장소. 허용 목록 `.gitignore`로 **서버 파일과 `docs/`의 운영 문서만 추적**하고, 자격 증명·캐시·에이전트 상태·로그·비공개 기획 문서는 제외 |
| `/root/qofo.github.io` | 블로그 git 저장소. 원격 `github.com/qofo/qofo.github.io`(공개). `main` = 원본, `gh-pages` = Pages가 서비스하는 빌드 결과(Pages 소스: `gh-pages` 브랜치 루트) |
| `/posts` | Hugo 전환 전의 글 저장소. 로컬 기록용이며 **원격을 붙이거나 push하지 않습니다**(옛 커밋에 개인 네트워크 정보가 있음) |
| 2026-09-17 개편 전 원본 | `/root/backups/pre-improve-20260917.tar.gz` (Termux 쪽 훅 포함) |

* **디렉터리 구성 (2026-09-25 정리)**: 서비스 코드는 `/root` 바로 아래에 둡니다(Termux 쪽 부팅 스크립트와 감시 작업이 이 경로를 직접 씁니다). 운영 문서는 `/root/docs/`, 로그는 `/root/logs/`, 가리기 전 원본 스크린샷은 `/root/screenshots/`에 있습니다.
* 블로그 글은 GitHub(`qofo/qofo.github.io`)가 기기 밖 사본입니다. 서버 코드는 `qofo/phone-homeserver`에 마스킹한 사본을 둡니다.
* ⚠️ 그 밖의 파일(로그, 자격 증명, 설정)은 **기기 밖 백업이 없습니다.** 필요하면 폰에서 `termux-setup-storage`를 실행해 저장소 권한을 허용하십시오.
* 현재 `/storage/emulated/0`은 권한 거부 상태라 `cp … /storage/emulated/0/Download/`는 실패합니다.

---

## 📋 9. 에이전트 퀵 레퍼런스 (Cheat Sheet)

| 목적 | 권장 명령어 |
|:---|:---|
| **서비스 상태 확인** | `/root/start_services.sh status` |
| **다운타임(비가용 시간) 확인** | `/root/start_services.sh downtime` |
| **정밀 다운타임 측정 프로브** | `python3 /root/measure_downtime.py --once` |
| **코드 수정 반영** | `/root/start_services.sh restart` |
| **유지보수로 끄기 / 다시 켜기** | `/root/start_services.sh stop` / `start` |
| **로그 확인** | `tail -f /root/logs/daemon.log /root/logs/ngrok.log` |
| **터널 공개 주소 확인** | `curl -s localhost:4040/api/tunnels` |
| **감시 작업 확인** | `termux-job-scheduler --pending` (4241 = 블로그, 4243 = 내부 문서 서버, 4245 = code-server, 4247 = 배터리 알림, 모두 15분 주기) |
| **배터리 기록 보기** | `tail /root/logs/battery_watch.log` (잔량·전류·전압. 방전 구간의 `mA`×`mV`가 실제 소비 전력입니다) |
| **code-server 상태** | `/root/code_server.sh status` (주소: `https://100.x.y.z:8443/`, Tailscale 전용, 안내: `CODE_SERVER_GUIDE.md`) |
| **내부 문서 서버 상태** | `/root/private_docs.sh status` (주소: `http://100.x.y.z:8081/`, Tailscale 전용) |
| **내부 문서 추가/제외** | `/root/private_docs.list`에 파일 경로를 한 줄 추가/삭제 (재시작 불필요) |
| **실제 CPU·가동 시간·부하** | `curl -s localhost:8080/api/metrics` |
| **패키지 설치** | `apt-get update && apt-get install -y <패키지명>` (sudo 불필요) |
| **메모리/스토리지 점검** | `free -m && df -h /` |
| **Tailscale IP** | `100.x.y.z` |
| **블로그 새 글 추가** | `/root/qofo.github.io/content/posts/09-<slug>.md` 작성(앞 글의 front matter 참고) → 커밋 → `/root/publish_blog.sh publish` (두 사본을 같은 커밋으로 빌드, 폰 교체, `main`·`gh-pages` 동시 push → GitHub가 1분 안에 Pages 갱신) |
| **폰에서만 미리 보기** | `/root/publish_blog.sh phone` (커밋 안 한 변경도 빌드, 재시작 불필요) |
| **블로그 배포 상태** | `/root/publish_blog.sh status`, `gh api repos/qofo/qofo.github.io/pages/builds/latest --jq .status` |
| **블로그 서버 시험** | `python3 /root/tests/test_serve_blog.py` (35개) |

---

## 🚧 10. 알려진 한계

* ngrok 무료 플랜의 브라우저 경고 페이지는 로컬 설정으로 없앨 수 없습니다. 유료 플랜이나 자체 도메인(Cloudflare Named Tunnel 등)이 필요합니다.
  * 대시보드를 폰 사본으로 한정한 뒤로 공개 사이트가 폰을 호출하는 경로는 없습니다. `serve_blog.py`의 CORS 헤더와 OPTIONS 응답은 남겨 두었습니다(시험이 지키는 동작이고, 다른 곳에서 수치를 쓸 여지를 남겼습니다).
  * ngrok 무료 플랜은 요청 수를 셉니다(월 20,000건). 폰 주소로 들어와 대시보드를 열면 3초마다 요청이 나가므로, 오래 열어 두지 마십시오(`config/phone/hugo.toml`의 `pollHome`, `pollDashboard`).
* 폰의 Ubuntu에는 tzdata가 없어서 Hugo 설정에 `timeZone`을 넣으면 폰 빌드가 실패합니다.
* Pages 빌드는 GitHub Actions가 아니라 폰에서 합니다. git이 쓰는 토큰(classic, `repo` 권한)에 `workflow` 권한이 없어 `.github/workflows/`를 push할 수 없기 때문입니다. 그래서 GitHub 웹에서 글을 고치면 Pages에 반영되지 않고, 폰에서 `publish_blog.sh publish`를 실행해야 합니다.
* 15분 주기 감시 작업은 Doze 중에 지연될 수 있습니다. Termux와 Termux:API 앱의 **배터리 최적화 해제**를 권장합니다.
* 감시 작업(4241)과 기동 요청(4242)은 인터넷 연결이 확인된 상태에서만 실행됩니다.
* 블로그 5편의 코드 예시는 v1 구조(`pgrep -f "serve_blog.py"` 기반 자동 시작) 기준이라 현재 구현과 다릅니다.
* 내부 문서 서버는 HTTP입니다. 전송 구간은 Tailscale(WireGuard)이 암호화하지만, 브라우저에는 "안전하지 않음"으로 표시됩니다. 이 기기에는 안드로이드 Tailscale 앱만 있고 `tailscale` CLI(`serve`/`cert`)가 없어서, HTTPS 인증서는 붙이지 않았습니다.
* proot 안의 프로세스는 proot가 ptrace로 추적하므로 `kill -STOP`이 먹지 않습니다(추적자가 정지 신호를 삼킴). 먹통 감지 시험은 응답하지 않는 가짜 서버로 해야 합니다.
