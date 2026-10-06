from pathlib import Path
from collections import Counter
from functools import lru_cache
import numpy as np
import UnityPy, json, sys, re
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

OUT = Path(__file__).resolve().parent / "native_rendering"
OUT.mkdir(exist_ok=True)
SOURCE = Path(sys.argv[1])
env = UnityPy.Environment(path=str(SOURCE))
manifest = json.loads((OUT.parent / "main_manifest.json").read_text(encoding="utf-8"))
config = json.loads((OUT.parent / "run_config.json").read_text(encoding="utf-8"))
scene_file = manifest["scene_file"]
generator = TypeTreeGenerator(manifest["unity_version"])
print(
    "Loading local Mono schemas; reading installed asset values with strict byte-count validation",
    flush=True,
)
generator.load_local_dll_folder(config["managed"])
env.typetree_generator = generator
print("Type information ready", flush=True)
g = env.load_file(str(SOURCE / "globalgamemanagers"))
dump = {}
for o in g.objects.values():
    if o.type.name in [
        "GraphicsSettings",
        "QualitySettings",
        "PlayerSettings",
        "BuildSettings",
    ]:
        dump[o.type.name] = o.read_typetree()
(OUT / "project_settings.json").write_text(json.dumps(dump, indent=2))
script_cache = {}
selected = {}
counts = Counter()
decode_errors = []


def script_name(p):
    if not p or not p.m_PathID:
        return ""
    r = p.deref()
    k = (r.assets_file.name, r.path_id)
    if k not in script_cache:
        s = r.read()
        script_cache[k] = f"{s.m_Namespace}.{s.m_ClassName}"
    return script_cache[k]


def visit_file(f):
    for o in list(f.objects.values()):
        kind = o.type.name
        if kind == "MonoBehaviour":
            try:
                d = o.parse_monobehaviour_head()
                name = script_name(d.m_Script)
                counts[name] += 1
                if not any(
                    x in name.lower()
                    for x in [
                        "instancing",
                        "renderpipeline",
                        "rendererdata",
                        "rendererfeature",
                        "volume",
                        "bloom",
                        "coloradjust",
                        "tonemapping",
                        "vignette",
                        "ambientocclusion",
                        "fog",
                        "godray",
                        "environmentmanager",
                        "environmentsettings",
                        "daynight",
                        "weatherprofile",
                        "timemanager",
                        "skybox",
                        "sunlight",
                        "depthoffield",
                        "screenSpace".lower(),
                        "colorlookup",
                        "whitebalance",
                    ]
                ):
                    continue
            except Exception:
                continue
        elif kind in ["RenderSettings", "LightmapSettings", "Light", "Camera"]:
            name = kind
        else:
            continue
        try:
            tree = o.read_typetree()
            if kind == "MonoBehaviour":
                head = o.parse_monobehaviour_head()
                tree["m_Script"] = {
                    "m_FileID": head.m_Script.m_FileID,
                    "m_PathID": head.m_Script.m_PathID,
                }
            selected[f"{Path(f.name).name}_{o.path_id}"] = {"type": name, "data": tree}
        except Exception as ex:
            decode_errors.append(
                {
                    "asset": f"{Path(f.name).name}_{o.path_id}",
                    "type": name,
                    "error": str(ex),
                }
            )
            print("ERROR", kind, o.path_id, str(ex), flush=True)
    print("SCANNED", f.name, "selected", len(selected), flush=True)


for filename in [
    "globalgamemanagers.assets",
    "resources.assets",
    *[p.name for p in sorted(SOURCE.glob("sharedassets*.assets"))],
    scene_file,
]:
    if (SOURCE / filename).exists():
        visit_file(env.load_file(str(SOURCE / filename)))
(OUT / "render_components.json").write_text(json.dumps(selected, indent=2, default=str))
(OUT / "script_counts.json").write_text(json.dumps(counts.most_common(), indent=2))
(OUT / "decode_errors.json").write_text(json.dumps(decode_errors, indent=2))
sf = next(f for f in env.files.values() if getattr(f, "name", "") == scene_file)
transforms = {}
names = {}
for o in sf.objects.values():
    if o.type.name in ["Transform", "RectTransform"]:
        t = o.read()
        transforms[o.path_id] = t
    elif o.type.name == "GameObject":
        d = o.read()
        names[o.path_id] = (d.m_Name, bool(d.m_IsActive))
bygo = {t.m_GameObject.m_PathID: i for i, t in transforms.items()}


@lru_cache(None)
def wm(i):
    if not i:
        return np.eye(4)
    t = transforms[i]
    q = t.m_LocalRotation
    x, y, z, w = q.x, q.y, q.z, q.w
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    s = t.m_LocalScale
    p = t.m_LocalPosition
    m = np.eye(4)
    m[:3, :3] = r @ np.diag([s.x, s.y, s.z])
    m[:3, 3] = [p.x, p.y, p.z]
    return wm(t.m_Father.m_PathID) @ m


@lru_cache(None)
def act(i):
    if not i:
        return True
    t = transforms[i]
    return names[t.m_GameObject.m_PathID][1] and act(t.m_Father.m_PathID)


for k, v in selected.items():
    if k.startswith(scene_file + "_"):
        go = v["data"].get("m_GameObject", {}).get("m_PathID")
        if go in bygo:
            v["world"] = wm(bygo[go]).tolist()
            v["name"] = names[go][0]
            v["active_hierarchy"] = act(bygo[go])
(OUT / "render_components.json").write_text(json.dumps(selected, indent=2, default=str))
print("DONE", len(selected), flush=True)
