# John → join the game over Tailscale

Tailscale is a free VPN that puts your PC and Kris's Mac on the same private
network so the game can connect over the internet. You do this once; after that
it just works. Everything happens on YOUR PC except accepting Kris's invite.

## 1. Accept Kris's invite

Kris sends you an invite link (looks like `https://login.tailscale.com/...`).
Open it, sign in with a Google/GitHub/Microsoft account, and accept. This puts
you on Kris's tailnet — that's what lets the two machines see each other.

## 2. Install Tailscale on Windows

```powershell
winget install Tailscale.Tailscale
```

Then launch Tailscale (system tray), sign in with the **same account** you used
to accept the invite, and leave it running/connected.

VERIFY: the Tailscale tray icon says Connected, and
`tailscale ip -4` in PowerShell prints a `100.x.x.x` address (yours).

## 3. Point the game at Kris's Tailscale IP

Kris will give you his Tailscale IP — it starts with `100.` (NOT the old
`192.168.x` LAN address; that only worked in-house). Put it in
`C:\code\high-fps-sunshine\sunshine\launcher\config.local.json`:

```json
{
  "iso_dir":     "C:\\sms\\bsmso-work",
  "dolphin_app": "C:\\code\\high-fps-sunshine\\dolphin-src\\Binary\\x64\\Dolphin.exe",
  "server_addr": "100.117.221.19"
}
```

Kris's Tailscale IP:  **`100.117.221.19`**  (machine `kriss-macbook-pro-193`)

## 4. Verify you can reach him BEFORE launching the game

```powershell
Test-NetConnection 100.117.221.19 -Port 27015
```

`TcpTestSucceeded : True` = you're good, launch the game normally
(`python drive_launcher.py "Online 120"`).

If it's `False`, the game cannot connect — fix this first, don't debug Dolphin:
- Both of you must show Connected in Tailscale.
- Confirm you typed Kris's `100.x` IP, not your own and not a LAN IP.
- Kris's server must be running (ask him to confirm).

## Notes

- Tailscale and your Radmin VPN can conflict — if you used Radmin before, quit
  it while on Tailscale so the game uses the right network.
- Keep Tailscale connected whenever you want to play; it reconnects on reboot if
  you leave it enabled.
