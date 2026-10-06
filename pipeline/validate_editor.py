import bpy, json, numpy as np
from pathlib import Path

root = Path(__file__).resolve().parent
build = json.loads((root / "editor_build_report.json").read_text(encoding="utf-8"))
batch = (
    json.loads((root / "editor_batch_report.json").read_text(encoding="utf-8"))
    if (root / "editor_batch_report.json").exists()
    else None
)
images = [im for im in bpy.data.images if im.source == "FILE"]
bad_images = [im.name for im in images if not im.packed_file or max(im.size) > 512]
mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]
finite_errors = []
vertices = 0
triangles = 0
for m in bpy.data.meshes:
    a = np.empty(len(m.vertices) * 3, dtype=np.float32)
    m.vertices.foreach_get("co", a)
    if not np.isfinite(a).all():
        finite_errors.append(m.name)
    vertices += len(m.vertices)
    counts = np.empty(len(m.polygons), dtype=np.int32)
    m.polygons.foreach_get("loop_total", counts)
    triangles += int(np.maximum(counts - 2, 0).sum())
renderer_ids = set()
terrain_errors = []
terrain_controls = []
for material in bpy.data.materials:
    if not material.node_tree:
        continue
    for node in material.node_tree.nodes:
        if node.label != "Native terrain weights":
            continue
        im = node.image
        pixels = np.empty(len(im.pixels), dtype=np.float32)
        im.pixels.foreach_get(pixels)
        pixels = pixels.reshape(-1, 4)
        weight_error = float(np.max(np.abs(pixels.sum(axis=1) - 1)))
        terrain_controls.append(
            {
                "material": material.name,
                "alpha_mode": im.alpha_mode,
                "maximum_weight_sum_error": weight_error,
            }
        )
        if (
            im.alpha_mode != "CHANNEL_PACKED"
            or im.colorspace_settings.name != "Non-Color"
            or weight_error > 4 / 255
        ):
            terrain_errors.append(material.name)
manifest = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
if len(terrain_controls) != len(manifest["terrains"]):
    terrain_errors.append("Terrain control count differs from source")
for o in mesh_objects:
    if o.get("unity_renderer_id") is not None:
        renderer_ids.add(o["unity_renderer_id"])
    renderer_ids.update(o.get("source_renderer_ids", []))
result = {
    "objects": len(bpy.data.objects),
    "mesh_objects": len(mesh_objects),
    "mesh_data": len(bpy.data.meshes),
    "unique_vertices": vertices,
    "unique_triangles": triangles,
    "packed_images": len(images),
    "bad_images": bad_images,
    "nonfinite_meshes": finite_errors,
    "engine": bpy.context.scene.render.engine,
    "forest_instances": sum(
        o.get("native_gpu_instance") is not None for o in mesh_objects
    ),
    "source_renderer_ids": len(renderer_ids),
    "terrain_controls": terrain_controls,
    "terrain_errors": terrain_errors,
    "full_detail_master_exists": (root / "Schedule_I_Main_FULL_DETAIL.blend").exists(),
}
expected_meshes = batch["mesh_objects"] if batch else build["editor"]["mesh_objects"]
result["passed"] = (
    not bad_images
    and not finite_errors
    and not terrain_errors
    and len(mesh_objects) == expected_meshes
    and renderer_ids == set(build["source_renderer_ids"])
    and result["full_detail_master_exists"]
)
(root / "editor_validation.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
if not result["passed"]:
    raise RuntimeError("Editor validation failed")
