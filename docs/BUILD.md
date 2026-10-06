# Building and troubleshooting

## Python entry point

The PowerShell wrapper uses Python 3.13 and installs `requirements.txt` into
`.venv`. To run the equivalent steps yourself:

If Python 3.13 is installed but not registered with `py`, pass
`-PythonPath 'C:\Path\To\Python313\python.exe'` to `build.ps1` on first setup.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe map.py doctor --game 'D:\Games\Schedule I'
.\.venv\Scripts\python.exe map.py build --game 'D:\Games\Schedule I'
```

Pass `--managed`, `--blender`, `--output`, `--through` or `--resume` as needed.
`doctor` checks discovery, Main scene availability, Blender version and the native
Mono schema folder. Actual schema decoding and render-layout checks occur during
extraction. A successful doctor run is not a completed map build.
Optional component decode failures are recorded in
`native_rendering/decode_errors.json`; a warning does not mean those settings were
recovered. Missing required daylight, volume or forest bindings stop the build.

## Phases and resume

1. **extract**: Main scene, terrain and textures; render settings; native binding
   resolution; forest transforms; shader properties; normal decoding; clear noon.
2. **scene**: full geometry/hierarchy, materials and presentation; fresh validation;
   full-detail master checkpoint.
3. **editor**: texture proxies, visible-object selection, reference batching,
   viewport defaults and fresh editor validation.

```powershell
.\build.ps1 -OutputPath 'D:\MapWork\Main-reference' -Through extract
.\build.ps1 -OutputPath 'D:\MapWork\Main-reference' -Resume
```

Repeat any explicit `-GamePath`, `-ManagedPath` and `-BlenderPath` options when
resuming. Completed phases are checked and skipped. An interrupted phase restarts
from its clean predecessor. A changed game install, script, schema DLL or completed
output requires a **new output directory**. Do not edit generated reference files
in place if you intend to resume; save your authored project elsewhere.

Input checks use sizes and modification times; they are change detection, not a
cryptographic guarantee of source authenticity. Completed key outputs and tooling
use SHA-256 (including extracted textures/meshes). Run only one build per output
directory at a time. Logs and checkpoints contain local paths; review/redact them before
sharing diagnostic excerpts. Do not upload entire logs or generated manifests.

## Common failures

- **No Mono schemas:** select a Mono game copy or provide a compatible native
  `Managed` directory. This repository intentionally supplies no assemblies.
- **Unsupported rendering layout / schema mismatch:** record the game version,
  runtime branch and short error. Required native fields changed or the schema
  copy is incompatible. Do not bypass checks or substitute arbitrary asset IDs.
- **Blender API error:** use the supported 5.2 series. Earlier compositor APIs
  differ. Future versions need validation before expanding the supported range.
- **Black terrain:** control maps must preserve RGBA channels independently and
  have Channel Packed alpha mode. The pipeline includes the repaired proxy path.
- **Unresponsive preview:** use the editor file, close the full master, start in
  Solid mode and allow initial shader compilation. Enable native scene lighting
  only when needed. The default editor retains full terrain geometry.
- **Out of disk/RAM:** close other Blender sessions, leave room for intermediate
  textures and several checkpoints, and choose a larger output drive. A generated
  `.blend1` backup may also occupy space. Never delete source game files to recover
  build space.

The runner executes one helper at a time and checks nonzero exit codes. Blender
Python exceptions use `--python-exit-code 1`. No GUI session is required to build.
