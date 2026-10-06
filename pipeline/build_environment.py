"""Executed by build_blender.py with its scene/data helpers in scope."""

# Rebind the latest deterministic material definitions after the geometry phase.
# This also permits material iteration without rebuilding the expensive scene hierarchy.
D = json.loads((ROOT / "main_manifest.json").read_text(encoding="utf-8"))
N = json.loads(
    (ROOT / "native_rendering/render_components.json").read_text(encoding="utf-8")
)
B = json.loads(
    (ROOT / "native_rendering/render_bindings.json").read_text(encoding="utf-8")
)
builder = (ROOT / "build_blender.py").read_text(encoding="utf-8")
if errors:
    (ROOT / "first_pass_findings.json").write_text(json.dumps(errors, indent=2))
    print("FIRST PASS FINDINGS", Counter(e["error"] for e in errors), flush=True)
    # A zero-scale source Transform cannot be inverted. Keep its batched geometry
    # in the original batch-root space and retain the source transform separately.
    geom_start = builder.index("# STAGE: GEOMETRY")
    geom_end = builder.index("# STAGE: OBJECTS")
    preserved_mesh_cache = mesh_cache
    exec(
        compile(
            builder[geom_start:geom_end],
            str(ROOT / "build_blender.py") + " geometry repair",
            "exec",
        )
    )
    mesh_cache = preserved_mesh_cache
    failed_ids = {e["renderer"] for e in errors}
    remaining = []
    for r in D["renderers"]:
        if r["id"] not in failed_ids:
            continue
        try:
            me = geometry(r)
            if me is None:
                continue
            o = bpy.data.objects.new(GO[r["go"]]["name"] + f"__R{r['id']}", me)
            if me.get("unity_singular_transform_preserved_in_world"):
                o.matrix_world = (
                    C
                    @ (
                        Matrix(GO[r["batch_root"]]["world"])
                        if r["batch_root"]
                        else Matrix.Identity(4)
                    )
                    @ C
                )
            else:
                o.parent = objects[r["go"]]
                o.matrix_local = Matrix.Identity(4)
            o["unity_renderer_id"] = r["id"]
            o["original_gameobject"] = r["go"]
            o["unity_lod"] = r["lod"]
            target_collection(r).objects.link(o)
        except Exception as ex:
            remaining.append({"renderer": r["id"], "error": str(ex)})
    errors[:] = remaining
    print("RECOVERED zero-scale batch transforms; remaining errors", errors, flush=True)
start = builder.index("# STAGE: MATERIALS")
end = builder.index("# STAGE: GEOMETRY")
exec(
    compile(
        builder[start:end],
        str(ROOT / "build_blender.py") + " material definitions",
        "exec",
    )
)
old_materials = [m for m in bpy.data.materials if m.get("unity_material_id")]
replacements = {}
for old in old_materials:
    replacements[old.name] = material(old["unity_material_id"])
for me in bpy.data.meshes:
    for i, old in enumerate(me.materials):
        if old and old.name in replacements:
            me.materials[i] = replacements[old.name]
original_names = {old.name: replacements[old.name] for old in old_materials}
bpy.data.batch_remove(ids=[old for old in old_materials if old.users == 0])
for original_name, new in original_names.items():
    new.name = original_name
bpy.data.batch_remove(ids=[im for im in bpy.data.images if im.users == 0])
terrain_collection = collection("Terrain — full resolution and native holes", reference)
for terrain in D["terrains"]:
    if len(terrain["alphas"]) != 1 or not 1 <= len(terrain["layers"]) <= 4:
        raise ValueError(
            "This terrain requires a multi-control-map adapter: " + terrain["name"]
        )
    print("BUILD terrain", terrain["name"], flush=True)
    td = np.load(ROOT / terrain["path"])
    height = td["heights"]
    holes = td["holes"]
    res = terrain["resolution"]
    scale = terrain["scale"]
    width = (res - 1) * scale[0]
    depth = (res - 1) * scale[2]
    mat = bpy.data.materials.new(terrain["name"] + " — native splat layers")
    mat.use_nodes = True
    nt = mat.node_tree
    bs = nt.nodes.get("Principled BSDF")
    bs.inputs["Roughness"].default_value = 0.95
    uv = make_node(nt, "ShaderNodeTexCoord")
    alpha = texnode(
        nt, {"id": terrain["alphas"][0]}, True, label="Native terrain weights"
    )
    if alpha:
        alpha.image.alpha_mode = "CHANNEL_PACKED"
        alpha.extension = "EXTEND"
        sep = make_node(nt, "ShaderNodeSeparateColor")
        nt.links.new(alpha.outputs["Color"], sep.inputs["Color"])
        weights = [
            sep.outputs["Red"],
            sep.outputs["Green"],
            sep.outputs["Blue"],
            alpha.outputs["Alpha"],
        ]
    else:
        weights = [1, 0, 0, 0]
    total = None
    for i, layer in enumerate(terrain["layers"]):
        mapping = make_node(nt, "ShaderNodeMapping", layer["name"] + " tiling")
        mapping.inputs["Scale"].default_value = (
            width / layer["size"][0],
            depth / layer["size"][1],
            1,
        )
        mapping.inputs["Location"].default_value = (
            layer["offset"][0] / layer["size"][0],
            layer["offset"][1] / layer["size"][1],
            0,
        )
        nt.links.new(uv.outputs["UV"], mapping.inputs["Vector"])
        tex = texnode(
            nt,
            {"id": layer["diffuse"]},
            vector=mapping.outputs["Vector"],
            label=layer["name"],
        )
        if tex:
            term = mix(nt, "MIX", (0, 0, 0, 1), tex.outputs["Color"], weights[i % 4])
            total = mix(nt, "ADD", total, term) if total else term
    if total:
        nt.links.new(total, bs.inputs["Base Color"])
    mat["height_normalization"] = 32766
    # Serialized tree Y values verify Unity's signed 16-bit height normalization of 32766.
    for z0 in range(0, res - 1, 256):
        for x0 in range(0, res - 1, 256):
            nz = min(256, res - 1 - z0)
            nx = min(256, res - 1 - x0)
            zz, xx = np.mgrid[z0 : z0 + nz + 1, x0 : x0 + nx + 1]
            verts = np.column_stack(
                (
                    xx.ravel() * scale[0],
                    zz.ravel() * scale[2],
                    height[zz, xx].ravel() / 32766 * scale[1],
                )
            ).astype(np.float32)
            zz0, xx0 = np.mgrid[0:nz, 0:nx]
            a = (zz0 * (nx + 1) + xx0).ravel()
            faces = np.column_stack((a, a + 1, a + nx + 2, a + nx + 1)).astype(np.int32)
            # Unity's serialized mask uses 255 for surface and 0 for a hole.
            faces = faces[holes[z0 : z0 + nz, x0 : x0 + nx].ravel() != 0]
            if not len(faces):
                continue
            used, remap = np.unique(faces, return_inverse=True)
            faces = remap.reshape(-1, 4).astype(np.int32)
            verts = verts[used]
            m = bpy.data.meshes.new(f"{terrain['name']}_{x0}_{z0}")
            m.vertices.add(len(verts))
            m.vertices.foreach_set("co", verts.ravel())
            m.loops.add(faces.size)
            m.loops.foreach_set("vertex_index", faces.ravel())
            m.polygons.add(len(faces))
            m.polygons.foreach_set(
                "loop_start", np.arange(len(faces), dtype=np.int32) * 4
            )
            m.polygons.foreach_set("loop_total", np.full(len(faces), 4, dtype=np.int32))
            m.polygons.foreach_set("use_smooth", np.ones(len(faces), dtype=bool))
            uvs = verts[:, :2] / [width, depth]
            m.uv_layers.new(name="UVMap").data.foreach_set(
                "uv", uvs[faces.ravel()].astype(np.float32).ravel()
            )
            m.materials.append(mat)
            m.update()
            o = bpy.data.objects.new(m.name, m)
            terrain_collection.objects.link(o)
            o.parent = objects[terrain["go"]]
            o["unity_terrain_sample_origin"] = [x0, z0]
            o["native_grid_spacing"] = [scale[0], scale[2]]
    for i, t in enumerate(terrain["trees"]):
        rootmatrix = Matrix.LocRotScale(
            Vector((t["p"][0] * width, t["p"][1] * scale[1], t["p"][2] * depth)),
            Quaternion((0, 1, 0), t["rotation"]),
            Vector((t["width"], t["height"], t["width"])),
        )
        for proto in terrain["prototypes"][t["index"]]:
            if proto["lod"] > 0:
                continue
            r = {
                "mesh": proto["mesh"],
                "materials": proto["materials"],
                "go": terrain["go"],
            }
            me = geometry(r)
            if not me:
                continue
            obj = bpy.data.objects.new(f"TerrainTree_{i}_{proto['name']}", me)
            treescol.objects.link(obj)
            obj.matrix_world = (
                C
                @ Matrix(GO[terrain["go"]]["world"])
                @ rootmatrix
                @ Matrix(proto["matrix"])
                @ C
            )
            obj["native_tree_distance"] = terrain["tree_distance"]
    print("TERRAIN DONE", terrain["name"], flush=True)

gpu = json.loads(
    (ROOT / "native_rendering/gpu_instances.json").read_text(encoding="utf-8")
)
forest = collection("Forest — native GPU instance placements", reference)
me = geometry(
    {"mesh": gpu["mesh"], "materials": [gpu["material"]], "go": D["terrains"][0]["go"]}
)
for i, (p, q) in enumerate(zip(gpu["positions"], gpu["rotations"])):
    o = bpy.data.objects.new(f"PineTree_GPU_{i:04}", me)
    forest.objects.link(o)
    o.matrix_world = (
        C
        @ Matrix.LocRotScale(
            Vector(p[:3]), Quaternion((q[3], *q[:3])), Vector((p[3],) * 3)
        )
        @ C
    )
    o["native_gpu_instance"] = i
print("GPU FOREST", len(forest.objects), flush=True)

rs = next(v["data"] for v in N.values() if v["type"] == "RenderSettings")
wn = scene.world.node_tree
wn.nodes.clear()
out = make_node(wn, "ShaderNodeOutputWorld")
bg = make_node(wn, "ShaderNodeBackground")
geom = make_node(wn, "ShaderNodeTexCoord")
sep = make_node(wn, "ShaderNodeSeparateXYZ")
wn.links.new(geom.outputs["Normal"], sep.inputs[0])
remap = make_node(wn, "ShaderNodeMapRange")
remap.inputs["From Min"].default_value = -1
remap.inputs["From Max"].default_value = 1
wn.links.new(sep.outputs["Z"], remap.inputs["Value"])
ramp = make_node(wn, "ShaderNodeValToRGB", "Native trilight ambient")


def color_dict(d):
    return (d["r"], d["g"], d["b"], d.get("a", 1))


ramp.color_ramp.elements[0].color = color_dict(rs["m_AmbientGroundColor"])
ramp.color_ramp.elements[1].color = color_dict(rs["m_AmbientSkyColor"])
ramp.color_ramp.elements.new(0.5).color = color_dict(rs["m_AmbientEquatorColor"])
wn.links.new(remap.outputs[0], ramp.inputs[0])
wn.links.new(ramp.outputs[0], bg.inputs["Color"])
bg.inputs["Strength"].default_value = rs["m_AmbientIntensity"] * 0.65
wn.links.new(bg.outputs[0], out.inputs["Surface"])

# Unity light +Z faces forward; Blender light -Z faces forward.
flip = Matrix.Rotation(math.pi, 4, "X")
light_count = 0
for key, v in N.items():
    if (
        not key.startswith(D["scene_file"] + "_")
        or v["type"] != "Light"
        or "world" not in v
    ):
        continue
    d = v["data"]
    kind = {0: "SPOT", 1: "SUN", 2: "POINT", 3: "AREA", 4: "AREA"}.get(
        d["m_Type"], "POINT"
    )
    l = bpy.data.lights.new(v["name"], kind)
    c = d["m_Color"]
    l.color = (c["r"], c["g"], c["b"])
    energy = d["m_Intensity"]
    # Directional intensity is comparable; point/spot power requires a renderer-specific conversion.
    l.energy = energy if kind == "SUN" else energy * 4 * math.pi
    if kind == "SUN":
        l.angle = math.radians(0.53)
    else:
        l.use_custom_distance = True
        l.cutoff_distance = d["m_Range"]
        if kind in ["POINT", "SPOT"]:
            l.shadow_soft_size = 0.1
    if kind == "SPOT":
        l.spot_size = math.radians(d["m_SpotAngle"])
        l.spot_blend = 0.25
    o = bpy.data.objects.new(v["name"] + "__" + key, l)
    lighting.objects.link(o)
    o.matrix_world = C @ Matrix(v["world"]) @ flip
    o.hide_render = not (
        v.get("active_hierarchy", True) and d.get("m_Enabled", 1) and energy > 0
    )
    o.hide_viewport = o.hide_render
    l["unity_intensity"] = energy
    l["unity_range"] = d["m_Range"]
    l["native_component_id"] = key
    light_count += 1
print("LIGHTS", light_count, flush=True)

daylight = json.loads(
    (ROOT / "native_rendering/noon_clear_evaluated.json").read_text(encoding="utf-8")
)
grad = daylight["gradients"]
scene["reference_hour"] = 12
scene["reference_weather"] = "ClearProfile"
sun = next(o for o in lighting.objects if o.data.get("native_component_id") == B["sun"])
sun.hide_render = False
sun.hide_viewport = False
sun.data.energy = daylight["sun_intensity"]
sun.data.color = grad["_sunLightGradient"]
sun.matrix_world = (
    C @ Matrix(daylight["pivot_world"]) @ Matrix.Rotation(math.pi / 2, 4, "X") @ flip
)
sky_renderer = N[B["controller"]]["data"]["_skyRenderer"]["m_PathID"]
for o in bpy.data.objects:
    if o.get("unity_renderer_id") == sky_renderer:
        o.hide_render = True
        o.hide_viewport = True
        o["replacement"] = "Native sky gradients in World nodes"
ramp.color_ramp.elements[0].color = (*grad["_ambientGroundGradient"], 1)
ramp.color_ramp.elements[1].color = (*grad["_ambientEquatorGradient"], 1)
ramp.color_ramp.elements[2].color = (*grad["_ambientSkyGradient"], 1)
bg.inputs["Strength"].default_value = 1
scene.world["native_noon_sky"] = json.dumps(daylight)


def camera(name, position, target, lens=40, ortho=None):
    d = bpy.data.cameras.new(name)
    d.lens = lens
    d.clip_start = MAP_CLIP_START
    d.clip_end = 4000
    if ortho:
        d.type = "ORTHO"
        d.ortho_scale = ortho
    o = bpy.data.objects.new(name, d)
    cameras.objects.link(o)
    o.location = position
    o.rotation_euler = (Vector(target) - o.location).to_track_quat("-Z", "Y").to_euler()
    return o


scene.camera = camera("Overview — southwest", (320, -420, 330), (5, 0, 2), 42)
camera("Map — orthographic top", (15, -10, 650), (15, -10, 0), ortho=580)
camera("Docks — expansion context", (-157, -133, 64), (-80, -55, 4), 45)
camera("Town — street materials", (25, -15, 25), (-8, 25, 3), 42)
camera("Town hall — reference comparison", (14, 65, 30), (59, 31, 7), 35)
camera("Arcade — reference comparison", (-80, 107, 20), (-47, 139, 4), 35)
for name, p, t in [
    ("North", (0, 420, 140), (0, 0, 5)),
    ("South", (0, -420, 140), (0, 0, 5)),
    ("East", (420, 0, 140), (0, 0, 5)),
    ("West", (-420, 0, 140), (0, 0, 5)),
]:
    camera(name + " — map review", p, t, 40)

# Native global-volume numeric settings. Algorithms remain Blender equivalents.
color = N[B["color"]]["data"]
bloom = N[B["bloom"]]["data"]
scene.view_settings.exposure = color["postExposure"]["m_Value"]
scene["native_global_postprocess"] = json.dumps(
    {"color": color, "bloom": bloom, "tonemapping": "disabled"}
)
nt = bpy.data.node_groups.new(
    "Native global volume — Blender equivalents", "CompositorNodeTree"
)
scene.compositing_node_group = nt
nt.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
rl = nt.nodes.new("CompositorNodeRLayers")
hs = nt.nodes.new("CompositorNodeHueSat")
hs.inputs["Saturation"].default_value = 1 + color["saturation"]["m_Value"] / 100
# Reconstruct distance haze from native fog color, with an explicitly tunable
# optical-density scale for Blender. This is a visual approximation of the custom pass.
scene.view_layers[0].use_pass_z = True
fog_depth = nt.nodes.new("ShaderNodeMath")
fog_depth.operation = "MULTIPLY"
fog_depth.inputs[1].default_value = -0.0005 * grad["_fogDensityGradient"][0]
nt.links.new(rl.outputs["Depth"], fog_depth.inputs[0])
fog_exp = nt.nodes.new("ShaderNodeMath")
fog_exp.operation = "EXPONENT"
nt.links.new(fog_depth.outputs[0], fog_exp.inputs[0])
fog_fac = nt.nodes.new("ShaderNodeMath")
fog_fac.operation = "SUBTRACT"
fog_fac.inputs[0].default_value = 1
nt.links.new(fog_exp.outputs[0], fog_fac.inputs[1])
fog_mix = nt.nodes.new("ShaderNodeMixRGB")
fog_mix.blend_type = "MIX"
fog_mix.inputs[2].default_value = (*grad["_fogColorGradient"], 1)
nt.links.new(fog_fac.outputs[0], fog_mix.inputs[0])
nt.links.new(rl.outputs["Image"], fog_mix.inputs[1])
nt.links.new(fog_mix.outputs[0], hs.inputs["Image"])
scene["fog_approximation_density_scale"] = 0.0005
bc = nt.nodes.new("CompositorNodeBrightContrast")
bc.inputs["Contrast"].default_value = color["contrast"]["m_Value"]
nt.links.new(hs.outputs["Image"], bc.inputs["Image"])
gl = nt.nodes.new("CompositorNodeGlare")
gl.inputs["Type"].default_value = "Fog Glow"
gl.inputs["Quality"].default_value = "High"
if "Threshold" in gl.inputs:
    gl.inputs["Threshold"].default_value = bloom["threshold"]["m_Value"]
elif hasattr(gl, "threshold"):
    gl.threshold = bloom["threshold"]["m_Value"]
if "Strength" in gl.inputs:
    gl.inputs["Strength"].default_value = bloom["intensity"]["m_Value"]
nt.links.new(bc.outputs["Image"], gl.inputs["Image"])
co = nt.nodes.new("NodeGroupOutput")
nt.links.new(gl.outputs["Image"], co.inputs["Image"])
for i, n in enumerate(nt.nodes):
    n.location = (i * 230, 0)

for name in ["project_settings.json", "render_components.json", "shader_metadata.json"]:
    p = ROOT / "native_rendering" / name
    if p.exists():
        txt = bpy.data.texts.new("Native evidence — " + name)
        txt.write(p.read_text(encoding="utf-8"))

# Resolve paths against the artifact directory before packing in a factory-startup process.
for im in bpy.data.images:
    if im.filepath.startswith("//"):
        im.filepath = str(ROOT / im.filepath[2:])
