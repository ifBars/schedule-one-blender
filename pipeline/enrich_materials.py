from pathlib import Path
import UnityPy, json, attrs

root = Path(__file__).resolve().parent
d = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
env = UnityPy.Environment(path=d["source"])
files = {}
shaders = {}
for k, m in d["materials"].items():
    name, pid = k.rsplit("_", 1)
    if name not in files:
        files[name] = env.load_file(str(Path(d["source"]) / name))
    src = files[name].objects[int(pid)].read()
    m["keywords"] = (
        getattr(src, "m_ValidKeywords", None)
        or (getattr(src, "m_ShaderKeywords", "") or "").split()
    )
    m["render_queue"] = getattr(src, "m_CustomRenderQueue", -1)
    shader = src.m_Shader.deref()
    sk = f"{shader.assets_file.name}_{shader.path_id}"
    m["shader_id"] = sk
    if sk not in shaders:
        s = shader.read()
        form = s.m_ParsedForm
        props = []
        for p in form.m_PropInfo.m_Props:
            props.append(
                {
                    "name": p.m_Name,
                    "description": p.m_Description,
                    "type": p.m_Type,
                    "flags": p.m_Flags,
                }
            )
        shaders[sk] = {
            "name": form.m_Name,
            "properties": props,
            "fallback": form.m_FallbackName,
            "note": "Properties are native. Runtime compiled shader bodies are not Blender-compatible.",
        }
    if len(shaders) % 10 == 0:
        print("shaders", len(shaders), flush=True)
(root / "main_manifest.json").write_text(json.dumps(d, separators=(",", ":")))
(root / "native_rendering/shader_metadata.json").write_text(
    json.dumps(shaders, indent=2)
)
print("DONE", len(shaders), flush=True)
