# Validation record

Local checks on 2026-10-05 used Windows, Python 3.13.11, game 0.4.7f9,
Unity 2022.3.62f2 and Blender 5.2.2 LTS. The source assets were from an IL2CPP
installation; a separate local Mono copy supplied serialized type schemas.
This is evidence for that combination, not certification of other game versions.

- A fresh virtual environment installed the pinned dependencies successfully.
- A clean extraction recovered 92,939 source transforms and 64,252 renderer
  records with no unresolved geometry/texture extraction errors.
- Native reference resolution recovered the daylight controller, global volume
  and 2,604 forest placements without build-specific path IDs.
- Fresh-process full-scene validation found no missing renderers or images,
  nonfinite geometry, terrain coverage errors, forest placement errors or sampled
  static-batch placement errors. Maximum checked world-transform error was below 0.00014m.
- The editor phase was rerun from that unchanged validated master after correcting
  Windows handling of Blender's `//` relative texture paths. Fresh validation passed:
  2,907 objects, 1,296 packed images at most 512px, and all 20,404 retained source
  renderer IDs. Both terrain controls used Channel Packed with weight-sum error
  below 0.008. Reference batching preserved vertex and triangle counts.
- A fresh Material Preview check visually confirmed green terrain and textured
  map geometry. The 960x640 viewport check peaked at 5,118 MiB physical working
  set and 11,442 MiB committed private memory. These are observed measurements
  for this scene and machine, not a guarantee for other systems.
- GitHub Actions runs synthetic tests, source compilation, and index/history
  audits without any game files. The path-resolution and terrain-channel defects
  have synthetic regression tests.

One optional `UniversalRenderPipelineGlobalSettings` component did not decode with
the available Mono schemas. This is recorded in the local `decode_errors.json`;
required lighting/volume/forest bindings resolved successfully. Do not interpret a
successful build as recovery of every URP setting or exact runtime shader parity.

All generated evidence, textures, manifests and Blender files remain local. Only
this numerical summary and original tooling are distributed.

## Road preview correction

The same local game extraction exposed two independent preview issues. The saved
four-way intersection material had wetness 0.9 and smoothness 1.0; eleven dry
materials using the same GroundWet shader had smoothness 0.2. The clear-weather
translation now derives wet outliers' smoothness from the median dry peer, while
retaining original values in material metadata. It does not reproduce the game's
runtime weather logic. A fresh Blender generator check verified roughness 0.8 for
the intersection and dry road, and unchanged roughness 1.0 for the overpass ramp.

At the same distant camera pose, increasing near clipping from 0.01m to 0.5m
removed bridge depth artifacts without changing geometry. Viewports and generated
reference cameras now use 0.5m. Near and distant Material Preview comparisons used
the saved editor scene. The corrected existing editor and full-detail files passed
fresh-process validation; editor geometry counts, packed texture budget and source
renderer coverage were unchanged. The extraction was not repeated for this change.

## Native bridge expansion prototype

Local validation on 2026-10-07 used Windows, Blender 5.2.2 LTS, Unity 2022.3.62f2,
and a separate Mono 0.4.7f9 Alternate game copy with MelonLoader 0.7.3. A copied
completed save reached normal gameplay; the user's original install/save was not
patched. Original editor and full-detail Blender hashes remained unchanged.

- The bridge planner produced fourteen 10 m spans and replaced three incomplete
  end groups. It added 94 invisible road-collision references and replaced 47
  native concrete deck objects with matching visuals and accurate mesh collision.
- The runtime built 631 placements using 173 shared compact meshes (39,536 unique
  vertices), with 575 mesh colliders. Native material objects and vertex streams
  were reused. The extension's repeating module uses 35 source meshes.
- 634 downward deck raycasts and two forward capsule sweeps passed across the new
  span and both joins. These probes initially missed a distance-enabled native
  box-collider lip; an actual native CharacterController traversal exposed it.
  After replacing the oversized deck boxes, the controller crossed both lanes
  from Unity Z=137 to Z=294 without falling or stalling. Returning to the menu and
  reloading produced exactly one expansion root with 631 parts.
- In-game aerial and road-level views were inspected for road/railing alignment
  and native rendering. The saved Blender scene reopened successfully, retained
  1,296 packed images no larger than 512px, rejected geometry/UV edits, and passed
  linked duplication/export checks. A textured Blender render was inspected.
- Unity imported the local preview into a real project. A rendered view exposed
  NumPy's shaped inverse-index output; flattening it before submesh slicing fixed
  the geometry. A synthetic regression test checks flat indices and submesh
  boundaries. The corrected preview contains 307,158 triangle indices across its
  instances and was checked visually. Preview materials are approximations.
- Synthetic Unity checks passed GPU-only mesh compaction, packed-color/UV
  preservation, transform rejection, and nonidentity static-batch root conversion.
- A fresh Mono extraction completed with 64,252 renderer records and zero extraction
  errors. Nonempty decoded renderers now retain shadow/receive-shadow metadata;
  required render bindings resolved. One optional native component still did not
  decode, as described above. Kit generation passed using this new extraction.

This is single-player Mono evidence. NPC navigation, traffic, multiplayer, IL2CPP,
new baked lighting and arbitrary edited-mesh export are not validated or supplied
by this prototype. Source tests, import success and gameplay evidence remain
separate. All asset-containing outputs and raw test evidence stayed local.
