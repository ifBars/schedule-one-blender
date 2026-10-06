"""Make an editing copy from the preserved full-detail map; retain visible geometry."""

import bpy, json, time, gc
from pathlib import Path
from functools import lru_cache
from mathutils import Matrix

root = Path(__file__).resolve().parent
scene = bpy.context.scene
textures = json.loads(
    (root / "editor_texture_manifest.json").read_text(encoding="utf-8")
)


def enabled_collections(lc, enabled=True):
    enabled = (
        enabled
        and not lc.exclude
        and not lc.hide_viewport
        and not lc.collection.hide_viewport
        and not lc.collection.hide_render
    )
    result = {lc.collection} if enabled else set()
    for c in lc.children:
        result.update(enabled_collections(c, enabled))
    return result


cols = enabled_collections(bpy.context.view_layer.layer_collection)
active = {
    o
    for c in cols
    for o in c.objects
    if not o.hide_render
    and not o.hide_viewport
    and o.type in {"MESH", "LIGHT", "CAMERA"}
}
by_name = {o.name: o for o in bpy.data.objects}


@lru_cache(None)
def world(name):
    o = by_name[name]
    local = o.matrix_parent_inverse @ o.matrix_basis
    return world(o.parent.name) @ local if o.parent else local.copy()


placement = {o.name: world(o.name).copy() for o in active}
expected_renderer_ids = sorted(
    o["unity_renderer_id"] for o in active if o.get("unity_renderer_id") is not None
)
source_stats = {
    "objects": len(bpy.data.objects),
    "mesh_data": len(bpy.data.meshes),
    "images": len(bpy.data.images),
}
anchor = None
for o in active:
    o.parent = None
    o.matrix_world = placement[o.name]
    delta = max(
        abs(o.matrix_basis[i][j] - placement[o.name][i][j])
        for i in range(4)
        for j in range(4)
    )
    if delta > 0.003:
        if anchor is None:
            anchor = bpy.data.objects.new("Native affine transform anchor", None)
            scene.collection.objects.link(anchor)
        o.parent = anchor
        o.matrix_parent_inverse = placement[o.name]
        o.matrix_basis = Matrix.Identity(4)
        o["preserved_affine_transform"] = True
if anchor:
    active.add(anchor)
print("FLATTENED", len(active), flush=True)
bpy.data.batch_remove(ids=[o for o in bpy.data.objects if o not in active])
world.cache_clear()
by_name.clear()
active.clear()
gc.collect()
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
print("PRUNED", len(bpy.data.objects), len(bpy.data.meshes), flush=True)
# Replace images instead of scaling them in Blender: scaling decodes all source
# pixels and may retain large CPU/GPU caches for the entire session.
replacements = {}
old_images = list(bpy.data.images)
for im in old_images:
    if im.source != "FILE":
        continue
    source = Path(bpy.path.abspath(im.filepath))
    entry = textures.get(str(source).lower())
    if not entry:
        raise RuntimeError("No proxy image for " + str(source))
    new = bpy.data.images.load(entry["path"], check_existing=False)
    new.name = im.name
    new.colorspace_settings.name = im.colorspace_settings.name
    new.alpha_mode = im.alpha_mode
    new["full_resolution_source"] = str(source)
    if entry.get("channel_packed"):
        new.alpha_mode = "CHANNEL_PACKED"
        new.colorspace_settings.name = "Non-Color"
    new["editor_texture_limit"] = 512
    replacements[im] = new
for material in bpy.data.materials:
    if material.node_tree:
        for n in material.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image in replacements:
                n.image = replacements[n.image]
for ng in [
    *bpy.data.node_groups,
    *[w.node_tree for w in bpy.data.worlds if w.node_tree],
]:
    for n in ng.nodes:
        if n.type == "TEX_IMAGE" and n.image in replacements:
            n.image = replacements[n.image]
bpy.data.batch_remove(
    ids=[im for im in old_images if im in replacements and im.users == 0]
)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
print("PROXY IMAGES", len(bpy.data.images), flush=True)
for im in bpy.data.images:
    if im.source == "FILE":
        im.pack()
        im.filepath = "//editor_textures/" + Path(im.filepath).name
# Keep source metadata in the external full-detail master and JSON manifests.
bpy.data.batch_remove(
    ids=[t for t in bpy.data.texts if t.name.startswith("Native evidence")]
)
scene.render.engine = "BLENDER_EEVEE"
scene.render.use_simplify = True
scene.render.simplify_subdivision = 0
scene.render.simplify_subdivision_render = 0
scene.eevee.taa_samples = 16
scene.eevee.taa_render_samples = 32
scene.eevee.use_raytracing = False
scene.eevee.shadow_pool_size = "128"
scene.cycles.texture_limit = "512"
scene.cycles.texture_limit_render = "512"
scene.cycles.preview_samples = 8
scene.cycles.use_preview_denoising = True
scene["workspace_profile"] = (
    "32 GB editing: visible geometry only, 512px packed material textures, Eevee"
)
scene["full_detail_master"] = "//Schedule_I_Main_FULL_DETAIL.blend"
scene["editing_note"] = (
    "Visible source meshes remain editable and keep world transforms and native IDs. Inactive variants and hierarchy are in the full-detail master."
)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            space.shading.use_scene_world = False
            space.shading.use_scene_lights = False
            space.shading.use_scene_world_render = False
            space.shading.use_scene_lights_render = False
            space.overlay.show_extras = False
doc = bpy.data.texts.get("START HERE — map expansion") or bpy.data.texts.new(
    "START HERE — map expansion"
)
doc.clear()
doc.write(
    "32 GB EDITING FILE\n\n512px packed texture copies; active geometry only; Eevee.\nUse Z > Material Preview for textured editing.\nFull-detail master: Schedule_I_Main_FULL_DETAIL.blend\nNative transforms and mesh IDs are retained. Inactive variants and original hierarchy live in the master.\nAdd your work to 06 · YOUR MAP EXPANSION.\n"
)
# Validate the retained placements independently after flattening.
max_delta = 0
for o in bpy.data.objects:
    if o.name in placement:
        actual = (
            o.matrix_parent_inverse @ o.matrix_basis if o.parent else o.matrix_basis
        )
        delta = max(
            abs(actual[i][j] - placement[o.name][i][j])
            for i in range(4)
            for j in range(4)
        )
        max_delta = max(max_delta, delta)
        if delta > 0.003:
            raise RuntimeError(
                "Flattening changed placement: " + o.name + " " + str(delta)
            )
report = {
    "source": source_stats,
    "editor": {
        "objects": len(bpy.data.objects),
        "mesh_objects": sum(o.type == "MESH" for o in bpy.data.objects),
        "mesh_data": len(bpy.data.meshes),
        "images": len(bpy.data.images),
        "materials": len(bpy.data.materials),
    },
    "source_renderer_ids": expected_renderer_ids,
    "maximum_world_transform_delta": max_delta,
    "texture_limit": 512,
    "engine": scene.render.engine,
}
(root / "editor_build_report.json").write_text(json.dumps(report, indent=2))
bpy.ops.wm.save_as_mainfile(
    filepath=str(root / "Schedule_I_Main_EDITOR.blend"), compress=True
)
summary = {key: value for key, value in report.items() if key != "source_renderer_ids"}
summary["source_renderer_count"] = len(expected_renderer_ids)
print("EDITOR SAVED", json.dumps(summary), flush=True)
