"""Drive smslaunch apply()+launch() for a named profile, headless.

Usage: python drive_launcher.py "Offline 360" [--apply-only]
"""
import json
import sys

sys.path.insert(0, r"C:\code\high-fps-sunshine\sunshine\launcher")

from smslaunch import launcher  # noqa: E402

PROFILES = r"C:\code\high-fps-sunshine\sunshine\launcher\profiles.json"


def main():
    name = sys.argv[1]
    apply_only = "--apply-only" in sys.argv
    data = json.loads(open(PROFILES, encoding="utf-8").read())
    prof = next(p for p in data["profiles"] if p["name"] == name)
    if "--fps" in sys.argv:
        prof = dict(prof)
        prof["fps"] = int(sys.argv[sys.argv.index("--fps") + 1])
    print(f"== profile: {prof}")
    launcher.apply(prof, log=print, force=True)
    if not apply_only:
        launcher.launch(prof, log=print)


if __name__ == "__main__":
    main()
