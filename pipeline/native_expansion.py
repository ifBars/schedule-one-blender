"""Blender native-kit construction, linked duplication and placement export.
Install this file as a Blender add-on, or run it with --kit/--plan/--output.
"""

bl_info = {
    "name": "Schedule One Native Expansion",
    "author": "ifBars",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "category": "Object",
}
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
import bpy
import numpy as np
from mathutils import Matrix, Vector
from bpy.props import StringProperty

SWAP = np.eye(4)[[0, 2, 1, 3]]
COLLECTION = "06 · YOUR MAP EXPANSION"


def geometry_digest(mesh):
    digest = hashlib.sha256()

    def add(collection, attribute, size, dtype):
        values = np.empty(len(collection) * size, dtype=dtype)
        collection.foreach_get(attribute, values)
        digest.update(values.tobytes())

    add(mesh.vertices, "co", 3, np.float32)
    add(mesh.loops, "vertex_index", 1, np.int32)
    add(mesh.polygons, "loop_total", 1, np.int32)
    add(mesh.polygons, "material_index", 1, np.int32)
    add(mesh.polygons, "use_smooth", 1, bool)
    add(mesh.corner_normals, "vector", 3, np.float32)
    for layer in mesh.uv_layers:
        digest.update(layer.name.encode())
        add(layer.data, "uv", 2, np.float32)
    for layer in mesh.color_attributes:
        digest.update((layer.name + layer.domain).encode())
        add(layer.data, "color", 4, np.float32)
    return digest.hexdigest()


def material_digest(obj):
    values = []
    for slot in obj.material_slots:
        material = slot.material
        if material is None:
            values.append(None)
            continue
        nodes = []
        if material.node_tree:
            for node in material.node_tree.nodes:
                inputs = []
                for socket in node.inputs:
                    if hasattr(socket, "default_value"):
                        value = socket.default_value
                        inputs.append(
                            (
                                socket.name,
                                list(value)
                                if hasattr(value, "__len__")
                                and not isinstance(value, str)
                                else value,
                            )
                        )
                nodes.append(
                    (
                        node.name,
                        node.bl_idname,
                        inputs,
                        getattr(node, "operation", None),
                        getattr(node, "blend_type", None),
                        getattr(node, "projection", None),
                        getattr(getattr(node, "image", None), "name", None),
                    )
                )
            links = [
                (
                    l.from_node.name,
                    l.from_socket.identifier,
                    l.to_node.name,
                    l.to_socket.identifier,
                )
                for l in material.node_tree.links
            ]
        else:
            links = []
        values.append(
            (
                material.name,
                list(material.diffuse_color),
                material.roughness,
                material.metallic,
                nodes,
                links,
            )
        )
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def suppress_reference(manifest, selectors):
    # Reference batches retain renderer order. Verify the complete face count before
    # removing selected ranges; a user-edited or incompatible reference must fail closed.
    objects = {o["id"]: o for o in manifest["objects"]}

    def path(obj):
        result = []
        while obj:
            result.append(obj["name"])
            obj = objects.get(obj["parent"])
        return result[::-1]

    selector_names = {r["path"][-1] for r in selectors}
    roots = {
        o["id"]
        for o in objects.values()
        if o["name"] in selector_names
        and any(
            path(o) == r["path"]
            and np.linalg.norm(np.asarray(o["world"])[:3, 3] - r["position"]) < 0.02
            for r in selectors
        )
    }
    hidden_ids = set()
    for obj in objects.values():
        current = obj
        while current:
            if current["id"] in roots:
                hidden_ids.add(obj["id"])
                break
            current = objects.get(current["parent"])
    renderers = {r["id"]: r for r in manifest["renderers"]}
    hidden = {r["id"] for r in renderers.values() if r["go"] in hidden_ids}
    from functools import lru_cache

    @lru_cache(None)
    def mesh_face_counts(mesh_key):
        info = manifest["meshes"][mesh_key]
        with np.load(
            Path(bpy.context.scene["expansion_reference_root"]) / info["path"]
        ) as arrays:
            return tuple(len(arrays[f"tri_{i}"]) for i in range(info["submeshes"]))

    def face_count(renderer_id):
        r = renderers[renderer_id]
        info = manifest["meshes"][r["mesh"]]
        count = r.get("batch_count", 0)
        subs = (
            range(r.get("batch_first", 0), r.get("batch_first", 0) + count)
            if count
            else range(info["submeshes"])
        )
        sizes = mesh_face_counts(r["mesh"])
        return sum(sizes[i] for i in subs)

    removed = 0
    for obj in list(bpy.context.scene.objects):
        if obj.get("unity_renderer_id") in hidden:
            obj.hide_set(True)
            obj.hide_render = True
            continue
        ids = list(obj.get("source_renderer_ids", []))
        if not hidden.intersection(ids):
            continue
        counts = [face_count(i) for i in ids]
        mesh = obj.data
        if sum(counts) != len(mesh.polygons) or any(
            p.loop_total != 3 for p in mesh.polygons
        ):
            raise ValueError(
                f"{obj.name}: reference batch provenance changed; use an unedited reference"
            )
        keep = np.repeat([i not in hidden for i in ids], counts)

        def read(items, prop, n, dtype):
            array = np.empty(len(items) * n, dtype=dtype)
            items.foreach_get(prop, array)
            return array.reshape(-1, n) if n > 1 else array

        loops = read(mesh.loops, "vertex_index", 1, np.int32).reshape(-1, 3)[keep]
        used, indices = np.unique(loops, return_inverse=True)
        replacement = bpy.data.meshes.new(mesh.name + " · expansion joins")
        replacement.from_pydata(
            read(mesh.vertices, "co", 3, np.float32)[used], [], indices.reshape(-1, 3)
        )
        for mat in mesh.materials:
            replacement.materials.append(mat)
        replacement.polygons.foreach_set(
            "material_index", read(mesh.polygons, "material_index", 1, np.int32)[keep]
        )
        replacement.polygons.foreach_set(
            "use_smooth", read(mesh.polygons, "use_smooth", 1, bool)[keep]
        )
        corner_keep = np.repeat(keep, 3)
        for layer in mesh.uv_layers:
            replacement.uv_layers.new(name=layer.name).data.foreach_set(
                "uv", read(layer.data, "uv", 2, np.float32)[corner_keep].ravel()
            )
        for layer in mesh.color_attributes:
            if layer.domain not in {"POINT", "CORNER"}:
                continue
            replacement.color_attributes.new(
                name=layer.name, type=layer.data_type, domain=layer.domain
            ).data.foreach_set(
                "color",
                read(layer.data, "color", 4, np.float32)[
                    used if layer.domain == "POINT" else corner_keep
                ].ravel(),
            )
        replacement.normals_split_custom_set(
            read(mesh.corner_normals, "vector", 3, np.float32)[corner_keep]
        )
        replacement.update()
        obj.data = replacement
        obj["expansion_suppressed_renderer_ids"] = [i for i in ids if i in hidden]
        obj["source_renderer_ids"] = [i for i in ids if i not in hidden]
        removed += int((~keep).sum())
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    print(f"Suppressed {removed} reference triangles at replacement joins", flush=True)


def export_recipe(path):
    scene = bpy.context.scene
    placements = []
    geometry_hashes = {}
    material_hashes = {}
    for obj in scene.objects:
        if "expansion_source" not in obj:
            continue
        if obj.type != "MESH" or obj.modifiers:
            raise ValueError(
                f"{obj.name}: native-reference export requires unmodified meshes"
            )
        if obj.data.name not in geometry_hashes:
            geometry_hashes[obj.data.name] = geometry_digest(obj.data)
        binding = tuple(
            slot.material.name if slot.material else None for slot in obj.material_slots
        )
        if binding not in material_hashes:
            material_hashes[binding] = material_digest(obj)
        if geometry_hashes[obj.data.name] != obj.get(
            "expansion_geometry_hash"
        ) or material_hashes[binding] != obj.get("expansion_material_hash"):
            raise ValueError(
                f"{obj.name}: native-reference export requires unchanged mesh geometry and no modifiers"
            )
        # Unity and Blender have opposite handedness: convert the entire transform once.
        matrix = SWAP @ np.asarray(obj.matrix_world) @ SWAP
        scale = np.linalg.norm(matrix[:3, :3], axis=0)
        rotation = matrix[:3, :3] / np.maximum(scale, 1e-20)
        if (
            not np.isfinite(matrix).all()
            or np.any(scale < 0.001)
            or np.any(scale > 100)
            or np.linalg.det(rotation) < 0
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-5)
        ):
            raise ValueError(
                f"{obj.name}: mirrored, singular or sheared transforms are unsupported"
            )
        if obj.get("expansion_collision", "none") not in {"none", "mesh"}:
            raise ValueError(f"{obj.name}: collision must be none or mesh")
        placements.append(
            {
                "id": obj.get("expansion_id", obj.name),
                "source": json.loads(obj["expansion_source"]),
                "matrix": matrix.ravel().tolist(),
                "collision": obj.get("expansion_collision", "none"),
                "render": obj.get("expansion_render", True),
            }
        )
    if not placements or len(placements) > 10000:
        raise ValueError("Export requires between 1 and 10000 native parts")
    ids = [p["id"] for p in placements]
    if len(set(ids)) != len(ids):
        raise ValueError(
            "Duplicate placement IDs; use Duplicate Native Kit to assign new identities"
        )
    document = {
        "schemaVersion": 1,
        "id": scene.get("expansion_id", "native-expansion"),
        "gameVersion": scene.get("expansion_game_version", ""),
        "scene": "Main",
        "placements": placements,
        "suppress": json.loads(scene.get("expansion_suppress", "[]")),
    }
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2), encoding="utf8")
    print(f"Exported {len(placements)} native references to {target}", flush=True)
    return document


def construct(kit_path, plan_path):
    kit = json.loads(Path(kit_path).read_text(encoding="utf8"))
    plan = json.loads(Path(plan_path).read_text(encoding="utf8"))
    if (
        bpy.context.scene.get("source_version", "").split(" ")[0]
        != kit["gameVersion"].split(" ")[0]
    ):
        raise ValueError(
            "Open the optimized reference generated from the same game version as this kit"
        )
    root = Path(kit["referenceRoot"])
    manifest = json.loads((root / "main_manifest.json").read_text(encoding="utf8"))
    objects = {o["id"]: o for o in manifest["objects"]}
    collection = bpy.data.collections.get(COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    if any("expansion_source" in o for o in collection.objects):
        raise ValueError("Expansion collection already has authored native pieces")
    material_map = {
        m.get("unity_material_id"): m
        for m in bpy.data.materials
        if m.get("unity_material_id")
    }
    meshes = {}
    anchor = np.asarray(kit["anchor"])
    for part in kit["parts"] + plan.get("collisionParts", []):
        if part["id"] in meshes:
            continue
        renderer = part["renderer"]
        info = manifest["meshes"][renderer["mesh"]]
        with np.load(root / info["path"]) as arrays:
            first, count = (
                renderer.get("batch_first", 0),
                renderer.get("batch_count", 0),
            )
            submeshes = (
                range(first, first + count) if count else range(info["submeshes"])
            )
            triangles, slots = [], []
            for slot, submesh in enumerate(submeshes):
                tris = arrays[f"tri_{submesh}"]
                triangles.append(tris)
                slots.extend([min(slot, len(renderer["materials"]) - 1)] * len(tris))
            triangles = np.concatenate(triangles)
            used, inverse = np.unique(triangles, return_inverse=True)
            vertices = arrays["vertices"][used, :3].astype(float)
            correction = np.eye(4)
            if count:
                batch_root = (
                    np.asarray(objects[renderer["batch_root"]]["world"])
                    if renderer.get("batch_root")
                    else np.eye(4)
                )
                correction = np.linalg.inv(np.asarray(part["world"])) @ batch_root
                vertices = vertices @ correction[:3, :3].T + correction[:3, 3]
            faces = inverse.reshape(-1, 3)[:, ::-1]
            mesh = bpy.data.meshes.new("Native kit · " + part["name"])
            mesh.from_pydata(vertices[:, [0, 2, 1]], [], faces)
            for material_id in renderer["materials"]:
                if material_id not in material_map:
                    raise ValueError(
                        f"Material {material_id} absent from opened reference; use the matching optimized editor file"
                    )
                mesh.materials.append(material_map[material_id])
            mesh.polygons.foreach_set(
                "material_index", np.asarray(slots, dtype=np.int32)
            )
            mesh.polygons.foreach_set("use_smooth", np.ones(len(faces), dtype=bool))
            for channel, label in [("uv0", "UVMap"), ("uv1", "LightmapUV")]:
                if channel in arrays:
                    layer = mesh.uv_layers.new(name=label)
                    layer.data.foreach_set(
                        "uv",
                        arrays[channel][used][faces, :2].astype(np.float32).ravel(),
                    )
            if "colors" in arrays:
                mesh.color_attributes.new(
                    name="UnityVertexColor", type="FLOAT_COLOR", domain="POINT"
                ).data.foreach_set(
                    "color", arrays["colors"][used].astype(np.float32).ravel()
                )
            if "normals" in arrays:
                normals = arrays["normals"][used, :3].astype(float) @ np.linalg.inv(
                    correction[:3, :3]
                )
                normals = normals[:, [0, 2, 1]]
                normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-12)
                mesh.normals_split_custom_set_from_vertices(normals)
            mesh.update()
            meshes[part["id"]] = mesh
    for index, pose in enumerate(plan["poses"] or [kit["anchor"]]):
        parent = bpy.data.objects.new(f"Native span {index + 1:02}", None)
        collection.objects.link(parent)
        parent.matrix_world = Matrix(SWAP @ np.asarray(pose) @ SWAP)
        parent["expansion_kit"] = kit["name"]
        parent["native_spacing"] = plan.get("spacing", 1)
        for part in kit["parts"]:
            mesh = meshes[part["id"]]
            obj = bpy.data.objects.new(part["name"], mesh)
            collection.objects.link(obj)
            obj.parent = parent
            obj.matrix_local = Matrix(
                SWAP @ np.linalg.inv(anchor) @ np.asarray(part["world"]) @ SWAP
            )
            obj["expansion_source"] = json.dumps(part["source"])
            obj["expansion_id"] = f"span-{index:03}-{part['id']}"
            obj["expansion_geometry_hash"] = geometry_digest(mesh)
            obj["expansion_material_hash"] = material_digest(obj)
            obj["expansion_collision"] = "none" if part["shadowMode"] == 3 else "mesh"
            obj.hide_render = part["shadowMode"] == 3
            obj.hide_set(part["shadowMode"] == 3)
    for part in plan.get("collisionParts", []):
        mesh = meshes[part["id"]]
        obj = bpy.data.objects.new("Collision only · " + part["name"], mesh)
        collection.objects.link(obj)
        obj.matrix_world = Matrix(SWAP @ np.asarray(part["world"]) @ SWAP)
        obj["expansion_source"] = json.dumps(part["source"])
        obj["expansion_id"] = "collision-" + part["id"]
        obj["expansion_geometry_hash"] = geometry_digest(mesh)
        obj["expansion_material_hash"] = material_digest(obj)
        obj["expansion_collision"] = "mesh"
        obj["expansion_render"] = part.get("replacementVisual", False)
        obj.hide_render = not obj["expansion_render"]
        obj.hide_set(not obj["expansion_render"])
    scene = bpy.context.scene
    scene["expansion_reference_root"] = str(root)
    suppress_reference(manifest, plan["suppress"])
    scene["expansion_id"] = (
        "north-island-bridge" if "bridge" in plan["name"].lower() else str(uuid.uuid4())
    )
    scene["expansion_game_version"] = kit["gameVersion"]
    scene["expansion_suppress"] = json.dumps(plan["suppress"])
    scene["expansion_kit_path"] = str(Path(kit_path).resolve())
    native_roots = [o for o in collection.objects if "expansion_kit" in o]
    center = sum((o.matrix_world.translation for o in native_roots), Vector()) / max(
        len(native_roots), 1
    )
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_location = center
                space.region_3d.view_distance = max(
                    35, len(native_roots) * plan.get("spacing", 1)
                )
                space.region_3d.view_rotation = Vector((1, -1, -0.7)).to_track_quat(
                    "-Z", "Y"
                )
                space.clip_start = 0.5
                space.shading.type = "SOLID"
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    if native_roots:
        native_roots[0].select_set(True)
        bpy.context.view_layer.objects.active = native_roots[0]
    scene.tool_settings.use_snap = True
    scene.tool_settings.snap_elements = {"INCREMENT"}
    scene.tool_settings.use_snap_grid_absolute = True
    return collection


class S1_OT_Export(bpy.types.Operator):
    bl_idname = "s1.export_native_expansion"
    bl_label = "Export Native Placements"
    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        try:
            export_recipe(self.filepath)
            self.report(
                {"INFO"}, "Native placements exported; no meshes or textures included"
            )
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

    def invoke(self, context, event):
        self.filepath = str(Path(bpy.data.filepath).with_suffix(".expansion.json"))
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class S1_OT_Duplicate(bpy.types.Operator):
    bl_idname = "s1.duplicate_native_kit"
    bl_label = "Duplicate Native Kit"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        source = context.active_object
        while source and "expansion_kit" not in source:
            source = source.parent
        if source is None:
            self.report({"ERROR"}, "Select a native kit or one of its parts")
            return {"CANCELLED"}
        collection = bpy.data.collections[COLLECTION]
        duplicate = source.copy()
        collection.objects.link(duplicate)
        duplicate.location.y += source.get("native_spacing", 1)
        for child in source.children:
            copy = child.copy()
            copy.data = child.data
            collection.objects.link(copy)
            copy.parent = duplicate
            copy.matrix_parent_inverse = child.matrix_parent_inverse.copy()
            copy.matrix_basis = child.matrix_basis.copy()
            copy["expansion_id"] = str(uuid.uuid4())
            copy.hide_set(child.hide_get())
        for obj in context.selected_objects:
            obj.select_set(False)
        duplicate.select_set(True)
        context.view_layer.objects.active = duplicate
        return {"FINISHED"}


class S1_PT_NativeExpansion(bpy.types.Panel):
    bl_label = "Schedule One Expansion"
    bl_idname = "S1_PT_native_expansion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Schedule One"

    def draw(self, context):
        self.layout.label(text="Native pieces · metre grid")
        self.layout.operator(S1_OT_Duplicate.bl_idname)
        self.layout.operator(S1_OT_Export.bl_idname)
        self.layout.label(text="Move/rotate/scale; keep source meshes unchanged")
        obj = context.active_object
        if obj and "expansion_source" in obj:
            self.layout.prop(
                obj, '["expansion_collision"]', text="Collision (mesh/none)"
            )


CLASSES = (S1_OT_Export, S1_OT_Duplicate, S1_PT_NativeExpansion)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    if "--" not in sys.argv:
        register()
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--kit", required=True)
        parser.add_argument("--plan", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--recipe", required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
        if Path(args.output).exists():
            raise ValueError("Output exists; refusing to overwrite authored work")
        construct(args.kit, args.plan)
        bpy.context.view_layer.update()
        export_recipe(args.recipe)
        bpy.ops.wm.save_as_mainfile(
            filepath=str(Path(args.output).resolve()), compress=True
        )
