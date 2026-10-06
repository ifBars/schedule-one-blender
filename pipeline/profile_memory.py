import bpy, json, ctypes, ctypes.wintypes as w
from pathlib import Path
from collections import Counter

root = Path(__file__).resolve().parent


class Memory(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [
        (n, ctypes.c_size_t)
        for n in [
            "PeakWorkingSetSize",
            "WorkingSetSize",
            "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage",
            "PagefileUsage",
            "PeakPagefileUsage",
        ]
    ]


def memory():
    p = Memory()
    p.cb = ctypes.sizeof(p)
    ctypes.windll.kernel32.GetCurrentProcess.restype = w.HANDLE
    fn = ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes = [w.HANDLE, ctypes.POINTER(Memory), w.DWORD]
    fn.restype = w.BOOL
    if not fn(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(p), p.cb):
        raise ctypes.WinError()
    return {
        k: round(getattr(p, k) / 2**20, 1)
        for k in [
            "WorkingSetSize",
            "PeakWorkingSetSize",
            "PagefileUsage",
            "PeakPagefileUsage",
        ]
    }


def enabled_collections(lc, enabled=True):
    enabled = (
        enabled
        and not lc.exclude
        and not lc.hide_viewport
        and not lc.collection.hide_viewport
        and not lc.collection.hide_render
    )
    result = {lc.collection} if enabled else set()
    for c in lc.children:
        result.update(enabled_collections(c, enabled))
    return result


cols = enabled_collections(bpy.context.view_layer.layer_collection)
active = [
    o
    for o in {o for c in cols for o in c.objects}
    if not o.hide_render and not o.hide_viewport
]
report = {
    "memory_mib": memory(),
    "all_objects": len(bpy.data.objects),
    "active_types": dict(Counter(o.type for o in active)),
    "active_meshes_unique": len({o.data for o in active if o.type == "MESH"}),
    "images": [
        {
            "name": im.name,
            "path": im.filepath,
            "packed_bytes": im.packed_file.size if im.packed_file else 0,
        }
        for im in bpy.data.images
        if im.source == "FILE"
    ],
}
(root / "memory_baseline.json").write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != "images"}), flush=True)
