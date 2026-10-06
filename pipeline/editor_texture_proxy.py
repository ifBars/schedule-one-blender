"""Resize color images normally and preserve independent terrain weight channels."""

import hashlib
from pathlib import Path
from PIL import Image


def source_image_path(path, root):
    # Blender uses // for paths relative to the .blend. On Windows, pathlib
    # otherwise interprets that prefix as an absolute UNC network path.
    if path.startswith("//"):
        return (root / path[2:]).resolve()
    source = Path(path)
    return (source if source.is_absolute() else root / source).resolve()


def make_proxy(source, output, channel_packed=False):
    stat = source.stat()
    revision = f"{str(source).lower()}:{stat.st_size}:{stat.st_mtime_ns}:512"
    if channel_packed:
        revision += ":independent-channels-v1"
    dest = output / (hashlib.sha256(revision.encode()).hexdigest()[:16] + ".png")
    with Image.open(source) as original:
        if channel_packed and original.mode != "RGBA":
            raise ValueError(
                "Terrain controls must have four independent RGBA channels"
            )
        before = original.size
        after = tuple(max(1, round(v * min(1, 512 / max(before)))) for v in before)
        if not dest.exists():
            if channel_packed:
                # RGBA resizing premultiplies alpha. Here alpha is a fourth
                # material weight, so that would erase the other three layers.
                channels = [
                    c.resize(after, Image.Resampling.BOX) for c in original.split()
                ]
                resized = Image.merge(original.mode, channels)
            else:
                resized = original.copy()
                resized.thumbnail((512, 512), Image.Resampling.LANCZOS)
                after = resized.size
            resized.save(dest)
        else:
            with Image.open(dest) as cached:
                after = cached.size
    return {
        "path": str(dest),
        "source_size": before,
        "editor_size": after,
        "channel_packed": channel_packed,
    }
