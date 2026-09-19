#!/bin/bash
# Publish the Hugo blog to both places from one source (/root/qofo.github.io).
#
#   publish_blog.sh phone     build the phone copy and switch serve_blog.py to it (no restart)
#   publish_blog.sh publish   require a clean, committed tree, build the phone copy, then
#                             git push so GitHub Actions rebuilds https://qofo.github.io/
#   publish_blog.sh status    which commit each copy serves
#
# Builds go to /root/blog_builds/<UTC time>; /root/blog_public is a symlink to the live one,
# replaced with rename(2), so a request never sees a half-written site. The last 3 builds
# are kept for rollback: ln -sfn <older build> /root/blog_public
set -euo pipefail

SRC=/root/qofo.github.io
LIVE=/root/blog_public
BUILDS=/root/blog_builds
KEEP=3
LOCAL=http://127.0.0.1:8080

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

source_rev() {
    local rev dirty=""
    rev=$(git -C "$SRC" rev-parse --short HEAD)
    [ -n "$(git -C "$SRC" status --porcelain)" ] && dirty="-dirty"
    printf '%s%s' "$rev" "$dirty"
}

build_phone() {
    command -v hugo >/dev/null || die "hugo is not installed (apt-get install hugo)"
    local stamp out rev posts
    stamp=$(date -u +%Y%m%d-%H%M%S)
    out="$BUILDS/$stamp"
    rev=$(source_rev)
    mkdir -p "$BUILDS"

    say "[build] $SRC @ $rev -> $out"
    if ! nice -n 10 hugo --source "$SRC" --environment phone --minify --destination "$out" \
            --cleanDestinationDir --logLevel warn; then
        rm -rf "$out"
        die "hugo build failed; the live site is unchanged"
    fi
    [ -f "$out/index.html" ] || { rm -rf "$out"; die "build has no index.html; the live site is unchanged"; }
    posts=$(find "$out/posts" -mindepth 2 -name index.html | wc -l)
    printf 'commit=%s\nbuilt=%s\nposts=%s\n' "$rev" "$(date -u '+%F %T UTC')" "$posts" > "$out/.build-info"

    # Atomic switch: make a new symlink, then rename it over the old one
    ln -sfn "$out" "$LIVE.tmp"
    mv -T "$LIVE.tmp" "$LIVE"
    say "[live]  $LIVE -> $out ($posts posts)"

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
        say "[check] $LOCAL/ -> HTTP $code, serving the Hugo build"
    else
        say "[check] $LOCAL/ -> HTTP $code, but not the Hugo home page (is serve_blog.py running? start_services.sh status)"
    fi
}

push_pages() {
    local branch ahead
    branch=$(git -C "$SRC" rev-parse --abbrev-ref HEAD)
    [ "$branch" = main ] || die "$SRC is on '$branch', not main"
    git -C "$SRC" fetch --quiet origin main
    ahead=$(git -C "$SRC" rev-list --count origin/main..HEAD)
    if [ "$ahead" = 0 ]; then
        say "[pages] origin/main already has $(git -C "$SRC" rev-parse --short HEAD); nothing to push"
        return
    fi
    say "[pages] pushing $ahead commit(s) to origin/main"
    git -C "$SRC" push origin main
    if command -v gh >/dev/null; then
        sleep 5
        gh run list --repo qofo/qofo.github.io --limit 1 \
            --json databaseId,status,displayTitle --template '{{range .}}[pages] Actions run {{.databaseId}}: {{.status}} ({{.displayTitle}}){{"\n"}}{{end}}' || true
        say "[pages] follow with: gh run watch --repo qofo/qofo.github.io"
    fi
}

status() {
    local info="(none)"
    [ -f "$LIVE/.build-info" ] && info=$(tr '\n' ' ' < "$LIVE/.build-info")
    say "Source:  $SRC @ $(source_rev)"
    say "Phone:   $info-> $(readlink "$LIVE" 2>/dev/null || echo 'no build')"
    if git -C "$SRC" rev-parse --verify --quiet origin/main >/dev/null; then
        say "Pages:   origin/main @ $(git -C "$SRC" rev-parse --short origin/main) (last fetch; https://qofo.github.io/)"
    fi
}

case "${1:-}" in
    phone)
        build_phone
        ;;
    publish)
        [ -z "$(git -C "$SRC" status --porcelain)" ] || die "$SRC has uncommitted changes; commit them first so both copies match"
        build_phone
        push_pages
        ;;
    status)
        status
        ;;
    *)
        sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
        exit 2
        ;;
esac
