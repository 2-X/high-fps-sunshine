"""BSMSO character skins (CharacterPack model ids).

The online mod has a full skin system (Luigi, Wario, Yoshi, ...) that the
Windows launcher exposes as a "Mario model" dropdown. Mechanism, verified
against the decompiled SMSO.Net CharacterPack codec, the _BSMSO.kxe strings,
and PROTOCOL.md:

- A skin is identified by an 8-char lowercase-hex id (upstream
  CustomModels/library.json). The wire/comm encoding is simply the ASCII
  bytes of that id, NUL-padded to 8; all-zero = retail Mario
  (CharacterPack.EncodeModelId).
- The game loads the pack from the DISC at /data/bsmso_models/<id>.arc
  (_BSMSO.kxe format string "%s%s.arc" with prefix "/data/bsmso_models/").
  Missing/invalid pack -> silent retail fallback, no crash. Peers therefore
  only see your skin if their own disc carries the same id (skins_install.py
  puts the packs on ours).
- Selection: comm block LocalMarioModelId @1297 + JoinRequest field; live
  switches go out as MarioModelIntent (TCP id 20) and come back to everyone
  via a forced RosterSnapshot. Remote slots land in RemoteMarioModelIds
  @1305 stride 8 (the bridge mirrors the roster there).

The id->name map below is upstream BSMSO_1.1 CustomModels/library.json
verbatim (ids are content-derived, so any 1.1 install agrees on them).
"""

# Display name -> model id. Names are lowercased, spaces -> "-" for CLI use.
SKINS = {
    "mario":        "",          # retail (empty id)
    "birdo":        "1b683fc7",
    "daytendo":     "36de327c",
    "luigi":        "cadf67c6",
    "needle":       "0654567c",
    "nightendo":    "5d82421c",
    "nokissia":     "6121808b",
    "piantissimo":  "9f79b83f",
    "shadow":       "23704068",
    "shadow-luigi": "cc27492b",
    "shadow-mario": "9598bd9d",
    "sonic":        "841192a3",
    "waluigi":      "78044865",
    "wario":        "3c297fff",
    "yoshi":        "f130b25e",
}

SKIN_NAMES = sorted(SKINS)


def resolve_skin(spec: str) -> str:
    """Skin name or raw 8-hex id -> normalized model id ('' = retail).

    Raises ValueError on anything unrecognized so a typo'd --skin fails the
    launch loudly instead of silently playing retail Mario.
    """
    s = (spec or "").strip().lower().replace(" ", "-")
    if s in ("", "retail", "none", "off"):
        return ""
    if s in SKINS:
        return SKINS[s]
    if len(s) == 8 and all(c in "0123456789abcdef" for c in s):
        return s  # raw id: allows packs we don't know a name for
    raise ValueError(
        f"unknown skin {spec!r} — use one of {', '.join(SKIN_NAMES)} "
        f"or a raw 8-hex model id")


def encode_model_id(model_id: str) -> bytes:
    """Model id string -> the 8-byte comm/wire field (ASCII, NUL-padded)."""
    return model_id.encode("ascii")[:8].ljust(8, b"\x00")


def skin_name(model_id: str) -> str:
    """Model id -> display name (falls back to the raw id)."""
    for name, mid in SKINS.items():
        if mid == model_id:
            return name
    return model_id or "mario"
