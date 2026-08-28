"""Named launch profiles + last-used state, persisted as JSON next to the app.

A profile is a plain dict (JSON-friendly). `default_profile()` documents the
schema and supplies sane values; `normalize()` repairs/upgrades older entries so
hand-edited or older files never crash the UI.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C


def default_profile(name="Default") -> dict:
    return {
        "name": name,
        "mode": "online",           # online (BSE disc) | offline (stock SMS disc)
        "fps": 120,                 # online: BSE native set; offline: any mult of 60
        "fov": 95,                  # HORIZONTAL FOV, degrees (the normal game number)
        "aspect": "mac",            # mac (16:10) | tv (16:9)
        "ghost": False,             # online only: also spawn the ghost bot
        # "off" | "portals" | "full"
        #   off     — no hires textures
        #   portals — pruned pack (M-portals, HUD icons; ~226MB vendored symlink)
        #   full    — full qashto/razius SMS 4K 2.0c pack (~770MB; Load/Textures/GMS)
        "hd_textures": "off",
        "player_name": "Player",    # online: name sent to the server
        # online: character skin (BSMSO CharacterPack) — a skins.py name
        # ("luigi") or raw 8-hex id. Needs the pack on the disc
        # (bsmso/mac-online/skins_install.py); missing pack = retail fallback.
        "skin": "mario",
        "qol": {k: dflt for k, _lbl, dflt, _pats in C.QOL_CATALOG},
    }


def normalize(p: dict) -> dict:
    d = default_profile(p.get("name", "Default"))
    d.update({k: p[k] for k in d if k in p and k != "qol"})
    # --- migrate legacy hd_portals bool → hd_textures tri-state ----------------
    # The generic d.update loop above only copies keys present in default_profile,
    # so "hd_textures" (new key) is already handled — but old profiles that have
    # only "hd_portals" need an explicit lift here.
    if "hd_textures" not in p and p.get("hd_portals"):
        d["hd_textures"] = "portals"
    # Clamp any unrecognised value (hand-edit typos, future rollback) to "off".
    if d.get("hd_textures") not in ("off", "portals", "full"):
        d["hd_textures"] = "off"
    q = dict(d["qol"])
    for k, v in (p.get("qol") or {}).items():
        if k in q:
            q[k] = bool(v)
    d["qol"] = q
    if d["mode"] not in ("online", "solo", "offline"):
        d["mode"] = "online"
    # Skin: unknown names/typos fall back to retail rather than crashing the
    # bridge launch later (resolve_skin raises there, loudly).
    try:
        C.SKINS_MOD.resolve_skin(d.get("skin", "mario"))
    except ValueError:
        d["skin"] = "mario"
    # FPS: BSE (online + solo) snaps to a native BSE value. Offline is any
    # multiple of 60, floor 60 (60 = native, no bundle; >=120 = fpspatch bundle).
    if C.engine_for(d["mode"]) == "bse":
        if d["fps"] not in C.BSE_FPS_VALUES:
            d["fps"] = min(C.BSE_FPS_VALUES, key=lambda x: abs(x - d["fps"]))
    else:
        d["fps"] = max(60, round(d["fps"] / 60) * 60)
    # FOV is horizontal degrees, clamped to a sane range — or None ("leave the
    # game's stock FOV alone", shown as a blank field).
    if d.get("fov") in (None, ""):
        d["fov"] = None
    else:
        d["fov"] = max(C.HFOV_MIN, min(C.HFOV_MAX, int(d["fov"])))
    return d


class Store:
    def __init__(self):
        self.profiles: list[dict] = []
        self.last_name: str | None = None
        self._src = C.PROFILES_JSON
        self.load()

    def load(self):
        # profiles.local.json (gitignored) shadows profiles.json when present —
        # lets individual machines keep personal profiles without dirtying the
        # tracked file. Saving always writes back to whichever file was loaded.
        src = C.PROFILES_LOCAL_JSON if C.PROFILES_LOCAL_JSON.exists() else C.PROFILES_JSON
        self._src = src
        if src.exists():
            try:
                raw = json.loads(src.read_text())
                self.profiles = [normalize(p) for p in raw.get("profiles", [])]
                self.last_name = raw.get("last")
            except Exception:
                self.profiles = []
        if not self.profiles:
            online = default_profile("Online 120")
            online.update(mode="online", fps=120, fov=95)
            offline = default_profile("Offline 240")
            offline.update(mode="offline", fps=240, fov=95)
            self.profiles = [normalize(online), normalize(offline)]
            self.last_name = "Online 120"
            self.save()

    def save(self):
        dest = getattr(self, "_src", C.PROFILES_JSON)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(
            {"last": self.last_name, "profiles": self.profiles}, indent=2))

    # ---- CRUD --------------------------------------------------------------
    def names(self) -> list[str]:
        return [p["name"] for p in self.profiles]

    def get(self, name: str) -> dict | None:
        return next((p for p in self.profiles if p["name"] == name), None)

    def upsert(self, profile: dict):
        profile = normalize(profile)
        for i, p in enumerate(self.profiles):
            if p["name"] == profile["name"]:
                self.profiles[i] = profile
                break
        else:
            self.profiles.append(profile)
        self.save()

    def delete(self, name: str):
        self.profiles = [p for p in self.profiles if p["name"] != name]
        self.save()

    def set_last(self, name: str):
        self.last_name = name
        self.save()

    def last(self) -> dict:
        return self.get(self.last_name) or (self.profiles[0] if self.profiles
                                            else default_profile())
