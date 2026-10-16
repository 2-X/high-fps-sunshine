#!/usr/bin/env python3
r"""
gecko.py — reliably add / replace / list / remove Gecko codes in a Dolphin
per-game GameSettings INI (default: the USA Super Mario Sunshine user INI).

WHY THIS EXISTS
---------------
Dolphin loads the *user* GameSettings INI at
  macOS:   ~/Library/Application Support/Dolphin/GameSettings/GMSE01.ini
  Windows: %APPDATA%\Dolphin Emulator\GameSettings\GMSE01.ini
and REWRITES it from its in-memory copy whenever it closes after you touched
per-game settings (e.g. toggled a Gecko code). So any edit made to that file
*while Dolphin is running* is silently reverted on quit. That is the "codes
don't show up" bug.

Rule enforced here: Dolphin must be fully quit before we edit. Then relaunch.

USAGE
-----
  # list current code titles
  python3 gecko.py list

  # add/replace a code (idempotent: replaces an existing code with same title)
  python3 gecko.py add --title "120fps + Diag-S" --code-file /tmp/diag_s.txt
  # ...or inline (use \n between the 8-hex-pair lines):
  python3 gecko.py add --title "My Code" --code $'044167B8 40000000\n042FCB24 60000000'

  # remove a code by (sub)string match on its title
  python3 gecko.py remove --title "Diag-S"

  # enable a code so its checkbox is ticked on next launch
  # (--title may be a substring; it is resolved against [Gecko] and the FULL
  #  matched title is written — Dolphin matches enabled entries by exact title)
  python3 gecko.py enable --title "120fps + Diag-S"

Options: --ini PATH (override target), --force (skip the Dolphin-running guard).
Every mutating op backs up the INI to <ini>.bak first.
"""
import argparse, os, re, subprocess, sys, shutil

if os.environ.get("SMS_DOLPHIN_USER"):
    # Same override the launcher honors (smslaunch.config): a Dolphin user dir
    # that is not the platform default, e.g. the Steam Deck's `-u` directory.
    USER_INI = os.path.join(os.path.expanduser(os.environ["SMS_DOLPHIN_USER"]),
                            "GameSettings", "GMSE01.ini")
elif sys.platform == "win32":
    USER_INI = os.path.join(os.environ.get("APPDATA", ""),
                            "Dolphin Emulator", "GameSettings", "GMSE01.ini")
else:
    USER_INI = os.path.expanduser(
        "~/Library/Application Support/Dolphin/GameSettings/GMSE01.ini")


def dolphin_running():
    """True only if the actual Dolphin emulator process is alive.

    Match the *process name* exactly — never the command line. The old check
    was `pgrep -if dolphin`, and -f matches the full argv: since this repo
    lives at .../high-fps-dolphin/, every helper launched from it (the BSMSO
    bridge.py / ghost_bot.py / memhelper, editors, this script itself) matched
    and the guard refused to write even with Dolphin fully quit.
    """
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Dolphin.exe", "/NH"],
                capture_output=True, text=True).stdout
            return "Dolphin.exe" in out
        # -x = exact match on the process name (the app-bundle binary is
        # Dolphin.app/Contents/MacOS/Dolphin). Case-sensitive on purpose.
        return subprocess.run(["pgrep", "-x", "Dolphin"],
                              capture_output=True, text=True).returncode == 0
    except Exception:
        return False


def read(ini):
    if not os.path.exists(ini):
        sys.exit(f"INI not found: {ini}")
    with open(ini, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write(ini, text):
    bak = ini + ".bak"
    shutil.copyfile(ini, bak)
    # normalize: exactly one trailing newline, no CRLF surprises
    text = text.replace("\r\n", "\n").rstrip("\n") + "\n"
    with open(ini, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {ini}  (backup: {bak})")


# ---- section helpers -------------------------------------------------------
SECT = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$", re.M)


def sections(text):
    """Return list of (name, start_idx, end_idx) covering each [Section]."""
    marks = [(m.group("name"), m.start()) for m in SECT.finditer(text)]
    res = []
    for i, (name, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        res.append((name, start, end))
    return res


def get_section(text, name):
    for n, s, e in sections(text):
        if n == name:
            return s, e
    return None


def ensure_section(text, name):
    if get_section(text, name):
        return text
    if not text.endswith("\n"):
        text += "\n"
    return text + f"[{name}]\n"


def code_titles(text, section="Gecko"):
    span = get_section(text, section)
    if not span:
        return []
    body = text[span[0]:span[1]]
    return [ln[1:].strip() for ln in body.splitlines() if ln.startswith("$")]


# ---- commands --------------------------------------------------------------
def cmd_list(text, args):
    print("[Gecko] codes:")
    for t in code_titles(text):
        print("  $" + t)
    print("\n[Gecko_Enabled]:")
    span = get_section(text, "Gecko_Enabled")
    if span:
        for ln in text[span[0]:span[1]].splitlines():
            if ln.startswith("$"):
                print("  " + ln)
    return None  # read-only


def _remove_block(text, title_substr, section="Gecko"):
    """Remove a $title code block (title + its hex lines up to next $ or section)."""
    span = get_section(text, section)
    if not span:
        return text, False
    s, e = span
    body = text[s:e]
    lines = body.splitlines(keepends=True)
    out, removed, i = [], False, 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("$") and title_substr in ln[1:]:
            removed = True
            i += 1
            while i < len(lines) and not lines[i].startswith("$") and not lines[i].startswith("["):
                i += 1
            continue
        out.append(ln)
        i += 1
    return text[:s] + "".join(out) + text[e:], removed


def cmd_add(text, args):
    if not args.title:
        sys.exit("--title required")
    code = args.code
    if args.code_file:
        code = read(args.code_file)
    if not code:
        sys.exit("provide --code or --code-file")
    # sanitize code lines: keep only 8+space+8 hex pair lines
    good = []
    for ln in code.replace("\r\n", "\n").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if re.fullmatch(r"[0-9A-Fa-f]{8} [0-9A-Fa-f]{8}", ln):
            good.append(ln.upper())
        else:
            sys.exit(f"bad code line (need 'XXXXXXXX XXXXXXXX'): {ln!r}")
    # replace if exists
    text, existed = _remove_block(text, args.title)
    text = ensure_section(text, "Gecko")
    s, e = get_section(text, "Gecko")
    block = f"${args.title}\n" + "\n".join(good) + "\n"
    # insert at end of [Gecko] section
    seg = text[s:e]
    seg = seg.rstrip("\n") + "\n" + block
    text = text[:s] + seg + text[e:]
    if args.enable:
        text = _enable(text, args.title)
    if "[" in args.title:
        print(f"WARNING: title contains '[' — Dolphin treats the bracket part as a "
              f"creator suffix and matches enable-lines against the stripped name "
              f"{dolphin_name(args.title)!r}. Prefer bracket-free titles.")
    print(("replaced" if existed else "added") + f" ${args.title} ({len(good)} lines)")
    return text


def dolphin_name(title):
    """The name Dolphin matches [Gecko_Enabled] lines against: it parses
    `$Name [creator]` by splitting at the first '[' and whitespace-stripping
    (GeckoCodeConfig.cpp), but compares enabled lines VERBATIM against that
    stripped name (CheatCodes.h). Writing a bracketed title into
    [Gecko_Enabled] therefore silently never enables the code — this kept the
    `... [kris]` BSE-120 particle-parity code uninstalled for days."""
    return title.split("[", 1)[0].strip()


def _enable(text, title):
    """Append $title to [Gecko_Enabled], normalized to the exact name Dolphin
    matches on (bracket/creator suffix stripped — see dolphin_name). A partial
    or bracket-suffixed title here silently never ticks the code."""
    name = dolphin_name(title)
    text = ensure_section(text, "Gecko_Enabled")
    s, e = get_section(text, "Gecko_Enabled")
    enabled = [ln[1:].strip() for ln in text[s:e].splitlines()
               if ln.startswith("$")]
    if name in enabled:
        return text
    seg = text[s:e].rstrip("\n") + f"\n${name}\n"
    return text[:s] + seg + text[e:]


def resolve_title(text, title_substr):
    """Resolve a (sub)string against the $ titles in [Gecko] (same substring
    matching as `remove`) and return the single full title. Exits on zero or
    ambiguous matches; an exact match wins over other substring matches."""
    titles = code_titles(text)
    matches = [t for t in titles if title_substr in t]
    if title_substr in matches:
        return title_substr
    if not matches:
        sys.exit(f"no [Gecko] code title contains {title_substr!r}\n"
                 "run `gecko.py list` to see available titles")
    if len(matches) > 1:
        sys.exit(f"{title_substr!r} is ambiguous, matches:\n"
                 + "\n".join(f"  ${t}" for t in matches))
    return matches[0]


def cmd_enable(text, args):
    if not args.title:
        sys.exit("--title required")
    full = resolve_title(text, args.title)
    print(f"enabled ${full}")
    return _enable(text, full)


def cmd_remove(text, args):
    if not args.title:
        sys.exit("--title required")
    text, removed = _remove_block(text, args.title)
    text2, _ = _remove_block(text, args.title, section="Gecko_Enabled")
    print(("removed" if removed else "no match for") + f" {args.title!r}")
    return text2


def main():
    ap = argparse.ArgumentParser(description="Manage Dolphin Gecko codes safely.")
    ap.add_argument("cmd", choices=["list", "add", "remove", "enable"])
    ap.add_argument("--title")
    ap.add_argument("--code")
    ap.add_argument("--code-file")
    ap.add_argument("--enable", action="store_true", help="also tick the checkbox")
    ap.add_argument("--ini", default=USER_INI)
    ap.add_argument("--force", action="store_true", help="skip the Dolphin-running guard")
    args = ap.parse_args()

    mutating = args.cmd in ("add", "remove", "enable")
    if mutating and dolphin_running() and not args.force:
        sys.exit("REFUSING: Dolphin is running — it will overwrite this edit on quit.\n"
                 "Quit Dolphin fully, then re-run. (Override with --force only if you "
                 "know Dolphin won't rewrite the INI.)")

    text = read(args.ini)
    result = {"list": cmd_list, "add": cmd_add,
              "remove": cmd_remove, "enable": cmd_enable}[args.cmd](text, args)
    if result is not None:
        write(args.ini, result)


if __name__ == "__main__":
    main()
