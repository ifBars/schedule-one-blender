"""Audit the Git index before publication. Never reads ignored build outputs."""

from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "requirements.txt",
    "build.ps1",
    "map.py",
    ".gitignore",
    ".gitattributes",
}
SOURCE_DIRS = {"s1blender", "pipeline", "tests", "scripts"}


def allowed_path(name):
    path = PurePosixPath(name)
    if name in ROOT_FILES:
        return True
    if len(path.parts) == 2 and path.parts[0] in SOURCE_DIRS and path.suffix == ".py":
        return True
    if len(path.parts) == 2 and path.parts[0] == "docs" and path.suffix == ".md":
        return True
    return path.parent == PurePosixPath(".github/workflows") and path.suffix == ".yml"


def inspect_blob(name, content, mode="100644"):
    errors = []
    if not allowed_path(name):
        errors.append("not in the source/documentation allowlist")
    if mode not in {"100644", "100755"}:
        errors.append("links and submodules are not allowed")
    if len(content) > 512 * 1024:
        errors.append("unexpectedly large source file")
    try:
        text = content.decode("utf-8")
        if "\0" in text:
            errors.append("binary content")
        # The allowlist is defense in depth; review still checks for embedded asset data.
        if any(len(line) > 12000 for line in text.splitlines()):
            errors.append("oversized line; inspect for embedded data")
    except UnicodeDecodeError:
        errors.append("non-text content")
    return errors


def check_object(name, object_id, mode, root):
    if not allowed_path(name) or mode not in {"100644", "100755"}:
        return inspect_blob(name, b"", mode)
    size = int(subprocess.check_output(["git", "cat-file", "-s", object_id], cwd=root))
    if size > 512 * 1024:
        return ["unexpectedly large source file"]
    content = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=root)
    return inspect_blob(name, content, mode)


def audit_history(root):
    failures = []
    seen = set()
    revisions = subprocess.check_output(
        ["git", "rev-list", "--all"], cwd=root, text=True
    ).splitlines()
    for revision in revisions:
        tree = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", revision], cwd=root
        )
        for record in tree.split(b"\0"):
            if not record:
                continue
            metadata, name = record.decode("utf-8").split("\t", 1)
            mode, kind, object_id = metadata.split()
            identity = (name, mode, object_id)
            if identity in seen:
                continue
            seen.add(identity)
            errors = check_object(name, object_id, mode, root)
            if errors:
                failures.append(f"{revision[:8]}:{name}: {', '.join(errors)}")
    return failures


def main():
    listing = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT)
    failures = []
    count = 0
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, name = record.decode("utf-8").split("\t", 1)
        mode, object_id, stage = metadata.split()
        errors = check_object(name, object_id, mode, ROOT)
        if stage != "0":
            errors.append("unresolved index stage")
        if errors:
            failures.append(f"{name}: {', '.join(errors)}")
        count += 1
    if not count:
        failures.append(
            "No staged/tracked files found; stage the intended source before auditing."
        )
    failures.extend(audit_history(ROOT))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        f"PASS: {count} tracked source/documentation files; reachable Git history also contains no rejected assets."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
