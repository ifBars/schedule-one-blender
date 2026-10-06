"""Evaluate native clear-weather gradients and day/night rotation at noon."""

from pathlib import Path
import json, colorsys
import numpy as np
import UnityPy

root = Path(__file__).resolve().parent
native = json.loads(
    (root / "native_rendering/render_components.json").read_text(encoding="utf-8")
)
bindings = json.loads(
    (root / "native_rendering/render_bindings.json").read_text(encoding="utf-8")
)
manifest = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
profile = native[bindings["clear_profile"]]["data"]
sky = profile["_skySettings"]


def gradient(d, t=0.5):
    g = d["Gradient"]
    n = g["m_NumColorKeys"]
    keys = []
    for i in range(n):
        k = g[f"key{i}"]
        keys.append((g[f"ctime{i}"] / 65535, [k["r"], k["g"], k["b"]]))
    rgb = [
        float(np.interp(t, [k[0] for k in keys], [k[1][i] for k in keys]))
        for i in range(3)
    ]
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb(
        h,
        min(1, s * d["_saturationMultiplier"]),
        min(1, v * d["_brightnessMultiplier"]),
    )


values = {
    k: gradient(v) for k, v in sky.items() if isinstance(v, dict) and "Gradient" in v
}
source = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))["source"]
e = UnityPy.load(str(Path(source) / manifest["scene_file"]))
f = next(
    f for f in e.files.values() if getattr(f, "name", "") == manifest["scene_file"]
)
pivot_id = native[bindings["controller"]]["data"]["_lightPivot"]["m_PathID"]
pivot = f.objects[pivot_id].read()
pivot_id = next(
    c.component.m_PathID
    for c in pivot.m_Component
    if c.component.deref().type.name == "Transform"
)


def world(tid):
    t = f.objects[tid].read()
    q = t.m_LocalRotation
    x, y, z, w = q.x, q.y, q.z, q.w
    m = np.eye(4)
    m[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    s = t.m_LocalScale
    p = t.m_LocalPosition
    m[:3, :3] = m[:3, :3] @ np.diag([s.x, s.y, s.z])
    m[:3, 3] = [p.x, p.y, p.z]
    return world(t.m_Father.m_PathID) @ m if t.m_Father.m_PathID else m


report = {
    "hour": 12,
    "profile": profile["m_Name"],
    "gradients": values,
    "sun_intensity": values["_sunIntensityGradient"][0] * 4,
    "pivot_world": world(pivot_id).tolist(),
    "sun_local_euler_degrees": [90, 0, 0],
    "schema_source": "User-provided Mono schemas; installed source asset values",
    "controller_evidence": "DayNightController.cs UpdateSky intensity multiplier and SetRotation; DynamicGradient.cs HSV multipliers",
}
(root / "native_rendering/noon_clear_evaluated.json").write_text(
    json.dumps(report, indent=2)
)
print("Native noon sun", report["sun_intensity"], "color", values["_sunLightGradient"])
