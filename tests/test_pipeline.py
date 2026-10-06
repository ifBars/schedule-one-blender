"""Synthetic fixtures only: no game data is required or permitted."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from s1blender import cli
from s1blender.discovery import choose, game_data

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proxy = load("proxy", ROOT / "pipeline/editor_texture_proxy.py")
audit = load("audit", ROOT / "scripts/audit_repo.py")
bindings = load("bindings", ROOT / "pipeline/render_binding_helpers.py")


class BindingTests(unittest.TestCase):
    def test_untranslated_volume_components_are_skipped(self):
        native = {"color": {"type": "Synthetic.ColorAdjustments"}}
        self.assertEqual(
            bindings.volume_component(native, ["unused", "color"], "ColorAdjustments"),
            "color",
        )

    def test_missing_or_ambiguous_required_component_fails(self):
        with self.assertRaises(RuntimeError):
            bindings.volume_component({}, ["unused"], "Bloom")
        with self.assertRaises(RuntimeError):
            bindings.volume_component(
                {"a": {"type": "Synthetic.Bloom"}, "b": {"type": "Synthetic.Bloom"}},
                ["a", "b"],
                "Bloom",
            )


class ProxyTests(unittest.TestCase):
    def test_zero_alpha_preserves_grass_and_fourth_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixels = np.zeros((1024, 1024, 4), dtype=np.uint8)
            pixels[:, :512, 0] = 255
            pixels[:, 512:, 3] = 255
            source = root / "synthetic.png"
            Image.fromarray(pixels).save(source)
            result = proxy.make_proxy(source, root, channel_packed=True)
            actual = np.asarray(Image.open(result["path"]))
            self.assertEqual(actual.shape, (512, 512, 4))
            np.testing.assert_array_equal(actual[0, 0], [255, 0, 0, 0])
            np.testing.assert_array_equal(actual[-1, -1], [0, 0, 0, 255])
            self.assertTrue(np.all(actual.sum(2) == 255))
            ordinary = proxy.make_proxy(source, root, channel_packed=False)
            self.assertNotEqual(result["path"], ordinary["path"])

    def test_does_not_upscale_small_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "small.png"
            Image.new("RGBA", (8, 4), (10, 20, 30, 195)).save(source)
            result = proxy.make_proxy(source, root, True)
            self.assertEqual(tuple(result["editor_size"]), (8, 4))
            self.assertEqual(
                Image.open(result["path"]).getpixel((0, 0)), (10, 20, 30, 195)
            )


class InputTests(unittest.TestCase):
    def test_ambiguous_install_requires_selection(self):
        with self.assertRaisesRegex(ValueError, "Specify --game"):
            choose(None, [Path("one"), Path("two")], "game")

    def test_accepts_install_or_data_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "Schedule I_Data"
            data.mkdir()
            (data / "globalgamemanagers").write_text("invented test marker")
            self.assertEqual(game_data(root), game_data(data))

    def test_output_cannot_overlap_game_or_repository(self):
        config = {
            "game": str(ROOT / "test-game/Schedule I_Data"),
            "managed": str(ROOT / "test-mono/Managed"),
        }
        for path in [
            ROOT,
            ROOT / "pipeline",
            ROOT / "docs",
            Path(config["game"]) / "output",
            ROOT.parent,
        ]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                cli.ensure_output(path, config)
        self.assertEqual(
            cli.ensure_output(ROOT / "builds/test", config), ROOT / "builds/test"
        )

    def test_failing_helper_is_not_reported_as_success(self):
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "code 7"):
                cli.run_step(
                    Path(tmp),
                    [sys.executable, "-c", "raise SystemExit(7)"],
                    "synthetic-failure",
                )

    def test_resume_does_not_overwrite_modified_output(self):
        import argparse
        import json

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            config = {
                "game": str(ROOT / "test-game/Schedule I_Data"),
                "managed": str(ROOT / "test-mono/Managed"),
            }
            product = output / "synthetic.txt"
            product.write_text("original")
            identity = {"config": config, "inputs": {}, "tooling": {}}
            state = {
                "identity": identity,
                "completed": {"extract": {"synthetic.txt": cli.digest(product)}},
            }
            (output / "build_state.json").write_text(json.dumps(state))
            product.write_text("user change")
            args = argparse.Namespace(
                output=str(output), resume=True, through="extract"
            )
            with (
                patch.object(cli, "fingerprint", return_value={}),
                patch.object(cli, "tooling_fingerprint", return_value={}),
            ):
                with patch.object(
                    cli.shutil,
                    "disk_usage",
                    return_value=type("Disk", (), {"free": 100 * 2**30})(),
                ):
                    with self.assertRaisesRegex(ValueError, "modified or removed"):
                        cli.build(args, config)
            self.assertEqual(product.read_text(), "user change")


class RepositoryAuditTests(unittest.TestCase):
    def test_deleted_asset_is_still_rejected_in_history(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                )

            git("init", "-b", "main")
            git("config", "user.name", "Synthetic Test")
            git("config", "user.email", "synthetic@example.invalid")
            (root / "forbidden.blend").write_bytes(
                b"invented fixture, not Blender or game data"
            )
            git("add", "forbidden.blend")
            git("-c", "commit.gpgsign=false", "commit", "-m", "synthetic initial")
            git("rm", "forbidden.blend")
            git("-c", "commit.gpgsign=false", "commit", "-m", "synthetic removal")
            self.assertTrue(
                any("forbidden.blend" in error for error in audit.audit_history(root))
            )

    def test_reusable_stage_boundaries_survive_formatting(self):
        extractor = (ROOT / "pipeline/extract_main.py").read_text(encoding="utf-8")
        compile(extractor.split("# STAGE: RENDERERS")[0], "extract_helpers", "exec")
        builder = (ROOT / "pipeline/build_blender.py").read_text(encoding="utf-8")
        for start, end in [("MATERIALS", "GEOMETRY"), ("GEOMETRY", "OBJECTS")]:
            block = builder.split("# STAGE: " + start)[1].split("# STAGE: " + end)[0]
            compile(block, "blender_helpers", "exec")

    def test_rejects_game_outputs_and_disguised_binaries(self):
        for name in [
            "scene.blend",
            "pipeline/game.dll",
            "docs/map.png",
            "builds/map.py",
            "pipeline/data.json",
        ]:
            with self.subTest(name=name):
                self.assertTrue(audit.inspect_blob(name, b"anything"))
        self.assertTrue(audit.inspect_blob("pipeline/asset.py", b"\x00asset"))
        self.assertTrue(audit.inspect_blob("pipeline/link.py", b"target", "120000"))

    def test_accepts_source_and_documentation(self):
        self.assertEqual(
            audit.inspect_blob("pipeline/example.py", b'print("synthetic")\n'), []
        )
        self.assertEqual(audit.inspect_blob("docs/BUILD.md", b"# Instructions\n"), [])


if __name__ == "__main__":
    unittest.main()
