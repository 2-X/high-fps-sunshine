#!/bin/zsh
# BSMSO online keepalive — supervises the dedicated server + your bridge so the
# session can't stay down once it's up. Runs forever; launchd restarts it if it
# ever exits (see com.kris.bsmso-keepalive.plist).
#
# Why a watchdog and not just launchd KeepAlive on each process: the failure we
# hit was a *wedged* bridge — the process stayed alive but its TCP link to the
# server went CLOSED and it never recovered ("Server not ready (Host is down)"
# on loop). "Process alive" is not health here. So:
#   * server  -> restarted whenever the process is gone.
#   * bridge  -> we own exactly one child (tracked by PID), and only restart it
#                on the real wedge signature (Server-not-ready while the server
#                is actually up). Normal stage transitions / title screen leave
#                the bridge's own retry loop alone, so a live puppet never drops.
#
#   start:  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kris.bsmso-keepalive.plist
#   stop:   launchctl bootout   gui/$(id -u)/com.kris.bsmso-keepalive
#   log:    /tmp/bsmso-keepalive.log   (bridge: /tmp/bsmso-bridge.log, server: /tmp/bsmso-server.log)
set -u
export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH

DIR="${0:A:h}"                     # this script's dir (mac-online)
LOG=/tmp/bsmso-keepalive.log
BRIDGE_LOG=/tmp/bsmso-bridge.log
INTERVAL=5                         # seconds between checks
WEDGE_LIMIT=4                      # consecutive wedge checks (~20s) before restart
BRIDGE_ARGS=(--server 127.0.0.1 --name Kris --aspect 2 --skin mario)
BPID=0                             # PID of the one bridge child we own

log(){ print -r -- "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG" }

server_up(){ pgrep -f SMSO.ServerHost >/dev/null }
dolphin_up(){ pgrep -x Dolphin >/dev/null }
bridge_running(){ (( BPID > 0 )) && kill -0 "$BPID" 2>/dev/null }
bridge_connected(){ lsof -nP -iTCP@127.0.0.1:27015 -sTCP:ESTABLISHED 2>/dev/null | grep -q Python }
# The exact failure mode we recover from: alive but can't reach an up server.
bridge_wedged(){ server_up && tail -5 "$BRIDGE_LOG" 2>/dev/null | grep -q "Server not ready"; }

start_server(){
  log "server down -> starting"
  nohup "$DIR/run_server.sh" >/tmp/bsmso-server.log 2>&1 &
  sleep 3
  server_up && log "server up" || log "server FAILED (see /tmp/bsmso-server.log)"
}

start_bridge(){
  # Reconcile to exactly one bridge: kill ours and any stray, then launch fresh.
  (( BPID > 0 )) && kill "$BPID" 2>/dev/null
  pkill -f 'bridge\.py' 2>/dev/null
  pkill -f 'memhelper/memhelper' 2>/dev/null
  sleep 1
  nohup python3 -u "$DIR/bridge.py" ${BRIDGE_ARGS} >"$BRIDGE_LOG" 2>&1 &
  BPID=$!
  log "bridge started pid=$BPID"
  sleep 2
}

log "=== keepalive started (dir=$DIR) ==="
wedge=0
while true; do
  server_up || start_server

  if dolphin_up; then
    if ! bridge_running; then
      start_bridge; wedge=0
    elif bridge_connected; then
      wedge=0                                 # healthy, in a stage, linked
    elif bridge_wedged; then
      (( wedge++ ))
      if (( wedge >= WEDGE_LIMIT )); then
        log "bridge wedged (Server-not-ready x${WEDGE_LIMIT}) -> restarting"
        start_bridge; wedge=0
      fi
    else
      wedge=0                                 # between stages / title: leave its own retry
    fi
  else
    wedge=0                                   # no game booted; nothing to bridge
  fi

  sleep $INTERVAL
done
