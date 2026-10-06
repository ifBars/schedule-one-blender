"""Create bounded editor image copies without decoding originals inside Blender."""

from pathlib import Path
import json
from editor_texture_proxy import make_proxy, source_image_path

root = Path(__file__).resolve().parent
output = root / "editor_textures"
output.mkdir(exist_ok=True)
images = json.loads((root / "memory_baseline.json").read_text(encoding="utf-8"))[
    "images"
]
scene = json.loads((root / "main_manifest.json").read_text(encoding="utf-8"))
terrain_controls = {
    str((root / scene["textures"][key]["path"]).resolve()).lower()
    for terrain in scene["terrains"]
    for key in terrain["alphas"]
}
manifest = {}
raw_before = raw_after = 0
for i, item in enumerate(images):
    source = source_image_path(item["path"], root)
    key = str(source).lower()
    if key in manifest:
        continue
    manifest[key] = make_proxy(source, output, channel_packed=key in terrain_controls)
    before = manifest[key]["source_size"]
    after = manifest[key]["editor_size"]
    raw_before += before[0] * before[1] * 4
    raw_after += after[0] * after[1] * 4
    if i % 200 == 0:
        print("TEXTURES", i, flush=True)
(root / "editor_texture_manifest.json").write_text(json.dumps(manifest, indent=2))
print(
    json.dumps(
        {
            "unique_images": len(manifest),
            "rgba8_original_mib": raw_before / 2**20,
            "rgba8_editor_mib": raw_after / 2**20,
        }
    ),
    flush=True,
)
