"""Run extraction and Blender in serial, with verifiable phase checkpoints."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .discovery import choose, find_blenders, find_games, game_data

REPO = Path(__file__).resolve().parents[1]
PHASES = ("extract", "scene", "editor")
EXTRACT = (
    "extract_main",
    "repair_extraction",
    "inspect_rendering",
    "resolve_render_bindings",
    "extract_gpu_instances",
    "enrich_materials",
    "convert_normals",
    "native_daylight",
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(path)


def preflight(args):
    if os.name != "nt":
        raise ValueError(
            "The extraction/build workflow currently supports Windows only."
        )
    data = game_data(choose(args.game, find_games(), "game"))
    blender = choose(args.blender, find_blenders(), "blender")
    if not blender.is_file():
        raise ValueError(f"Blender executable not found: {blender}")
    version_text = subprocess.check_output(
        [str(blender), "--version"], text=True, timeout=30
    )
    if not version_text.startswith("Blender 5.2."):
        raise ValueError(
            "Blender 5.2.x is required for the compositor and Eevee API used here."
        )
    managed = (
        Path(args.managed).expanduser().resolve() if args.managed else data / "Managed"
    )
    if not (managed / "Assembly-CSharp.dll").is_file():
        raise ValueError(
            "Mono schemas are required. Use an alternate/alternate-beta game copy, "
            "or pass --managed to a compatible local Mono copy's Managed folder. "
            "MelonLoader interop DLLs are not native Mono schemas."
        )
    import UnityPy

    env = UnityPy.Environment(path=str(data))
    source = env.load_file(str(data / "globalgamemanagers"))
    settings = {
        o.type.name: o.read_typetree()
        for o in source.objects.values()
        if o.type.name in ("BuildSettings", "PlayerSettings")
    }
    main = [
        i
        for i, p in enumerate(settings["BuildSettings"]["scenes"])
        if p.endswith("/Main.unity")
    ]
    if len(main) != 1 or not (data / f"level{main[0]}").is_file():
        raise ValueError(
            "A unique serialized Main scene was not found in this install."
        )
    return {
        "game": str(data),
        "managed": str(managed),
        "blender": str(blender),
        "blender_version": version_text.splitlines()[0],
        "game_version": settings["PlayerSettings"]["bundleVersion"],
        "unity_version": settings["BuildSettings"]["m_Version"],
        "scene_file": f"level{main[0]}",
    }


def fingerprint(config):
    data = Path(config["game"])
    inputs = [data / "globalgamemanagers", data / config["scene_file"]]
    inputs += (
        sorted(data.glob("*.assets"))
        + sorted(data.glob("*.resS"))
        + sorted(data.glob("*.resource"))
    )
    inputs += sorted(Path(config["managed"]).glob("*.dll"))
    return {
        str(p): {"bytes": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
        for p in inputs
    }


def tooling_fingerprint():
    paths = sorted((REPO / "pipeline").glob("*.py")) + [
        REPO / "docs/WORKSPACE.md",
        REPO / "requirements.txt",
    ]
    paths += sorted((REPO / "s1blender").glob("*.py"))
    return {str(p.relative_to(REPO)): digest(p) for p in paths}


def ensure_output(output, config):
    output = output.resolve()
    for protected in (
        REPO / "pipeline",
        REPO / "s1blender",
        Path(config["game"]).parent,
        Path(config["managed"]),
    ):
        if (
            output == protected
            or output.is_relative_to(protected)
            or protected.is_relative_to(output)
        ):
            raise ValueError(
                f"Output overlaps protected input/source directory: {protected}"
            )
    if output == REPO or REPO.is_relative_to(output):
        raise ValueError(
            "Use a separate output directory, not the repository root or its parent."
        )
    if output.is_relative_to(REPO) and not output.is_relative_to(REPO / "builds"):
        raise ValueError(
            "In-repository builds must be inside the ignored builds directory."
        )
    return output


def run_step(output, command, label):
    logs = output / "logs"
    logs.mkdir(exist_ok=True)
    print(f"\n[{label}] Log: {logs / (label + '.log')}", flush=True)
    started = time.monotonic()
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    with (logs / (label + ".log")).open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=output,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            code = process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            process.stdout.close()
    if code:
        raise RuntimeError(
            f"{label} exited with code {code}. See its log, fix the cause, then use --resume."
        )
    print(f"[{label}] completed in {time.monotonic() - started:.1f}s", flush=True)


def phase(output, config, name):
    def py(script):
        args = [sys.executable, str(output / (script + ".py"))]
        if script in ("extract_main", "repair_extraction", "inspect_rendering"):
            args.append(config["game"])
        run_step(output, args, script)

    def blend(script, source=None):
        args = [
            config["blender"],
            "--background",
            "--factory-startup",
            "--disable-autoexec",
        ]
        if source:
            args.append(str(output / source))
        args += ["--python-exit-code", "1", "--python", str(output / (script + ".py"))]
        run_step(output, args, script)

    if name == "extract":
        for script in EXTRACT:
            py(script)
        manifest = json.loads(
            (output / "main_manifest.json").read_text(encoding="utf-8")
        )
        if manifest["errors"]:
            raise RuntimeError(
                "Extraction has unresolved errors; inspect the local extraction/repair reports."
            )
        warnings = json.loads(
            (output / "native_rendering/decode_errors.json").read_text(encoding="utf-8")
        )
        if warnings:
            print(
                f"WARNING: {len(warnings)} optional native components could not be decoded. "
                "See native_rendering/decode_errors.json; required bindings were resolved.",
                flush=True,
            )
        return ["main_manifest.json"] + [
            str(p.relative_to(output))
            for folder in ("extracted", "native_rendering")
            for p in sorted((output / folder).rglob("*"))
            if p.is_file()
        ]
    if name == "scene":
        blend("build_blender")
        for script in ("refine_visuals", "finish_materials", "validate_blend"):
            blend(script, "Schedule_I_Main.blend")
        shutil.copy2(
            output / "Schedule_I_Main.blend",
            output / "Schedule_I_Main_FULL_DETAIL.blend",
        )
        return ["Schedule_I_Main_FULL_DETAIL.blend", "validation_report.json"]
    blend("profile_memory", "Schedule_I_Main_FULL_DETAIL.blend")
    py("make_editor_textures")
    blend("build_editor", "Schedule_I_Main_FULL_DETAIL.blend")
    for script in ("batch_editor_arrays", "finish_editor", "validate_editor"):
        blend(script, "Schedule_I_Main_EDITOR.blend")
    shutil.copy2(
        output / "Schedule_I_Main_EDITOR.blend", output / "Schedule_I_Main.blend"
    )
    return [
        "Schedule_I_Main_EDITOR.blend",
        "Schedule_I_Main.blend",
        "editor_validation.json",
    ]


def build(args, config):
    output = ensure_output(Path(args.output), config)
    marker = output / "build_state.json"
    identity = {
        "config": config,
        "inputs": fingerprint(config),
        "tooling": tooling_fingerprint(),
    }
    if marker.exists():
        if not args.resume:
            raise ValueError(
                "This output already contains a build. Use --resume or choose a new output directory."
            )
        state = json.loads(marker.read_text())
        if state["identity"] != identity:
            raise ValueError(
                "Inputs or tooling changed since the checkpoint. Choose a new output directory."
            )
    else:
        if output.exists() and any(output.iterdir()):
            raise ValueError(
                "Refusing to overwrite an unmanaged nonempty output directory."
            )
        output.mkdir(parents=True, exist_ok=True)
        state = {"identity": identity, "completed": {}, "status": "created"}
        atomic_json(marker, state)
    free = shutil.disk_usage(output).free / 2**30
    if free < 15 and not state["completed"]:
        raise ValueError(
            f"Only {free:.1f} GiB free at output; leave at least 15 GiB before building."
        )
    for script in (REPO / "pipeline").glob("*.py"):
        shutil.copy2(script, output / script.name)
    shutil.copy2(REPO / "docs/WORKSPACE.md", output / "README.md")
    atomic_json(output / "run_config.json", config)
    # A failed phase always restarts from its clean predecessor.
    for name in PHASES[: PHASES.index(args.through) + 1]:
        if name in state["completed"]:
            for filename, expected in state["completed"][name].items():
                if (
                    not (output / filename).is_file()
                    or digest(output / filename) != expected
                ):
                    raise ValueError(
                        f"Completed output was modified or removed: {filename}. Use a new output directory."
                    )
            print(f"[{name}] verified completed checkpoint", flush=True)
            continue
        state.update(status="running", current_phase=name)
        atomic_json(marker, state)
        try:
            outputs = phase(output, config, name)
            if fingerprint(config) != identity["inputs"]:
                raise RuntimeError(
                    "The source game or schemas changed during the build; use a new output directory."
                )
        except BaseException:
            state["status"] = "failed"
            atomic_json(marker, state)
            raise
        state["completed"][name] = {p: digest(output / p) for p in outputs}
        state["status"] = "complete"
        atomic_json(marker, state)
    print(f"\nCompleted through {args.through}: {output}", flush=True)
    if args.through == "editor":
        print(f"Open {output / 'Schedule_I_Main.blend'}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a local Blender map from your own Schedule I installation."
    )
    parser.add_argument("command", choices=("doctor", "build"))
    parser.add_argument(
        "--game",
        help="Game install or Schedule I_Data folder; otherwise detect Steam installation",
    )
    parser.add_argument(
        "--managed",
        help="Compatible local Mono Managed folder; defaults to the game data folder",
    )
    parser.add_argument(
        "--blender",
        help="Blender 5.2 executable; otherwise detect Steam/standard installation",
    )
    parser.add_argument(
        "--output",
        default=str(REPO / "builds" / datetime.now().strftime("Main-%Y%m%d-%H%M%S")),
    )
    parser.add_argument(
        "--through",
        choices=PHASES,
        default="editor",
        help="Last phase to run (default: editor)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the same output after verifying inputs and tooling",
    )
    args = parser.parse_args(argv)
    try:
        config = preflight(args)
        print(json.dumps(config, indent=2), flush=True)
        if args.command == "build":
            build(args, config)
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        ImportError,
        subprocess.SubprocessError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "Build interrupted. Use --resume with the same output to rebuild the interrupted phase.",
            file=sys.stderr,
        )
        return 130
