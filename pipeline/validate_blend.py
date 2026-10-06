"""Fresh-process checks of the final .blend against the native scene manifest."""

import bpy, json, numpy as np, sys, time
from functools import lru_cache
from pathlib import Path
from mathutils import Matrix

root = Path(__file__).resolve().parent
d = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
C = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float)
objects = {
    o.get("unity_id"): o for o in bpy.data.objects if o.get("unity_id") is not None
}
renderers = {
    o.get("unity_renderer_id"): o
    for o in bpy.data.objects
    if o.get("unity_renderer_id") is not None
}
missing = []
transform_errors = []
finite_errors = []
max_error = 0
by_name = {o.name: o for o in bpy.data.objects}


@lru_cache(None)
def composed(name):
    o = by_name[name]
    local = np.asarray(o.matrix_parent_inverse @ o.matrix_basis, dtype=float)
    return composed(o.parent.name) @ local if o.parent else local


for i, g in enumerate(d["objects"]):
    if g["id"] not in objects:
        missing.append({"object": g["id"]})
        continue
    actual = composed(objects[g["id"]].name)
    expected = C @ np.asarray(g["world"]) @ C
    delta = float(np.max(np.abs(actual - expected)))
    max_error = max(max_error, delta)
    if delta > 0.003:
        transform_errors.append(
            {"object": g["id"], "name": g["name"], "max_delta": delta}
        )
for r in d["renderers"]:
    if r.get("empty") or d["meshes"][r["mesh"]]["triangles"] == 0:
        continue
    if r["id"] not in renderers:
        missing.append({"renderer": r["id"]})
print(
    "TRANSFORMS",
    len(objects),
    "maximum delta",
    max_error,
    "missing",
    len(missing),
    flush=True,
)
vertices = 0
triangles = 0
uv_meshes = 0
for m in bpy.data.meshes:
    a = np.empty(len(m.vertices) * 3, dtype=np.float32)
    m.vertices.foreach_get("co", a)
    if not np.isfinite(a).all():
        finite_errors.append(m.name)
    vertices += len(m.vertices)
    counts = np.empty(len(m.polygons), dtype=np.int32)
    m.polygons.foreach_get("loop_total", counts)
    triangles += int(np.maximum(counts - 2, 0).sum())
    uv_meshes += bool(m.uv_layers)
missing_images = [
    im.name
    for im in bpy.data.images
    if im.source == "FILE"
    and not im.packed_file
    and not Path(bpy.path.abspath(im.filepath)).exists()
]
go = {o["id"]: o for o in d["objects"]}
batch_errors = []
batch_checks = 0
for r in [r for r in d["renderers"] if r.get("batch_count") and r["id"] in renderers][
    ::1200
]:
    with np.load(root / d["meshes"][r["mesh"]]["path"]) as a:
        used = np.unique(
            np.concatenate(
                [
                    a[f"tri_{i}"]
                    for i in range(
                        r["batch_first"], r["batch_first"] + r["batch_count"]
                    )
                ]
            )
        )[:16]
        v = a["vertices"][used, :3]
        rw = np.asarray(go[r["batch_root"]]["world"]) if r["batch_root"] else np.eye(4)
        expected = (C @ rw @ np.column_stack((v, np.ones(len(v)))).T).T[:, :3]
        obj = renderers[r["id"]]
        actual = np.array([v.co[:] for v in obj.data.vertices[: len(v)]])
        actual = (
            composed(obj.name) @ np.column_stack((actual, np.ones(len(actual)))).T
        ).T[:, :3]
        delta = float(np.max(np.abs(actual - expected))) if len(v) else 0
        if delta > 0.005:
            batch_errors.append({"renderer": r["id"], "delta": delta})
        batch_checks += 1
gpu = json.loads(
    (root / "native_rendering/gpu_instances.json").read_text(encoding="utf-8")
)
forest = {
    o.get("native_gpu_instance"): o
    for o in bpy.data.objects
    if o.get("native_gpu_instance") is not None
}
forest_errors = []
for i, p in enumerate(gpu["positions"]):
    if i not in forest:
        forest_errors.append({"index": i, "error": "missing"})
        continue
    o = forest[i]
    expected = np.array((p[0], p[2], p[1]))
    delta = float(np.max(np.abs(np.asarray(o.location) - expected)))
    if delta > 0.001:
        forest_errors.append({"index": i, "position_error": delta})
terrain_checks = []
terrain_errors = []
for t in d["terrains"]:
    tiles = [
        o
        for o in bpy.data.objects
        if o.get("unity_terrain_sample_origin") is not None
        and o.parent
        and o.parent.get("unity_id") == t["go"]
    ]
    with np.load(root / t["path"]) as a:
        expected = int(np.count_nonzero(a["holes"]))
        actual = sum(len(o.data.polygons) for o in tiles)
    terrain_checks.append(
        {
            "terrain": t["name"],
            "tiles": len(tiles),
            "expected_surface_quads": expected,
            "actual_surface_quads": actual,
        }
    )
    if actual != expected:
        terrain_errors.append(t["name"])
visible_helpers = []
for r in d["renderers"]:
    o = renderers.get(r["id"])
    if o and not any(r.get("materials", [])) and not o.hide_render:
        visible_helpers.append(r["id"])
result = {
    "source_game": d["version"],
    "objects": len(bpy.data.objects),
    "source_transforms_checked": len(d["objects"]),
    "source_renderers": len(d["renderers"]),
    "imported_renderers": len(renderers),
    "mesh_datablocks": len(bpy.data.meshes),
    "vertices_unique": vertices,
    "triangles_unique": triangles,
    "uv_meshes": uv_meshes,
    "materials": len(bpy.data.materials),
    "packed_images": sum(bool(im.packed_file) for im in bpy.data.images),
    "file_images": sum(im.source == "FILE" for im in bpy.data.images),
    "missing_images": missing_images,
    "missing_objects_or_renderers": missing,
    "transform_errors": transform_errors,
    "max_world_transform_error": max_error,
    "nonfinite_meshes": finite_errors,
    "static_batch_checks": batch_checks,
    "static_batch_errors": batch_errors,
    "native_gpu_tree_instances": len(forest),
    "forest_errors": forest_errors,
    "terrain_checks": terrain_checks,
    "terrain_errors": terrain_errors,
    "visible_materialless_helpers": visible_helpers,
    "limitations": ["shader and compositor translations are not engine-equivalent"],
}
(root / "validation_report.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
if (
    missing
    or transform_errors
    or finite_errors
    or missing_images
    or batch_errors
    or forest_errors
    or terrain_errors
    or visible_helpers
):
    raise RuntimeError("Validation has unresolved findings")
