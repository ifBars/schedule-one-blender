# Architecture and limits

The CLI snapshots original stage scripts and a workspace README into each local
output directory. This keeps stage-relative file references deterministic and
gives agents inspectable scripts next to private intermediate data. Python does
asset decoding; Blender's own Python does scene creation. Offline extraction does not execute game code.

UnityPy locates Main through BuildSettings, follows native asset references and
decodes mesh channels, static batches, terrain heights/holes, splat textures and
materials. Native Mono assemblies provide missing serialized type layouts. The
same local schema folder may decode an IL2CPP copy only when the layouts match.
Required daylight/volume/forest bindings are selected by identity and references,
not constants from the original developer's game install.

The full scene preserves the source hierarchy and alternate visibility states.
The editor flattens visible objects, retains affine transforms where decomposing
them would lose information, and batches ordinary reference meshes into 64m
chunks with source-ID provenance. Forest meshes are shared; terrain tiles remain
separate. Texture proxies are bounded to 512px and packed for portability.

Terrain controls use independent-channel BOX reduction. Ordinary color textures
use Pillow's color/alpha-aware LANCZOS reduction. Packed Unity normal maps are
decoded into tangent-space RGB. This distinction is necessary: alpha can describe
transparency, a fourth terrain material, or unrelated shader data.

The importer translates common Lit, foliage, triplanar/world-space, cutout, water,
emission and glass materials. Compiled custom shaders cannot execute in Blender.
Noon gradients, URP volume values and ambient settings inform approximate Blender
lights/world/compositor settings. Dynamic water, shoreline intersection foam,
vegetation motion, weather, volumetric effects and procedural grass are not exact.
The noon sun controller factor and height normalization are verified assumptions
for the tested game version and require review if native behavior changes.

Serialized skinned meshes are frozen; runtime-spawned entities and gameplay state
are absent. The reference stage alone does not create a playable mod. The optional
[native expansion workflow](EXPANSIONS.md) adds a placement recipe, a Mono runtime
loader and a local Unity preview. It supports native mesh placement and explicit
collision, with no gameplay component cloning or navigation/network integration.

CI can prove synthetic channel preservation, discovery behavior, output guards
and repository hygiene. Full scene completeness requires the user's local game,
fresh Blender validation and visual inspection; none of those assets belongs in CI.

The native loader reads GPU mesh buffers because shipped static batches often lack
CPU copies. It compacts the selected submeshes, preserves vertex streams and undoes
batching using `Transform.worldToLocalMatrix * Renderer.localToWorldMatrix`.
Unity documents why the renderer matrix is required for batched coordinates in
[Renderer.localToWorldMatrix](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Renderer-localToWorldMatrix.html).
Reference selectors use names plus original world positions, with exact material
and shader-name checks. Game-version tokens must match; path IDs are never used at
runtime. This is compatibility checking, not proof of identical geometry in every
build sharing a version number.
