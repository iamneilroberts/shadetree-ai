#!/usr/bin/env bash
# Start, stop or check the shadetree console and its Cloudflare tunnel.
#   scripts/console-restart.sh                 restart both (stops any that are running first); console in --demo mode
#   scripts/console-restart.sh start --port /dev/serial/by-id/<adapter>    restart with your own console arguments
#   scripts/console-restart.sh stop | status
# Options (before the console arguments): --no-tunnel  leave the tunnel alone (console only)
# Env: SHADETREE_PORT (8765), SHADETREE_HOST (shadetree.fuxed.org)
# Only touches this project's processes: the console on SHADETREE_PORT and the cloudflared whose
# TUNNEL_TOKEN is ours. Other cloudflared tunnels on this machine are never stopped.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${SHADETREE_PORT:-8765}"
HOST="${SHADETREE_HOST:-shadetree.fuxed.org}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/shadetree"
CFG="$HOME/.config/shadetree"
TOKEN_FILE="$CFG/tunnel-token"
PY="$REPO/.venv/bin/python"   # a worktree has no .venv of its own: fall back to the main clone's
[ -x "$PY" ] || PY="/home/neil/dev/obd-reader/.venv/bin/python"
mkdir -p "$STATE" && chmod 700 "$STATE"

cmd="${1:-start}"; [ $# -gt 0 ] && shift
tunnel=1
if [ "${1:-}" = "--no-tunnel" ]; then tunnel=0; shift; fi
args=("$@"); [ ${#args[@]} -eq 0 ] && args=(--demo)

console_pids() {  # this port's console, whether we started it or you did by hand
  pgrep -f -- "obd_reader console .*--http-port $PORT( |$)|shadetree-ai console .*--http-port $PORT( |$)" || true
}
tunnel_pids() {   # cloudflared processes that carry our token (read from /proc, never printed)
  [ -s "$TOKEN_FILE" ] || return 0
  local want p; want="$(cat "$TOKEN_FILE")"
  for p in $(pgrep -x cloudflared || true); do
    [ "$(tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | sed -n 's/^TUNNEL_TOKEN=//p')" = "$want" ] && echo "$p"
  done
}
stop_pids() {  # TERM, wait up to 5 s, then KILL
  local label="$1"; shift
  [ $# -eq 0 ] && { echo "$label: not running"; return; }
  kill "$@" 2>/dev/null
  for _ in $(seq 1 25); do kill -0 "$@" 2>/dev/null || break; sleep 0.2; done
  kill -9 "$@" 2>/dev/null
  echo "$label: stopped ($*)"
}
do_stop() {
  stop_pids console $(console_pids)
  [ $tunnel -eq 1 ] && stop_pids tunnel $(tunnel_pids)
  return 0
}
need_token() {
  [ -s "$TOKEN_FILE" ] && return 0
  echo "tunnel: no $TOKEN_FILE yet; fetching it with remote_access.py (needs ~/.config/shadetree/cloudflare.env)"
  mkdir -p "$CFG" && chmod 700 "$CFG"
  ( umask 077; python3 "$REPO/scripts/remote_access.py" token > "$TOKEN_FILE" ) && [ -s "$TOKEN_FILE" ] \
    || { rm -f "$TOKEN_FILE"; echo "tunnel: could not get a token. Save one in $TOKEN_FILE (chmod 600) and rerun, or use --no-tunnel." >&2; return 1; }
}
do_start() {
  [ -x "$PY" ] || { echo "no $PY: run python3 -m venv .venv && .venv/bin/pip install -e . in $REPO" >&2; exit 1; }
  [ $tunnel -eq 1 ] && { need_token || exit 1; }
  do_stop
  ( umask 077; : > "$STATE/console.log" )
  cd "$REPO" || exit 1
  PYTHONPATH="$REPO/src" setsid nohup "$PY" -m obd_reader console "${args[@]}" --http-port "$PORT" --allow-host "$HOST" \
      >> "$STATE/console.log" 2>&1 < /dev/null &
  echo $! > "$STATE/console.pid"
  for _ in $(seq 1 50); do grep -q "^console" "$STATE/console.log" 2>/dev/null && break; sleep 0.2; done
  if ! grep -q "^console" "$STATE/console.log"; then echo "console: did not start. Last log lines:" >&2; tail -5 "$STATE/console.log" >&2; exit 1; fi
  echo "console: started (pid $(cat "$STATE/console.pid"), log $STATE/console.log)"
  if [ $tunnel -eq 1 ]; then
    ( umask 077; : > "$STATE/tunnel.log" )
    TUNNEL_TOKEN="$(cat "$TOKEN_FILE")" setsid nohup cloudflared tunnel --no-autoupdate run >> "$STATE/tunnel.log" 2>&1 < /dev/null &
    echo $! > "$STATE/tunnel.pid"
    for _ in $(seq 1 50); do grep -q "Registered tunnel connection" "$STATE/tunnel.log" 2>/dev/null && break; sleep 0.3; done
    grep -q "Registered tunnel connection" "$STATE/tunnel.log" && echo "tunnel: connected (pid $(cat "$STATE/tunnel.pid"))" \
      || echo "tunnel: started but no connection yet; check $STATE/tunnel.log" >&2
  fi
  echo; grep -E "^console" "$STATE/console.log"
}
do_status() {
  local c t; c="$(console_pids | tr '\n' ' ')"; t="$(tunnel_pids | tr '\n' ' ')"
  echo "console (port $PORT): ${c:-not running}"
  echo "tunnel (our token):  ${t:-not running}"
  [ -n "$c" ] && grep -E "^console" "$STATE/console.log" 2>/dev/null
  return 0
}
case "$cmd" in
  start|restart) do_start ;;
  stop) do_stop ;;
  status) do_status ;;
  *) echo "usage: $0 [start|stop|status] [--no-tunnel] [console arguments]" >&2; exit 2 ;;
esac
