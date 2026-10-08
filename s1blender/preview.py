"""Write a local-only Unity preview package from the user's extraction and placements."""

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image


def identity(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:20]


def generate(kit_path, plan_path, recipe_path, output):
    kit = json.loads(Path(kit_path).read_text(encoding="utf8"))
    plan = json.loads(Path(plan_path).read_text(encoding="utf8"))
    recipe = json.loads(Path(recipe_path).read_text(encoding="utf8"))
    root = Path(kit["referenceRoot"])
    manifest = json.loads((root / "main_manifest.json").read_text(encoding="utf8"))
    objects = {o["id"]: o for o in manifest["objects"]}
    from .expansion import safe_output

    output = safe_output(output, root)
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Choose an empty preview directory; generated previews are never overwritten"
        )
    parts = {
        identity(p["source"]): p for p in kit["parts"] + plan.get("collisionParts", [])
    }
    needed = {identity(p["source"]) for p in recipe["placements"]}
    if not needed <= parts.keys():
        raise ValueError("Recipe contains sources outside this kit/plan")
    meshes = []
    material_ids = set()
    for key in sorted(needed):
        part = parts[key]
        renderer = part["renderer"]
        info = manifest["meshes"][renderer["mesh"]]
        with np.load(root / info["path"]) as arrays:
            count = renderer.get("batch_count", 0)
            first = renderer.get("batch_first", 0) if count else 0
            submeshes = [
                arrays[f"tri_{i}"]
                for i in range(first, first + (count or info["submeshes"]))
            ]
            used, compact = np.unique(np.concatenate(submeshes), return_inverse=True)
            compact = compact.ravel()
            correction = np.eye(4)
            if count:
                batch_root = (
                    np.asarray(objects[renderer["batch_root"]]["world"])
                    if renderer.get("batch_root")
                    else np.eye(4)
                )
                correction = np.linalg.inv(part["world"]) @ batch_root
            vertices = (
                arrays["vertices"][used, :3] @ correction[:3, :3].T + correction[:3, 3]
            )
            normals = (
                arrays["normals"][used, :3] @ np.linalg.inv(correction[:3, :3])
                if "normals" in arrays
                else np.zeros_like(vertices)
            )
            normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-12)
            subs, offset = [], 0
            for submesh in submeshes:
                length = submesh.size
                subs.append({"indices": compact[offset : offset + length].tolist()})
                offset += length
            meshes.append(
                {
                    "id": key,
                    "name": part["name"],
                    "positions": vertices.ravel().tolist(),
                    "normals": normals.ravel().tolist(),
                    "uv": arrays["uv0"][used, :2].ravel().tolist()
                    if "uv0" in arrays
                    else [],
                    "submeshes": subs,
                    "materials": renderer["materials"],
                    "shadowMode": part["shadowMode"],
                }
            )
            material_ids.update(renderer["materials"])
    output.mkdir(parents=True, exist_ok=True)
    materials = []
    for key in sorted(material_ids):
        source = manifest["materials"][key]
        worldspace = "Worldspace" in source["shader"]
        texture = next(
            (
                source["textures"][name]
                for name in ("_DiffuseTexture", "_BaseMap", "_MainTex")
                if source["textures"].get(name, {}).get("id")
            ),
            None,
        )
        texture_file = None
        if texture:
            image = manifest["textures"].get(texture["id"], {})
            if image.get("path"):
                texture_file = texture["id"] + ".png"
                with Image.open(root / image["path"]) as pixels:
                    pixels.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    pixels.save(output / texture_file)
        materials.append(
            {
                "id": key,
                "name": source["name"],
                "nativeShader": source["shader"],
                "color": source["colors"].get(
                    "_Color" if worldspace else "_BaseColor", [1, 1, 1, 1]
                ),
                "smoothness": source["floats"].get("_Smoothness", 0.2),
                "metallic": source["floats"].get("_Metallic", 0),
                "texture": texture_file,
                "scale": texture.get("scale", [1, 1]) if texture else [1, 1],
                "offset": texture.get("offset", [0, 0]) if texture else [0, 0],
            }
        )
    for placement in recipe["placements"]:
        placement["mesh"] = identity(placement["source"])
    target = output / "preview.local.json"
    target.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "recipe": recipe,
                "meshes": meshes,
                "materials": materials,
            }
        ),
        encoding="utf8",
    )
    print(f"Local Unity preview: {target} ({len(meshes)} meshes; do not distribute)")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("kit", "plan", "recipe", "output"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    generate(args.kit, args.plan, args.recipe, args.output)


if __name__ == "__main__":
    main()
