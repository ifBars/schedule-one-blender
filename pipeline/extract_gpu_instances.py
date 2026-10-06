"""Recover baked tree transforms through native references rather than fixed IDs."""

from pathlib import Path
import json
import numpy as np
import UnityPy

root = Path(__file__).resolve().parent
d = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
native = json.loads(
    (root / "native_rendering/render_components.json").read_text(encoding="utf-8")
)
bindings = json.loads(
    (root / "native_rendering/render_bindings.json").read_text(encoding="utf-8")
)
instance = native[bindings["forest"]]["data"]
assets = bindings["forest_assets"]
env = UnityPy.Environment(path=d["source"])
files = {}


def reader(key):
    filename, pid = key.rsplit("_", 1)
    if filename not in files:
        files[filename] = env.load_file(str(Path(d["source"]) / filename))
    return files[filename].objects[int(pid)]


def raw(key):
    texture = reader(key).read()
    if texture.m_TextureFormat != 20:
        raise ValueError("Expected RGBAFloat instance data")
    return np.frombuffer(texture.get_image_data(), dtype="<f4").reshape(-1, 4)


pos = raw(assets["PositionData"])
rot = raw(assets["RotationData"])
valid = pos[:, 3] > 0
if len(pos) != len(rot) or int(valid.sum()) != instance["InstanceCount"]:
    raise ValueError("Baked tree texture count does not match native InstanceCount")
if not np.isfinite(pos[valid]).all() or not np.isfinite(rot[valid]).all():
    raise ValueError("Nonfinite tree transforms")
if any(instance["PositionOffset"].values()):
    raise ValueError("Nonzero LOD0 position offset needs a verified shader adapter")
if assets["Mesh"] not in d["meshes"] or assets["Material"] not in d["materials"]:
    from UnityPy.classes import PPtr
    import sys

    sys.argv = [str(root / "extract_main.py"), d["source"]]
    script = (root / "extract_main.py").read_text(encoding="utf-8")
    scope = {"__file__": str(root / "extract_main.py")}
    exec(
        compile(
            script[: script.index("# STAGE: RENDERERS")],
            str(root / "extract_main.py"),
            "exec",
        ),
        scope,
    )
    scope.update(meshes=d["meshes"], materials=d["materials"], textures=d["textures"])
    for field, converter in [("Mesh", "mesh"), ("Material", "material")]:
        obj = reader(assets[field])
        scope[converter](
            PPtr(m_FileID=0, m_PathID=obj.path_id, assetsfile=obj.assets_file)
        )
    (root / "main_manifest.json").write_text(json.dumps(d, separators=(",", ":")))
data = {
    "source": bindings["forest"],
    "mesh": assets["Mesh"],
    "material": assets["Material"],
    "positions": pos[valid].tolist(),
    "rotations": rot[valid].tolist(),
    "count": int(valid.sum()),
    "note": "Native LOD0 transforms; highest-detail mesh at every distance.",
}
(root / "native_rendering/gpu_instances.json").write_text(
    json.dumps(data, separators=(",", ":"))
)
print("GPU TREE INSTANCES", data["count"], flush=True)
