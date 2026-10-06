# Architecture and limits

The CLI snapshots original stage scripts and a workspace README into each local
output directory. This keeps stage-relative file references deterministic and
gives agents inspectable scripts next to private intermediate data. Python does
asset decoding; Blender's own Python does scene creation. No game code is executed.

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
are absent. This does not create a Unity mod, collision/navigation solution or
networked map expansion. Author original content against the reference and test
the actual mod separately.

CI can prove synthetic channel preservation, discovery behavior, output guards
and repository hygiene. Full scene completeness requires the user's local game,
fresh Blender validation and visual inspection; none of those assets belongs in CI.
