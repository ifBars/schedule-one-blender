"""Clear-weather surface approximations; original source values stay untouched."""

import math
from statistics import median


MAP_CLIP_START = 0.5


def clear_weather_smoothness(materials):
    """Match wet GroundWet outliers to dry peers from this installed game.

    Serialized wetness is not a runtime weather snapshot. The generated scene
    uses clear noon, so use the median dry peer rather than a saved wet extreme.
    This is a Blender approximation, not execution of the game's shader graph.
    Without a dry reference, preserve the source rather than invent a value.
    """
    ground = {
        key: material.get("floats", {})
        for key, material in materials.items()
        if material.get("shader") == "Shader Graphs/GroundWet"
    }
    dry = [
        values["_Smoothness"]
        for values in ground.values()
        if values.get("_RainValue") == 0
        and "_Smoothness" in values
        and math.isfinite(values["_Smoothness"])
        and 0 <= values["_Smoothness"] <= 1
    ]
    if not dry:
        return {}
    smoothness = median(dry)
    return {
        key: smoothness
        for key, values in ground.items()
        if values.get("_RainValue", 0) > 0 and values.get("_Smoothness", 0) > smoothness
    }
