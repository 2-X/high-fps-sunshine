# high-fps-sunshine: Super Mario Sunshine at 120–240fps

Play Super Mario Sunshine (NTSC-U, GMSE01) at 120fps and beyond — 240fps
confirmed on both an M2 MacBook and a Windows PC — with correct game speed,
audio, timers, and animations. Built from a patched Dolphin fork, a curated and
generated Gecko code stack, and a Textual TUI launcher. Optional widescreen
(16:9 / 16:10 including 2D screens), online multiplayer via BSMSO (cross-rate
supported), and HD textures.

**No Nintendo game files are included or distributed. You must dump your own disc.**

Full documentation, setup guide, and technical reference:
**[sunshine/README.md](sunshine/README.md)**

> Formerly `2-X/high-fps-dolphin` (archived). Full history preserved here;
> existing clones: `git remote set-url origin https://github.com/2-X/high-fps-sunshine.git`

---

### Quick orientation

| Path | Contents |
|---|---|
| `sunshine/README.md` | Public-facing setup guide and technical reference (start here) |
| `sunshine/launcher/` | TUI launcher (`sunshine/launcher/sms` to run) |
| `sunshine/research/scripts/fpspatch.py` | The bundle generator — emits the full Gecko fix stack for any target rate |
| `sunshine/dolphin-patches/` | `high-fps-dolphin.patch` + build instructions |
| `sunshine/HIGH-FPS-CATALOG.md` | Master fix catalog (addresses, Gecko, root causes) |
| `sunshine/HANDOFF-PC.md` | Windows / high-fps-PC reference |
| `sunshine/HANDOFF-MAC.md` | Mac setup router |
| `sunshine/HANDOFF-MAC-240.md` | 240fps on the M2: peek gate + loose-SyncGPU dual-core |
| `sunshine/bsmso/` | Online multiplayer (BSMSO) integration, bridge, tooling |

---

### Dependencies not vendored here

```bash
# patched Dolphin (required for correct audio and full Gecko code capacity)
git clone https://github.com/dolphin-emu/dolphin
cd dolphin
git checkout $(cut -d' ' -f1 sunshine/dolphin-patches/UPSTREAM_COMMIT.txt)
git apply sunshine/dolphin-patches/high-fps-dolphin.patch
# then: mkdir build && cd build && cmake .. && make -j$(nproc)

# SMS decomp (JP) - research reference only
git clone https://github.com/doldecomp/sms
```

Texture pack zips are `.gitignored` (GitHub 100 MB limit). A curated subset
(M-portal textures, HUD elements) is committed at `sunshine/textures/GMSE01-pruned/`.
Full packs: see [sunshine/README.md §6](sunshine/README.md#6-hd-texture-packs-links-only).
