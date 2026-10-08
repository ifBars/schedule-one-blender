// Synthetic Unity checks. Copy this file, runtime/Recipe.cs and runtime/NativeMesh.cs
// to Assets/Editor. Run -executeMethod NativeExpansionTests.Run with graphics enabled.
using System;
using System.Linq;
using ScheduleOne.NativeExpansion;
using UnityEngine;

public static class NativeExpansionTests
{
    static void Require(bool value, string message) { if (!value) throw new Exception(message); }
    static float[] Values(Matrix4x4 matrix)
    {
        var result = new float[16]; for (int i = 0; i < 16; i++) result[i] = matrix[i / 4, i % 4]; return result;
    }
    public static void Run()
    {
        var transform = Matrix4x4.TRS(new Vector3(3, 8, -11), Quaternion.Euler(0, 37, 0), new Vector3(2, 3, 4));
        var obj = new GameObject("synthetic source"); var extracted = (Mesh)null;
        var mesh = new Mesh();
        try
        {
            RecipeValidation.ApplyTransform(obj.transform, RecipeValidation.Transform(Values(transform)));
            Require(Vector3.Distance(obj.transform.position, new Vector3(3, 8, -11)) < .00001f, "position conversion");
            Require(Vector3.Distance(obj.transform.lossyScale, new Vector3(2, 3, 4)) < .00001f, "scale conversion");
            foreach (var bad in new[] { Matrix4x4.Scale(new Vector3(-1, 1, 1)), Matrix4x4.Scale(new Vector3(0, 1, 1)) })
            {
                bool rejected = false; try { RecipeValidation.Transform(Values(bad)); } catch (ArgumentException) { rejected = true; }
                Require(rejected, "invalid transform accepted");
            }
            mesh.vertices = new[] { Vector3.zero, Vector3.right, Vector3.up, new Vector3(99, 99, 99) };
            mesh.normals = Enumerable.Repeat(Vector3.forward, 4).ToArray();
            mesh.uv = new[] { Vector2.zero, Vector2.right, Vector2.up, Vector2.one };
            mesh.colors32 = Enumerable.Repeat(new Color32(12, 34, 56, 255), 4).ToArray();
            mesh.triangles = new[] { 0, 1, 2 };
            obj.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = obj.AddComponent<MeshRenderer>();
            mesh.UploadMeshData(true);
            Require(!mesh.isReadable, "fixture must have no CPU mesh copy");
            extracted = new NativeMeshReader().Extract(renderer, 1);
            Require(extracted.vertexCount == 3, "unreferenced vertex was not compacted");
            Require(extracted.triangles.SequenceEqual(new[] { 0, 1, 2 }), "indices changed");
            Require(extracted.uv[2] == Vector2.up, "UV changed");
            Require(extracted.colors32[0].g == 34, "packed color changed");
            Require(extracted.vertices[1] == Vector3.right, "nonstatic local position changed");
            var batchRoot = new GameObject("synthetic batch root");
            var first = GameObject.CreatePrimitive(PrimitiveType.Cube);
            var second = GameObject.CreatePrimitive(PrimitiveType.Cube);
            Mesh unbatched = first.GetComponent<MeshFilter>().sharedMesh;
            var expected = unbatched.vertices;
            Mesh compact = null;
            try
            {
                batchRoot.transform.SetPositionAndRotation(new Vector3(30, 4, -7), Quaternion.Euler(0, 27, 0));
                first.transform.SetParent(batchRoot.transform, false); first.transform.localPosition = new Vector3(2, 0, 3);
                second.transform.SetParent(batchRoot.transform, false); second.transform.localPosition = new Vector3(5, 0, 3);
                StaticBatchingUtility.Combine(new[] { first, second }, batchRoot);
                var batched = first.GetComponent<MeshRenderer>();
                Require(batched.isPartOfStaticBatch, "fixture failed to static-batch");
                compact = new NativeMeshReader().Extract(batched, 1);
                foreach (var vertex in compact.vertices)
                    Require(expected.Any(v => Vector3.Distance(v, vertex) < .0001f), "nonidentity batch-root conversion changed geometry");
            }
            finally { UnityEngine.Object.DestroyImmediate(batchRoot); if (compact) UnityEngine.Object.DestroyImmediate(compact); }
            Debug.Log("NATIVE_SYNTHETIC PASS: GPU compaction, UV/color preservation, TRS rejection, nonidentity static batch root");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(obj); UnityEngine.Object.DestroyImmediate(mesh);
            if (extracted) UnityEngine.Object.DestroyImmediate(extracted);
        }
    }
}
