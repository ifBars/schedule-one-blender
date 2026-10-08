# Native map expansions

The experimental expansion workflow places meshes from your installed game and
binds the actual native materials at runtime. It creates a new Blender file and
leaves the extracted reference unchanged. Windows, Blender 5.2.x and the Mono
alternate-beta game are the current target. See [validation](VALIDATION.md) for the
specific versions exercised. IL2CPP and multiplayer have not been validated.

## Generate the bridge example

First build the reference using the normal [extraction workflow](BUILD.md). Close
Blender and the game while generating another scene on a 32 GB machine. From the
repository root, use your own paths:

```powershell
.\.venv\Scripts\python.exe -m s1blender.expansion `
  --reference "D:\MyMapReference" `
  --scene "D:\MyMapReference\Schedule_I_Main_EDITOR.blend" `
  --blender "D:\SteamLibrary\steamapps\common\Blender\blender.exe" `
  --output "D:\MyBridgeExpansion" --bridge
```

This writes `Expansion.blend`, `map.expansion.json`, the local native kit and a
`UnityPreview` folder. Use a new empty output folder. Repository-local output must
be under ignored `builds/`. All generated content stays local.

The example discovers the last complete mainland span and first complete island
span, checks their spacing/alignment, replaces partial ends, and repeats a complete
native bridge module between them. On the tested map this is fourteen 10 m spans.
It adds collision-only copies of the approach road surfaces. The native concrete
decks use distance-enabled box colliders extending above the visible road, so those
objects are replaced with identical native visuals and accurate mesh collision.
Collision-only road copies have rendering disabled; replaced originals are hidden,
so this does not produce overlapping visible road surfaces. Broken ends are hidden
in the authored reference and disabled reversibly by the runtime loader.

The example requires the recognized native overpass hierarchy. It fails clearly
when the endpoints/template change; it does not invent a route across a new map.

## Author in Blender

1. Open the generated `Expansion.blend`. Solid view is the fast startup default;
   use **Z > Material Preview** for textures. Existing 512px texture proxies remain.
2. Install `pipeline/native_expansion.py` through Blender **Preferences > Add-ons >
   Install from Disk**, then enable **Schedule One Native Expansion**.
3. Open the **Schedule One** tab in the viewport sidebar (**N**). Select a native
   span or one of its children and use **Duplicate Native Kit**. This creates linked
   mesh instances with new placement IDs and moves the copy by one native module.
4. Move/rotate/scale the root or its pieces. Metre units and absolute grid snapping
   are enabled. Bridge modules use 10 m spacing; their children retain native local
   offsets. Blender Y is Unity Z; Blender Z is Unity Y.
5. Use **Export Native Placements** to save a new `.expansion.json` recipe. For an
   individual piece, the panel's collision field accepts `mesh` or `none`.

The export contains selectors, transforms and collision options, with no mesh or
texture arrays. The exporter checks geometry, UVs, material bindings and common material-node
settings for unsupported edits. Mesh, shader and texture edits cannot be represented;
keep native materials and images unchanged. Modifiers, mirrored transforms and shear
are also rejected. Use the kit duplication button instead of Shift-D, which copies
placement IDs. Do not apply object transforms to native-reference meshes.

To start with a different native group, replace `--bridge` with an exact hierarchy
path, for example `--group "Map/Hyland Point/Overpass/Overpass Segment (13)"`.
Omit `--scene` and `--blender` to prepare only the local kit/plan. The initial version
supports one source kit per authored workspace; combine/rearrange its native parts
as needed. Selected sources must be active LOD0 MeshRenderers in the local manifest.
It does not export arbitrary new geometry, skinned meshes or gameplay components.

## Load in the game

Use a **Mono alternate/alternate-beta copy with MelonLoader 0.7.3**, matching the
reference game version. Build against that copy with a .NET SDK:

```powershell
dotnet build runtime/NativeExpansion.csproj -c Release `
  -p:GamePath="D:/MyMonoGameCopy"
```

Copy only `runtime/bin/Release/netstandard2.1/ScheduleOne.NativeExpansion.dll` into
that copy's `Mods` folder. Create `UserData/NativeExpansions` under the game directory
and copy your `.expansion.json` there. Load a save normally. Look for
`NATIVE_EXPANSION READY` in the MelonLoader log. Test with a copied save first.

The loader resolves native scene paths and source positions, checks version and
material/shader names, reads each selected GPU mesh subset, and shares that compact
mesh across its instances. It preserves native vertex attributes, native material
objects, shadow flags and game render settings. No original scene files or save
formats are patched. Returning to the menu releases generated meshes and restores
suppressed objects; loading Main again rebuilds one instance per recipe ID.

Remove a recipe and reload Main to remove that expansion. Keep all clients' local
files consistent if experimenting with multiplayer, but multiplayer behavior is
unverified. There is no NPC navigation, traffic routing, property ownership,
network-object spawning or baked lighting generation in this prototype. Native
shaders and runtime lighting are reused; a relocated object does not inherit a
new lightmap or newly placed reflection probes.

## Preview in Unity

The first command also generates a **local asset-containing preview**, separate
from the placement-only recipe. After editing/re-exporting in Blender, generate a
fresh preview directory:

```powershell
.\.venv\Scripts\python.exe -m s1blender.preview `
  --kit "D:\MyBridgeExpansion\native-kit.json" `
  --plan "D:\MyBridgeExpansion\layout-plan.json" `
  --recipe "D:\MyBridgeExpansion\map.expansion.json" `
  --output "D:\MyBridgeExpansion\UnityPreview-v2"
```

In a local Unity 2022.3 project, copy `unity/NativeExpansionImporter.cs` into
`Assets/Editor`. Choose **Schedule One > Import Local Expansion Preview**, then
select `preview.local.json`. The importer creates a prefab, meshes, materials,
textures and a scene under a new `Assets/NativeExpansionLocal/Import-*` folder.
It never overwrites an earlier import. URP/Lit is used when installed; otherwise
it uses Standard. Unity preview materials are simplified color/albedo/smoothness
translations. Custom shader graphs, triplanar mapping, normal maps, wetness and
post-processing are not reconstructed by this preview importer. The in-game loader
uses the actual materials instead.

The Unity preview contains expansion placements, without the full native map backdrop.
It preserves placement coordinates and collision for inspection;
it is not an export-back authoring tool. Make placement changes in Blender and
regenerate the recipe/preview. You do not need Unity to run the native-reference
mod. Do not build or distribute a bundle containing the generated native meshes.

**Keep generated Blender files, extracted assets, previews, Unity projects and
screenshots local.** This repository distributes original tooling and instructions
only. Its license does not license the game's assets.

## Validation and agent handoff

Run the Python tests and repository audit described in [AGENTS.md](../AGENTS.md).
Validate a newly saved authoring file in a fresh Blender process:

```powershell
& "D:\SteamLibrary\steamapps\common\Blender\blender.exe" `
  --background "D:\MyBridgeExpansion\Expansion.blend" --python-exit-code 1 `
  --python pipeline/validate_expansion.py -- --report "D:\MyBridgeExpansion\validation.local.json"
```

For the optional GPU-only synthetic Unity check, copy `unity/NativeExpansionTests.cs`,
`runtime/Recipe.cs` and `runtime/NativeMesh.cs` into `Assets/Editor` of a disposable
local project, then call `NativeExpansionTests.Run` with `-executeMethod`. Keep
graphics enabled for GPU readback. These tests contain synthetic geometry only.
Keep fresh extraction, Blender validation, Unity import, and gameplay evidence
separate. A successful compile or import alone does not prove a traversable bridge.
