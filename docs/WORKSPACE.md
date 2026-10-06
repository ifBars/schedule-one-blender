# Your local Schedule I map workspace

Open `Schedule_I_Main.blend` for everyday editing. It is identical to
`Schedule_I_Main_EDITOR.blend`: 512px packed textures, spatially batched reference
meshes, separate terrain tiles, and linked forest meshes. Start with Z > Material
Preview. Both textured viewport modes use studio lighting by default. Initial
shader compilation can pause the viewport.

`Schedule_I_Main_FULL_DETAIL.blend` retains original texture sizes, individual
objects, native hierarchy, inactive objects and alternate LODs. It is much larger.
Avoid opening both files simultaneously on a 32 GB machine. Enable native scene
lights/world in the viewport shading popover only when needed.

Save your edits under a new filename, outside this generated build directory.
The build directory is a reproducible cache, not your authored mod project.

## Authoring an expansion

Add your own content to `06 · YOUR MAP EXPANSION`. Keep the reference origin fixed.
One Blender unit is one metre. Unity `(x,y,z)` maps to Blender `(x,z,y)`; apply the
inverse once when exporting game coordinates. The axis swap reverses handedness;
the importer adjusts winding and normals. Do not apply another conversion if your
exporter already performs it.

Reference chunks have `source_renderer_ids` linking back to the local
`main_manifest.json`. Use the full-detail file when you need individual original
objects. Inactive and alternative LOD collections are excluded initially; turning
all LODs on at once produces overlap. Terrain blend maps contain four independent
weights and must use Non-Color + Channel Packed. Never resize them as transparency.

Map viewports and reference cameras use a 0.5m near clipping distance to prevent
distant bridge surfaces from flickering. For close detail work, temporarily lower
View > Clip Start in the sidebar, then restore 0.5m before viewing the whole map.
Clear-weather road shading matches saved wet GroundWet outliers to the median
smoothness of native dry peers. This is an approximation; original material
parameters remain available in each material's `source_parameters` property.

This is a serialized visual reference, not a playable Unity project. Collision,
navigation, save integration, multiplayer, runtime-spawned objects, procedural
grass, weather and gameplay scripts are not reconstructed. Custom shaders and
postprocessing are Blender approximations. Validate your own expansion in-game.

## Keep game-derived outputs local

This directory contains assets generated from your installed game. Do not upload
it, its textures, manifests, assemblies or `.blend` files to the tooling repository.
Distribute your own authored content independently. The repository's MIT license
applies to its tooling, not to the game's assets or these generated scenes.
