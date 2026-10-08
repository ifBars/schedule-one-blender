"""Prepare local native kits and reference-only expansion recipes."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np


def matrix(value):
    result = np.asarray(value, dtype=float).reshape(4, 4)
    if not np.isfinite(result).all() or not np.allclose(result[3], [0, 0, 0, 1]):
        raise ValueError("Expected a finite affine matrix")
    return result


def validate_transform(value):
    result = matrix(value)
    scale = np.linalg.norm(result[:3, :3], axis=0)
    if np.any(scale < 0.001) or np.any(scale > 100):
        raise ValueError("Scale must be positive and between 0.001 and 100")
    rotation = result[:3, :3] / scale
    if np.linalg.det(rotation) < 0 or not np.allclose(
        rotation.T @ rotation, np.eye(3), atol=1e-5
    ):
        raise ValueError("Mirrored or sheared native instances are not supported")
    return result


def unity_matrix(blender_matrix):
    swap = np.eye(4)[[0, 2, 1, 3]]
    return validate_transform(swap @ matrix(blender_matrix) @ swap)


class Catalog:
    def __init__(self, reference):
        self.root = Path(reference).resolve()
        self.data = json.loads(
            (self.root / "main_manifest.json").read_text(encoding="utf8")
        )
        self.objects = {o["id"]: o for o in self.data["objects"]}
        self.children = defaultdict(list)
        for obj in self.objects.values():
            self.children[obj["parent"]].append(obj["id"])
        self.renderers = self.data["renderers"]

    def path(self, object_id):
        names = []
        while object_id:
            obj = self.objects[object_id]
            names.append(obj["name"])
            object_id = obj["parent"]
        return names[::-1]

    def find(self, path):
        names = path.split("/")
        matches = [
            o
            for o in self.objects.values()
            if o["name"] == names[-1] and self.path(o["id"]) == names
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one source group {path!r}; found {len(matches)}"
            )
        return matches[0]

    def descendants(self, object_id):
        result = {object_id}
        pending = [object_id]
        while pending:
            children = self.children[pending.pop()]
            result.update(children)
            pending.extend(children)
        return result

    def reference(self, object_id):
        obj = self.objects[object_id]
        return {
            "path": self.path(object_id),
            "position": np.asarray(obj["world"])[:3, 3].tolist(),
        }

    def visible(self, object_id):
        ids = self.descendants(object_id)
        return [
            r
            for r in self.renderers
            if r["go"] in ids
            and r.get("active")
            and r.get("enabled")
            and r.get("lod", 0) == 0
            and not r.get("empty")
        ]

    def kit(self, group):
        root = self.find(group)
        renderers = self.visible(root["id"])
        if not renderers:
            raise ValueError("Source group has no visible LOD0 meshes")
        parts = []
        for renderer in renderers:
            if renderer.get("kind", "MeshRenderer") != "MeshRenderer":
                raise ValueError(
                    "Native kits currently require MeshRenderer sources; choose a static group"
                )
            obj = self.objects[renderer["go"]]
            if obj["name"] == "Graffiti":
                continue
            source = self.reference(obj["id"])
            source["materials"] = [
                self.data["materials"][m]["name"] for m in renderer["materials"]
            ]
            source["shaders"] = [
                self.data["materials"][m]["shader"] for m in renderer["materials"]
            ]
            source["submeshes"] = (
                renderer.get("batch_count")
                or self.data["meshes"][renderer["mesh"]]["submeshes"]
            )
            identity = hashlib.sha256(
                json.dumps(source, sort_keys=True).encode()
            ).hexdigest()[:20]
            parts.append(
                {
                    "id": identity,
                    "name": obj["name"],
                    "source": source,
                    "world": obj["world"],
                    "renderer": renderer,
                    "shadowMode": renderer.get(
                        "shadow_mode",
                        3
                        if any(
                            name in {"ShadowCaster", "ShadowCasters"}
                            for name in source["path"]
                        )
                        else 1,
                    ),
                    "receiveShadows": renderer.get("receive_shadows", True),
                }
            )
        return {
            "schemaVersion": 1,
            "gameVersion": self.data["version"],
            "referenceRoot": str(self.root),
            "name": root["name"],
            "anchor": root["world"],
            "parts": parts,
        }


def bridge_plan(catalog):
    mainland = catalog.find("Map/Hyland Point/Overpass")
    island = catalog.find("Map/Island")

    def spans(parent):
        return sorted(
            [
                catalog.objects[i]
                for i in catalog.children[parent["id"]]
                if catalog.objects[i]["name"].startswith("Overpass Segment")
            ],
            key=lambda o: o["world"][2][3],
        )

    def complete(obj):
        names = {catalog.objects[r["go"]]["name"] for r in catalog.visible(obj["id"])}
        return {"Road", "Road (1)", "Concrete"} <= names

    source_spans = spans(mainland)
    destination = next(o for o in spans(island) if complete(o))
    complete_spans = [o for o in source_spans if complete(o)]
    endpoint = complete_spans[-1]
    spacing = float(np.median(np.diff([o["world"][2][3] for o in complete_spans[-6:]])))
    start = np.asarray(endpoint["world"])[:3, 3]
    finish = np.asarray(destination["world"])[:3, 3]
    if spacing <= 0 or not np.allclose(start[:2], finish[:2], atol=0.01):
        raise ValueError("Bridge endpoints are not collinear at matching heights")
    steps = (finish[2] - start[2]) / spacing
    if not np.isclose(steps, round(steps), atol=0.001) or steps < 2 or steps > 100:
        raise ValueError("Unsupported bridge gap or irregular native spacing")
    # A complete span with both support meshes keeps the example structurally native.
    template = catalog.find("Map/Hyland Point/Overpass/Overpass Segment (13)")
    if not complete(template):
        raise ValueError("The expected complete native bridge template changed")
    poses = []
    for i in range(1, round(steps)):
        pose = matrix(template["world"]).copy()
        pose[:3, 3] = start + [0, 0, i * spacing]
        poses.append(pose.tolist())
    suppress = [
        catalog.reference(o["id"])
        for o in source_spans + spans(island)
        if start[2] < o["world"][2][3] < finish[2] and not complete(o)
    ]
    collision_parts = [
        part
        for obj in complete_spans + [o for o in spans(island) if complete(o)]
        for part in catalog.kit("/".join(catalog.path(obj["id"])))["parts"]
        if part["name"] in {"Road", "Road (1)", "Concrete"}
    ]
    # Native streamed deck boxes extend above the visible surface. Replace those
    # objects with identical visuals and accurate mesh collision instead of fighting
    # the game's distance-based collider enable/disable logic every frame.
    for part in collision_parts:
        part["replacementVisual"] = part["name"] == "Concrete"
        if part["replacementVisual"]:
            suppress.append(part["source"])
    return {
        "name": "North island bridge",
        "group": "/".join(catalog.path(template["id"])),
        "poses": poses,
        "suppress": suppress,
        "spacing": spacing,
        "collisionParts": collision_parts,
        "from": start.tolist(),
        "to": finish.tolist(),
    }


def safe_output(value, reference=None):
    output = Path(value).expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if (
        output == repo
        or repo.is_relative_to(output)
        or (output.is_relative_to(repo) and not output.is_relative_to(repo / "builds"))
    ):
        raise ValueError(
            "In-repository generated output must be inside ignored builds/"
        )
    if reference:
        reference = Path(reference).resolve()
        if (
            output == reference
            or reference.is_relative_to(output)
            or output.is_relative_to(reference)
        ):
            raise ValueError(
                "Use a separate expansion folder, outside the reference extraction"
            )
    return output


def prepare(args):
    catalog = Catalog(args.reference)
    output = safe_output(args.output, catalog.root)
    if bool(args.scene) != bool(args.blender):
        raise ValueError(
            "Provide --scene and --blender together, or omit both for kit preparation only"
        )
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Choose an empty output folder; existing authored work is preserved"
        )
    plan = (
        bridge_plan(catalog)
        if args.bridge
        else {"name": "Native kit", "group": args.group, "poses": [], "suppress": []}
    )
    kit = catalog.kit(plan["group"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "native-kit.json").write_text(json.dumps(kit, indent=2), encoding="utf8")
    (output / "layout-plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf8"
    )
    print(
        f"Prepared {len(kit['parts'])} native parts and {len(plan['poses'])} instances in {output}",
        flush=True,
    )
    if args.scene:
        import subprocess
        from .preview import generate

        scene = Path(args.scene).resolve()
        if not scene.is_file():
            raise ValueError(f"Reference scene missing: {scene}")
        subprocess.run(
            [
                str(Path(args.blender).resolve()),
                "--background",
                str(scene),
                "--python-exit-code",
                "1",
                "--python",
                str(
                    Path(__file__).resolve().parents[1] / "pipeline/native_expansion.py"
                ),
                "--",
                "--kit",
                str(output / "native-kit.json"),
                "--plan",
                str(output / "layout-plan.json"),
                "--output",
                str(output / "Expansion.blend"),
                "--recipe",
                str(output / "map.expansion.json"),
            ],
            check=True,
        )
        generate(
            output / "native-kit.json",
            output / "layout-plan.json",
            output / "map.expansion.json",
            output / "UnityPreview",
        )
        print(
            f"Open {output / 'Expansion.blend'}. Install pipeline/native_expansion.py as a Blender add-on."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference", required=True, help="Local generated reference directory"
    )
    parser.add_argument("--output", required=True, help="New local workspace directory")
    parser.add_argument(
        "--scene", help="Optimized reference .blend; also requires --blender"
    )
    parser.add_argument(
        "--blender", help="Blender executable for automatic construction"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--bridge", action="store_true", help="Prepare the north-island bridge example"
    )
    group.add_argument("--group", help="Exact native hierarchy path for a reusable kit")
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
