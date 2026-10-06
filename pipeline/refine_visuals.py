"""Apply visual corrections identified against native reference screenshots."""

import bpy, json, sys
from pathlib import Path

root = Path(__file__).resolve().parent
d = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
rs = {r["id"]: r for r in d["renderers"]}
hidden = 0
for o in bpy.data.objects:
    r = rs.get(o.get("unity_renderer_id"))
    if r and not any(r.get("materials", [])):
        o.hide_render = True
        o.hide_viewport = True
        o["visibility_note"] = (
            "No native material: Unity does not draw this navigation/outline helper."
        )
        hidden += 1
s = bpy.context.scene
nt = s.compositing_node_group
bc = next(n for n in nt.nodes if n.bl_idname == "CompositorNodeBrightContrast")
inp = bc.inputs["Image"].links[0].from_socket
dest = [l.to_socket for l in bc.outputs["Image"].links]
sep = nt.nodes.new("CompositorNodeSeparateColor")
sep.mode = "RGB"
nt.links.new(inp, sep.inputs["Image"])
comb = nt.nodes.new("CompositorNodeCombineColor")
comb.mode = "RGB"
contrast = 1 + bc.inputs["Contrast"].default_value / 100
for channel in ["Red", "Green", "Blue"]:
    prev = sep.outputs[channel]
    for op, value in [
        ("MAXIMUM", 0),
        ("DIVIDE", 0.18),
        ("POWER", contrast),
        ("MULTIPLY", 0.18),
    ]:
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        n.inputs[1].default_value = value
        nt.links.new(prev, n.inputs[0])
        prev = n.outputs[0]
    nt.links.new(prev, comb.inputs[channel])
for socket in dest:
    nt.links.new(comb.outputs["Image"], socket)
bc.mute = True
bc.label = "Native numeric contrast preserved; log-space equivalent below"
s["contrast_translation"] = (
    "Power curve about linear 18 percent grey; approximation to native log grading."
)
print("Hidden material-less native helper renderers", hidden, flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(root / "Schedule_I_Main.blend"), compress=True)
