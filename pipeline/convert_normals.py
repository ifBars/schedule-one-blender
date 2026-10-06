from pathlib import Path
import json, numpy as np
from PIL import Image

root = Path(__file__).resolve().parent
d = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
ids = {
    t["id"]
    for m in d["materials"].values()
    for k, t in m["textures"].items()
    if "normal" in k.lower() or k == "_BumpMap"
}
out = root / "extracted/normals"
out.mkdir(exist_ok=True)
converted = 0
for k in ids:
    t = d["textures"][k]
    if t.get("format") not in [12, 25] or not t.get("path"):
        continue
    im = (
        np.asarray(Image.open(root / t["path"]).convert("RGBA"), dtype=np.float32) / 255
    )
    # Unity UnpackNormalmapRGorAG: X lives in alpha for DXT5nm, or red for BC5.
    x = (im[:, :, 0] * im[:, :, 3]) * 2 - 1
    y = im[:, :, 1] * 2 - 1
    z = np.sqrt(np.maximum(0, 1 - x * x - y * y))
    rgb = np.stack((x, y, z), axis=2) * 0.5 + 0.5
    path = out / f"{k}.png"
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(path)
    t["normal_path"] = str(path.relative_to(root))
    converted += 1
    if converted % 100 == 0:
        print("normal maps", converted, flush=True)
(root / "main_manifest.json").write_text(json.dumps(d, separators=(",", ":")))
print("DONE", converted, flush=True)
