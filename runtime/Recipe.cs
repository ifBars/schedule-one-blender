using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace ScheduleOne.NativeExpansion
{
    [Serializable] public sealed class SourceReference
    {
        public string[] path;
        public float[] position;
        public string[] materials;
        public string[] shaders;
        public int submeshes;
    }
    [Serializable] public sealed class Placement
    {
        public string id;
        public SourceReference source;
        public float[] matrix;
        public string collision;
        public bool render = true;
    }
    [Serializable] public sealed class Recipe
    {
        public int schemaVersion;
        public string id;
        public string gameVersion;
        public string scene;
        public Placement[] placements;
        public SourceReference[] suppress;
    }

    public static class RecipeValidation
    {
        public static Matrix4x4 Transform(float[] values)
        {
            if (values == null || values.Length != 16) throw new ArgumentException("Expected 16 matrix elements");
            var result = new Matrix4x4();
            for (int i = 0; i < 16; i++)
            {
                if (float.IsNaN(values[i]) || float.IsInfinity(values[i])) throw new ArgumentException("Non-finite transform");
                result[i / 4, i % 4] = values[i];
            }
            if (Mathf.Abs(result[3, 0]) > 0.00001f || Mathf.Abs(result[3, 1]) > 0.00001f ||
                Mathf.Abs(result[3, 2]) > 0.00001f || Mathf.Abs(result[3, 3] - 1) > 0.00001f)
                throw new ArgumentException("Non-affine transform");
            var x = (Vector3)result.GetColumn(0); var y = (Vector3)result.GetColumn(1); var z = (Vector3)result.GetColumn(2);
            foreach (float scale in new[] { x.magnitude, y.magnitude, z.magnitude })
                if (scale < 0.001f || scale > 100) throw new ArgumentException("Unsupported scale");
            x.Normalize(); y.Normalize(); z.Normalize();
            if (Mathf.Abs(Vector3.Dot(x, y)) > 0.0001f || Mathf.Abs(Vector3.Dot(x, z)) > 0.0001f ||
                Mathf.Abs(Vector3.Dot(y, z)) > 0.0001f || Vector3.Dot(Vector3.Cross(x, y), z) < 0.9999f)
                throw new ArgumentException("Mirrored or sheared transform");
            return result;
        }

        public static void ApplyTransform(Transform target, Matrix4x4 matrix)
        {
            target.localPosition = matrix.GetColumn(3);
            target.localRotation = Quaternion.LookRotation(matrix.GetColumn(2), matrix.GetColumn(1));
            target.localScale = new Vector3(((Vector3)matrix.GetColumn(0)).magnitude,
                ((Vector3)matrix.GetColumn(1)).magnitude, ((Vector3)matrix.GetColumn(2)).magnitude);
        }

        public static GameObject Resolve(Scene scene, SourceReference reference)
        {
            if (reference == null || reference.path == null || reference.path.Length == 0 ||
                reference.path.Length > 64 || reference.position == null || reference.position.Length != 3)
                throw new ArgumentException("Invalid source selector");
            foreach (float v in reference.position)
                if (float.IsNaN(v) || float.IsInfinity(v)) throw new ArgumentException("Invalid source position");
            var candidates = new List<Transform>();
            foreach (var root in scene.GetRootGameObjects())
                if (root.name == reference.path[0]) candidates.Add(root.transform);
            for (int depth = 1; depth < reference.path.Length; depth++)
            {
                var next = new List<Transform>();
                foreach (var parent in candidates)
                    for (int i = 0; i < parent.childCount; i++)
                        if (parent.GetChild(i).name == reference.path[depth]) next.Add(parent.GetChild(i));
                candidates = next;
            }
            var position = new Vector3(reference.position[0], reference.position[1], reference.position[2]);
            candidates.RemoveAll(t => Vector3.Distance(t.position, position) > 0.02f);
            if (candidates.Count != 1) throw new InvalidOperationException("Source selector must resolve uniquely: " +
                string.Join("/", reference.path) + " (matches " + candidates.Count + ")");
            return candidates[0].gameObject;
        }
    }
}
