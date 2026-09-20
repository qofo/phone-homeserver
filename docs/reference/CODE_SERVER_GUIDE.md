# code-server 사용 안내 (브라우저에서 쓰는 VS Code)

> **작성일**: 2026년 9월 20일  
> **대상**: 이 폰 서버의 주인, 후속 AI 에이전트  
> **관련 문서**: `SERVER_ENVIRONMENT_SPEC.md` 5장, `AI_HANDOFF_NOTES.md` 10절

---

## 1. 한눈에 보기

| 항목 | 값 |
|:---|:---|
| 주소 | **`https://<this-device>.<tailnet>.ts.net:8443/`** 또는 `https://100.x.y.z:8443/` (Tailscale에 연결된 기기에서만 열림) |
| 로그인 | 비밀번호 (아래 3절) |
| 열리는 폴더 | `/root` (블로그 원본은 `/root/qofo.github.io`) |
| 터미널 | 편집기 안의 터미널(`` Ctrl+` ``)은 **proot 우분투의 bash**입니다 |
| 버전 | code-server 4.137.0 (VS Code 1.137.0) |
| 확장 마켓 | Open VSX (Microsoft 마켓이 아님) |
| 메모리 | 대기 중 약 150MB. 편집기를 열면 확장 호스트만큼 늘어남 |

## 2. 왜 VS Code Remote-SSH가 안 됐는가

VS Code의 Remote-SSH로 폰(Termux의 sshd, 8022 포트)에 접속하면 폰에 남은 로그가 이렇습니다.

```
error This machine does not meet Visual Studio Code Server's prerequisites, expected either...
  - find libstdc++.so or ldconfig for GNU environments
  - find /lib/ld-musl-aarch64.so.1, which is required to run the Visual Studio Code Server in musl environments
```

SSH로 들어간 곳은 우분투가 아니라 **Termux 자체**입니다. Termux는 안드로이드의 C 라이브러리(bionic) 위에서 돌기 때문에, glibc나 musl을 요구하는 VS Code Server가 설치되지 않습니다. 우분투(proot) 안에는 glibc 2.43과 libstdc++가 있으므로, 그 안에서 code-server를 돌리고 브라우저로 접속하는 방식을 택했습니다.

## 3. 비밀번호

비밀번호는 `/root/.config/code-server/config.yaml`의 `password:` 줄에 있습니다(무작위 24자, 파일 권한 600). 우분투 셸에서 확인합니다.

```bash
grep '^password:' /root/.config/code-server/config.yaml
```

바꾸려면 그 줄을 고친 뒤 `/root/code_server.sh restart`를 실행합니다. 로그인 시도는 code-server가 분당 2회, 시간당 12회로 제한합니다.

## 4. 처음 접속하기: 인증서 신뢰 설정 (기기마다 한 번)

이 서버는 **폰 안에서 만든 개인 인증 기관(CA)**의 인증서로 HTTPS를 씁니다. 이 CA를 기기에 등록하지 않으면 브라우저가 "연결이 비공개로 설정되어 있지 않습니다" 경고를 띄웁니다. 경고를 넘기면 편집 자체는 되지만, 다음 기능이 동작하지 않습니다.

- 마크다운 미리보기, 확장 소개 페이지 같은 **웹뷰** (서비스 워커가 필요한데, 인증서 오류가 있는 출처에서는 등록되지 않음)
- 우클릭 메뉴의 붙여넣기 같은 **클립보드 API**
- **앱으로 설치(PWA)** 

그래서 CA를 한 번 등록하는 것을 권합니다.

### 이 CA는 안전한가

CA 인증서에는 **이름 제약(Name Constraints)**이 걸려 있습니다. 이 CA가 보증할 수 있는 대상은 Tailscale 주소(`100.64.0.0/10`, `fd7a:115c:a1e0::/48`)와 `*.ts.net` 이름뿐입니다. 키가 새어 나가더라도 은행이나 포털 같은 다른 사이트를 흉내 내는 인증서는 만들 수 없습니다. 발급해서 검증해 본 결과입니다.

| 인증서에 적은 이름 | 검증 결과 |
|:---|:---|
| `IP:100.x.y.z` (이 폰의 Tailscale 주소) | 통과 |
| `DNS:<this-device>.<tailnet>.ts.net` (이 폰의 MagicDNS 이름) | 통과 |
| `DNS:phone.tail1234.ts.net` | 통과 |
| `IP:192.168.0.42` (LAN 주소) | **거부** |
| `DNS:example.com` | **거부** |

등록하기 전에 지문이 아래와 같은지 확인합니다.

```
CA: O=phone-homeserver, CN=code-server local CA (<만든 날짜>)   유효기간 10년
SHA-256 <code_server.sh status가 보여 주는 값>
```

### ① CA 파일 받기

1. 브라우저로 `https://<this-device>.<tailnet>.ts.net:8443/`을 엽니다. 경고가 뜨면 "고급 → 계속"으로 넘어갑니다(이 한 번만).
2. 비밀번호로 로그인합니다.
3. 왼쪽 탐색기에서 `.config/code-server/tls/ca.crt`를 **우클릭 → 다운로드**합니다.
   - `ca.key`, `server.key`는 **받지 않습니다.** 비밀 키입니다.

### ② 기기에 등록하기

**Windows (Chrome, Edge)**
1. 받은 `ca.crt`를 더블클릭 → **인증서 설치**
2. 저장소 위치: **현재 사용자** → "모든 인증서를 다음 저장소에 저장" → **신뢰할 수 있는 루트 인증 기관**
3. 보안 경고에서 지문이 위 값과 같은지 확인하고 **예**
4. 브라우저를 완전히 닫았다가 다시 엽니다.

Firefox는 자체 저장소를 씁니다: 설정 → 개인정보 및 보안 → 인증서 보기 → 인증 기관 → 가져오기 → "웹 사이트 식별" 체크.

**Android (Chrome)**
1. 설정 → 보안(생체 인식 및 보안) → 기타 보안 설정 → **기기에 저장된 인증서 설치**(기기마다 이름이 조금 다름) → **CA 인증서**
2. 경고를 확인하고 다운로드 폴더의 `ca.crt`를 고릅니다.
3. Chrome을 다시 엽니다.

**macOS / iPhone**
- macOS: `ca.crt`를 키체인 접근에 추가 → 인증서 정보 → 신뢰 → "항상 신뢰"
- iPhone: 파일을 열어 프로파일 설치 → 설정 → 일반 → 정보 → 인증서 신뢰 설정에서 켜기

### ③ 확인

주소창에 경고 없이 자물쇠가 보이면 끝입니다. 이후에는 Chrome/Edge 메뉴의 **"앱 설치"**(Android는 "홈 화면에 추가")로 설치하면 브라우저 탭이 아니라 별도 창으로 열립니다. 이렇게 쓰면 `Ctrl+W`, `Ctrl+N` 같은 단축키를 브라우저가 가로채지 않고 VS Code가 받습니다.

## 5. 쓰는 방법

- **블로그 글 쓰기**: `qofo.github.io/content/posts/`에서 글을 고치고, 마크다운 미리보기(`Ctrl+Shift+V`)로 확인한 뒤, 소스 제어 탭에서 커밋합니다. 발행은 터미널에서 `/root/publish_blog.sh publish`를 실행합니다.
- **폰 사본 미리보기**: 터미널에서 `/root/publish_blog.sh phone` 실행 후 `https://100.x.y.z:8443/proxy/8080/`을 엽니다. code-server가 로그인한 사용자에게만 폰 안의 포트를 중계합니다.
- **서버 스크립트 수정**: `/root`의 `*.sh`, `*.py`. 고친 뒤의 배포 절차는 `AI_HANDOFF_NOTES.md` 1절 규칙을 따릅니다.
- **확장 설치**: 확장 탭에서 검색해 설치합니다. Open VSX에 없는 Microsoft 전용 확장(Pylance, Remote 계열, Copilot 등)은 설치할 수 없습니다. 확장마다 메모리를 쓰므로 필요한 것만 설치합니다.

## 6. 설정해 둔 것

`/root/.local/share/code-server/User/settings.json`

- `/root`의 폴더는 약 3400개이고 대부분 캐시와 설치 파일(`.local` 1237개, `.gemini` 835개, `.npm` 443개 등)입니다. 파일 감시와 검색에서 뺐고, 빼고 나면 약 30개가 남습니다.
  - proot 안에서 보이는 inotify 한도(`/proc/sys/fs/inotify/max_user_watches`의 4096)는 **proot-distro가 붙인 가짜 파일**입니다. `sysctl`로 고쳐도 그 파일만 바뀝니다. 실제 여유는 `inotify_add_watch`로 재서 5862개였습니다(다른 프로세스가 쓰는 몫은 제외한 값).
- 텔레메트리, 업데이트 확인, git 자동 fetch를 껐습니다.
- 로그인한 사람만 쓰는 편집기이므로 "제한 모드(Workspace Trust)" 확인 창을 껐습니다.

편집 습관에 관한 설정(글꼴, 테마, 줄 끝 공백 처리 등)은 건드리지 않았습니다.

## 7. 보안 구조

| 층 | 내용 | 확인 결과 (2026-09-20) |
|:---|:---|:---|
| 바인딩 | Tailscale 주소에만 바인딩 | `127.0.0.1:8443`, LAN:8443 → 연결 거부 (curl exit 7) |
| 공개 터널 | ngrok은 8080만 전달 | 8443은 인터넷에 노출되지 않음 |
| TLS | 이름 제약 CA의 인증서 | CA 없이 접속 → curl exit 60 (인증서 불신) |
| 비밀번호 | 로그인 전에는 편집기·포트 중계 모두 차단 | `/`, `/proxy/8080/` → 302 `/login` |
| WebSocket | 로그인·출처 검사 | 로그인+같은 출처 101, 로그인 없음 401, 다른 출처 403 |

DNS 리바인딩(남의 웹페이지가 내 브라우저를 통해 tailnet 주소로 요청하는 공격)은 두 겹으로 막힙니다. 인증서가 IP 주소에만 발급돼 있어서 다른 도메인 이름으로는 TLS가 성립하지 않고, WebSocket은 출처가 다르면 403입니다.

⚠️ **code-server는 폰의 모든 파일과 셸을 여는 도구입니다.** 인터넷(ngrok)에 절대 노출하지 마십시오. 비밀번호를 다른 사람과 공유하지 마십시오.

## 8. 운영

| 목적 | 명령 |
|:---|:---|
| 상태 | `/root/code_server.sh status` |
| 재시작 | `/root/code_server.sh restart` |
| 끄기 (메모리가 필요할 때) / 다시 켜기 | `/root/code_server.sh stop` / `start` |
| 로그 | `tail -f /root/code_server.log` |

- 감시 데몬은 블로그(`start_services.sh`), 문서 서버(`private_docs.sh`)와 **완전히 따로** 돕니다. 감시 작업은 4245(15분 주기), 기동 요청은 4246입니다.
- 부팅 때 Termux:Boot(`~/.termux/boot/start-server.sh`)가 런처 `termux/ensure-code-server.sh`를 실행합니다.
- 서버 인증서에는 Tailscale IP와 MagicDNS 이름이 함께 들어 있습니다(`code_server.sh`의 `MAGIC_DNS`). 이름으로 접속하면 IP가 바뀌어도 주소가 그대로입니다.
- Tailscale 주소가 없으면 기다리고(`WAITING`), 주소가 바뀌면 새 주소로 인증서를 다시 발급하고 다시 띄웁니다. 서버 인증서는 397일짜리이고 만료 30일 전에 자동으로 갱신됩니다. CA는 2036년까지 유효하므로 기기에 다시 등록할 일은 없습니다.
- 복구 시험 결과 (2026-09-20):
  - 바깥 프로세스 `kill -9` → 2초 만에 감지, 즉시 재기동
  - 안쪽 서버 `kill -9` → 6초 만에 감지, 32초 만에 다시 서비스
  - `restart` 명령 → 13초
- 아직 시험하지 않은 것: Tailscale을 실제로 껐다 켰을 때의 `WAITING`/`OFFLINE` 전환. 코드는 문서 서버와 같은 방식입니다.
