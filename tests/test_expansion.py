"""Synthetic expansion tests: no game data or fixture assets."""

import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from s1blender.expansion import (
    Catalog,
    bridge_plan,
    matrix,
    safe_output,
    unity_matrix,
    validate_transform,
)
from scripts.audit_repo import allowed_path


class TransformTests(unittest.TestCase):
    def test_translation_and_rotation_convert_once(self):
        native = np.array(
            [[0, -2, 0, 7], [1, 0, 0, 8], [0, 0, 3, 9], [0, 0, 0, 1]], dtype=float
        )
        swap = np.eye(4)[[0, 2, 1, 3]]
        np.testing.assert_allclose(unity_matrix(swap @ native @ swap), native)

    def test_rejects_shear_mirror_singular_and_nonfinite(self):
        for transform in [
            np.diag([-1, 1, 1, 1]),
            np.diag([0, 1, 1, 1]),
            np.array([[1, 0.2, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]),
            np.full((4, 4), np.nan),
        ]:
            with self.assertRaises(ValueError):
                validate_transform(transform)

    def test_rejects_projective_matrix(self):
        value = np.eye(4)
        value[3, 0] = 0.2
        with self.assertRaises(ValueError):
            matrix(value)

    def test_generated_output_cannot_enter_source_or_reference(self):
        repo = Path(__file__).resolve().parents[1]
        for path in [
            repo,
            repo.parent,
            repo / "runtime" / "assets",
            repo / "s1blender",
        ]:
            with self.assertRaises(ValueError):
                safe_output(path)
        self.assertEqual(
            safe_output(repo / "builds" / "example"), repo / "builds" / "example"
        )
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                safe_output(Path(temp) / "child", temp)

    def test_native_source_allowlist_stays_narrow(self):
        self.assertTrue(allowed_path("runtime/NativeMesh.cs"))
        self.assertTrue(allowed_path("unity/NativeExpansionImporter.cs"))
        for path in [
            "runtime/game.dll",
            "runtime/Unknown.cs",
            "unity/Asset.asset",
            "unity/preview.json",
        ]:
            self.assertFalse(allowed_path(path))


class PreviewTests(unittest.TestCase):
    def test_triangle_indices_are_flat_and_preserve_submesh_boundaries(self):
        from s1blender.preview import generate

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "reference"
            root.mkdir()
            vertices = np.array(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float
            )
            np.savez(
                root / "mesh.npz",
                vertices=vertices,
                normals=np.tile([0, 0, 1], (4, 1)),
                tri_0=np.array([[0, 1, 2]]),
                tri_1=np.array([[2, 1, 3]]),
            )
            source = {
                "path": ["Synthetic"],
                "position": [0, 0, 0],
                "materials": ["A", "B"],
                "shaders": ["Test", "Test"],
                "submeshes": 2,
            }
            part = {
                "source": source,
                "name": "Synthetic",
                "world": np.eye(4).tolist(),
                "shadowMode": 1,
                "renderer": {"mesh": "mesh", "materials": ["a", "b"]},
            }
            material = {
                "name": "Test",
                "shader": "Test",
                "colors": {},
                "floats": {},
                "textures": {},
            }
            manifest = {
                "objects": [],
                "meshes": {"mesh": {"path": "mesh.npz", "submeshes": 2}},
                "materials": {"a": material, "b": material},
                "textures": {},
            }
            documents = {
                root / "main_manifest.json": manifest,
                Path(temp) / "kit.json": {"referenceRoot": str(root), "parts": [part]},
                Path(temp) / "plan.json": {},
                Path(temp) / "recipe.json": {"placements": [{"source": source}]},
            }
            for path, data in documents.items():
                path.write_text(json.dumps(data))
            output = generate(
                Path(temp) / "kit.json",
                Path(temp) / "plan.json",
                Path(temp) / "recipe.json",
                Path(temp) / "preview",
            )
            mesh = json.loads(output.read_text())["meshes"][0]
            self.assertEqual(
                mesh["submeshes"], [{"indices": [0, 1, 2]}, {"indices": [2, 1, 3]}]
            )
            self.assertEqual(len(mesh["positions"]), 12)


class CatalogTests(unittest.TestCase):
    def fixture(self, root):
        data = dict(
            version="synthetic",
            objects=[],
            renderers=[],
            materials={"m": {"name": "Test", "shader": "TestShader"}},
            meshes={"mesh": {"submeshes": 1}},
        )

        def obj(name, parent, z=0):
            identity = len(data["objects"]) + 1
            world = np.eye(4)
            world[2, 3] = z
            data["objects"].append(
                dict(id=identity, name=name, parent=parent, world=world.tolist())
            )
            return identity

        map_id = obj("Map", 0)
        mainland = obj("Hyland Point", map_id)
        overpass = obj("Overpass", mainland)
        island = obj("Island", map_id)

        def span(parent, name, z, complete):
            span_id = obj(name, parent, z)
            for name in ["Road", "Road (1)", "Concrete"] if complete else ["Concrete"]:
                mesh_id = obj(name, span_id, z)
                data["renderers"].append(
                    dict(
                        id=mesh_id + 100,
                        go=mesh_id,
                        mesh="mesh",
                        materials=["m"],
                        active=True,
                        enabled=True,
                        lod=0,
                    )
                )

        span(overpass, "Overpass Segment (13)", 0, True)
        span(overpass, "Overpass Segment (14)", 10, True)
        span(overpass, "Overpass Segment (15)", 20, False)
        span(island, "Overpass Segment (16)", 40, False)
        span(island, "Overpass Segment (17)", 50, True)
        (root / "main_manifest.json").write_text(json.dumps(data))
        return Catalog(root)

    def test_gap_replaces_partial_ends_and_adds_only_approach_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = self.fixture(Path(temp))
            plan = bridge_plan(catalog)
            self.assertEqual([p[2][3] for p in plan["poses"]], [20, 30, 40])
            self.assertEqual(len(plan["suppress"]), 5)
            self.assertEqual(
                sum(p["replacementVisual"] for p in plan["collisionParts"]), 3
            )
            self.assertEqual(len(plan["collisionParts"]), 9)
            self.assertEqual(plan["spacing"], 10)
            kit = catalog.kit(plan["group"])
            self.assertEqual(kit["parts"][0]["source"]["materials"], ["Test"])
            self.assertEqual(kit["parts"][0]["source"]["submeshes"], 1)

    def test_ambiguous_group_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = self.fixture(root)
            data = catalog.data
            data["objects"].append(dict(data["objects"][0], id=999))
            (root / "main_manifest.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                Catalog(root).find("Map")


if __name__ == "__main__":
    unittest.main()
