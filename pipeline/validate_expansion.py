"""Fresh-process validation of an authored native expansion (original reference stays untouched)."""

import argparse
import json
from pathlib import Path
import runpy
import sys
import tempfile
import bpy
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    addon = runpy.run_path(str(Path(__file__).with_name("native_expansion.py")))
    authored = [o for o in bpy.context.scene.objects if "expansion_source" in o]
    if not authored:
        raise ValueError("No authored native placements")
    bad_images = [
        i.name
        for i in bpy.data.images
        if i.source == "FILE" and (not i.packed_file or max(i.size) > 512)
    ]
    if bad_images:
        raise ValueError(f"Editor texture budget violated: {bad_images[:5]}")
    nonfinite = []
    for mesh in bpy.data.meshes:
        positions = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get("co", positions)
        if not np.isfinite(positions).all():
            nonfinite.append(mesh.name)
    if nonfinite:
        raise ValueError(f"Nonfinite mesh geometry: {nonfinite[:5]}")
    with tempfile.TemporaryDirectory() as temp:
        recipe = addon["export_recipe"](Path(temp) / "check.expansion.json")
        obj = authored[0]
        original = obj.data.vertices[0].co.copy()
        obj.data.vertices[0].co.x += 0.25
        try:
            rejected = False
            try:
                addon["export_recipe"](Path(temp) / "edited.expansion.json")
            except ValueError:
                rejected = True
            if not rejected:
                raise AssertionError("Modified geometry was silently exported")
        finally:
            obj.data.vertices[0].co = original
            obj.data.update()
        if obj.data.uv_layers:
            uv = obj.data.uv_layers[0].data[0].uv.copy()
            obj.data.uv_layers[0].data[0].uv.x += 0.25
            try:
                rejected = False
                try:
                    addon["export_recipe"](Path(temp) / "uv.expansion.json")
                except ValueError:
                    rejected = True
                if not rejected:
                    raise AssertionError("Modified UVs were silently exported")
            finally:
                obj.data.uv_layers[0].data[0].uv = uv
        addon["export_recipe"](Path(temp) / "restored.expansion.json")
        addon["register"]()
        root = next(o for o in bpy.context.scene.objects if "expansion_kit" in o)
        bpy.context.view_layer.objects.active = root
        before = set(bpy.data.objects)
        try:
            assert bpy.ops.s1.duplicate_native_kit() == {"FINISHED"}
            bpy.context.view_layer.update()
            duplicate = addon["export_recipe"](Path(temp) / "duplicate.expansion.json")
            assert len(duplicate["placements"]) == len(recipe["placements"]) + len(
                root.children
            )
        finally:
            bpy.data.batch_remove(ids=list(set(bpy.data.objects) - before))
            addon["unregister"]()
    report = {
        "passed": True,
        "placements": len(recipe["placements"]),
        "visible_placements": sum(p.get("render", True) for p in recipe["placements"]),
        "unique_meshes": len({o.data.name for o in authored}),
        "all_meshes": len(bpy.data.meshes),
        "packed_images": len([i for i in bpy.data.images if i.source == "FILE"]),
        "geometry_and_uv_edits_rejected": True,
        "linked_duplication_passed": True,
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
