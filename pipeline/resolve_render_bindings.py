"""Resolve native references by component identity, never by one build's path IDs."""

import json
from pathlib import Path
import UnityPy
from UnityPy.classes import PPtr
from render_binding_helpers import volume_component as select_volume_component

root = Path(__file__).resolve().parent
manifest = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
native = json.loads(
    (root / "native_rendering/render_components.json").read_text(encoding="utf-8")
)
env = UnityPy.Environment(path=manifest["source"])
files = {}


def unique(description, predicate):
    matches = [key for key, value in native.items() if predicate(key, value)]
    if len(matches) != 1:
        raise RuntimeError(
            f"Unsupported rendering layout: expected one {description}, found {len(matches)}"
        )
    return matches[0]


def pointer_key(owner, pointer):
    filename = owner.rsplit("_", 1)[0]
    if filename not in files:
        files[filename] = env.load_file(str(Path(manifest["source"]) / filename))
    reader = PPtr(**pointer, assetsfile=files[filename]).deref()
    return f"{Path(reader.assets_file.name).name}_{reader.path_id}"


controller = unique(
    "active DayNightController",
    lambda k, v: (
        v["type"].endswith(".DayNightController") and v.get("active_hierarchy")
    ),
)
clear = unique(
    "ClearProfile",
    lambda k, v: (
        v["type"].endswith(".WeatherProfile")
        and v["data"].get("m_Name") == "ClearProfile"
    ),
)
volume = unique(
    "enabled global volume with full weight",
    lambda k, v: (
        v["type"] == "UnityEngine.Rendering.Volume"
        and v.get("active_hierarchy")
        and v["data"].get("m_Enabled")
        and v["data"].get("m_IsGlobal")
        and v["data"].get("weight") == 1
    ),
)
profile = pointer_key(volume, native[volume]["data"]["sharedProfile"])
components = [pointer_key(profile, p) for p in native[profile]["data"]["components"]]


def volume_component(name):
    return select_volume_component(native, components, name)


forest = unique(
    "tree LOD0 instance data",
    lambda k, v: (
        v["type"].endswith(".InstanceObjectData")
        and v["data"].get("m_Name") == "InstanceData_TreeInstance_LOD0"
    ),
)
control = native[controller]["data"]
result = {
    "controller": controller,
    "clear_profile": clear,
    "sun": pointer_key(controller, control["_sunLight"]),
    "sky_renderer": pointer_key(controller, control["_skyRenderer"]),
    "light_pivot": pointer_key(controller, control["_lightPivot"]),
    "color": volume_component("ColorAdjustments"),
    "bloom": volume_component("Bloom"),
    "forest": forest,
    "forest_assets": {
        field: pointer_key(forest, native[forest]["data"][field])
        for field in ["Mesh", "Material", "PositionData", "RotationData"]
    },
}
manager = unique(
    "active InstancingManager",
    lambda k, v: v["type"].endswith(".InstancingManager") and v.get("active_hierarchy"),
)
bound = [
    pointer_key(manager, p) for p in native[manager]["data"]["BackedInstanceObjects"]
]
if forest not in bound:
    raise RuntimeError(
        "The recovered forest is not referenced by the active instancing manager"
    )
(root / "native_rendering/render_bindings.json").write_text(
    json.dumps(result, indent=2)
)
print("Resolved daylight, global volume and forest references", flush=True)
