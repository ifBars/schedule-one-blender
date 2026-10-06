"""Selection rules shared by native binding resolution and synthetic tests."""


def volume_component(native, components, name):
    matches = [
        key
        for key in components
        if key in native and native[key]["type"].endswith("." + name)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one {name} in the native global volume; found {len(matches)}"
        )
    return matches[0]
