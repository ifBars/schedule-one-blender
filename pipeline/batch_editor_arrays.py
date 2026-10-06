"""Batch map reference draws directly, without per-object operator deletion."""

import bpy, json, math, numpy as np
from pathlib import Path
from collections import defaultdict
from mathutils import Vector

root = Path(__file__).resolve().parent
scene = bpy.context.scene
groups = defaultdict(list)
for o in list(bpy.data.objects):
    if (
        o.type != "MESH"
        or o.get("native_gpu_instance") is not None
        or o.get("unity_terrain_sample_origin") is not None
    ):
        continue
    if any(
        m and "water" in m.get("unity_shader", "").lower() for m in o.data.materials
    ):
        continue
    center = o.matrix_world @ Vector(
        tuple(sum(v[i] for v in o.bound_box) / 8 for i in range(3))
    )
    groups[(math.floor(center.x / 64), math.floor(center.y / 64))].append(o)


def read(collection, prop, components, dtype):
    a = np.empty(len(collection) * components, dtype=dtype)
    collection.foreach_get(prop, a)
    return a.reshape(-1, components) if components > 1 else a


chunkscol = bpy.data.collections.new("Static reference — editable 64m chunks")
next(c for c in bpy.data.collections if c.name.startswith("01 ·")).children.link(
    chunkscol
)
before = len(bpy.data.objects)
input_mesh_objects = sum(o.type == "MESH" for o in bpy.data.objects)
remove = []
chunks = []
input_triangles = output_triangles = 0
input_vertices = output_vertices = 0
for index, (key, objects) in enumerate(sorted(groups.items())):
    verts = []
    loops = []
    counts = []
    normals = []
    uvs = []
    uv2 = []
    colors = []
    smooth = []
    mat_indices = []
    materials = []
    mat_lookup = {}
    offset = 0
    native_ids = []
    minimum = np.full(3, np.inf)
    maximum = np.full(3, -np.inf)
    for o in objects:
        m = o.data
        world = np.asarray(o.matrix_world, dtype=np.float64)
        co = read(m.vertices, "co", 3, np.float32)
        transformed = co @ world[:3, :3].T + world[:3, 3]
        if len(co):
            minimum = np.minimum(minimum, transformed.min(0))
            maximum = np.maximum(maximum, transformed.max(0))
        verts.append(transformed.astype(np.float32))
        total = read(m.polygons, "loop_total", 1, np.int32)
        counts.append(total)
        starts = read(m.polygons, "loop_start", 1, np.int32)
        indices = np.arange(len(m.loops))
        if np.linalg.det(world[:3, :3]) < 0:
            indices = np.repeat(starts * 2 + total - 1, total) - indices
        loops.append(read(m.loops, "vertex_index", 1, np.int32)[indices] + offset)
        n = read(m.corner_normals, "vector", 3, np.float32)[indices]
        n = n @ np.linalg.pinv(world[:3, :3])
        length = np.linalg.norm(n, axis=1)
        n /= np.maximum(length[:, None], 1e-12)
        normals.append(n.astype(np.float32))
        for name, target in [("UVMap", uvs), ("LightmapUV", uv2)]:
            layer = m.uv_layers.get(name)
            target.append(
                read(layer.data, "uv", 2, np.float32)[indices]
                if layer
                else np.zeros((len(m.loops), 2), np.float32)
            )
        color = m.color_attributes.get("UnityVertexColor")
        colors.append(
            read(color.data, "color", 4, np.float32)
            if color and color.domain == "POINT"
            else np.ones((len(m.vertices), 4), np.float32)
        )
        smooth.append(read(m.polygons, "use_smooth", 1, bool))
        lookup = []
        for material in m.materials:
            if material not in mat_lookup:
                mat_lookup[material] = len(materials)
                materials.append(material)
            lookup.append(mat_lookup[material])
        ids = read(m.polygons, "material_index", 1, np.int32)
        mat_indices.append(
            np.asarray(lookup, dtype=np.int32)[ids]
            if lookup
            else np.zeros(len(ids), np.int32)
        )
        offset += len(m.vertices)
        if o.get("unity_renderer_id") is not None:
            native_ids.append(o["unity_renderer_id"])
        input_triangles += int(np.maximum(total - 2, 0).sum())
        input_vertices += len(m.vertices)
    me = bpy.data.meshes.new(f"Reference_{key[0]}_{key[1]}")
    vertices = np.concatenate(verts)
    poly_counts = np.concatenate(counts)
    loop_indices = np.concatenate(loops)
    me.vertices.add(len(vertices))
    me.vertices.foreach_set("co", vertices.ravel())
    me.loops.add(len(loop_indices))
    me.loops.foreach_set("vertex_index", loop_indices)
    me.polygons.add(len(poly_counts))
    me.polygons.foreach_set("loop_start", np.cumsum(poly_counts) - poly_counts)
    me.polygons.foreach_set("loop_total", poly_counts)
    me.polygons.foreach_set("use_smooth", np.concatenate(smooth))
    for material in materials:
        me.materials.append(material)
    me.polygons.foreach_set("material_index", np.concatenate(mat_indices))
    for name, values in [("UVMap", uvs), ("LightmapUV", uv2)]:
        me.uv_layers.new(name=name).data.foreach_set(
            "uv", np.concatenate(values).ravel()
        )
    me.color_attributes.new(
        name="UnityVertexColor", type="BYTE_COLOR", domain="POINT"
    ).data.foreach_set("color", np.concatenate(colors).ravel())
    me.update()
    me.normals_split_custom_set(np.concatenate(normals))
    joined = bpy.data.objects.new(f"Reference chunk {key[0]:+03d} {key[1]:+03d}", me)
    chunkscol.objects.link(joined)
    joined["source_renderer_ids"] = native_ids
    joined["reference_chunk_metres"] = 64
    joined["editing_note"] = (
        "Editable static batch. Individual source objects are in FULL_DETAIL.blend."
    )
    output_triangles += int(np.maximum(poly_counts - 2, 0).sum())
    output_vertices += len(vertices)
    bounds_error = (
        float(
            max(
                np.max(abs(vertices.min(0) - minimum)),
                np.max(abs(vertices.max(0) - maximum)),
            )
        )
        if len(vertices)
        else 0
    )
    chunks.append(
        {
            "name": joined.name,
            "source_objects": len(objects),
            "renderer_ids": native_ids,
            "world_bounds_delta": bounds_error,
        }
    )
    remove.extend(objects)
    print(
        "BATCH",
        index + 1,
        "/",
        len(groups),
        "objects",
        len(objects),
        "vertices",
        len(vertices),
        flush=True,
    )
bpy.data.batch_remove(ids=remove)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
scene.eevee.taa_samples = 4
scene["workspace_profile"] = (
    "32 GB editor: spatially batched reference geometry, 512px textures, Eevee"
)
report = {
    "before_objects": before,
    "input_mesh_objects": input_mesh_objects,
    "objects": len(bpy.data.objects),
    "mesh_objects": sum(o.type == "MESH" for o in bpy.data.objects),
    "mesh_data": len(bpy.data.meshes),
    "chunks": chunks,
    "forest_instances": sum(
        o.get("native_gpu_instance") is not None for o in bpy.data.objects
    ),
    "input_vertices": input_vertices,
    "output_vertices": output_vertices,
    "input_triangles": input_triangles,
    "output_triangles": output_triangles,
}
assert input_vertices == output_vertices and input_triangles == output_triangles
assert max(c["world_bounds_delta"] for c in chunks) < 0.001
(root / "editor_batch_report.json").write_text(json.dumps(report, indent=2))
bpy.ops.wm.save_as_mainfile(
    filepath=str(root / "Schedule_I_Main_EDITOR.blend"), compress=True
)
print("BATCH COMPLETE", len(bpy.data.objects), len(bpy.data.meshes), flush=True)
