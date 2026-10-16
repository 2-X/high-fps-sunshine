#!/usr/bin/env python3
"""Add the Gaming Mode entries (non-Steam shortcuts) to the RUNNING Steam client.

Talks to Steam's own JS API over the CEF debug port the Deck client keeps open
(127.0.0.1:8080, SharedJSContext), so nothing is edited on disk, Steam is not
restarted, and a running game is not disturbed. Idempotent: an entry that
already exists (matched by name) is updated in place, never duplicated.

    add-steam-shortcuts.py            add / refresh the entries
    add-steam-shortcuts.py --list     show the matching entries and exit
"""
import base64
import json
import os
import socket
import struct
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE = str(HERE / "sms-deck")
ENTRIES = [
    ("Super Mario Sunshine 120fps", "offline"),
    ("Super Mario Sunshine 120fps Online", "online"),
    ("Super Mario Sunshine 120fps Solo (BSE)", "solo"),
]
PORT = 8080


def _ws_eval(js: str):
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5))
    url = next(t for t in tabs if t["title"] == "SharedJSContext")["webSocketDebuggerUrl"]
    path = url.split(f"127.0.0.1:{PORT}", 1)[1]
    s = socket.create_connection(("127.0.0.1", PORT), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    if b" 101 " not in buf.split(b"\r\n", 1)[0]:
        raise RuntimeError(f"websocket upgrade refused: {buf[:80]!r}")
    buf = buf.split(b"\r\n\r\n", 1)[1]
    data = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": js, "awaitPromise": True, "returnByValue": True}}).encode()
    mask, n = os.urandom(4), len(data)
    hdr = b"\x81" + (bytes([0x80 | n]) if n < 126
                     else b"\xfe" + struct.pack(">H", n) if n < 65536
                     else b"\xff" + struct.pack(">Q", n))
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def need(k):
        nonlocal buf
        while len(buf) < k:
            chunk = s.recv(65536)
            if not chunk:
                raise EOFError("Steam closed the debug socket")
            buf += chunk
        out, buf = buf[:k], buf[k:]
        return out

    msg = b""
    while True:
        b0, b1 = need(2)
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", need(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", need(8))[0]
        chunk = need(ln)
        if b0 & 0x0F in (0, 1, 2):
            msg += chunk
            if b0 & 0x80:
                r = json.loads(msg)
                msg = b""
                if r.get("id") == 1:
                    s.close()
                    res = r.get("result", {})
                    if "exceptionDetails" in res:
                        raise RuntimeError(json.dumps(res["exceptionDetails"])[:1500])
                    return res.get("result", {}).get("value")


LIST_JS = """(() => Array.from(appStore.allApps)
  .filter(a => a.app_type == 1073741824 && %s.includes(a.display_name))
  .map(a => ({appid: a.appid, name: a.display_name})))()"""

ADD_JS = """(async () => {
  const [name, exe, startDir, opts] = %s;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let app = Array.from(appStore.allApps)
      .find(a => a.app_type == 1073741824 && a.display_name == name);
  let appid = app ? app.appid : await SteamClient.Apps.AddShortcut(name, exe, startDir, opts);
  await sleep(500);
  // AddShortcut ignores some of its arguments on current clients — set each.
  SteamClient.Apps.SetShortcutName(appid, name);
  SteamClient.Apps.SetShortcutExe(appid, JSON.stringify(exe));
  SteamClient.Apps.SetShortcutStartDir(appid, JSON.stringify(startDir));
  SteamClient.Apps.SetShortcutLaunchOptions(appid, opts);
  await sleep(500);
  return {appid, name, existed: !!app};
})()"""


def main():
    names = [n for n, _ in ENTRIES]
    try:
        if "--list" in sys.argv:
            print(json.dumps(_ws_eval(LIST_JS % json.dumps(names)), indent=1))
            return 0
        for name, mode in ENTRIES:
            r = _ws_eval(ADD_JS % json.dumps([name, EXE, str(HERE), mode]))
            print(f"{'updated' if r['existed'] else 'added  '}: {r['name']} "
                  f"(appid {r['appid']}) -> {EXE} {mode}")
    except (OSError, StopIteration) as exc:
        print(f"Steam's debug port is not reachable ({exc!r}). Is Steam running? "
              "Otherwise add sms-deck by hand: Steam > Add a Non-Steam Game, "
              "launch option 'offline', 'online' or 'solo'.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
