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
