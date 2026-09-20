#!/bin/bash
# Publish the Hugo blog to both places from one source (/root/qofo.github.io).
#
#   publish_blog.sh phone     build the phone copy and switch serve_blog.py to it (no restart);
#                             uncommitted changes are allowed, as a preview
#   publish_blog.sh pages     build the GitHub Pages copy and commit it to the local gh-pages
#                             branch (no push)
#   publish_blog.sh publish   require a clean tree, build both copies from that commit, then
#                             push main and gh-pages together (https://qofo.github.io/)
#   publish_blog.sh status    which commit each copy serves
#
# Phone builds go to /root/blog_builds/<UTC time>; /root/blog_public is a symlink to the live
# one, replaced with rename(2), so a request never sees a half-written site. The last 3 builds
# are kept for rollback: ln -sfn <older build> /root/blog_public
set -euo pipefail

SRC=/root/qofo.github.io
LIVE=/root/blog_public
BUILDS=/root/blog_builds
KEEP=3
LOCAL=http://127.0.0.1:8080
PAGES_URL=https://qofo.github.io/
PAGES_BRANCH=gh-pages
PAGES_CHANGED=0
PAGES_SHA=""

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
git_src() { git -C "$SRC" "$@"; }

source_rev() {
    local dirty=""
    [ -n "$(git_src status --porcelain)" ] && dirty="-dirty"
    printf '%s%s' "$(git_src rev-parse --short HEAD)" "$dirty"
}

# hugo_build <dest> [hugo args...]: build, check, and report how many posts came out
hugo_build() {
    local out=$1; shift
    command -v hugo >/dev/null || die "hugo is not installed (apt-get install hugo)"
    if ! nice -n 10 hugo --source "$SRC" --minify --destination "$out" --cleanDestinationDir \
            --logLevel warn --quiet "$@"; then
        rm -rf "$out"
        die "hugo build failed; nothing was published"
    fi
    [ -f "$out/index.html" ] || { rm -rf "$out"; die "build has no index.html; nothing was published"; }
    local sources built
    sources=$(find "$SRC/content/posts" -name '*.md' ! -name '_index.md' | wc -l)
    # -path '*/page/*' skips posts/page/N/, the paginator's own pages: the theme's list
    # template paginates the section, and those are not posts.
    built=$(find "$out/posts" -mindepth 2 -name index.html -not -path '*/page/*' | wc -l)
    # Hugo skips drafts and future-dated posts without an error
    [ "$sources" = "$built" ] || say "[warn]  $sources post files but $built built (draft or future date?)"
    BUILT_POSTS=$built
}

build_phone() {
    local stamp out rev
    stamp=$(date -u +%Y%m%d-%H%M%S)
    out="$BUILDS/$stamp"
    rev=$(source_rev)
    mkdir -p "$BUILDS"

    hugo_build "$out" --environment phone
    printf 'commit=%s\nbuilt=%s\nposts=%s\n' "$rev" "$(date -u '+%F %T UTC')" "$BUILT_POSTS" > "$out/.build-info"

    # Atomic switch: make a new symlink, then rename it over the old one
    ln -sfn "$out" "$LIVE.tmp"
    mv -T "$LIVE.tmp" "$LIVE"
    say "[phone] $rev -> $out ($BUILT_POSTS posts), live now"

    # Keep the newest $KEEP builds; never the live one
    local live_target old
    live_target=$(readlink -f "$LIVE")
    ls -1d "$BUILDS"/*/ 2>/dev/null | sed 's:/$::' | sort | head -n -"$KEEP" | while read -r old; do
        [ "$old" = "$live_target" ] || rm -rf "$old"
    done

    local code body
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$LOCAL/" || true)
    body=$(curl -s --max-time 5 "$LOCAL/" || true)
    if grep -q 'id=legacy-links' <<<"$body"; then
        say "[phone] $LOCAL/ -> HTTP $code, serving the Hugo build"
    else
        say "[phone] $LOCAL/ -> HTTP $code, but not the Hugo home page (start_services.sh status)"
    fi
}

# Build the Pages copy and commit it on top of gh-pages without touching the working tree:
# a throwaway index file, write-tree and commit-tree.
build_pages() {
    local tmp out idx tree parent commit rev
    tmp=$(mktemp -d)
    out="$tmp/site"
    idx="$tmp/index"
    rev=$(source_rev)
    hugo_build "$out"
    touch "$out/.nojekyll"   # serve the files as they are; no Jekyll pass

    git_src fetch --quiet origin 2>/dev/null || say "[warn]  git fetch failed; using local refs"
    parent=$(git_src rev-parse -q --verify "refs/remotes/origin/$PAGES_BRANCH" \
             || git_src rev-parse -q --verify "refs/heads/$PAGES_BRANCH" || true)

    (cd "$out" && GIT_DIR="$SRC/.git" GIT_WORK_TREE="$out" GIT_INDEX_FILE="$idx" git add -A)
    tree=$(GIT_INDEX_FILE="$idx" git_src write-tree)
    rm -rf "$tmp"

    if [ -n "$parent" ] && [ "$(git_src rev-parse "$parent^{tree}")" = "$tree" ]; then
        git_src update-ref "refs/heads/$PAGES_BRANCH" "$parent"
        say "[pages] $rev builds the same site as $PAGES_BRANCH $(git_src rev-parse --short "$parent"); no new commit"
        return
    fi
    PAGES_CHANGED=1
    commit=$(git_src commit-tree "$tree" ${parent:+-p "$parent"} \
             -m "Build $rev: $(git_src log -1 --format=%s HEAD)" -m "Built from main with hugo --minify ($BUILT_POSTS posts).")
    git_src update-ref "refs/heads/$PAGES_BRANCH" "$commit"
    PAGES_SHA=$commit
    say "[pages] $PAGES_BRANCH -> $(git_src rev-parse --short "$commit") ($BUILT_POSTS posts), not pushed yet"
}

# Pushing to gh-pages does not reliably start a Pages build: it did for one release and
# not for the next (waited 8 minutes). So wait a little, then ask for a build over the
# API with the same token git uses, and report what GitHub did with it.
await_pages_build() {
    PAGES_SHA="$1" python3 - <<'PYEOF'
import json, os, re, time, urllib.error, urllib.request

REPO = "qofo/qofo.github.io"
sha = os.environ["PAGES_SHA"][:7]
token = re.match(r"https://[^:]+:([^@]+)@", open("/root/.git-credentials").read().strip()).group(1)
headers = {"Authorization": f"token {token}", "User-Agent": "publish_blog", "Accept": "application/vnd.github+json"}

def api(path, method="GET"):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}",
                                 data=b"" if method == "POST" else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {"message": e.read().decode(errors="replace")[:200]}
    except OSError as e:
        return 0, {"message": str(e)}

def latest():
    code, body = api("/pages/builds/latest")
    return (body.get("status"), (body.get("commit") or "")[:7]) if code == 200 else (None, None)

for _ in range(6):          # up to a minute in case GitHub starts one by itself
    if latest()[1] == sha:
        break
    time.sleep(10)
else:
    code, body = api("/pages/builds", "POST")
    if code != 201:
        print(f"[pages] could not request a build (HTTP {code}: {body.get('message', '')})")
        print(f"[pages] ask for one with: gh api -X POST repos/{REPO}/pages/builds")
        raise SystemExit(0)
    print("[pages] no build started on its own; requested one")

for _ in range(30):         # then up to five minutes for it to finish
    status, commit = latest()
    if commit == sha and status in ("built", "errored"):
        where = "https://qofo.github.io/" if status == "built" else "check the repository settings"
        print(f"[pages] build {status} for {commit} -> {where}")
        raise SystemExit(0)
    time.sleep(10)
print(f"[pages] still building; check: gh api repos/{REPO}/pages/builds/latest --jq .status")
PYEOF
}

push_both() {
    local branch
    branch=$(git_src rev-parse --abbrev-ref HEAD)
    [ "$branch" = main ] || die "$SRC is on '$branch', not main"
    say "[push]  origin main $PAGES_BRANCH"
    git_src push --atomic origin main "$PAGES_BRANCH"
    if [ "$PAGES_CHANGED" = 1 ]; then
        await_pages_build "$PAGES_SHA"
    else
        say "[pages] site unchanged; $PAGES_URL keeps its current build"
    fi
}

status() {
    local info="(none)"
    [ -f "$LIVE/.build-info" ] && info=$(tr '\n' ' ' < "$LIVE/.build-info")
    say "Source:  $SRC @ $(source_rev)"
    say "Phone:   $info-> $(readlink "$LIVE" 2>/dev/null || echo 'no build')"
    if git_src rev-parse -q --verify "refs/remotes/origin/$PAGES_BRANCH" >/dev/null; then
        say "Pages:   origin/$PAGES_BRANCH @ $(git_src log -1 --format='%h %s' "origin/$PAGES_BRANCH") (as of last fetch)"
    else
        say "Pages:   origin/$PAGES_BRANCH not found (never published, or not fetched)"
    fi
}

case "${1:-}" in
    phone)
        build_phone
        ;;
    pages)
        build_pages
        ;;
    publish)
        [ -z "$(git_src status --porcelain)" ] || die "$SRC has uncommitted changes; commit them first so both copies match"
        build_pages
        build_phone
        push_both
        ;;
    status)
        status
        ;;
    *)
        sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
        exit 2
        ;;
esac
