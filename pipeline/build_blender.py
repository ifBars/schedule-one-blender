"""Rebuild editable Main map from the local manifest in a clean Blender process."""

from pathlib import Path
from functools import lru_cache
from collections import Counter
import json, math, sys, time, gc
import bpy
import numpy as np
from mathutils import Matrix, Vector, Quaternion

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from surface_settings import MAP_CLIP_START, clear_weather_smoothness

D = json.loads((ROOT / "main_manifest.json").read_text(encoding="utf-8"))
clear_smoothness = clear_weather_smoothness(D["materials"])
N = json.loads(
    (ROOT / "native_rendering/render_components.json").read_text(encoding="utf-8")
)
GO = {o["id"]: o for o in D["objects"]}
C = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
CN = np.asarray(C, dtype=np.float64)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "Main - installed " + D["version"]
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1
scene["unity_to_blender"] = "Unity (x,y,z) -> Blender (x,z,y); one unit = one metre"
scene["source_game"] = D["source"]
scene["source_version"] = D["version"]
scene["native_shader_note"] = (
    "Compiled Unity shaders are translated to Blender nodes, not executed."
)
scene.render.engine = "CYCLES"
scene.cycles.samples = 24
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6
scene.cycles.transparent_max_bounces = 12
scene.render.resolution_x = 1600
scene.render.resolution_y = 1100
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.world = bpy.data.worlds.new("Native ambient — reconstructed")
scene.world.use_nodes = True


def collection(name, parent=None, hidden=False):
    c = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(c)
    c.hide_render = hidden
    return c


reference = collection("01 · MAIN MAP — native reference")
inactive = collection("02 · Inactive and disabled — toggle to inspect", hidden=True)
lodcoll = collection("03 · LOD alternatives — toggle to inspect", hidden=True)
treescol = collection(
    "04 · Terrain tree instances — native distance is zero", hidden=True
)
lighting = collection("05 · Native lights and atmosphere")
expansion = collection("06 · YOUR MAP EXPANSION")
cameras = collection("07 · Review cameras")
hierarchy = collection("00 · Source hierarchy")
regions = {}
objects = {}
errors = []
material_notes = {}


@lru_cache(None)
def region(go):
    chain = []
    cur = go
    while cur:
        chain.append(GO[cur]["name"])
        cur = GO[cur]["parent"]
    for n in chain:
        if n.startswith("Region_"):
            return n
    return chain[-2] if len(chain) > 1 else chain[-1]


def target_collection(r):
    if not r["active"] or not r["enabled"]:
        return inactive
    if r["lod"] > 0:
        return lodcoll
    name = region(r["go"])
    if name not in regions:
        regions[name] = collection(name, reference)
    return regions[name]


def make_node(nt, typ, label="", x=0, y=0):
    n = nt.nodes.new(typ)
    n.label = label
    n.location = (x, y)
    return n


# STAGE: MATERIALS
@lru_cache(None)
def image(k, noncolor=False):
    if not k:
        return None
    d = D["textures"].get(k, {})
    if not d.get("path"):
        return None
    path = d.get("normal_path", d["path"]) if noncolor else d["path"]
    im = bpy.data.images.load(str(ROOT / path), check_existing=not noncolor)
    im.name = d["name"] + (" [data]" if noncolor else "")
    if noncolor:
        im.colorspace_settings.name = "Non-Color"
    im.filepath = str(ROOT / path)
    return im


def texnode(nt, t, noncolor=False, vector=None, label=""):
    im = image(t.get("id"), noncolor)
    if not im:
        return None
    n = make_node(nt, "ShaderNodeTexImage", label)
    n.image = im
    n.extension = "REPEAT"
    if vector:
        nt.links.new(vector, n.inputs["Vector"])
    elif t.get("scale", [1, 1]) != [1, 1] or t.get("offset", [0, 0]) != [0, 0]:
        uv = make_node(nt, "ShaderNodeTexCoord")
        mp = make_node(nt, "ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (*t["scale"], 1)
        mp.inputs["Location"].default_value = (*t["offset"], 0)
        nt.links.new(uv.outputs["UV"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    return n


def mix(nt, mode, a, b, fac=1, label=""):
    n = make_node(nt, "ShaderNodeMixRGB", label)
    n.blend_type = mode
    if hasattr(fac, "node"):
        nt.links.new(fac, n.inputs[0])
    else:
        n.inputs[0].default_value = fac
    for idx, v in [(1, a), (2, b)]:
        if hasattr(v, "node"):
            nt.links.new(v, n.inputs[idx])
        else:
            n.inputs[idx].default_value = v
    return n.outputs[0]


def mathnode(nt, op, a, b=None):
    n = make_node(nt, "ShaderNodeMath")
    n.operation = op
    for i, v in enumerate([a, b]):
        if v is None:
            continue
        if hasattr(v, "node"):
            nt.links.new(v, n.inputs[i])
        else:
            n.inputs[i].default_value = v
    return n.outputs[0]


@lru_cache(None)
def material(k):
    if not k:
        m = bpy.data.materials.new("Unassigned native material")
        return m
    d = D["materials"][k]
    shader = d["shader"]
    f = d["floats"]
    colors = d["colors"]
    ts = d["textures"]
    m = bpy.data.materials.new(d["name"])
    m.use_nodes = True
    m["unity_shader"] = shader
    m["unity_material_id"] = k
    m["source_parameters"] = json.dumps(
        {"floats": f, "colors": colors, "textures": ts}, separators=(",", ":")
    )
    nt = m.node_tree
    bs = nt.nodes.get("Principled BSDF")
    bs.location = (650, 100)
    nt.nodes.get("Material Output").location = (920, 100)
    color = (
        colors.get("_Color", [1, 1, 1, 1])
        if "Worldspace" in shader
        else colors.get("_BaseColor", colors.get("_Color", [1, 1, 1, 1]))
    )
    # Shader graph tint alpha is often unused; keep opaque RGB independent of alpha.
    color = (*color[:3], 1)
    bs.inputs["Base Color"].default_value = color
    m.diffuse_color = color
    smooth = f.get("_Smoothness", f.get("_Glossiness", 0.15))
    if k in clear_smoothness:
        smooth = clear_smoothness[k]
        m["clear_weather_smoothness"] = smooth
        m["surface_translation_note"] = (
            "Clear-weather approximation using median native dry GroundWet smoothness; "
            "serialized wet values retained in source_parameters"
        )
    bs.inputs["Roughness"].default_value = max(0.03, min(1, 1 - smooth))
    bs.inputs["Metallic"].default_value = max(0, min(1, f.get("_Metallic", 0)))
    notes = []
    worldspace = any(x in shader.lower() for x in ["worldspace", "triplanar"])
    vector = None
    if worldspace:
        geom = make_node(nt, "ShaderNodeNewGeometry", "World coordinates")
        mapping = make_node(nt, "ShaderNodeMapping", "Native world tiling")
        nt.links.new(geom.outputs["Position"], mapping.inputs["Vector"])
        tile = f.get("_Tiling", 1)
        tile2 = colors.get("_Tiling2", [1, 1, 0, 0])
        mapping.inputs["Scale"].default_value = (tile * tile2[0], tile * tile2[1], tile)
        mapping.inputs["Rotation"].default_value.z = math.radians(f.get("_Rotation", 0))
        vector = mapping.outputs["Vector"]
        notes.append("world-space box projection; native projection seams may differ")
    basekey = next(
        (
            n
            for n in [
                "_BaseMap",
                "_DiffuseTexture",
                "_MainTex",
                "_BaseColor",
                "_Albedo",
                "_AlbedoTexture",
                "_MainTexture",
                "_Texture",
                "_Color",
                "_Mat1_BaseTexture",
            ]
            if n in ts
        ),
        None,
    )
    if not basekey:
        basekey = next(
            (
                n
                for n in ts
                if any(v in n.lower() for v in ["albedo", "diffuse", "basecolor"])
            ),
            None,
        )
    base = texnode(nt, ts[basekey], vector=vector, label=basekey) if basekey else None
    out = None
    if base:
        if worldspace:
            base.projection = "BOX"
            base.projection_blend = 0.15
        out = mix(
            nt, "MULTIPLY", base.outputs["Color"], color, label="Native base tint"
        )
    if shader == "M_BlendMaster" and base:
        tint = colors.get("_Mat1_Color", [1, 1, 1, 1])
        tint = (*tint[:3], 1)
        out = mix(nt, "MULTIPLY", base.outputs["Color"], tint)
        bs.inputs["Roughness"].default_value = max(0.04, f.get("_Mat1_Roughness", 0.6))
        if "_Mat2_BaseTexture" in ts:
            second = texnode(
                nt, ts["_Mat2_BaseTexture"], label="Native secondary surface"
            )
            vc = make_node(nt, "ShaderNodeVertexColor", "Native vertex blend")
            vc.layer_name = "UnityVertexColor"
            sep = make_node(nt, "ShaderNodeSeparateColor")
            nt.links.new(vc.outputs["Color"], sep.inputs["Color"])
            if second:
                out = mix(nt, "MIX", out, second.outputs["Color"], sep.outputs["Green"])
        notes.append(
            "two surfaces with vertex-color blend; proprietary wear/detail math approximated"
        )
    if "ModularMaster" in shader and base:
        for mask, ck, fk in [
            ("_DoorMask", "Color_3AED6903", "Vector1_E6803737"),
            ("_GarageDoorMask", "Color_8CD000C2", "Vector1_148E1D84"),
            ("_WallColor1Mask", "Color_D97C66B0", "Vector1_A4AFA520"),
            ("_WallColor2Mask", "Color_10A92CEA", "Vector1_1C8DC315"),
            ("_WallColor3Mask", "Color_3D553EDD", "Vector1_FB5E3C0E"),
        ]:
            if mask in ts and f.get(fk, 0) > 0:
                masknode = texnode(nt, ts[mask], True, label=mask)
                if masknode:
                    fac = mathnode(nt, "MULTIPLY", masknode.outputs["Color"], f[fk])
                    tinted = mix(nt, "MULTIPLY", out, colors.get(ck, [1, 1, 1, 1]))
                    out = mix(
                        nt, "MIX", out, tinted, fac, label="Native modular tint mask"
                    )
        notes.append("modular wall/door masks and saved tints reconstructed")
    if out:
        if any(n in f for n in ["_Hue", "_Saturation", "_Lightness"]):
            hsv = make_node(
                nt, "ShaderNodeHueSaturation", "Native material color correction"
            )
            hsv.inputs["Hue"].default_value = 0.5 + f.get("_Hue", 0)
            hsv.inputs["Saturation"].default_value = f.get("_Saturation", 1)
            hsv.inputs["Value"].default_value = f.get("_Lightness", 1)
            nt.links.new(out, hsv.inputs["Color"])
            out = hsv.outputs[0]
        nt.links.new(out, bs.inputs["Base Color"])
    alpha_clip = (
        f.get("_AlphaClip", 0) > 0
        or f.get("_AlphaCutoffEnable", 0) > 0
        or any(
            x in shader.lower()
            for x in ["leaves", "grass", "alphaclip", "cutout", "instancedlitbase"]
        )
    )
    transparent = f.get("_Surface", 0) == 1 or any(
        x in shader.lower() for x in ["transparent", "glass", "particle"]
    )
    if base and (alpha_clip or transparent):
        alpha = base.outputs["Alpha"]
        if alpha_clip:
            alpha = mathnode(
                nt, "GREATER_THAN", alpha, f.get("_Cutoff", f.get("_AlphaCutoff", 0.5))
            )
        nt.links.new(alpha, bs.inputs["Alpha"])
        m.surface_render_method = "DITHERED"
    normalkey = next(
        (
            n
            for n in [
                "_BumpMap",
                "_NormalTexture",
                "_NormalMap",
                "_ModularNormal",
                "_BumpTexture",
                "_Normal",
                "_Mat1_Base_Normal",
            ]
            if n in ts
        ),
        None,
    )
    if normalkey and not worldspace:
        tex = texnode(nt, ts[normalkey], True, label=normalkey)
        if tex:
            normal = make_node(nt, "ShaderNodeNormalMap", "Tangent normal")
            normal.inputs["Strength"].default_value = f.get(
                "_BumpScale", f.get("_NormalStrength", 1)
            )
            nt.links.new(tex.outputs["Color"], normal.inputs["Color"])
            nt.links.new(normal.outputs["Normal"], bs.inputs["Normal"])
    metalkey = next(
        (n for n in ["_MetallicGlossMap", "_Metallic_Map"] if n in ts), None
    )
    if metalkey:
        t = texnode(nt, ts[metalkey], True, vector=vector, label=metalkey)
        if t:
            nt.links.new(t.outputs["Color"], bs.inputs["Metallic"])
            rough = mathnode(
                nt, "SUBTRACT", 1, mathnode(nt, "MULTIPLY", t.outputs["Alpha"], smooth)
            )
            nt.links.new(rough, bs.inputs["Roughness"])
    aokey = next((n for n in ["_OcclusionMap", "_ModularAO"] if n in ts), None)
    if aokey and out:
        a = texnode(nt, ts[aokey], True, label=aokey)
        if a:
            nt.links.new(
                mix(
                    nt,
                    "MULTIPLY",
                    out,
                    a.outputs["Color"],
                    f.get("_OcclusionStrength", 1),
                ),
                bs.inputs["Base Color"],
            )
    emission = colors.get("_EmissionColor", colors.get("_EmissiveColor", [0, 0, 0, 1]))
    if max(emission[:3]) > 0 and (
        "_EMISSION" in d.get("keywords", []) or "_EmissionMap" in ts
    ):
        bs.inputs["Emission Color"].default_value = emission
        bs.inputs["Emission Strength"].default_value = 1
        if "_EmissionMap" in ts:
            t = texnode(nt, ts["_EmissionMap"], label="Emission")
            if t:
                nt.links.new(
                    mix(nt, "MULTIPLY", t.outputs["Color"], emission),
                    bs.inputs["Emission Color"],
                )
    if "water" in shader.lower():
        col = colors.get("_DeepColor", colors.get("_BaseColor", [0.035, 0.20, 0.25, 1]))
        bs.inputs["Base Color"].default_value = (*col[:3], 1)
        bs.inputs["Metallic"].default_value = 0.05
        bs.inputs["Roughness"].default_value = 0.17
        bs.inputs["Transmission Weight"].default_value = 0.30
        bs.inputs["IOR"].default_value = 1.333
        noise = make_node(nt, "ShaderNodeTexNoise", "Static water surface")
        noise.inputs["Scale"].default_value = 1.8
        noise.inputs["Detail"].default_value = 3
        bump = make_node(nt, "ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.18
        bump.inputs["Distance"].default_value = 0.07
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs[0], bs.inputs["Normal"])
        notes.append(
            "static water approximation; depth foam/refraction/wave runtime not ported"
        )
    if "glass" in shader.lower():
        bs.inputs["Transmission Weight"].default_value = 0.8
        bs.inputs["Roughness"].default_value = 0.08
        bs.inputs["IOR"].default_value = 1.45
        notes.append("glass transmission approximation")
    if "unlit" in shader.lower() and out:
        nt.links.new(out, bs.inputs["Emission Color"])
        bs.inputs["Emission Strength"].default_value = 1
    if shader.startswith("Shader Graphs/") and not notes:
        notes.append(
            "saved textures/parameters mapped; graph operations are not available as source"
        )
    material_notes[k] = {
        "name": d["name"],
        "shader": shader,
        "base_texture": basekey,
        "notes": notes,
    }
    # Arrange nodes to keep the generated materials inspectable.
    for i, n in enumerate(nt.nodes):
        if n not in [bs, nt.nodes.get("Material Output")]:
            n.location = (-900 + (i % 5) * 270, -(i // 5) * 250)
    return m


# STAGE: GEOMETRY
@lru_cache(maxsize=32)
def mesh_arrays(k):
    with np.load(ROOT / D["meshes"][k]["path"]) as a:
        return {n: a[n] for n in a.files}


mesh_cache = {}


def geometry(r):
    k = r["mesh"]
    batch = r.get("batch_count", 0)
    first = r.get("batch_first", 0)
    skin = bool(r.get("bones"))
    cachekey = (k, first, batch, tuple(r["materials"]), r["go"] if batch or skin else 0)
    if cachekey in mesh_cache:
        return mesh_cache[cachekey]
    a = mesh_arrays(k)
    subids = (
        range(first, first + batch) if batch else range(D["meshes"][k]["submeshes"])
    )
    faceparts = []
    matparts = []
    for mi, si in enumerate(subids):
        t = a[f"tri_{si}"]
        faceparts.append(t)
        matparts.append(
            np.full(len(t), min(mi, max(0, len(r["materials"]) - 1)), dtype=np.int32)
        )
    faces = np.concatenate(faceparts) if faceparts else np.empty((0, 3), dtype=np.int32)
    if not len(faces):
        return None
    used, inverse = np.unique(faces, return_inverse=True)
    faces = inverse.reshape(-1, 3)[:, ::-1].astype(np.int32)
    verts = a["vertices"][used, :3].astype(np.float64)
    normals = a.get("normals")
    normals = normals[used, :3].astype(np.float64) if normals is not None else None
    singular = False
    if batch:
        objworld = np.asarray(GO[r["go"]]["world"])
        rootworld = (
            np.asarray(GO[r["batch_root"]]["world"]) if r["batch_root"] else np.eye(4)
        )
        singular = abs(np.linalg.det(objworld[:3, :3])) < 1e-15
        correction = np.eye(4) if singular else np.linalg.inv(objworld) @ rootworld
        verts = verts @ correction[:3, :3].T + correction[:3, 3]
        if normals is not None:
            normals = normals @ np.linalg.inv(correction[:3, :3])
    if skin and "bind_poses" in a:
        bones = r["bones"]
        poses = a["bind_poses"]
        weights = a["bone_weights"][used]
        indices = a["bone_indices"][used]
        transform = np.asarray(
            [
                np.linalg.inv(np.asarray(GO[r["go"]]["world"]))
                @ np.asarray(GO[g]["world"])
                @ poses[i]
                if g in GO and i < len(poses)
                else np.eye(4)
                for i, g in enumerate(bones)
            ]
        )
        if len(transform) and indices.max(initial=0) < len(transform):
            skinv = np.zeros_like(verts)
            for slot in range(min(indices.shape[1], weights.shape[1])):
                tr = transform[indices[:, slot]]
                skinv += (
                    np.einsum("nij,nj->ni", tr[:, :3, :3], verts) + tr[:, :3, 3]
                ) * weights[:, slot, None]
            verts = skinv
            normals = None
    verts = verts[:, [0, 2, 1]].astype(np.float32)
    m = bpy.data.meshes.new(D["meshes"][k]["name"][:45] + f"__{r['go']}")
    m.vertices.add(len(verts))
    m.vertices.foreach_set("co", verts.ravel())
    m.loops.add(faces.size)
    m.loops.foreach_set("vertex_index", faces.ravel())
    m.polygons.add(len(faces))
    m.polygons.foreach_set("loop_start", np.arange(len(faces), dtype=np.int32) * 3)
    m.polygons.foreach_set("loop_total", np.full(len(faces), 3, dtype=np.int32))
    m.polygons.foreach_set("material_index", np.concatenate(matparts))
    m.polygons.foreach_set("use_smooth", np.ones(len(faces), dtype=bool))
    for uvname in ["uv0", "uv1"]:
        if uvname in a:
            uv = a[uvname][used, :2][faces.ravel()]
            layer = m.uv_layers.new(name="UVMap" if uvname == "uv0" else "LightmapUV")
            layer.data.foreach_set("uv", uv.ravel())
    if "colors" in a:
        cols = a["colors"][used]
        if cols.shape[1] == 3:
            cols = np.column_stack((cols, np.ones(len(cols))))
        layer = m.color_attributes.new(
            name="UnityVertexColor", type="BYTE_COLOR", domain="POINT"
        )
        layer.data.foreach_set("color", cols.ravel())
    for mk in r["materials"]:
        m.materials.append(material(mk))
    m.update()
    if normals is not None:
        normals = normals[:, [0, 2, 1]]
        length = np.linalg.norm(normals, axis=1)
        length[length == 0] = 1
        m.normals_split_custom_set_from_vertices((normals / length[:, None]).tolist())
    m["unity_mesh_id"] = k
    if singular:
        m["unity_singular_transform_preserved_in_world"] = True
    mesh_cache[cachekey] = m
    return m


# STAGE: OBJECTS
print(
    "BUILD",
    len(D["objects"]),
    "hierarchy records",
    len(D["renderers"]),
    "renderers",
    flush=True,
)
mesh_gos = {
    r["go"]
    for r in D["renderers"]
    if not r.get("empty") and D["meshes"][r["mesh"]]["triangles"] > 0
}
for i, g in enumerate(D["objects"]):
    if g["id"] in mesh_gos:
        continue
    o = bpy.data.objects.new(g["name"][:48] + f"__{g['id']}", None)
    o.empty_display_size = 0.08
    hierarchy.objects.link(o)
    objects[g["id"]] = o
print("HIERARCHY placeholders", len(objects), flush=True)

for i, r in enumerate(sorted(D["renderers"], key=lambda r: r.get("mesh", ""))):
    if r.get("empty"):
        continue
    try:
        m = geometry(r)
        if m is None:
            continue
        o = bpy.data.objects.new(GO[r["go"]]["name"][:48] + f"__R{r['id']}", m)
        if m.get("unity_singular_transform_preserved_in_world"):
            o.matrix_world = (
                C
                @ (
                    Matrix(GO[r["batch_root"]]["world"])
                    if r["batch_root"]
                    else Matrix.Identity(4)
                )
                @ C
            )
            o["original_gameobject"] = r["go"]
        elif r["go"] in objects:
            o.parent = objects[r["go"]]
            o.matrix_local = Matrix.Identity(4)
        else:
            objects[r["go"]] = o
        o["unity_renderer_id"] = r["id"]
        o["unity_lod"] = r["lod"]
        o["native_shader_translation"] = True
        if not any(r.get("materials", [])):
            o.hide_render = True
            o.hide_viewport = True
            o["visibility_note"] = (
                "No native material: Unity does not draw this navigation/outline helper."
            )
        target_collection(r).objects.link(o)
    except Exception as ex:
        errors.append(
            {"renderer": r["id"], "name": GO[r["go"]]["name"], "error": str(ex)}
        )
    if i % 2000 == 0:
        print(
            "BUILD renderers",
            i,
            "meshes",
            len(bpy.data.meshes),
            "errors",
            len(errors),
            flush=True,
        )
print("LINK source transforms", flush=True)
for g in D["objects"]:
    if g["id"] not in objects:
        o = bpy.data.objects.new(g["name"][:48] + f"__{g['id']}", None)
        hierarchy.objects.link(o)
        objects[g["id"]] = o
for g in D["objects"]:
    o = objects[g["id"]]
    o["unity_id"] = g["id"]
    o["unity_name"] = g["name"]
    o["unity_active"] = g["active_hierarchy"]
    o["unity_position"] = g["p"]
    o["unity_rotation_xyzw"] = g["q"]
    o["unity_scale"] = g["s"]
    if g["parent"]:
        o.parent = objects[g["parent"]]
    # Explicit TRS preserves rotation when a source scale axis is zero.
    o.location = (g["p"][0], g["p"][2], g["p"][1])
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = (g["q"][3], -g["q"][0], -g["q"][2], -g["q"][1])
    o.scale = (g["s"][0], g["s"][2], g["s"][1])
mesh_arrays.cache_clear()
gc.collect()

# Terrain reconstruction and native presentation are in a separate reproducible module.
try:
    exec(
        compile(
            (ROOT / "build_environment.py").read_text(encoding="utf-8"),
            str(ROOT / "build_environment.py"),
            "exec",
        )
    )
except BaseException:
    bpy.ops.wm.save_as_mainfile(
        filepath=str(ROOT / "Main_incomplete_checkpoint.blend"), compress=True
    )
    raise

for coll in [inactive, lodcoll, treescol]:
    scene.view_layers[0].layer_collection.children[coll.name].exclude = True
scene.view_layers[0].active_layer_collection = scene.view_layers[
    0
].layer_collection.children[expansion.name]
scene.render.image_settings.file_format = "PNG"
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.clip_start = MAP_CLIP_START
            space.clip_end = 3000
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            space.region_3d.view_distance = 360
            space.region_3d.view_location = (0, 0, 0)
            space.region_3d.view_rotation = Quaternion(
                (0.880, 0.280, 0.116, 0.365)
            ).normalized()
            space.overlay.show_extras = False
report = {
    "objects": len(bpy.data.objects),
    "meshes": len(bpy.data.meshes),
    "materials": len(bpy.data.materials),
    "images": len(bpy.data.images),
    "vertices": sum(len(m.vertices) for m in bpy.data.meshes),
    "polygons": sum(len(m.polygons) for m in bpy.data.meshes),
    "errors": errors,
    "material_notes": material_notes,
}
(ROOT / "blender_build_report.json").write_text(json.dumps(report, indent=2))
doc = bpy.data.texts.new("START HERE — map expansion")
doc.write((ROOT / "README.md").read_text(encoding="utf-8"))
print("PACKING textures", len(bpy.data.images), flush=True)
bpy.ops.file.pack_all()
print("SAVING", flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "Schedule_I_Main.blend"), compress=True)
print(
    "DONE",
    json.dumps({k: v for k, v in report.items() if k != "material_notes"}),
    flush=True,
)
