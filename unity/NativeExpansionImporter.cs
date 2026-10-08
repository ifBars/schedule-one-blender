// Copy to Assets/Editor in a LOCAL Unity project. Generated assets must never be published.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class NativeExpansionImporter
{
    [Serializable] public class Preview { public int schemaVersion; public Recipe recipe; public MeshData[] meshes; public MaterialData[] materials; }
    [Serializable] public class Recipe { public string id; public Placement[] placements; }
    [Serializable] public class Placement { public string id, mesh, collision; public bool render = true; public float[] matrix; }
    [Serializable] public class MeshData { public string id, name; public float[] positions, normals, uv; public Indices[] submeshes; public string[] materials; public int shadowMode; }
    [Serializable] public class Indices { public int[] indices; }
    [Serializable] public class MaterialData { public string id, name, nativeShader, texture; public float[] color, scale, offset; public float smoothness, metallic; }

    [MenuItem("Schedule One/Import Local Expansion Preview")]
    public static void Choose()
    {
        string path = EditorUtility.OpenFilePanel("Local expansion preview (contains game assets)", "", "json");
        if (!string.IsNullOrEmpty(path)) Import(path);
    }

    // -executeMethod NativeExpansionImporter.ImportBatch --preview <absolute local path>
    public static void ImportBatch()
    {
        string[] arguments = Environment.GetCommandLineArgs();
        int option = Array.IndexOf(arguments, "--preview");
        if (option < 0 || option + 1 >= arguments.Length) throw new ArgumentException("--preview is required");
        Import(arguments[option + 1]);
    }

    public static void Import(string path)
    {
        var data = JsonUtility.FromJson<Preview>(File.ReadAllText(path));
        if (data == null || data.schemaVersion != 1 || data.recipe == null || data.meshes == null || data.materials == null)
            throw new ArgumentException("Unsupported local preview");
        string folder = "Assets/NativeExpansionLocal/Import-" + Guid.NewGuid().ToString("N");
        Directory.CreateDirectory(folder); AssetDatabase.Refresh();
        var materials = new Dictionary<string, Material>();
        foreach (var source in data.materials)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            if (!shader) throw new InvalidOperationException("Install URP or use the built-in render pipeline");
            var material = new Material(shader) { name = source.name + " (preview)" };
            var color = new Color(source.color[0], source.color[1], source.color[2], source.color[3]);
            material.SetColor(material.HasProperty("_BaseColor") ? "_BaseColor" : "_Color", color);
            material.SetFloat("_Metallic", source.metallic);
            material.SetFloat(material.HasProperty("_Smoothness") ? "_Smoothness" : "_Glossiness", source.smoothness);
            if (!string.IsNullOrEmpty(source.texture))
            {
                if (Path.GetFileName(source.texture) != source.texture) throw new ArgumentException("Texture must be a sibling filename");
                string destination = folder + "/" + source.texture;
                if (!File.Exists(destination)) File.Copy(Path.Combine(Path.GetDirectoryName(path), source.texture), destination);
                AssetDatabase.ImportAsset(destination);
                var importer = (TextureImporter)AssetImporter.GetAtPath(destination);
                importer.maxTextureSize = 512; importer.SaveAndReimport();
                string property = material.HasProperty("_BaseMap") ? "_BaseMap" : "_MainTex";
                material.SetTexture(property, AssetDatabase.LoadAssetAtPath<Texture2D>(destination));
                material.SetTextureScale(property, new Vector2(source.scale[0], source.scale[1]));
                material.SetTextureOffset(property, new Vector2(source.offset[0], source.offset[1]));
            }
            AssetDatabase.CreateAsset(material, folder + "/" + source.id + ".mat");
            materials.Add(source.id, material);
        }
        var meshes = new Dictionary<string, Mesh>();
        var descriptions = new Dictionary<string, MeshData>();
        foreach (var source in data.meshes)
        {
            var mesh = new Mesh { name = source.name, indexFormat = IndexFormat.UInt32 };
            int count = source.positions.Length / 3;
            var vertices = new Vector3[count]; var normals = new Vector3[count]; var uv = new Vector2[count];
            for (int i = 0; i < count; i++)
            {
                vertices[i] = new Vector3(source.positions[i * 3], source.positions[i * 3 + 1], source.positions[i * 3 + 2]);
                normals[i] = new Vector3(source.normals[i * 3], source.normals[i * 3 + 1], source.normals[i * 3 + 2]);
                if (source.uv.Length == count * 2) uv[i] = new Vector2(source.uv[i * 2], source.uv[i * 2 + 1]);
            }
            mesh.vertices = vertices; mesh.normals = normals; mesh.uv = uv; mesh.subMeshCount = source.submeshes.Length;
            for (int i = 0; i < source.submeshes.Length; i++)
            {
                var indices = source.submeshes[i].indices;
                if (indices == null || indices.Length % 3 != 0 || indices.Any(index => index < 0 || index >= count))
                    throw new ArgumentException("Invalid triangle array in local preview");
                mesh.SetTriangles(indices, i);
            }
            mesh.RecalculateBounds(); mesh.RecalculateTangents();
            AssetDatabase.CreateAsset(mesh, folder + "/" + source.id + ".asset");
            meshes.Add(source.id, mesh); descriptions.Add(source.id, source);
        }
        var root = new GameObject("LOCAL PREVIEW - " + data.recipe.id);
        foreach (var part in data.recipe.placements)
        {
            if (part.matrix == null || part.matrix.Length != 16) throw new ArgumentException("Invalid placement matrix");
            var matrix = new Matrix4x4();
            for (int i = 0; i < 16; i++) matrix[i / 4, i % 4] = part.matrix[i];
            var obj = new GameObject(part.id); obj.transform.SetParent(root.transform, false);
            obj.transform.localPosition = matrix.GetColumn(3);
            obj.transform.localRotation = Quaternion.LookRotation(matrix.GetColumn(2), matrix.GetColumn(1));
            obj.transform.localScale = new Vector3(((Vector3)matrix.GetColumn(0)).magnitude, ((Vector3)matrix.GetColumn(1)).magnitude, ((Vector3)matrix.GetColumn(2)).magnitude);
            obj.AddComponent<MeshFilter>().sharedMesh = meshes[part.mesh];
            var renderer = obj.AddComponent<MeshRenderer>(); renderer.enabled = part.render;
            renderer.sharedMaterials = descriptions[part.mesh].materials.Select(id => materials[id]).ToArray();
            renderer.shadowCastingMode = (ShadowCastingMode)descriptions[part.mesh].shadowMode;
            if (part.collision == "mesh") obj.AddComponent<MeshCollider>().sharedMesh = meshes[part.mesh];
        }
        PrefabUtility.SaveAsPrefabAsset(root, folder + "/Expansion.prefab");
        EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene(), folder + "/ExpansionPreview.unity");
        AssetDatabase.SaveAssets(); Selection.activeGameObject = root;
        Debug.Log("NATIVE_PREVIEW PASS: " + data.recipe.placements.Length + " placements, " + meshes.Count + " meshes. " + folder);
        Debug.LogWarning("LOCAL GAME ASSETS: do not distribute this preview. Runtime uses actual native materials; preview shaders are approximations.");
    }
}
