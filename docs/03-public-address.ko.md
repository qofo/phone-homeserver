# 3. 도메인을 사지 않고 공개 주소 갖기

[English](03-public-address.md) · <b>한국어</b>

[← 2. 웹 서버](02-web-server.ko.md) · 다음: [4. 계속 떠 있게](04-always-on.ko.md)

---

폰은 그때그때 붙어 있는 망의 사설 주소를 갖는다. 어느 길로 나갈지는 조건 세 개가
결정했다.

1. **도메인을 사지 않는다.**
2. **공유기를 건드리지 않는다.**
3. **폰이 옮겨 다녀도 같은 주소** — 집 와이파이, 카페 와이파이, LTE.

세 방식을 순서대로 시도했고, 셋을 모두 만족한 것은 하나였다.

## 3.1 포트포워딩이 보통 답이 아닌 이유

가장 먼저 떠오르는 방법은 DDNS와 포트포워딩이다. 실패했고, 배울 것이 있는 방식으로
실패했다. 새로 만든 DuckDNS 주소로 외부에서 요청하자 남의 웹 서버가 응답했다.

```
$ curl -I http://<내-서브도메인>.duckdns.org
HTTP/1.1 200 OK
Server: Microsoft-IIS/10.0
```

DuckDNS는 올바른 공인 IP를 가리키고 있었다. 그 IP의 80번 포트는 몇 년 전에 데스크톱
PC로 포워딩되어 있었다. **도메인은 요청을 집 현관까지만 안내하고, 그 안에서 어느 방으로
갈지는 공유기가 정한다.**

8080 포트 규칙을 추가하면 접속은 됐을 것이고, 그래도 조건을 만족하지 못한다.

- 공유기 관리자 권한이 필요하다.
- 폰을 들고 집을 나서는 순간 끝난다.
- HTTPS 인증서 문제를 직접 떠안는다.

게다가 모바일망과 상당수 아파트 망에는 포워딩할 대상 자체가 없다. 공유기의 WAN 주소가
`100.64.0.0/10` 안에 있다면 통신사 수준 NAT(CGNAT) 뒤에 있는 것이고, 어떤 포트도 열 수
없다. 계획을 세우기 전에 확인한다.

```bash
curl -s https://api.ipify.org          # 인터넷이 보는 내 주소
ip route get 1.1.1.1                   # 공유기가 내게 준 주소
```

두 값이 다른 것은 NAT이고 정상이다. WAN 주소가 `100.64.0.0/10`이면 CGNAT이고, 터널만이
길이다.

## 3.2 Cloudflare Tunnel — 도메인이 있다면 가장 깔끔하다

터널은 폰이 바깥으로 거는 연결이므로 포워딩할 것도, 열 것도 없다. Cloudflare의 방식은
두 가지다.

**Quick Tunnel**은 계정이 필요 없고, 누군가에게 페이지를 보여 주는 가장 빠른 길이다.

```bash
cloudflared tunnel --url http://localhost:8080
```

무작위 `*.trycloudflare.com` 주소를 출력하고, 재시작마다 바뀐다. 블로그의 주소가 아니라
시연 도구다.

**Named Tunnel**은 이름이 고정된다. `cloudflared tunnel login`을 쓰는 대신 대시보드에서
터널을 만들고 토큰으로 실행한다. 폰에서 브라우저 로그인은 도중에 만료되기 쉽고, 성공해도
`cert.pem`이 안드로이드 다운로드 폴더에 떨어져서 컨테이너 안으로 직접 옮겨야 한다.

```bash
cloudflared tunnel run --token eyJh...
```

연결 품질은 한 번도 문제가 아니었다. 사전 점검을 전부 통과하고 가장 가까운 엣지에
QUIC으로 붙었다.

```
INF  SUMMARY: Environment is healthy. cloudflared will use 'quic' as primary protocol.
INF  Registered tunnel connection location=icn01 protocol=quic
```

막히는 곳은 **Public Hostname** 단계다. Named Tunnel에 공개 주소를 붙이려면
**내가 소유하고 Cloudflare 네임서버로 위임한** 도메인이 있어야 한다. `*.duckdns.org`나
`*.ts.net` 같은 무료 서브도메인은 위임할 수 없으므로 등록 자체가 불가능하다. 조건 1에
걸린다.

> **쓰지 않기로 한 설정은 지운다.** ngrok으로 갈아탄 뒤 며칠이 지나도 Cloudflare
> 대시보드에는 ngrok 도메인을 가리키는 호스트네임이 남아 있었다. 소유하지 않은 주소를
> 목적지로 지정한 터널이라 동작할 수 없고, 나중에 로그를 읽는 사람만 헷갈리게 한다.

## 3.3 ngrok 무료 고정 도메인 — 이 저장소가 쓰는 방식

ngrok 무료 계정에는 바뀌지 않는 도메인 하나가 포함된다. 설정은 토큰 한 줄이 전부다.

```yaml
# ~/.config/ngrok/ngrok.yml
version: "3"
agent:
  authtoken: <발급받은 토큰>
```

```bash
/usr/local/bin/ngrok http 8080 \
    --url https://<내-도메인>.ngrok-free.dev \
    --pooling-enabled \
    --log stdout
```

도메인 값 0원, 공유기 변경 0건, 어느 망에서든 같은 주소다.

### 여기서 `--pooling-enabled`는 선택이 아니다

에이전트를 빠르게 재시작하면 ngrok이 거부한다.

```
failed to start tunnel: The endpoint 'https://<내-도메인>.ngrok-free.dev'
is already online. ... ERR_NGROK_334
```

엣지가 이전 세션을 정리하기 전에 새 에이전트가 같은 주소를 요구한 것이다.
`--pooling-enabled`를 붙이면 두 세션이 잠시 공존하며 인수인계한다. 크래시 때 프로세스를
다시 띄우는 감독자를 쓰면 하루 안에 이 오류를 만나므로, 필수 옵션으로 취급한다.

### 무료 플랜의 대가

브라우저로 무료 ngrok 도메인에 들어가면 경고 페이지가 먼저 나온다. 같은 URL이 요청자에
따라 다르게 동작한다.

```bash
$ curl -s -o /dev/null -w "%{http_code} %{size_download}\n" https://<내-도메인>.ngrok-free.dev/
200 39813        # 블로그 본문

$ curl -s -A "Mozilla/5.0 (Linux; Android 14) ... Chrome/140.0" ... 
200 2902         # "You are about to visit ..."  (ERR_NGROK_6024)
```

사람은 버튼을 한 번 더 누르고, `curl`과 RSS 리더와 API 호출은 영향을 받지 않는다.
`ngrok-skip-browser-warning` 헤더를 보내면 건너뛸 수 있는데, 그것이 바로
[`02-web-server.ko.md`](02-web-server.ko.md)에서 CORS preflight를 유발한 비표준
헤더다.

## 3.4 세 방식 비교

| | Cloudflare Named Tunnel | DuckDNS + 포트포워딩 | ngrok 무료 고정 도메인 |
|:---|:---|:---|:---|
| 개인 도메인 | **필요** | 불필요 | 불필요 |
| 공유기 권한 | 불필요 | **필요** | 불필요 |
| CGNAT 뒤에서 | 가능 | **불가** | 가능 |
| HTTPS | 자동 | 직접 발급·갱신 | 자동 |
| 집 밖에서 | 정상 | **불가** | 정상 |
| 방문자 경험 | 깨끗함 | 깨끗함 | **경고 페이지 1회** |
| 난이도 | 중 (DNS 위임) | 중 (공유기 권한) | 하 |

도메인을 이미 갖고 있다면 Cloudflare가 가장 깔끔하다. 아무것도 없이 오늘 고정 주소가
필요하다면 ngrok이다.

## 3.5 비공개 서비스는 이 경로에 올리지 않는다

공개 터널이 나르는 것은 블로그뿐이다. 문서 뷰어와 code-server는 비밀번호를 걸어도 이
터널로 내보내지 않는다. 대신 Tailscale 주소에 바인딩한다.
[`05-private-access.ko.md`](05-private-access.ko.md)의 내용이다.

다음: 사람이 손대지 않아도 돌아가게 만든다 → [4. 계속 떠 있게](04-always-on.ko.md)
