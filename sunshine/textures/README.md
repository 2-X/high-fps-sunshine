**`GMSE01-pruned/` (IN GIT, canonical since 2026-08-11)** - the pruned qashto/razius UHD
pack actually in use on the desktop: M-portal textures incl. the full THP preview movie
planes, FLUDD/lives/coin HUD, digits, episode-select wordmarks/logos/shine icons (nothing
else; prune manifest: `../research/memory/sunshine-hd-texture-prune.md`). 228MB, 1155 .dds.
Install: copy the folder to `Load\Textures\GMSE01\`; GFX.ini [Settings] `HiresTextures = True`,
`CacheHiresTextures = True`. Light enough for any GPU (HUD + portals only).

The FULL texture pack zips live here on disk but are .gitignored (GitHub's 100MB limit).
Transfer them by direct copy / cloud drive, or `git lfs track "*.zip"` before committing.
- SMS 4K 2.0c (1080p).zip  (441MB) - was live on the Mac
- SMS 4K 2.0c (4K).zip     (820MB) - recommended for the PC

The SMS launcher's "HD textures: full" setting auto-extracts and installs these zips
on first use; manual extraction below is only needed if the zips are absent.

Install: extract inner `Load/Textures/GMS/` into Dolphin's `Load\Textures\GMS\`.
Enable: GFX.ini [Settings] HiresTextures = True, CacheHiresTextures = True.
