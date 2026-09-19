"""Black-box tests for serve_blog.py: static Hugo build + /api/metrics.

Run: python3 /root/tests/test_serve_blog.py   (uses port 18090 and a temp dir)
     SERVE_BLOG=/path/to/copy.py python3 ...   tests another copy of the server
"""
import http.client, json, os, shutil, subprocess, sys, tempfile, time

S = tempfile.mkdtemp(prefix="serve_blog_test_")
SERVER = os.environ.get("SERVE_BLOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "serve_blog.py")
PORT = 18090
SITE = f"{S}/live"  # symlink, repointed like publish_blog.sh does
results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


def start():
    env = dict(os.environ, BLOG_PORT=str(PORT), BLOG_SITE_DIR=SITE)
    log = open(f"{S}/server.log", "w")
    proc = subprocess.Popen([sys.executable, "-u", SERVER], env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        time.sleep(0.1)
        try:
            c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2); c.request("HEAD", "/"); c.getresponse(); c.close()
            return proc
        except OSError:
            if proc.poll() is not None:
                return proc
    return proc


def req(method, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.putrequest(method, path, skip_accept_encoding=True)  # send the raw path, unnormalised
    for k, v in (headers or {}).items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    data = r.read()
    hdrs = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, hdrs, data


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


CSS = "site.min." + "a" * 64 + ".css"

def make_build(name, marker):
    b = f"{S}/builds/{name}"
    write(f"{b}/index.html", f"<h1>{marker}</h1>")
    write(f"{b}/404.html", "<h1>NOT-FOUND-PAGE</h1>")
    write(f"{b}/posts/a/index.html", "<h1>POST-A</h1>")
    write(f"{b}/series/스마트폰/index.html", "<h1>SERIES-KO</h1>")
    write(f"{b}/css/{CSS}", "body{}")
    write(f"{b}/index.xml", "<rss/>")
    write(f"{b}/favicon.svg", "<svg/>")
    write(f"{b}/.build-info", "commit=deadbeef")
    os.symlink(f"{S}/outside", f"{b}/escape")
    return b


write(f"{S}/outside/secret.txt", "TOP-SECRET-MARKER")
write(f"{S}/builds/secret.txt", "TOP-SECRET-MARKER")

p = start()
try:
    print("== A. 빌드가 없을 때 ==")
    st, h, body = req("GET", "/")
    check("/ 는 200 대체 페이지 (헬스체크가 재시작 루프에 빠지지 않음)", st == 200 and "qofo.github.io" in body.decode(), str(st))
    st, h, body = req("GET", "/posts/a/")
    check("다른 경로는 404", st == 404, str(st))
    st, h, body = req("GET", "/api/metrics")
    check("빌드와 무관하게 /api/metrics 200", st == 200 and "cpu" in json.loads(body), str(st))

    b1 = make_build("b1", "BUILD-ONE")
    os.symlink(b1, SITE)

    print("== B. 정적 파일 ==")
    st, h, body = req("GET", "/")
    check("/ → index.html", st == 200 and b"BUILD-ONE" in body and h.get("content-type") == "text/html; charset=utf-8", str(st))
    check("HTML 은 no-cache", h.get("cache-control") == "no-cache", h.get("cache-control"))
    st, h, body = req("GET", "/posts/a/")
    check("/posts/a/ → index.html", st == 200 and b"POST-A" in body, str(st))
    st, h, _ = req("GET", "/posts/a")
    check("슬래시 없는 디렉터리는 301 /posts/a/", st == 301 and h.get("location") == "/posts/a/", f"{st} {h.get('location')}")
    st, h, _ = req("GET", "//posts/a")
    check("//posts/a 는 프로토콜 상대 주소로 리디렉트하지 않음", st == 301 and h.get("location") == "/posts/a/", f"{st} {h.get('location')}")
    st, h, _ = req("GET", "/posts/a?x=1")
    check("쿼리는 무시하고 리디렉트", st == 301 and h.get("location") == "/posts/a/", f"{st} {h.get('location')}")
    ko = "/series/%EC%8A%A4%EB%A7%88%ED%8A%B8%ED%8F%B0"
    st, h, body = req("GET", ko + "/")
    check("퍼센트 인코딩된 한글 경로", st == 200 and b"SERIES-KO" in body, str(st))
    st, h, _ = req("GET", ko)
    check("한글 디렉터리 리디렉트도 인코딩된 Location", st == 301 and h.get("location") == ko + "/", f"{st} {h.get('location')}")
    st, h, body = req("GET", f"/css/{CSS}")
    check("지문 붙은 CSS 는 immutable 캐시", st == 200 and "immutable" in h.get("cache-control", "") and h.get("content-type", "").startswith("text/css"), h.get("cache-control"))
    st, h, _ = req("GET", "/index.xml")
    check("XML 타입", st == 200 and h.get("content-type", "").startswith("application/xml"), h.get("content-type"))
    st, h, _ = req("GET", "/favicon.svg")
    check("SVG 타입과 nosniff", st == 200 and h.get("content-type") == "image/svg+xml" and h.get("x-content-type-options") == "nosniff")

    st, h, body = req("GET", "/posts/a/")
    etag = h.get("etag", "")
    st2, h2, body2 = req("GET", "/posts/a/", {"If-None-Match": etag})
    check("ETag 일치 시 304, 본문 없음", bool(etag) and st2 == 304 and body2 == b"", f"{st2} {etag}")
    st, h, body = req("HEAD", "/posts/a/")
    check("HEAD 는 본문 없이 길이만", st == 200 and body == b"" and h.get("content-length") == str(len(b"<h1>POST-A</h1>")))

    print("== C. 경로 조작과 숨김 파일 ==")
    for path in ["/../secret.txt", "/%2e%2e/secret.txt", "/posts/..%2f..%2fsecret.txt", "/posts/%2e%2e/%2e%2e/secret.txt",
                 "/escape/secret.txt", "/escape/", "/.build-info", "/posts/a/%00", "/%ff", "/posts\\..\\..\\secret.txt"]:
        st, h, body = req("GET", path)
        check(f"{path} → 404, 비밀 노출 없음", st == 404 and b"TOP-SECRET" not in body and b"deadbeef" not in body, str(st))
    st, h, body = req("GET", "/nope/")
    check("없는 경로는 사이트의 404.html", st == 404 and b"NOT-FOUND-PAGE" in body, str(st))
    st, h, _ = req("GET", "/api/posts")
    check("옛 /api/posts 는 없어짐", st == 404, str(st))
    st, h, _ = req("POST", "/api/metrics")
    check("POST 는 501", st == 501, str(st))

    print("== D. 대시보드 API 와 CORS ==")
    st, h, body = req("GET", "/api/metrics", {"Origin": "https://qofo.github.io"})
    data = json.loads(body)
    check("/api/metrics JSON", st == 200 and h.get("content-type") == "application/json; charset=utf-8" and len(data["cpu"]["cores"]) == 8)
    check("CORS 허용과 no-store", h.get("access-control-allow-origin") == "*" and h.get("cache-control") == "no-store")
    st, h, body = req("OPTIONS", "/api/metrics", {"Origin": "https://qofo.github.io", "Access-Control-Request-Method": "GET",
                                                  "Access-Control-Request-Headers": "ngrok-skip-browser-warning"})
    check("preflight 204 에 ngrok 헤더 허용", st == 204 and h.get("access-control-allow-origin") == "*"
          and "ngrok-skip-browser-warning" in h.get("access-control-allow-headers", "").lower(), f"{st} {h}")
    st, h, _ = req("OPTIONS", "/")
    check("다른 경로 OPTIONS 에는 CORS 헤더 없음", st == 204 and "access-control-allow-origin" not in h, str(st))

    print("== E. 빌드 교체 (심볼릭 링크 재지정, 재시작 없음) ==")
    b2 = make_build("b2", "BUILD-TWO")
    os.symlink(b2, SITE + ".tmp")
    os.replace(SITE + ".tmp", SITE)
    st, h, body = req("GET", "/")
    check("재시작 없이 새 빌드를 서비스", st == 200 and b"BUILD-TWO" in body, str(st))
    check("서버 프로세스 생존", p.poll() is None)
finally:
    p.terminate()
    p.wait(timeout=5)
    shutil.rmtree(S, ignore_errors=True)

passed = sum(results)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
