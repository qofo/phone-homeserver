# 5. 비공개 접근 — 나만 닿을 수 있는 서비스

[English](05-private-access.md) · <b>한국어</b>

[← 4. 계속 떠 있게](04-always-on.ko.md) · 다음: [6. 운영](06-operations.ko.md)

---

블로그는 공개하려고 만든 것이다. 이 폰에 있는 다른 두 개는 아니다. 개인 문서를 읽는
뷰어와, 모든 파일에 쓰기 권한을 가진 편집기다. 이 문서는 방화벽이 없는 기기에서 그 둘을
비공개로 유지하는 방법이다.

![공개 경로와 tailnet 전용 경로](images/network-paths.svg)

## 5.1 위협 모델부터 적는다

| 누가 | 무엇을 시도할 수 있는가 |
|:---|:---|
| 같은 와이파이의 낯선 사람 | 서브넷을 스캔해서 열린 포트에 붙는다 |
| 인터넷의 스캐너 | ngrok 도메인을 훑어 다른 경로를 찾는다 |
| URL 하나를 얻은 사람 | 옆 경로를 추측하거나, 의도한 범위 밖의 파일을 읽는다 |
| **내 브라우저에서 도는 남의 웹페이지** | 내 기기를 출발지로 삼아 비공개 서비스에 요청한다 |

설계를 결정하는 것은 마지막 줄이다. 내 브라우저에서 출발한 요청은 네트워크 수준의 통제를
전부 통과하므로, 따로 답이 필요하다(5.4).

## 5.2 Tailscale, 그리고 1층: 바인딩 주소가 방화벽이다

**Tailscale은 안드로이드 앱으로** 설치한다. 컨테이너 안이 아니다. 폰이 호스트로서 내
tailnet에 참여하고, 폰의 `100.x.y.z` 주소에서 듣고 있는 것은 내가 로그인한 다른 기기에서만
닿는다.

일반 서버라면 `0.0.0.0`에 띄우고 방화벽으로 VPN 인터페이스만 열 것이다. 여기서는 그럴 수
없다. `iptables`가 설치돼 있지 않고, 설치해도 `proot`의 가짜 root에는 커널 방화벽 규칙을
넣을 권한이 없다. 그래서 소켓을 Tailscale 주소 자체에 바인딩하고, 다른 인터페이스로 들어온
연결은 커널이 거부한다.

그 주소를 알아내는 일이 생각보다 까다롭다. 최소 rootfs에는 `ip` 명령이 없고,
`/proc/net/fib_trie`는 권한 거부이고, 안드로이드의 VPN 인터페이스는 이번 부팅에 `tun0`,
다음 부팅에 `tun1`이다. 커널에 직접 묻는다.

```python
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")

def find_tailnet_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            try:
                packed = fcntl.ioctl(sock.fileno(), 0x8915,      # SIOCGIFADDR
                                     struct.pack("256s", name.encode()[:15]))
            except OSError:
                continue
            ip = socket.inet_ntoa(packed[20:24])
            if ipaddress.ip_address(ip) in TAILNET_V4:
                return ip
    finally:
        sock.close()
    return None
```

바인딩 주소를 설정으로 바꿀 수 있게 하면 언젠가 누군가 — 미래의 나를 포함해서 —
`0.0.0.0`을 넣는다. 그래서 허용 범위 밖의 주소는 경고가 아니라 시작 실패다.

```
$ PRIVATE_DOCS_BIND=0.0.0.0 python3 private_docs_server.py
refusing to bind to 0.0.0.0: only tailnet (100.64.0.0/10) or loopback addresses are allowed
$ echo $?
2
```

**VPN은 꺼질 수 있다.** Tailscale은 앱이라 사람이 끄기도 하고, 재부팅 직후에는 아직 켜지지
않았다. 서버는 세 상태 중 하나를 파일에 적고, 임의로 판단하지 않는다.

| 상태 | 뜻 | 서버의 행동 |
|:---|:---|:---|
| `waiting` | 아직 tailnet 주소가 없음 | 5초마다 다시 찾고, 소켓은 아예 열지 않는다 |
| `listening <주소>:8081` | 정상 | 30초마다 주소를 다시 확인한다 |
| `offline <주소>:8081` | 바인딩한 뒤 VPN이 꺼짐 | 그대로 기다린다. 같은 주소로 돌아오면 `listening` |

주소가 **바뀌면** 종료 코드 3으로 끝난다. 바인딩한 소켓은 새 주소로 옮길 수 없으니, 감독자가
새 주소에 다시 붙게 띄운다. "주소를 못 찾았으니 일단 `0.0.0.0`으로"라는 경로는 코드 어디에도
없다. **실패하면 닫힌 쪽으로 실패한다.**

## 5.3 2층과 3층: 접속자 주소, 그리고 `Host`

바인딩만으로 충분해 보인다. 그래도 요청마다 다시 확인한다. 설정 실수로 바인딩이 넓어져도
접근이 함께 넓어지지는 않아야 하기 때문이다.

```python
def _peer_ok(self):
    peer = ipaddress.ip_address(self.client_address[0].split("%")[0])
    if peer.version == 6 and peer.ipv4_mapped:
        peer = peer.ipv4_mapped
    return any(peer in net for net in ALLOWED_NETS)   # 100.64.0.0/10, fd7a:115c:a1e0::/48
```

여기서부터가 흥미롭다. **DNS 리바인딩**은 위의 모든 검사를 무력화한다.

1. 공격자가 `evil.example`을 소유하고, 처음에는 자기 IP를 아주 짧은 TTL로 응답한다.
2. 내가 그 페이지를 열고, 자바스크립트가 로드된다.
3. DNS 응답이 **내 tailnet 주소**로 바뀐다.
4. 페이지가 `http://evil.example:8081/raw/plan.md`를 요청한다. 브라우저에게 이것은
   *같은 출처*이므로 스크립트가 응답을 읽을 수 있다.
5. 요청은 내 노트북에서 출발했으니 접속자 검사를 통과한다.

공격자가 위조할 수 없는 것 하나가 `Host` 헤더다. 브라우저가 허용하지 않는다. 그래서 서버는
`Host`가 내 tailnet의 이름이나 주소일 때만 응답한다.

```python
def _host_ok(self):
    host = (self.headers.get("Host") or "").strip()
    # ... 포트 떼기 ...
    try:
        return any(ipaddress.ip_address(name) in net for net in ALLOWED_NETS)
    except ValueError:
        pass
    name = name.lower().rstrip(".")
    return bool(name) and (name.endswith(".ts.net")   # MagicDNS 전체 이름
                           or "." not in name)        # MagicDNS 짧은 이름
```

`localhost.evil.com`처럼 그럴듯한 이름은 점이 있고 `.ts.net`으로 끝나지 않으므로 거부된다.
CORS 허용 헤더도 절대 보내지 않는다. 다른 출처의 페이지가 이 응답을 읽을 합법적인 이유는
없다.

거부는 로그에 남긴다. **성공한 읽기는 남기지 않는다.** 이 서버의 로그에 있어야 할 것은
이상한 접근뿐이다.

```
[DENY] Host header outside the tailnet peer=100.x.y.z host='evil.example.com' path='/'
```

## 5.4 4층: 디렉터리가 아니라 허용 목록

정적 파일 서버를 `/root`에 물리면 경로 조작 버그 하나로 SSH 키가 새어 나간다. 이 서버는
파일 시스템을 노출하지 않는다. 목록에 적힌 문서만 존재한다.

```
# private_docs.list — 여기 없는 파일은 URL을 알아도 열리지 않는다
idea.md
idea-plan.md
HUGO_MIGRATION_PLAN.md
```

요청의 파일 이름은 **목록을 조회하는 키**로만 쓰이고, 경로를 조립하는 데는 쓰이지 않는다.
조회 테이블은 인코딩을 어떻게 비틀어도 빠져나갈 수 없다. 이름 규칙(`.md`로 끝남, 점으로
시작하지 않음)과 2MB 크기 제한도 있다. 목록은 요청마다 다시 읽으므로 한 줄 추가는 재시작
없이 반영된다.

## 5.5 5층: 브라우저 안에서의 방어

이 문서들에는 웹에서 붙여 온 텍스트가 섞여 있고, 그 말은 HTML이 섞일 수 있다는 뜻이다.
마크다운은 HTML을 그대로 통과시키므로 **내 문서가 내 브라우저에서 스크립트를 실행하는**
일이 가능하다.

- 서버는 마크다운을 해석하지 않는다. 원문을 `text/plain`으로 내주고, 브라우저가
  [marked](https://github.com/markedjs/marked)로 변환한 뒤
  [DOMPurify](https://github.com/cure53/DOMPurify)로 정화한다.
- 두 라이브러리는 CDN에서 불러오지 않고 **폰에 두었다.** 내려받을 때 CDN이 공개한 SRI
  해시(sha512)와 대조했다.
- 정화 단계에서 원격 이미지의 `src`를 지운다. 문서를 여는 것만으로 내가 무엇을 언제 읽는지가
  외부 서버에 기록되면 안 된다.
- 모든 응답에 엄격한 헤더를 붙인다.

```
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self';
                         img-src 'self' data:; connect-src 'self'; base-uri 'none';
                         form-action 'none'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
X-Robots-Tag: noindex, nofollow
Cache-Control: no-store
```

`script-src 'self'`는 인라인 스크립트와 `eval`을 막는다. 정화가 뚫려도 실행되지 않는다.
대가로 뷰어 자신의 코드도 인라인 스크립트와 인라인 스타일을 쓸 수 없다. 테스트에 "뷰어가
자기 CSP를 어기지 않는가" 항목이 따로 있는 이유다.

## 5.6 감독자를 따로 둔다

문서 뷰어와 code-server는 각자의 감독자와 작업 번호를 갖는다
([`04-always-on.ko.md`](04-always-on.ko.md)). 공개 감독자에 합치면 블로그를 잘못
재시작할 때 비공개 서비스가 함께 끌려가고, `--kill-on-exit` 연쇄가 셋을 모두 데려갈 수
있다. 시작 조건도 다르다. 블로그는 바로 시작할 수 있지만, 비공개 서비스는 Tailscale을
기다려야 한다.

## 5.7 code-server: tailnet 안에서 HTTPS로 여는 VS Code

데스크톱 VS Code의 Remote-SSH는 여기서 동작하지 않고, 로그가 이유를 말해 준다.

```
error This machine does not meet Visual Studio Code Server's prerequisites, expected either...
  - find libstdc++.so or ldconfig for GNU environments
  - find /lib/ld-musl-aarch64.so.1, which is required ... in musl environments
```

SSH가 도착하는 곳은 **Termux**이고, 그곳은 glibc도 musl도 아닌 bionic이다. 한 겹 안의
컨테이너에는 glibc 2.43이 있다. 그래서 그 안에서 `code-server`를 돌리고 브라우저로 연다.

VPN 안이라도 HTTPS는 선택이 아니다. HTTPS가 아니면 브라우저가 클립보드와 서비스 워커 등
편집기가 필요한 기능을 내주지 않는다. 매번 클릭해서 지나가야 하는 자가 서명 인증서는
없는 것보다 나쁘므로, 폰이 작은 CA를 돌리고 기기마다 그 CA를 한 번 신뢰한다.

핵심은 **이름 제약(Name Constraints)**이다. 내가 신뢰한 루트 CA는 기본적으로 인터넷의 어떤
이름이든 보증할 수 있다. X.509에는 그 범위를 줄이는 장치가 있고, 검증하는 쪽은 그것을
지켜야 한다.

```bash
openssl req -x509 -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -subj "/CN=phone-homeserver local CA" -days 3650 \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "nameConstraints=critical,permitted;IP:100.64.0.0/255.192.0.0,\
permitted;IP:fd7a:115c:a1e0::/ffff:ffff:ffff::,permitted;DNS:ts.net" \
  -keyout ca.key -out ca.crt
```

이 CA는 tailnet 주소와 `*.ts.net` 이름만 서명할 수 있다. LAN IP나 공개 도메인용으로 발급한
인증서는, 기기가 그 CA를 신뢰하더라도 검증에 실패한다.

나머지는 `code_server.sh`가 한다. Tailscale 주소를 찾고, 그 주소와 MagicDNS 이름을
`subjectAltName`에 넣은 서버 인증서를 발급하고, 만료 전에 갱신하고, 편집기를 띄운다.

```bash
code-server --bind-addr "$ip:8443" --auth password \
            --cert "$SRV_CRT" --cert-key "$SRV_KEY" /root
```

헬스체크는 응답만이 아니라 인증서까지 검증한다. 인증서가 우리 것이 아니거나 만료됐으면
실패로 친다.

```bash
curl -s -o /dev/null -w '%{http_code}' --max-time 5 --cacert "$CA_CRT" "https://$1/healthz"
```

실무적인 메모 둘. 시작 뒤 **90초 유예**를 준다. 폰에서는 뜨는 데 시간이 걸리고, 너무 일찍
찌르면 무한히 죽인다. 그리고 프로세스가 **두 개**다. 래퍼와, 실제로 듣고 있는 Node
프로세스다. 하나만 맞히는 패턴을 쓰면 이미 돌고 있는 서비스를 다시 띄운다.

CA를 신뢰시키는 방법: `ca.crt`를 기기마다 복사해 설치한다. 안드로이드는 설정 → 보안 →
암호화 및 사용자 인증 정보 → 인증서 설치 → CA 인증서, macOS는 키체인 접근, 리눅스는
`/usr/local/share/ca-certificates`에 두고 `update-ca-certificates`다. 그 전에
`./code_server.sh status`가 출력하는 SHA-256 지문을 대조한다.

## 5.8 확인

```bash
python3 tests/test_private_docs.py          # 블랙박스 보안 테스트 47개
curl -s -o /dev/null -w '%{http_code}\n' http://<폰-LAN-IP>:8081/    # 000이 나와야 한다
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://100.x.y.z:8081/
./code_server.sh status
```

이 테스트는 경로 조작, 심볼릭 링크 탈출, 허용 목록 우회, 접속자와 `Host` 검사, 보안 헤더,
뷰어 자신의 CSP 준수를 확인한다. 추가로 해 볼 만한 확인이 있다. 로컬 CA로 LAN IP용
인증서를 발급해서 검증이 **실패하는지** 본다. 이름 제약이 일하고 있다는 증거다.

다음: 매일의 건강 관리 → [6. 운영](06-operations.ko.md)
