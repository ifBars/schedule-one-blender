"""Final native-texture water and foliage translations for the reference scene."""

import bpy, json, sys
from pathlib import Path

root = Path(__file__).resolve().parent
d = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
for m in bpy.data.materials:
    shader = m.get("unity_shader", "")
    if shader != "Custom/InstancedLitBase_Deferred" and "Stylized Water" not in shader:
        continue
    p = json.loads(m["source_parameters"])
    nt = m.node_tree
    f = p["floats"]
    colors = p["colors"]
    bs = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    if shader == "Custom/InstancedLitBase_Deferred":
        bs.inputs["Emission Strength"].default_value = 0
        for n in nt.nodes:
            if n.bl_idname == "ShaderNodeHueSaturation":
                n.inputs["Value"].default_value = 0.55
            if n.bl_idname == "ShaderNodeMath" and n.operation == "GREATER_THAN":
                n.inputs[1].default_value = f["_AlphaCutoff"]
        m["foliage_scattering_note"] = (
            "Diffuse brightness calibrated to 0.55 for missing native subsurface light; native lightness 0.13 remains in source_parameters."
        )
        continue
    geom = nt.nodes.new("ShaderNodeNewGeometry")

    def texture(prop, tiling, data=False):
        td = d["textures"][p["textures"][prop]["id"]]
        path = str(root / (td.get("normal_path", td["path"]) if data else td["path"]))
        im = bpy.data.images.load(path, check_existing=True)
        if data:
            im.colorspace_settings.name = "Non-Color"
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = im
        tex.label = "Native water " + prop
        mapping = nt.nodes.new("ShaderNodeVectorMath")
        mapping.operation = "MULTIPLY"
        mapping.inputs[1].default_value = (tiling, tiling, 0)
        nt.links.new(geom.outputs["Position"], mapping.inputs[0])
        nt.links.new(mapping.outputs[0], tex.inputs["Vector"])
        return tex

    if "_BumpMap" in p["textures"]:
        tex = texture("_BumpMap", f.get("_NormalTiling", 0.4), True)
        normal = nt.nodes.new("ShaderNodeNormalMap")
        normal.inputs["Strength"].default_value = f.get("_NormalStrength", 0.2)
        nt.links.new(tex.outputs["Color"], normal.inputs["Color"])
        nt.links.new(normal.outputs[0], bs.inputs["Normal"])
    if "_FoamTex" in p["textures"] and f.get("_FoamOn", 0):
        tex = texture("_FoamTex", f.get("_FoamTiling", 0.2), True)
        threshold = nt.nodes.new("ShaderNodeMath")
        threshold.operation = "GREATER_THAN"
        threshold.inputs[1].default_value = max(0.5, 1 - f.get("_FoamBaseAmount", 0.2))
        nt.links.new(tex.outputs["Color"], threshold.inputs[0])
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MIX"
        mix.inputs[1].default_value = (*colors["_BaseColor"][:3], 1)
        mix.inputs[2].default_value = (*colors["_FoamColor"][:3], 1)
        nt.links.new(threshold.outputs[0], mix.inputs[0])
        nt.links.new(mix.outputs[0], bs.inputs["Base Color"])
    m["water_translation_note"] = (
        "Native normal and foam textures in world space, frozen surface foam; dynamic depth foam and wave displacement remain approximations."
    )
doc = bpy.data.texts.get("START HERE — map expansion")
doc.clear()
doc.write((root / "README.md").read_text(encoding="utf-8"))
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(root / "Schedule_I_Main.blend"), compress=True)
