using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace ScheduleOne.NativeExpansion
{
    // GPU readback is required for static-batched game meshes without CPU Read/Write copies.
    // Keep original vertex layouts so colors, tangents and every UV channel survive extraction.
    public sealed class NativeMeshReader
    {
        sealed class Buffers
        {
            public byte[][] streams;
            public int[] strides;
            public byte[] indices;
        }
        readonly Dictionary<Mesh, Buffers> cache = new Dictionary<Mesh, Buffers>();
        public void Clear() => cache.Clear();

        Buffers Read(Mesh mesh)
        {
            if (cache.TryGetValue(mesh, out var cached)) return cached;
            var buffers = new Buffers { streams = new byte[mesh.vertexBufferCount][], strides = new int[mesh.vertexBufferCount] };
            for (int stream = 0; stream < mesh.vertexBufferCount; stream++)
            {
                using (var buffer = mesh.GetVertexBuffer(stream))
                {
                    buffers.strides[stream] = buffer.stride;
                    buffers.streams[stream] = new byte[checked(buffer.count * buffer.stride)];
                    buffer.GetData(buffers.streams[stream]);
                }
            }
            using (var buffer = mesh.GetIndexBuffer())
            {
                buffers.indices = new byte[checked(buffer.count * buffer.stride)];
                buffer.GetData(buffers.indices);
            }
            cache.Add(mesh, buffers);
            return buffers;
        }

        public Mesh Extract(MeshRenderer renderer, int submeshCount)
        {
            var filter = renderer.GetComponent<MeshFilter>();
            if (!filter || !filter.sharedMesh) throw new InvalidOperationException("Source requires a MeshFilter");
            var source = filter.sharedMesh;
            int first = renderer.isPartOfStaticBatch ? renderer.subMeshStartIndex : 0;
            if (submeshCount < 1 || first + submeshCount > source.subMeshCount)
                throw new InvalidOperationException("Source submesh layout changed");
            if (source.GetVertexAttributeFormat(VertexAttribute.Position) != VertexAttributeFormat.Float32)
                throw new NotSupportedException("Source positions must use Float32");
            var buffers = Read(source);
            var remap = new Dictionary<int, int>();
            var vertices = new List<int>();
            var indices = new List<int[]>();
            int indexSize = source.indexFormat == IndexFormat.UInt16 ? 2 : 4;
            for (int sub = first; sub < first + submeshCount; sub++)
            {
                var descriptor = source.GetSubMesh(sub);
                if (descriptor.topology != MeshTopology.Triangles) throw new NotSupportedException("Only triangle sources are supported");
                var triangles = new int[descriptor.indexCount];
                for (int i = 0; i < triangles.Length; i++)
                {
                    int offset = checked((descriptor.indexStart + i) * indexSize);
                    int index = checked((indexSize == 2 ? BitConverter.ToUInt16(buffers.indices, offset) :
                        (int)BitConverter.ToUInt32(buffers.indices, offset)) + descriptor.baseVertex);
                    if (index < 0 || index >= source.vertexCount) throw new InvalidOperationException("Invalid native index");
                    if (!remap.TryGetValue(index, out int compact))
                    {
                        compact = vertices.Count; remap.Add(index, compact); vertices.Add(index);
                    }
                    triangles[i] = compact;
                }
                indices.Add(triangles);
            }
            var attributes = source.GetVertexAttributes();
            var streams = new byte[buffers.streams.Length][];
            for (int stream = 0; stream < streams.Length; stream++)
            {
                int stride = buffers.strides[stream];
                streams[stream] = new byte[checked(vertices.Count * stride)];
                for (int i = 0; i < vertices.Count; i++)
                    Buffer.BlockCopy(buffers.streams[stream], vertices[i] * stride, streams[stream], i * stride, stride);
            }
            if (renderer.isPartOfStaticBatch)
            {
                // Renderer matrices include the static-batch root; Transform matrices do not.
                var local = renderer.transform.worldToLocalMatrix * renderer.localToWorldMatrix;
                var normal = local.inverse.transpose;
                foreach (var attribute in attributes)
                {
                    if (attribute.attribute != VertexAttribute.Position && attribute.attribute != VertexAttribute.Normal &&
                        attribute.attribute != VertexAttribute.Tangent) continue;
                    if (attribute.format != VertexAttributeFormat.Float32 || attribute.dimension < 3)
                        throw new NotSupportedException("Position/normal/tangent must use Float32");
                    byte[] stream = streams[attribute.stream];
                    int stride = buffers.strides[attribute.stream], fieldOffset = source.GetVertexAttributeOffset(attribute.attribute);
                    for (int i = 0; i < vertices.Count; i++)
                    {
                        int offset = i * stride + fieldOffset;
                        var value = new Vector3(BitConverter.ToSingle(stream, offset), BitConverter.ToSingle(stream, offset + 4),
                            BitConverter.ToSingle(stream, offset + 8));
                        value = attribute.attribute == VertexAttribute.Position ? local.MultiplyPoint3x4(value) :
                            (attribute.attribute == VertexAttribute.Normal ? normal.MultiplyVector(value) : local.MultiplyVector(value)).normalized;
                        Buffer.BlockCopy(BitConverter.GetBytes(value.x), 0, stream, offset, 4);
                        Buffer.BlockCopy(BitConverter.GetBytes(value.y), 0, stream, offset + 4, 4);
                        Buffer.BlockCopy(BitConverter.GetBytes(value.z), 0, stream, offset + 8, 4);
                        if (attribute.attribute == VertexAttribute.Tangent && attribute.dimension == 4 && local.determinant < 0)
                            Buffer.BlockCopy(BitConverter.GetBytes(-BitConverter.ToSingle(stream, offset + 12)), 0, stream, offset + 12, 4);
                    }
                }
            }
            var result = new Mesh { name = "Native expansion: " + renderer.name, indexFormat = IndexFormat.UInt32 };
            try
            {
                result.SetVertexBufferParams(vertices.Count, attributes);
                for (int stream = 0; stream < streams.Length; stream++)
                {
                    if (result.GetVertexBufferStride(stream) != buffers.strides[stream])
                        throw new NotSupportedException("Native vertex stride cannot be preserved");
                    result.SetVertexBufferData(streams[stream], 0, 0, streams[stream].Length, stream);
                }
                result.subMeshCount = indices.Count;
                for (int i = 0; i < indices.Count; i++) result.SetTriangles(indices[i], i, false);
                result.RecalculateBounds();
                return result;
            }
            catch { UnityEngine.Object.Destroy(result); throw; }
        }
    }
}
