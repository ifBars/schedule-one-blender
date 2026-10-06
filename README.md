# Schedule One Blender

Create an editable Blender reference of Schedule I's Main map from **your own
installed game**. This repository contains tooling only: no game files, extracted
assets, textures, assemblies, or downloadable game scenes.

The pipeline recovers scene transforms, meshes, material textures, terrain and
painted layers, baked forest placements, and native lighting/render settings. It
produces a full-detail master plus a smaller editor workspace for map expansions.

## Requirements

- Windows, Python **3.13** with the `py` launcher, and Blender **5.2.x**.
- A local Schedule I installation that you own. The tool reads it; it does not
  launch the game or install a mod.
- Native **Mono assemblies** for render-setting schemas. With an
  `alternate`/`alternate-beta` Mono installation, its own `Managed` directory is
  used automatically. For an IL2CPP installation, supply a compatible local Mono
  copy with `-ManagedPath`. The tool does not download game files, change Steam
  branches, or use MelonLoader interop assemblies as schemas.
- 32 GB RAM recommended, at least 15 GiB free for a fresh build, and additional
  room for your authored work. Close memory-heavy applications during extraction.

The original pipeline was tested with game **0.4.7f9**, Unity **2022.3.62f2**,
and Blender **5.2.2**. Other game versions are not certified. Native references are
resolved by component identity instead of fixed asset IDs; unsupported layouts
stop with a diagnostic rather than silently omitting required data.

## Quick start

Download this repository using GitHub's **Code → Download ZIP** and extract it,
or clone it. Open PowerShell in its folder:

```powershell
.\build.ps1 -Doctor
.\build.ps1
```

The first command creates a local Python environment, installs the pinned open
source dependencies, and checks the paths and basic prerequisites. The second
builds both scenes. A unique Steam game and Blender install are detected
automatically. If multiple candidates exist, specify the paths explicitly:

```powershell
.\build.ps1 `
  -GamePath 'D:\Games\Schedule I' `
  -ManagedPath 'D:\Games\Schedule I Mono\Schedule I_Data\Managed' `
  -BlenderPath 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' `
  -OutputPath 'D:\MapWork\Main-reference'
```

Omit `-ManagedPath` for a Mono game copy that contains its own native assemblies.
If PowerShell blocks a downloaded script, inspect it and use `Unblock-File
.\build.ps1`, or use the Python commands in [the build guide](docs/BUILD.md).

Builds can take a while. Each step prints progress and writes its own log. By
default, generated files go into an ignored `builds/Main-<timestamp>` directory.
No extracted content is sent over the network. Dependency installation uses PyPI.

## What to open

| Output | Use |
| --- | --- |
| `Schedule_I_Main.blend` | Default optimized editor: 512px textures, editable 64m reference chunks, Eevee |
| `Schedule_I_Main_EDITOR.blend` | Identical explicit editor copy |
| `Schedule_I_Main_FULL_DETAIL.blend` | Original texture resolution, individual objects, hierarchy and LOD alternatives |

Use **Z → Material Preview** for textured editing. The editor keeps terrain tiles
and forest instances separate. Both textured viewport modes default to studio
lighting to avoid expensive native shadow setup. First-time shader compilation
can still pause the viewport. The smaller editor does not make the full-detail
master inexpensive to open.

Save your own project under a new name. Add expansion content to
`06 · YOUR MAP EXPANSION`; see [the authoring guide](docs/WORKSPACE.md).

## Automation and contributing

- [Build phases, resume, troubleshooting](docs/BUILD.md)
- [Agent instructions and validation contract](AGENTS.md)
- [Architecture and fidelity limits](docs/ARCHITECTURE.md)
- [Tested configuration and validation results](docs/VALIDATION.md)
- [Contribution rules](CONTRIBUTING.md)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\audit_repo.py
```

CI uses synthetic tests only. It never downloads the game or publishes generated
scenes. Blender render parity is approximate: compiled Unity shaders cannot run
in Blender, and runtime lighting/weather, procedural grass, interactions,
collision and navigation require separate game/mod work.

## Ownership

Unofficial community tooling; not affiliated with the game developer. Bring your
own game copy. Keep all generated game-derived files local. Do not contribute game
assets, decompiled game code, assemblies, extracted manifests, screenshots or
`.blend` files. Share your own original mod content independently. The MIT license
covers this repository's original tooling only; it grants no rights to game assets.

Extraction uses [UnityPy](https://github.com/K0lb3/UnityPy) and its type-tree
generator, with NumPy and Pillow. Scene creation runs in your installed Blender.
These dependencies retain their own licenses and are installed separately.
