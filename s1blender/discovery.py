"""Bounded Steam library and Blender discovery; no full-disk search."""

import os
from pathlib import Path
import re
import shutil


def steam_roots():
    roots = []
    if os.name == "nt":
        import winreg

        for hive, key, value in [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Valve\Steam",
                "InstallPath",
            ),
        ]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
    roots.append(
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam"
    )
    libraries = list(roots)
    for root in roots:
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            libraries.extend(
                Path(p.replace("\\\\", "\\"))
                for p in re.findall(
                    r'"path"\s+"([^"\n]+)"', vdf.read_text(encoding="utf-8")
                )
            )
    return list(dict.fromkeys(p.resolve() for p in libraries if p.is_dir()))


def game_data(path):
    path = Path(path).expanduser().resolve()
    data = path / "Schedule I_Data" if (path / "Schedule I_Data").is_dir() else path
    if not (data / "globalgamemanagers").is_file():
        raise ValueError(f"Not a game data folder: {data}")
    return data


def find_games():
    candidates = [
        p / "steamapps/common/Schedule I/Schedule I_Data" for p in steam_roots()
    ]
    return [p for p in candidates if (p / "globalgamemanagers").is_file()]


def find_blenders():
    candidates = []
    command = shutil.which("blender")
    if command:
        candidates.append(Path(command))
    candidates += [p / "steamapps/common/Blender/blender.exe" for p in steam_roots()]
    program_files = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    candidates += sorted(
        (program_files / "Blender Foundation").glob("Blender */blender.exe"),
        reverse=True,
    )
    return list(dict.fromkeys(p.resolve() for p in candidates if p.is_file()))


def choose(explicit, candidates, label):
    if explicit:
        return Path(explicit).expanduser().resolve()
    if len(candidates) != 1:
        listing = ", ".join(str(p) for p in candidates) or "none"
        raise ValueError(f"Specify --{label}; discovered candidates: {listing}")
    return candidates[0]
