"""Local-only reproducible extraction of the installed Main scene; never runs game code."""

from pathlib import Path
from collections import Counter
from functools import lru_cache
import json, sys, time, hashlib, re, math
import numpy as np
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

OUT = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1])
CACHE = OUT / "extracted"
for part in ["meshes", "textures", "terrain"]:
    (CACHE / part).mkdir(parents=True, exist_ok=True)
env = UnityPy.Environment(path=str(SOURCE))
global_file = env.load_file(str(SOURCE / "globalgamemanagers"))
settings = {
    o.type.name: o.read_typetree()
    for o in global_file.objects.values()
    if o.type.name in ["PlayerSettings", "BuildSettings"]
}
scene_index = next(
    i
    for i, s in enumerate(settings["BuildSettings"]["scenes"])
    if s.endswith("/Main.unity")
)
scene = env.load_file(str(SOURCE / f"level{scene_index}"))
errors = []
materials, textures, meshes, terrains = {}, {}, {}, []
gos, transforms, transform_go, filters, renderers, lods = {}, {}, {}, {}, {}, {}
counts = Counter(o.type.name for o in scene.objects.values())
print(
    "SOURCE",
    settings["PlayerSettings"]["bundleVersion"],
    "objects",
    len(scene.objects),
    flush=True,
)


def vector(v):
    return [v.x, v.y, v.z] + ([v.w] if hasattr(v, "w") else [])


def rgba(v):
    return [v.r, v.g, v.b, v.a]


def key(reader):
    return f"{Path(reader.assets_file.name).name}_{reader.path_id}"


def ref(ptr):
    return key(ptr.deref()) if ptr and ptr.m_PathID else None


def plain(d):
    return dict(d) if not isinstance(d, dict) else d


for i, o in enumerate(scene.objects.values()):
    kind = o.type.name
    if kind not in [
        "GameObject",
        "Transform",
        "RectTransform",
        "MeshFilter",
        "MeshRenderer",
        "SkinnedMeshRenderer",
        "LODGroup",
        "Terrain",
    ]:
        continue
    d = o.read()
    if kind == "GameObject":
        gos[o.path_id] = {
            "id": o.path_id,
            "name": d.m_Name,
            "active": bool(d.m_IsActive),
            "layer": d.m_Layer,
        }
    elif kind in ["Transform", "RectTransform"]:
        go = d.m_GameObject.m_PathID
        transforms[go] = {
            "transform": o.path_id,
            "parent_transform": d.m_Father.m_PathID,
            "p": vector(d.m_LocalPosition),
            "q": vector(d.m_LocalRotation),
            "s": vector(d.m_LocalScale),
        }
        transform_go[o.path_id] = go
    elif kind == "MeshFilter":
        filters[d.m_GameObject.m_PathID] = d.m_Mesh
    elif kind in ["MeshRenderer", "SkinnedMeshRenderer"]:
        renderers[o.path_id] = (kind, d)
    elif kind == "LODGroup":
        for n, lod in enumerate(d.m_LODs):
            for r in lod.renderers:
                lods[r.renderer.m_PathID] = min(n, lods.get(r.renderer.m_PathID, 100))
    else:
        terrains.append(d)
    if i % 50000 == 0:
        print("scene records", i, flush=True)
for go, t in transforms.items():
    t["parent"] = transform_go.get(t.pop("parent_transform"), 0)
    gos[go].update(t)


def trs(p, q, s):
    x, y, z, w = q
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    m = np.eye(4)
    m[:3, :3] = r @ np.diag(s)
    m[:3, 3] = p
    return m


@lru_cache(None)
def world(go):
    t = gos[go]
    local = trs(t["p"], t["q"], t["s"])
    return world(t["parent"]) @ local if t["parent"] else local


@lru_cache(None)
def active(go):
    return gos[go]["active"] and (not gos[go]["parent"] or active(gos[go]["parent"]))


def texture(ptr):
    if not ptr or not ptr.m_PathID:
        return None
    reader = ptr.deref()
    k = key(reader)
    if k in textures:
        return k
    if reader.type.name != "Texture2D":
        textures[k] = {"name": reader.type.name, "unsupported": True}
        return k
    try:
        d = reader.read()
        path = CACHE / "textures" / f"{k}.png"
        if not path.exists():
            d.image.save(path)
        textures[k] = {
            "name": d.m_Name,
            "path": str(path.relative_to(OUT)),
            "width": d.m_Width,
            "height": d.m_Height,
            "format": d.m_TextureFormat,
        }
    except Exception as ex:
        errors.append({"kind": "texture", "id": k, "error": str(ex)})
        textures[k] = {"name": k, "error": str(ex)}
    return k


def material(ptr):
    if not ptr or not ptr.m_PathID:
        return None
    reader = ptr.deref()
    k = key(reader)
    if k in materials:
        return k
    d = reader.read()
    props = d.m_SavedProperties
    shader = ""
    try:
        sh = d.m_Shader.deref_parse_as_object()
        shader = getattr(sh, "m_Name", "") or sh.m_ParsedForm.m_Name
    except Exception:
        pass
    m = {
        "name": d.m_Name,
        "shader": shader,
        "floats": plain(props.m_Floats),
        "colors": {n: rgba(v) for n, v in props.m_Colors},
        "textures": {},
    }
    materials[k] = m
    for n, v in props.m_TexEnvs:
        if v.m_Texture.m_PathID:
            m["textures"][n] = {
                "id": texture(v.m_Texture),
                "scale": [v.m_Scale.x, v.m_Scale.y],
                "offset": [v.m_Offset.x, v.m_Offset.y],
            }
    return k


def mesh(ptr):
    if not ptr or not ptr.m_PathID:
        return None
    reader = ptr.deref()
    k = key(reader)
    if k in meshes:
        return k
    d = reader.read()
    # Unity stores flags in the high nibble; UnityPy checks raw dimension before masking it.
    for channel in d.m_VertexData.m_Channels or []:
        channel.dimension &= 0xF
    h = MeshHandler(d)
    h.process()
    data = {"vertices": np.asarray(h.m_Vertices or [], dtype=np.float32).reshape(-1, 3)}
    triangles = h.get_triangles()
    info = {
        "name": d.m_Name,
        "path": f"extracted/meshes/{k}.npz",
        "vertices": len(data["vertices"]),
        "submeshes": len(triangles),
        "triangles": sum(len(t) for t in triangles),
    }
    for i, t in enumerate(triangles):
        data[f"tri_{i}"] = np.array(t, dtype=np.int32).reshape(-1, 3) + (
            d.m_SubMeshes[i].baseVertex or 0
        )
    for name, attr in [
        ("normals", "m_Normals"),
        ("colors", "m_Colors"),
        ("uv0", "m_UV0"),
        ("uv1", "m_UV1"),
    ]:
        v = getattr(h, attr, None)
        if v is not None and len(v) == len(data["vertices"]):
            data[name] = np.asarray(v, dtype=np.float32)
    if h.m_BoneIndices and h.m_BoneWeights and d.m_BindPose:
        data["bone_indices"] = np.asarray(h.m_BoneIndices, dtype=np.int32)
        data["bone_weights"] = np.asarray(h.m_BoneWeights, dtype=np.float32)
        data["bind_poses"] = np.asarray(
            [
                [[getattr(m, f"e{r}{c}") for c in range(4)] for r in range(4)]
                for m in d.m_BindPose
            ]
        )
    np.savez(OUT / info["path"], **data)
    meshes[k] = info
    return k


# STAGE: RENDERERS
records = []
for i, (rid, (kind, d)) in enumerate(renderers.items()):
    go = d.m_GameObject.m_PathID
    try:
        ptr = d.m_Mesh if kind == "SkinnedMeshRenderer" else filters.get(go)
        if ptr is None or not ptr.m_PathID:
            records.append({"id": rid, "go": go, "empty": True})
            continue
        mk = mesh(ptr)
        batch = d.m_StaticBatchInfo
        r = {
            "id": rid,
            "go": go,
            "mesh": mk,
            "materials": [material(p) for p in d.m_Materials],
            "enabled": bool(d.m_Enabled),
            "active": active(go),
            "lod": lods.get(rid, 0),
            "kind": kind,
            "batch_first": batch.firstSubMesh if batch else 0,
            "batch_count": batch.subMeshCount if batch else 0,
            "batch_root": transform_go.get(d.m_StaticBatchRoot.m_PathID, 0)
            if d.m_StaticBatchRoot
            else 0,
        }
        if kind == "SkinnedMeshRenderer":
            r["bones"] = [transform_go.get(b.m_PathID, 0) for b in d.m_Bones]
        records.append(r)
    except Exception as ex:
        errors.append(
            {
                "kind": "renderer",
                "id": rid,
                "go": go,
                "name": gos[go]["name"],
                "error": str(ex),
            }
        )
    if i % 2000 == 0:
        print(
            "renderers",
            i,
            "/",
            len(renderers),
            "meshes",
            len(meshes),
            "textures",
            len(textures),
            "errors",
            len(errors),
            flush=True,
        )

terrain_records = []
for t in terrains:
    d = t.m_TerrainData.deref_parse_as_object()
    k = key(d.object_reader)
    hm = d.m_Heightmap
    res = hm.m_Resolution
    heights = np.asarray(hm.m_Heights, dtype=np.uint16).reshape(res, res)
    holes = (
        np.asarray(hm.m_Holes, dtype=np.uint8).reshape(res - 1, res - 1)
        if hm.m_Holes
        else np.zeros((res - 1, res - 1), dtype=np.uint8)
    )
    np.savez(CACHE / "terrain" / f"{k}.npz", heights=heights, holes=holes)
    print(
        "TERRAIN",
        d.m_Name,
        "res",
        res,
        "height range",
        int(heights.min()),
        int(heights.max()),
        "holes",
        np.unique(holes, return_counts=True),
        flush=True,
    )
    layers = []
    for p in d.m_SplatDatabase.m_TerrainLayers or []:
        l = p.deref_parse_as_object()
        layers.append(
            {
                "name": l.m_Name,
                "diffuse": texture(l.m_DiffuseTexture),
                "normal": texture(l.m_NormalMapTexture),
                "size": [l.m_TileSize.x, l.m_TileSize.y],
                "offset": [l.m_TileOffset.x, l.m_TileOffset.y],
            }
        )
    trees = d.m_DetailDatabase.m_TreeInstances
    tree_data = [
        {
            "p": vector(v.position),
            "width": v.widthScale,
            "height": v.heightScale,
            "rotation": v.rotation or 0,
            "index": v.index,
        }
        for v in trees
    ]
    prototypes = []

    def prefab_node(go_ptr, parent_matrix):
        obj = go_ptr.deref_parse_as_object()
        components = [c.component.deref_parse_as_object() for c in obj.m_Component]
        tr = next(c for c in components if type(c).__name__ == "Transform")
        mat = parent_matrix @ trs(
            vector(tr.m_LocalPosition),
            vector(tr.m_LocalRotation),
            vector(tr.m_LocalScale),
        )
        mf = next((c for c in components if type(c).__name__ == "MeshFilter"), None)
        mr = next((c for c in components if type(c).__name__ == "MeshRenderer"), None)
        result = []
        if mf and mr:
            result.append(
                {
                    "name": obj.m_Name,
                    "matrix": mat.tolist(),
                    "mesh": mesh(mf.m_Mesh),
                    "materials": [material(p) for p in mr.m_Materials],
                    "lod": int(re.search(r"LOD[ _]?(\d)", obj.m_Name, re.I).group(1))
                    if re.search(r"LOD[ _]?(\d)", obj.m_Name, re.I)
                    else 0,
                }
            )
        for child in tr.m_Children:
            result.extend(prefab_node(child.deref_parse_as_object().m_GameObject, mat))
        return result

    for p in d.m_DetailDatabase.m_TreePrototypes:
        prototypes.append(prefab_node(p.prefab, np.eye(4)))
    # Keep the exact procedural foliage paint data; generated positions belong to Unity's runtime.
    detail = d.m_DetailDatabase
    (CACHE / "terrain" / f"{k}_details.json").write_text(
        json.dumps(
            {
                "patch_count": detail.m_PatchCount,
                "patch_samples": detail.m_PatchSamples,
                "patches": [
                    {"layers": p.layerIndices, "coverage": p.coverage}
                    for p in detail.m_Patches
                ],
            },
            separators=(",", ":"),
        )
    )
    terrain_records.append(
        {
            "go": t.m_GameObject.m_PathID,
            "name": d.m_Name,
            "path": f"extracted/terrain/{k}.npz",
            "resolution": res,
            "scale": vector(hm.m_Scale),
            "layers": layers,
            "alphas": [texture(p) for p in d.m_SplatDatabase.m_AlphaTextures],
            "enabled": bool(t.m_Enabled),
            "draw": t.m_DrawHeightmap,
            "trees": tree_data,
            "prototypes": prototypes,
            "tree_distance": t.m_TreeDistance,
            "material": material(t.m_MaterialTemplate),
        }
    )

used = set(r["go"] for r in records if not r.get("empty")) | {
    t["go"] for t in terrain_records
}
for r in records:
    used.update(b for b in r.get("bones", []) if b)
for go in list(used):
    p = gos[go]["parent"]
    while p:
        used.add(p)
        p = gos[p]["parent"]
for go in used:
    gos[go]["world"] = world(go).tolist()
    gos[go]["active_hierarchy"] = bool(active(go))
manifest = {
    "source": str(SOURCE),
    "scene": "Main",
    "version": settings["PlayerSettings"]["bundleVersion"],
    "unity_version": settings["BuildSettings"]["m_Version"],
    "scene_file": f"level{scene_index}",
    "source_counts": dict(counts),
    "objects": [gos[g] for g in sorted(used)],
    "renderers": records,
    "meshes": meshes,
    "materials": materials,
    "textures": textures,
    "terrains": terrain_records,
    "errors": errors,
}
(OUT / "main_manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
(OUT / "extraction_report.json").write_text(
    json.dumps(
        {
            "version": manifest["version"],
            "source_counts": dict(counts),
            "objects": len(used),
            "renderers": len(records),
            "meshes": len(meshes),
            "materials": len(materials),
            "textures": len(textures),
            "terrain": len(terrain_records),
            "errors": errors,
        },
        indent=2,
    )
)
print(
    "DONE",
    len(used),
    "objects",
    len(records),
    "renderers",
    len(errors),
    "errors",
    flush=True,
)
