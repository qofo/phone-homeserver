#!/data/data/com.termux/files/usr/bin/sh
# Runs Claude Code inside a tmux session so the work keeps going after the SSH
# terminal closes. Running this again later re-attaches to the same session.
#
# Must be started from the Termux side, outside proot: a tmux server started inside
# proot is a proot tracee and dies with the login session (--kill-on-exit).
PREFIX=/data/data/com.termux/files/usr
TMUX_BIN=$PREFIX/bin/tmux
SESSION=claude

# Termux sets this only in login shells (profile.d/tmux.sh). Pin it so the shell that
# creates the session and the one that re-attaches later always find the same socket.
export TMUX_TMPDIR=${TMUX_TMPDIR:-$PREFIX/var/run}

if [ "$(awk '/^TracerPid/{print $2}' /proc/$$/status)" != "0" ]; then
    echo "claude-session: run this from the Termux shell, not inside proot ('exit' first)." >&2
    exit 1
fi

if "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
    exec "$TMUX_BIN" attach-session -t "$SESSION"
fi

# Resume the latest /root conversation; fall back to a login shell when Claude exits
exec "$TMUX_BIN" new-session -s "$SESSION" \
    "$PREFIX/bin/proot-distro login ubuntu -- /bin/bash -lc 'cd /root && claude --continue; exec bash -l'"
