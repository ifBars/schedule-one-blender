using System;
using System.Collections.Generic;
using System.IO;
using MelonLoader;
using Newtonsoft.Json;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

[assembly: MelonInfo(typeof(ScheduleOne.NativeExpansion.ExpansionMod), "Native Map Expansion", "0.1.0", "ifBars")]
[assembly: MelonGame("TVGS", "Schedule I")]
namespace ScheduleOne.NativeExpansion
{
    public sealed class ExpansionMod : MelonMod
    {
        readonly List<GameObject> roots = new List<GameObject>();
        readonly List<Mesh> meshes = new List<Mesh>();
        readonly Dictionary<GameObject, bool> suppressed = new Dictionary<GameObject, bool>();
        int pendingScene = -1;
        float deadline, readyAt;
        public override void OnSceneWasInitialized(int buildIndex, string name)
        {
            if (name != "Main") return;
            Cleanup();
            pendingScene = SceneManager.GetSceneByName(name).handle;
            deadline = Time.realtimeSinceStartup + 90;
            readyAt = Time.realtimeSinceStartup + 5;
        }
        public override void OnSceneWasUnloaded(int buildIndex, string name)
        {
            if (name == "Main") { pendingScene = -1; Cleanup(); }
        }
        public override void OnDeinitializeMelon() => Cleanup();
        public override void OnUpdate()
        {
            if (pendingScene == -1 || Time.realtimeSinceStartup < readyAt) return;
            var scene = SceneManager.GetSceneByName("Main");
            if (!scene.IsValid() || !scene.isLoaded || scene.handle != pendingScene) return;
            bool ready = false;
            foreach (var root in scene.GetRootGameObjects()) if (root.name == "Map") ready = true;
            if (!ready && Time.realtimeSinceStartup < deadline) return;
            pendingScene = -1;
            if (!ready) { LoggerInstance.Error("Main map readiness timed out"); return; }
            string folder = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "UserData", "NativeExpansions");
            if (!Directory.Exists(folder)) return;
            foreach (string path in Directory.GetFiles(folder, "*.expansion.json"))
            {
                try
                {
                    if (new FileInfo(path).Length > 16 * 1024 * 1024) throw new InvalidOperationException("Recipe exceeds 16 MiB");
                    Apply(JsonConvert.DeserializeObject<Recipe>(File.ReadAllText(path), new JsonSerializerSettings { TypeNameHandling = TypeNameHandling.None, MaxDepth = 64 }), scene);
                }
                catch (Exception error) { LoggerInstance.Error(Path.GetFileName(path) + ": " + error); }
            }
        }

        public void Apply(Recipe recipe, Scene scene)
        {
            if (recipe == null || recipe.schemaVersion != 1 || recipe.scene != "Main" ||
                string.IsNullOrWhiteSpace(recipe.id) || string.IsNullOrWhiteSpace(recipe.gameVersion) || recipe.placements == null || recipe.placements.Length < 1 || recipe.placements.Length > 10000)
                throw new InvalidOperationException("Invalid expansion recipe");
            if (Application.version.Split(' ')[0] != recipe.gameVersion.Split(' ')[0])
                throw new InvalidOperationException("Game version mismatch. Regenerate from this game copy: " + Application.version);
            foreach (var existing in roots) if (existing && existing.name == "NativeExpansion/" + recipe.id)
                throw new InvalidOperationException("Expansion ID already loaded");
            var sources = new MeshRenderer[recipe.placements.Length];
            var transforms = new Matrix4x4[recipe.placements.Length];
            var ids = new HashSet<string>();
            for (int i = 0; i < sources.Length; i++)
            {
                var part = recipe.placements[i];
                if (part == null || string.IsNullOrEmpty(part.id) || !ids.Add(part.id) ||
                    (part.collision != "none" && part.collision != "mesh")) throw new InvalidOperationException("Invalid placement identity/collision");
                transforms[i] = RecipeValidation.Transform(part.matrix);
                sources[i] = RecipeValidation.Resolve(scene, part.source).GetComponent<MeshRenderer>();
                if (!sources[i]) throw new InvalidOperationException("Source is not a MeshRenderer");
                var materials = sources[i].sharedMaterials;
                if (part.source.materials == null || part.source.shaders == null || materials.Length != part.source.materials.Length ||
                    materials.Length != part.source.shaders.Length || part.source.submeshes < 1)
                    throw new InvalidOperationException("Missing or changed material signature");
                for (int m = 0; m < materials.Length; m++)
                    if (!materials[m] || materials[m].name != part.source.materials[m] || !materials[m].shader ||
                        materials[m].shader.name != part.source.shaders[m]) throw new InvalidOperationException("Native material signature changed");
            }
            var hide = new List<GameObject>();
            foreach (var reference in recipe.suppress ?? Array.Empty<SourceReference>())
            {
                var target = RecipeValidation.Resolve(scene, reference);
                if (reference.path.Length < 3 || reference.path[0] != "Map") throw new InvalidOperationException("Suppression must target a map subtree");
                hide.Add(target);
            }
            var root = new GameObject("NativeExpansion/" + recipe.id);
            root.SetActive(false);
            SceneManager.MoveGameObjectToScene(root, scene);
            var reader = new NativeMeshReader();
            var templates = new Dictionary<MeshRenderer, Mesh>();
            var created = new List<Mesh>();
            try
            {
                for (int i = 0; i < sources.Length; i++)
                {
                    var source = sources[i]; var part = recipe.placements[i];
                    if (!templates.TryGetValue(source, out var mesh))
                    {
                        mesh = reader.Extract(source, part.source.submeshes);
                        templates.Add(source, mesh); created.Add(mesh);
                    }
                    var obj = new GameObject(part.id) { layer = source.gameObject.layer };
                    obj.transform.SetParent(root.transform, false);
                    RecipeValidation.ApplyTransform(obj.transform, transforms[i]);
                    obj.AddComponent<MeshFilter>().sharedMesh = mesh;
                    var renderer = obj.AddComponent<MeshRenderer>();
                    renderer.sharedMaterials = source.sharedMaterials;
                    renderer.enabled = part.render;
                    renderer.shadowCastingMode = source.shadowCastingMode;
                    renderer.receiveShadows = source.receiveShadows;
                    renderer.renderingLayerMask = source.renderingLayerMask;
                    renderer.lightProbeUsage = LightProbeUsage.BlendProbes;
                    renderer.reflectionProbeUsage = source.reflectionProbeUsage;
                    if (part.collision == "mesh")
                    {
                        var collider = obj.AddComponent<MeshCollider>(); collider.sharedMesh = mesh;
                        var originalCollider = source.GetComponent<Collider>();
                        if (originalCollider) collider.sharedMaterial = originalCollider.sharedMaterial;
                    }
                }
                foreach (var obj in hide)
                {
                    if (!suppressed.ContainsKey(obj)) suppressed.Add(obj, obj.activeSelf);
                    obj.SetActive(false);
                }
                roots.Add(root); meshes.AddRange(created); root.SetActive(true);
                Physics.SyncTransforms();
                LoggerInstance.Msg("NATIVE_EXPANSION READY " + recipe.id + ": " + sources.Length + " parts, " + created.Count + " shared meshes");
            }
            catch
            {
                UnityEngine.Object.Destroy(root);
                foreach (var mesh in created) UnityEngine.Object.Destroy(mesh);
                throw;
            }
            finally { reader.Clear(); }
        }
        void Cleanup()
        {
            foreach (var pair in suppressed) if (pair.Key) pair.Key.SetActive(pair.Value);
            suppressed.Clear();
            foreach (var root in roots) if (root) UnityEngine.Object.Destroy(root);
            foreach (var mesh in meshes) if (mesh) UnityEngine.Object.Destroy(mesh);
            roots.Clear(); meshes.Clear();
        }
    }
}
