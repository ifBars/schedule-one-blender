from pathlib import Path

root = Path(__file__).resolve().parent
source = (root / "extract_main.py").read_text(encoding="utf-8")
exec(
    compile(
        source[: source.index("# STAGE: RENDERERS")],
        str(root / "extract_main.py"),
        "exec",
    )
)
manifest = json.loads((OUT / "main_manifest.json").read_text(encoding="utf-8"))
meshes = manifest["meshes"]
materials = manifest["materials"]
textures = manifest["textures"]
failures = []
repaired = []
for err in manifest["errors"]:
    if err["kind"] != "renderer":
        failures.append(err)
        continue
    rid = err["id"]
    kind, d = renderers[rid]
    go = d.m_GameObject.m_PathID
    try:
        ptr = d.m_Mesh if kind == "SkinnedMeshRenderer" else filters.get(go)
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
        manifest["renderers"].append(r)
        repaired.append(rid)
    except Exception as ex:
        err["error"] = str(ex)
        failures.append(err)
used = {o["id"] for o in manifest["objects"]}
for r in manifest["renderers"]:
    if not r.get("empty"):
        used.add(r["go"])
        used.update(b for b in r.get("bones", []) if b)
for go in list(used):
    p = gos[go]["parent"]
    while p:
        used.add(p)
        p = gos[p]["parent"]
for go in used:
    gos[go]["world"] = world(go).tolist()
    gos[go]["active_hierarchy"] = bool(active(go))
manifest["objects"] = [gos[g] for g in sorted(used)]
manifest["errors"] = failures
(OUT / "main_manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
(OUT / "repair_report.json").write_text(
    json.dumps(
        {
            "repaired_renderers": len(repaired),
            "errors": failures,
            "source_empty_meshes": [k for k, m in meshes.items() if not m["vertices"]],
        },
        indent=2,
    )
)
print("REPAIRED", len(repaired), "ERRORS", failures, flush=True)
