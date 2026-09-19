"""Black-box tests for private_docs_server.py (loopback bind; production checks stay on).

Run: python3 /root/tests/test_private_docs.py   (uses ports 18081-18084 and a temp dir)
"""
import http.client, json, os, shutil, signal, subprocess, sys, tempfile, time

S = tempfile.mkdtemp(prefix="private_docs_test_")
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "private_docs_server.py")
PORT = 18081
results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def start(env_extra, port=PORT):
    env = dict(os.environ, PRIVATE_DOCS_BIND="127.0.0.1", PRIVATE_DOCS_PORT=str(port),
               PRIVATE_DOCS_STATE=f"{S}/state_{port}", PRIVATE_DOCS_LIST=f"{S}/list_test.txt", **env_extra)
    log = open(f"{S}/server_{port}.log", "w")
    proc = subprocess.Popen([sys.executable, "-u", SERVER], env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(50):
        time.sleep(0.1)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2); c.request("GET", "/healthz"); c.getresponse(); c.close()
            return proc
        except OSError:
            if proc.poll() is not None:
                return proc
    return proc


def req(method, path, headers=None, port=PORT, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, hdrs, data


# fixtures: two allowed docs, one secret file that is NOT in the list
os.makedirs(f"{S}/docs", exist_ok=True)
open(f"{S}/docs/a.md", "w", encoding="utf-8").write("# 문서 A\n\n[B](b.md) [숨김](secret.md)\n\n## 절\n")
open(f"{S}/docs/b.md", "w", encoding="utf-8").write("# 문서 B\n\n본문\n")
open(f"{S}/docs/secret.md", "w", encoding="utf-8").write("# 비밀\nTOP-SECRET-MARKER\n")
open(f"{S}/docs/.hidden.md", "w", encoding="utf-8").write("# hidden\n")
open(f"{S}/list_test.txt", "w", encoding="utf-8").write(
    f"# comment\n{S}/docs/a.md\n{S}/docs/b.md  # trailing comment\n{S}/docs/.hidden.md\n{S}/docs/missing.md\n"
    f"{S}/docs/not_markdown.txt\n../../etc/passwd\n")

print("== A. 허용된 접속(루프백 허용) ==")
p = start({"PRIVATE_DOCS_ALLOW": "127.0.0.0/8"})
try:
    st, h, body = req("GET", "/")
    check("목록 페이지 200", st == 200 and "문서 A" in body.decode() and "문서 B" in body.decode())
    check("허용 목록에 없는 secret.md 는 목록에 없음", "secret" not in body.decode().lower())
    check(".hidden.md·없는 파일·비마크다운은 목록에서 제외", "hidden" not in body.decode() and "missing" not in body.decode())
    check("보안 헤더", h.get("x-content-type-options") == "nosniff" and "script-src 'self'" in h.get("content-security-policy", "")
          and h.get("referrer-policy") == "no-referrer" and h.get("cache-control") == "no-store" and h.get("x-frame-options") == "DENY")
    check("Server 헤더에 파이썬 버전 없음", "python" not in h.get("server", "").lower(), h.get("server", ""))

    st, h, body = req("GET", "/raw/a.md")
    check("raw 원문 200 + text/plain", st == 200 and h["content-type"].startswith("text/plain") and "문서 A" in body.decode())
    st, h, body = req("GET", "/doc/a.md")
    check("뷰어 페이지 200 + text/html", st == 200 and h["content-type"].startswith("text/html") and 'data-doc="a.md"' in body.decode())
    st, _, body = req("GET", "/api/docs")
    names = [d["name"] for d in json.loads(body)]
    check("/api/docs 는 허용된 문서만", names == ["a.md", "b.md"], str(names))

    print("== B. 경로 조작·허용 목록 우회 시도 ==")
    for label, path in [
        ("허용 목록 밖 파일(secret.md)", "/raw/secret.md"),
        ("../ 상위 경로", "/raw/../docs/secret.md"),
        ("인코딩된 ../", "/raw/..%2Fdocs%2Fsecret.md"),
        ("이중 인코딩", "/raw/%252e%252e%252fsecret.md"),
        ("/etc/passwd", "/raw/..%2F..%2F..%2Fetc%2Fpasswd"),
        ("NUL 바이트", "/raw/a.md%00.png"),
        ("숨김 파일", "/raw/.hidden.md"),
        ("정적 파일 밖", "/static/../private_docs_server.py"),
        ("정적 파일 인코딩", "/static/..%2Fprivate_docs_server.py"),
        ("허용되지 않은 정적 이름", "/static/private_docs.list"),
        ("뷰어로 secret", "/doc/secret.md"),
        ("디렉터리", "/raw/"),
    ]:
        st, _, body = req("GET", path)
        check(f"차단: {label}", st in (404, 400) and b"TOP-SECRET" not in body, f"HTTP {st}")

    print("== C. 메서드·Host 헤더 ==")
    for m in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
        st, h, _ = req(m, "/", body=b"x")
        check(f"{m} → 405", st == 405 and h.get("allow") == "GET, HEAD", f"HTTP {st}")
    st, h, body = req("HEAD", "/raw/a.md")
    check("HEAD 는 본문 없음", st == 200 and body == b"" and int(h["content-length"]) > 0)
    st, _, _ = req("GET", "/", headers={"Host": "evil.example.com"})
    check("Host: 외부 도메인 → 403 (DNS 리바인딩 방어)", st == 403)
    st, _, _ = req("GET", "/", headers={"Host": "127.0.0.1:18081"})
    check("Host: 허용 대역 IP → 200", st == 200)
    st, _, _ = req("GET", "/", headers={"Host": "my-phone.tail1234.ts.net:8081"})
    check("Host: *.ts.net → 200", st == 200)
    st, _, _ = req("GET", "/", headers={"Host": "my-phone"})
    check("Host: 단일 라벨(MagicDNS 짧은 이름) → 200", st == 200)
    st, _, _ = req("GET", "/", headers={"Host": "192.168.0.42:8081"})
    check("Host: 사설 LAN IP → 403", st == 403)
    st, _, _ = req("GET", "/", headers={"Host": "localhost.evil.com"})
    check("Host: localhost.evil.com → 403", st == 403)
    st, h, _ = req("GET", "/raw/a.md", headers={"Origin": "http://evil.example.com"})
    check("CORS 허용 헤더를 절대 주지 않음", "access-control-allow-origin" not in h)
    st, _, body = req("GET", "/" + "A" * 9000)
    check("아주 긴 경로도 안전하게 404", st in (404, 414), f"HTTP {st}")

    print("== D. 로그 ==")
    time.sleep(0.3)
    log = open(f"{S}/server_{PORT}.log", encoding="utf-8").read()
    check("거부된 요청은 로그에 남음(DENY)", "[DENY] Host header outside the tailnet" in log)
    check("일반 요청(문서 열람)은 로그에 남기지 않음", "/raw/a.md" not in log and "/doc/a.md" not in log)
finally:
    p.send_signal(signal.SIGTERM); p.wait(timeout=5)

print("== E. 접속자 IP 검사: 루프백 접속을 tailnet 대역만 허용 ==")
p = start({"PRIVATE_DOCS_ALLOW": "100.64.0.0/10"}, port=18082)
try:
    for path in ("/", "/raw/a.md", "/healthz", "/static/style.css"):
        st, _, body = req("GET", path, port=18082)
        check(f"tailnet 밖 접속자 {path} → 403", st == 403 and b"forbidden" in body, f"HTTP {st}")
    log = open(f"{S}/server_18082.log", encoding="utf-8").read()
    check("로그에 peer 거부 기록", "[DENY] peer outside the tailnet peer=127.0.0.1" in log)
finally:
    p.send_signal(signal.SIGTERM); p.wait(timeout=5)

print("== F. 바인딩 안전장치 ==")
for addr, want in [("0.0.0.0", 2), ("192.168.0.42", 2), ("::", 2), ("8.8.8.8", 2)]:
    env = dict(os.environ, PRIVATE_DOCS_BIND=addr, PRIVATE_DOCS_PORT="18083", PRIVATE_DOCS_STATE=f"{S}/state_18083")
    r = subprocess.run([sys.executable, SERVER], env=env, capture_output=True, text=True, timeout=10)
    check(f"BIND={addr} 는 실행을 거부", r.returncode == want and "refusing" in r.stdout, f"exit={r.returncode}")

print("== G. 종료 처리 ==")
p = start({"PRIVATE_DOCS_ALLOW": "127.0.0.0/8"}, port=18084)
check("상태 파일: listening", open(f"{S}/state_18084").read().startswith("listening 127.0.0.1:18084"))
p.send_signal(signal.SIGTERM); rc = p.wait(timeout=5)
check("SIGTERM 로 정상 종료(0)와 상태 파일 삭제", rc == 0 and not os.path.exists(f"{S}/state_18084"), f"exit={rc}")

print(f"\n결과: {sum(results)}/{len(results)} 통과")
shutil.rmtree(S, ignore_errors=True)
sys.exit(0 if all(results) else 1)
