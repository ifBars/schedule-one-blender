import bpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from surface_settings import MAP_CLIP_START

for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.clip_start = MAP_CLIP_START
            shading = area.spaces.active.shading
            shading.type = "SOLID"
            shading.use_scene_world = False
            shading.use_scene_lights = False
            shading.use_scene_world_render = False
            shading.use_scene_lights_render = False
            if hasattr(shading, "use_compositor"):
                shading.use_compositor = "DISABLED"
doc = bpy.data.texts.get("START HERE — map expansion")
doc.clear()
doc.write(
    "OPTIMIZED MAP EDITOR\n\nUse Z > Material Preview or Rendered for textured editing. Both viewport modes default to studio lighting. Native scene lights/world can be enabled in the viewport shading popover at additional cost.\n\nThe reference has editable 64-metre chunks, native forest instances, and 512px packed texture copies. Visible map geometry and game coordinates are retained. Each chunk stores its source_renderer_ids.\n\nPut your new meshes in 06 · YOUR MAP EXPANSION.\n\nSchedule_I_Main_FULL_DETAIL.blend preserves the original full-resolution textures, individual objects, native hierarchy and inactive/LOD variants. Use that file for full-detail reference or final Cycles rendering. It is large and should not be opened alongside this editing file on a 32GB system.\n"
)
bpy.context.scene["viewport_lighting"] = (
    "Studio for responsive editing; native lighting remains available in viewport toggles and full-detail master"
)
doc.write(
    "\nMap viewports use a 0.5m near clip to prevent distant bridge flicker. "
    "Lower View > Clip Start temporarily for close detail work. "
    "Wet GroundWet material outliers use native dry-peer smoothness for the "
    "clear-weather approximation; source_parameters retains the original values.\n"
)
bpy.ops.wm.save_as_mainfile(
    filepath=str(root / "Schedule_I_Main_EDITOR.blend"), compress=True
)
