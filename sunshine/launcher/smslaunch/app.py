"""Textual TUI for the Super Mario Sunshine high-FPS launcher.

Left  : saved profiles (select to load, New / Duplicate / Delete).
Right : the editor for the selected profile, then Save / Apply & Launch. The
        launch log streams what exists, what gets generated, and the
        enabled-set diff (no separate preview panel).
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Header, Footer, Static, Button, Input, Select,
                             Checkbox, ListView, ListItem, Label, RichLog)
from textual import work

from . import config as C
from . import launcher as L
from .inieditor import Ini, DolphinRunning
from .profiles import Store, default_profile, normalize


MODES = [("Online (server + bridge)", "online"),
         ("Solo — BSE moveset (no server)", "solo"),
         ("Offline (stock high-fps)", "offline")]
ASPECTS = [(v["label"], k) for k, v in C.ASPECTS.items()]


class Launcher(App):
    CSS = """
    Screen { layout: horizontal; }
    #left { width: auto; border-right: solid $panel; }
    #right { width: 1fr; }
    #profiles { height: 1fr; border: round $panel; }
    .row { height: auto; }
    .lbl { width: 18; content-align: left middle; color: $text-muted; }
    Input, Select { width: 1fr; }
    #qol { height: auto; border: round $panel; padding: 0 1; }
    #log { height: 1fr; min-height: 12; border: round $panel; }
    Button { margin: 0 1 0 0; }
    .title { text-style: bold; color: $accent; }
    """
    BINDINGS = [("ctrl+s", "save", "Save"), ("ctrl+l", "launch", "Apply & Launch"),
                ("ctrl+q", "quit", "Quit"),
                # ctrl+c also quits (priority so it fires even from an Input).
                Binding("ctrl+c", "quit", "Quit", priority=True, show=False)]

    def __init__(self):
        super().__init__()
        self.store = Store()
        self.working = normalize(self.store.last())

    # ---------------------------------------------------------------- compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="left"):
                yield Static("Profiles", classes="title")
                yield ListView(id="profiles")
                with Horizontal(classes="row"):
                    yield Button("New", id="new", variant="primary")
                    yield Button("Dup", id="dup")
                    yield Button("Del", id="del", variant="error")
            with VerticalScroll(id="right"):
                yield Static("Profile", classes="title")
                with Horizontal(classes="row"):
                    yield Label("Name", classes="lbl"); yield Input(id="name")
                with Horizontal(classes="row"):
                    yield Label("Online / Offline", classes="lbl")
                    yield Select(MODES, id="mode", allow_blank=False)
                with Horizontal(classes="row"):
                    yield Label("FPS", classes="lbl"); yield Input(id="fps")
                with Horizontal(classes="row"):
                    yield Label("FOV (h°, blank=keep)", classes="lbl"); yield Input(id="fov")
                with Horizontal(classes="row"):
                    yield Label("Aspect / widescreen", classes="lbl")
                    yield Select(ASPECTS, id="aspect", allow_blank=False)
                # Online-only rows: hidden unless mode == "online" (see _sync).
                with Horizontal(classes="row", id="row_player"):
                    yield Label("Player (online)", classes="lbl")
                    yield Input(id="player_name")
                with Horizontal(classes="row", id="row_skin"):
                    yield Label("Skin (online)", classes="lbl")
                    yield Select(
                        [(n.replace("-", " ").title(), n) for n in C.SKIN_NAMES],
                        id="skin", allow_blank=False,
                    )
                with Horizontal(classes="row", id="row_ghost"):
                    yield Label("Ghost bot", classes="lbl")
                    yield Checkbox("spawn ghost (online)", id="ghost")
                yield Static("QOL fixes", classes="title")
                with VerticalScroll(id="qol"):
                    for key, label, _d, _p in C.QOL_CATALOG:
                        yield Checkbox(label, id=f"qol_{key}")
                    # HD textures live in this section too. It's a texture-pack
                    # selection (not a Gecko code), so it keeps its own
                    # hd_textures field/wiring — only its row moved in here.
                    with Horizontal(classes="row"):
                        yield Label("HD textures", classes="lbl")
                        yield Select(
                            [("Off", "off"),
                             ("Portals + HUD (pruned, 226MB)", "portals"),
                             ("Full pack (SMS 4K 2.0c)", "full")],
                            id="hd_textures", allow_blank=False,
                        )
                with Horizontal(classes="row"):
                    yield Button("Save", id="save", variant="success")
                    yield Button("Apply & Launch", id="launch", variant="warning")
                yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    # ------------------------------------------------------------------ mount
    def on_mount(self):
        self._reload_list()
        self._load_working()
        self._sync()

    def _reload_list(self):
        lv = self.query_one("#profiles", ListView)
        lv.clear()
        for name in self.store.names():
            lv.append(ListItem(Label(name), name=name))
        self._fit_left_width()

    def _fit_left_width(self):
        """Size the left column to the longest profile name (plus panel
        chrome), capped at 40% of the terminal width so it never crowds
        the profile editor on the right."""
        longest = max((len(n) for n in self.store.names()), default=0)
        # chrome: container border-right (1) + list round border (2)
        # + scrollbar slack (2)
        want = longest + 5
        cap = max(1, int(self.size.width * 0.40))
        self.query_one("#left").styles.width = min(want, cap)

    def on_resize(self, _ev=None):
        self._fit_left_width()

    # ------------------------------------------------------- form <-> profile
    def _load_working(self):
        p = self.working
        self.query_one("#name", Input).value = p["name"]
        self.query_one("#mode", Select).value = p["mode"]
        self.query_one("#fps", Input).value = str(p["fps"])
        self.query_one("#fov", Input).value = "" if p.get("fov") is None else str(p["fov"])
        self.query_one("#aspect", Select).value = p["aspect"]
        self.query_one("#player_name", Input).value = p.get("player_name", "Kris")
        self.query_one("#skin", Select).value = (
            p.get("skin") if p.get("skin") in C.SKIN_NAMES else "mario")
        self.query_one("#ghost", Checkbox).value = bool(p["ghost"])
        self.query_one("#hd_textures", Select).value = p.get("hd_textures", "off")
        for key in [k for k, *_ in C.QOL_CATALOG]:
            self.query_one(f"#qol_{key}", Checkbox).value = bool(p["qol"].get(key))

    def _gather(self) -> dict:
        def i(id_): return self.query_one(f"#{id_}", Input).value.strip()
        try:
            fps = int(i("fps"))
        except ValueError:
            fps = 120
        fov_raw = i("fov")
        if fov_raw == "":
            fov = None                 # blank = leave the game's stock FOV
        else:
            try:
                fov = int(fov_raw)
            except ValueError:
                fov = None
        p = {
            "name": i("name") or "Default",
            "mode": self.query_one("#mode", Select).value,
            "fps": fps,
            "fov": fov,
            "aspect": self.query_one("#aspect", Select).value,
            "player_name": i("player_name") or "Kris",
            "skin": self.query_one("#skin", Select).value,
            "ghost": self.query_one("#ghost", Checkbox).value,
            "hd_textures": self.query_one("#hd_textures", Select).value,
            "qol": {k: self.query_one(f"#qol_{k}", Checkbox).value
                    for k, *_ in C.QOL_CATALOG},
        }
        return normalize(p)

    # ----------------------------------------------------- form normalization
    def _sync(self):
        """Gather + normalize the form (bse FPS snap, mode->engine) and push
        the normalized values back. Replaces the old preview refresh."""
        self.working = self._gather()
        self._sync_form_quiet()
        # Grey out QOL codes that don't exist on this engine's disc (e.g. the
        # blue-coin save box: the online build has no blue-coin dialog).
        engine = C.engine_for(self.working["mode"])
        for key, _label, _d, pats in C.QOL_CATALOG:
            cb = self.query_one(f"#qol_{key}", Checkbox)
            cb.disabled = pats.get(engine) is None
        # Player name + ghost bot are only used by the online server/bridge;
        # hide them entirely in solo/offline where they do nothing.
        online = self.working["mode"] == "online"
        self.query_one("#row_player").display = online
        # Skin rides the bridge's comm-block write, so online only for now
        # (solo would need a standalone poke — untested whether the kxe polls
        # LocalMarioModelId without a session).
        self.query_one("#row_skin").display = online
        self.query_one("#row_ghost").display = online

    def _sync_form_quiet(self):
        """Push normalized non-text values back without triggering a preview
        storm. FPS/FOV text inputs are deliberately NOT rewritten here — that
        would fight you mid-keystroke; the preview shows the effective (snapped)
        value, and it's committed on Save."""
        self._quiet = True
        try:
            self.query_one("#mode", Select).value = self.working["mode"]
        finally:
            self._quiet = False

    _quiet = False

    # ------------------------------------------------------------- events
    def on_list_view_selected(self, ev: ListView.Selected):
        name = ev.item.name
        p = self.store.get(name)
        if p:
            self.working = normalize(p)
            self.store.set_last(name)
            self._load_working()
            self._sync()

    def on_input_changed(self, _ev):
        if not self._quiet:
            self._sync()

    def on_select_changed(self, _ev):
        if not self._quiet:
            self._sync()

    def on_checkbox_changed(self, _ev):
        if not self._quiet:
            self._sync()

    def on_button_pressed(self, ev: Button.Pressed):
        bid = ev.button.id
        if bid == "new":
            self.working = default_profile(self._unique_name("New profile"))
            self._load_working(); self._sync()
        elif bid == "dup":
            p = self._gather(); p["name"] = self._unique_name(p["name"] + " copy")
            self.working = p; self._load_working(); self._sync()
        elif bid == "del":
            self.action_delete()
        elif bid == "save":
            self.action_save()
        elif bid == "launch":
            self.action_launch()

    def _unique_name(self, base):
        names = set(self.store.names())
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    # ------------------------------------------------------------- actions
    def action_save(self):
        p = self._gather()
        self.store.upsert(p)
        self.store.set_last(p["name"])
        self.working = p
        self._reload_list()
        self._log(f"[green]Saved profile '{p['name']}'.[/green]")

    def action_delete(self):
        name = self._gather()["name"]
        self.store.delete(name)
        self._reload_list()
        if self.store.profiles:
            self.working = normalize(self.store.profiles[0])
            self._load_working(); self._sync()
        self._log(f"[yellow]Deleted '{name}'.[/yellow]")

    def action_launch(self):
        self.action_save()
        self._log("[b]— Apply & Launch —[/b]")
        self._run_apply_launch(self.working)

    def action_quit(self):
        self.exit()

    # ------------------------------------------------------------- worker
    def _log(self, msg):
        self.query_one("#log", RichLog).write(msg)

    @work(thread=True)
    def _run_apply_launch(self, profile):
        def log(m): self.call_from_thread(self._log, m)
        try:
            L.apply(profile, log=log)
            L.launch(profile, log=log)
            log("[green b]Done.[/green b]")
        except DolphinRunning as e:
            log(f"[red]{e}[/red]")
        except Exception as e:
            log(f"[red]FAILED: {e}[/red]")


def main():
    import sys
    # A newcomer needs an ISO AND the patched Dolphin build before the launcher
    # can do anything. If either is missing, offer the setup wizard on a TTY;
    # otherwise print a clear, actionable, non-interactive error (CI / wrappers).
    missing = []
    if not C.ISO_OFFLINE.exists():
        missing.append(f"ISO not found: {C.ISO_OFFLINE}")
    if not C.DOLPHIN_APP.exists():
        missing.append(f"Dolphin.app not found: {C.DOLPHIN_APP}")

    if missing:
        if sys.stdin.isatty() and sys.stdout.isatty():
            print("\n[sms] Setup is incomplete:")
            for m in missing:
                print(f"      - {m}")
            print()
            try:
                ans = input("Run the first-run setup wizard now? (Y/n): ").strip()
            except EOFError:
                ans = "n"
            if ans == "" or ans[0].lower() == "y":
                from .setup_wizard import run
                run(interactive=True)
                # config.py resolves paths at import time; a fresh process
                # picks up whatever the wizard wrote. Ask the user to re-run
                # rather than hot-reloading module-global constants in place.
                print("\n[sms] Setup finished. Run  ./sms  again to launch.")
                return
            print("      Skipped. Re-run `./sms setup` when ready.")
            sys.exit(1)
        # Non-interactive: clear error, no prompt.
        print(
            "\n[sms] Setup is incomplete (non-interactive):\n"
            + "".join(f"      - {m}\n" for m in missing)
            + "\nRun the setup wizard interactively:\n"
            "      ./sms setup\n"
            "\nOr point the launcher at your files one of two ways:\n"
            "\n  1. sunshine/launcher/config.local.json  (gitignored):\n"
            '       { "iso_offline": "/path/to/Super Mario Sunshine (USA).rvz",\n'
            '         "dolphin_app": "/path/to/Dolphin.app" }\n'
            "     (copy config.local.json.example to get started)\n"
            "\n  2. Environment variables:\n"
            '       export SMS_ISO_OFFLINE="/path/to/Super Mario Sunshine (USA).rvz"\n'
            '       export SMS_DOLPHIN_APP="/path/to/Dolphin.app"\n',
            file=sys.stderr,
        )
        sys.exit(1)
    Launcher().run()


if __name__ == "__main__":
    main()
