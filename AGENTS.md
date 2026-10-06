# Agent instructions

## Scope and ownership

This repository is **bring your own game copy**. Only original tooling,
documentation and synthetic tests belong in Git. Never add game files, binaries,
decompiled game code, extracted meshes/textures, manifests, screenshots, `.blend`
files or locally generated reports. Do not add game data to releases, CI artifacts,
issue attachments or Git LFS. Read source game files without modifying the install.

`pipeline/` contains stage scripts; `s1blender/` owns discovery, orchestration and
checkpoints; `build.ps1` bootstraps Python. The runner snapshots scripts into an
isolated build directory so scripts resolve data relative to their own location.
Edit repository source, not a generated snapshot. All generated content belongs in
ignored `builds/` or outside the repository. Preserve existing user projects.

## Invariants

- Unity `(x,y,z)` → Blender `(x,z,y)`, one unit = one metre, reflected winding.
- Preserve source transform and renderer IDs, UVs, normals, material assignments,
  terrain holes and native layer weights. Keep zero-scale TRS rotation intact.
- Resolve native references through their owning serialized file. Never assume
  path IDs, renderer counts, Steam drive letters or a developer's absolute paths.
- Read MonoBehaviour schemas from the user's native Mono assemblies. Keep Mono
  schema provenance separate from the actual source assets (which may be IL2CPP).
- Treat schema decode failures as diagnostics. Required render bindings must be
  unambiguous; fail clearly on unsupported layouts.
- Terrain RGBA control channels are independent weights. Resize separately;
  use Non-Color + CHANNEL_PACKED. Ordinary RGBA transparency resizing erases grass.
- Retain the 512px editor proxy budget, shared forest meshes, spatial batches and
  studio viewport defaults. Do not decode every original texture in the editor.
- Avoid per-object `users_collection` scans or repeated name lookup on huge scenes.
  Enumerate collections once, cache maps, and use batch removal for large sets.
- Do not force kill user Blender sessions. Run helper processes serially and
  terminate only helpers owned by the current invocation if interrupted.

## Validation

Run `python -m unittest discover -s tests -v`, compile the Python sources, and run
`python scripts/audit_repo.py` before committing. Tests must use synthetic fixtures.
For extractor changes, run `build.ps1 -Through extract` on an explicitly selected
local copy. For geometry/material changes, validate fresh Blender processes using
`validate_blend.py` and `validate_editor.py`, then inspect an actual textured preview.
Source/test success is not in-game or visual parity proof.

Record tested game/Unity/Blender versions and numerical validation summaries in
prose. Do not commit raw local reports. Never claim another game version or an
untested operating system is supported because the code compiles.

Build checkpoints bind input paths/sizes/timestamps and source hashes. Resume only
with the same inputs/tooling; after changing code, use a new output directory.
Completed `.blend` files are hash-checked to avoid overwriting user edits.
Publication requires a clean index and reachable-history audit; Git ignore rules alone are not
proof that a repository contains no game assets.
