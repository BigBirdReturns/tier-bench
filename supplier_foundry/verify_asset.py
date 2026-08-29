#!/usr/bin/env python3
"""Dependency-free semantic verifier for the first Supplier Foundry glTF pilot.

The verifier intentionally supports the bounded glTF 2.0 surface exercised by the
pilot: ordinary buffers, buffer views, accessors, indexed triangle primitives,
node matrices or TRS transforms, and GLB or JSON glTF containers. Compressed,
sparse, skinned, morphed, or non-triangle products fail visibly instead of being
silently approximated.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

GLB_MAGIC = b"glTF"
GLB_JSON = 0x4E4F534A
GLB_BIN = 0x004E4942
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 128
MAX_NODES = 100_000
MAX_TRIANGLES = 2_000_000

COMPONENTS: dict[int, tuple[str, int, bool, int | None]] = {
    5120: ("b", 1, True, 127),
    5121: ("B", 1, False, 255),
    5122: ("h", 2, True, 32767),
    5123: ("H", 2, False, 65535),
    5125: ("I", 4, False, 4294967295),
    5126: ("f", 4, True, None),
}
TYPE_WIDTH = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class AssetError(ValueError):
    pass


def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AssetError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def json_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        raise AssetError(f"JSON nesting exceeds {MAX_JSON_DEPTH}")
    if isinstance(value, dict):
        for child in value.values():
            json_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            json_depth(child, depth + 1)
    return depth


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json_bytes(raw: bytes, source: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetError(f"invalid JSON in {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise AssetError(f"glTF root must be an object: {source}")
    json_depth(value)
    if (value.get("asset") or {}).get("version") != "2.0":
        raise AssetError(f"{source} is not glTF 2.0")
    return value


def load_glb(path: Path) -> tuple[dict[str, Any], bytes | None]:
    raw = path.read_bytes()
    if len(raw) > MAX_ASSET_BYTES:
        raise AssetError(f"asset exceeds {MAX_ASSET_BYTES} bytes: {path}")
    if len(raw) < 12:
        raise AssetError(f"truncated GLB header: {path}")
    magic, version, declared_length = struct.unpack_from("<4sII", raw, 0)
    if magic != GLB_MAGIC or version != 2 or declared_length != len(raw):
        raise AssetError(f"invalid GLB header: {path}")
    offset = 12
    json_chunk: bytes | None = None
    bin_chunk: bytes | None = None
    while offset < len(raw):
        if offset + 8 > len(raw):
            raise AssetError(f"truncated GLB chunk header: {path}")
        length, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        end = offset + length
        if end > len(raw):
            raise AssetError(f"truncated GLB chunk: {path}")
        chunk = raw[offset:end]
        offset = end
        if kind == GLB_JSON:
            if json_chunk is not None:
                raise AssetError(f"multiple GLB JSON chunks: {path}")
            json_chunk = chunk.rstrip(b" \t\r\n\x00")
        elif kind == GLB_BIN:
            if bin_chunk is not None:
                raise AssetError(f"multiple GLB BIN chunks: {path}")
            bin_chunk = chunk
    if json_chunk is None:
        raise AssetError(f"GLB has no JSON chunk: {path}")
    return load_json_bytes(json_chunk, str(path)), bin_chunk


def load_gltf(path: Path) -> tuple[dict[str, Any], list[bytes]]:
    if not path.is_file():
        raise AssetError(f"asset is absent: {path}")
    if path.stat().st_size > MAX_ASSET_BYTES:
        raise AssetError(f"asset exceeds {MAX_ASSET_BYTES} bytes: {path}")
    if path.suffix.lower() == ".glb":
        document, binary = load_glb(path)
    elif path.suffix.lower() == ".gltf":
        document = load_json_bytes(path.read_bytes(), str(path))
        binary = None
    else:
        raise AssetError(f"unsupported asset extension: {path.suffix}")

    buffers: list[bytes] = []
    for index, row in enumerate(document.get("buffers") or []):
        if not isinstance(row, dict):
            raise AssetError(f"buffer {index} must be an object")
        uri = row.get("uri")
        if uri is None:
            if index != 0 or binary is None:
                raise AssetError(f"buffer {index} has no URI or GLB BIN chunk")
            payload = binary[: int(row.get("byteLength", len(binary)))]
        elif isinstance(uri, str) and uri.startswith("data:"):
            try:
                header, encoded = uri.split(",", 1)
            except ValueError as exc:
                raise AssetError(f"malformed data URI in buffer {index}") from exc
            if ";base64" not in header:
                raise AssetError(f"only base64 data URIs are supported in buffer {index}")
            try:
                payload = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise AssetError(f"invalid base64 in buffer {index}") from exc
        elif isinstance(uri, str):
            target = (path.parent / uri).resolve()
            if path.parent.resolve() not in target.parents and target != path.parent.resolve():
                raise AssetError(f"buffer URI escapes the asset directory: {uri}")
            if not target.is_file() or target.stat().st_size > MAX_ASSET_BYTES:
                raise AssetError(f"external buffer is absent or oversized: {target}")
            payload = target.read_bytes()
        else:
            raise AssetError(f"buffer {index} URI must be a string")
        declared = int(row.get("byteLength", -1))
        if declared < 0 or len(payload) < declared:
            raise AssetError(f"buffer {index} is shorter than declared byteLength")
        buffers.append(payload)
    return document, buffers


def normalized_value(value: int | float, component_type: int, normalized: bool) -> float | int:
    if not normalized or component_type == 5126:
        return value
    _, _, signed, denominator = COMPONENTS[component_type]
    assert denominator is not None
    if signed:
        return max(float(value) / denominator, -1.0)
    return float(value) / denominator


def accessor_values(document: dict[str, Any], buffers: list[bytes], index: int) -> list[tuple[float | int, ...]]:
    accessors = document.get("accessors") or []
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        raise AssetError(f"invalid accessor index: {index}")
    accessor = accessors[index]
    if accessor.get("sparse") is not None:
        raise AssetError(f"sparse accessor {index} is outside the pilot verifier")
    if "bufferView" not in accessor:
        raise AssetError(f"accessor {index} has no bufferView")
    views = document.get("bufferViews") or []
    view_index = accessor["bufferView"]
    if not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise AssetError(f"accessor {index} has invalid bufferView")
    view = views[view_index]
    buffer_index = view.get("buffer")
    if not isinstance(buffer_index, int) or not 0 <= buffer_index < len(buffers):
        raise AssetError(f"bufferView {view_index} has invalid buffer")
    component_type = accessor.get("componentType")
    if component_type not in COMPONENTS:
        raise AssetError(f"accessor {index} has unsupported componentType {component_type}")
    accessor_type = accessor.get("type")
    width = TYPE_WIDTH.get(accessor_type)
    if width is None:
        raise AssetError(f"accessor {index} has unsupported type {accessor_type}")
    count = accessor.get("count")
    if not isinstance(count, int) or count < 0 or count > MAX_TRIANGLES * 3:
        raise AssetError(f"accessor {index} count is invalid")
    fmt, component_size, _, _ = COMPONENTS[component_type]
    element_size = component_size * width
    stride = view.get("byteStride", element_size)
    if not isinstance(stride, int) or stride < element_size:
        raise AssetError(f"accessor {index} has invalid stride")
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    payload = buffers[buffer_index]
    values: list[tuple[float | int, ...]] = []
    unpack = struct.Struct("<" + fmt * width)
    for item in range(count):
        start = offset + item * stride
        end = start + element_size
        if start < 0 or end > len(payload):
            raise AssetError(f"accessor {index} exceeds buffer bounds")
        raw = unpack.unpack_from(payload, start)
        values.append(tuple(normalized_value(v, component_type, bool(accessor.get("normalized"))) for v in raw))
    return values


def identity_matrix() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def multiply_matrix(a: list[float], b: list[float]) -> list[float]:
    result = [0.0] * 16
    for column in range(4):
        for row in range(4):
            result[column * 4 + row] = sum(a[k * 4 + row] * b[column * 4 + k] for k in range(4))
    return result


def node_matrix(node: dict[str, Any]) -> list[float]:
    if "matrix" in node:
        matrix = node["matrix"]
        if not isinstance(matrix, list) or len(matrix) != 16:
            raise AssetError("node matrix must contain 16 numbers")
        return [float(value) for value in matrix]

    translation = node.get("translation", [0.0, 0.0, 0.0])
    rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    scale = node.get("scale", [1.0, 1.0, 1.0])
    if len(translation) != 3 or len(rotation) != 4 or len(scale) != 3:
        raise AssetError("node TRS dimensions are invalid")
    x, y, z, w = (float(value) for value in rotation)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0:
        raise AssetError("node quaternion has zero length")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    sx, sy, sz = (float(value) for value in scale)
    tx, ty, tz = (float(value) for value in translation)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        (1 - 2 * (yy + zz)) * sx,
        (2 * (xy + wz)) * sx,
        (2 * (xz - wy)) * sx,
        0.0,
        (2 * (xy - wz)) * sy,
        (1 - 2 * (xx + zz)) * sy,
        (2 * (yz + wx)) * sy,
        0.0,
        (2 * (xz + wy)) * sz,
        (2 * (yz - wx)) * sz,
        (1 - 2 * (xx + yy)) * sz,
        0.0,
        tx,
        ty,
        tz,
        1.0,
    ]


def transform_point(matrix: list[float], point: tuple[float | int, ...]) -> tuple[float, float, float]:
    if len(point) < 3:
        raise AssetError("POSITION accessor is not VEC3")
    x, y, z = (float(point[i]) for i in range(3))
    w = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15]
    if abs(w) < 1e-12:
        raise AssetError("node transform produced zero homogeneous coordinate")
    return (
        (matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12]) / w,
        (matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13]) / w,
        (matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14]) / w,
    )


def round_point(point: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(0.0 if abs(value) < 0.0000005 else round(value, 6) for value in point)  # type: ignore[return-value]


def semantic_report(path: Path) -> dict[str, Any]:
    document, buffers = load_gltf(path)
    nodes = document.get("nodes") or []
    meshes = document.get("meshes") or []
    scenes = document.get("scenes") or []
    if len(nodes) > MAX_NODES:
        raise AssetError(f"asset exceeds {MAX_NODES} nodes")
    if not isinstance(scenes, list) or not scenes:
        raise AssetError("asset has no scene")

    scene_reports: list[dict[str, Any]] = []
    total_triangles = 0
    all_points: list[tuple[float, float, float]] = []
    named_nodes: dict[str, list[float]] = {}

    def visit(node_index: int, parent: list[float], active: set[int], triangles: list[str]) -> None:
        nonlocal total_triangles
        if not isinstance(node_index, int) or not 0 <= node_index < len(nodes):
            raise AssetError(f"scene references invalid node {node_index}")
        if node_index in active:
            raise AssetError(f"node cycle detected at {node_index}")
        node = nodes[node_index]
        world = multiply_matrix(parent, node_matrix(node))
        name = node.get("name")
        if isinstance(name, str) and name:
            matrix = [0.0 if abs(value) < 0.0000005 else round(value, 6) for value in world]
            prior = named_nodes.get(name)
            if prior is not None and prior != matrix:
                raise AssetError(f"named node {name!r} appears with conflicting transforms")
            named_nodes[name] = matrix
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            if not isinstance(mesh_index, int) or not 0 <= mesh_index < len(meshes):
                raise AssetError(f"node {node_index} references invalid mesh")
            mesh = meshes[mesh_index]
            for primitive_index, primitive in enumerate(mesh.get("primitives") or []):
                mode = primitive.get("mode", 4)
                if mode != 4:
                    raise AssetError(f"mesh {mesh_index} primitive {primitive_index} is not TRIANGLES")
                position_index = (primitive.get("attributes") or {}).get("POSITION")
                if position_index is None:
                    raise AssetError(f"mesh {mesh_index} primitive {primitive_index} has no POSITION")
                positions = accessor_values(document, buffers, position_index)
                if primitive.get("indices") is None:
                    indices = list(range(len(positions)))
                else:
                    index_values = accessor_values(document, buffers, primitive["indices"])
                    if any(len(value) != 1 for value in index_values):
                        raise AssetError("index accessor is not SCALAR")
                    indices = [int(value[0]) for value in index_values]
                if len(indices) % 3:
                    raise AssetError("triangle index count is not divisible by three")
                total_triangles += len(indices) // 3
                if total_triangles > MAX_TRIANGLES:
                    raise AssetError(f"asset exceeds {MAX_TRIANGLES} triangles")
                transformed = [round_point(transform_point(world, position)) for position in positions]
                all_points.extend(transformed)
                for offset in range(0, len(indices), 3):
                    ids = indices[offset:offset + 3]
                    if any(index < 0 or index >= len(transformed) for index in ids):
                        raise AssetError("triangle index exceeds POSITION accessor")
                    triangle = sorted(transformed[index] for index in ids)
                    triangles.append("|".join(",".join(f"{value:.6f}" for value in point) for point in triangle))
        active.add(node_index)
        for child in node.get("children") or []:
            visit(child, world, active, triangles)
        active.remove(node_index)

    for scene_index, scene in enumerate(scenes):
        triangles: list[str] = []
        for node_index in scene.get("nodes") or []:
            visit(node_index, identity_matrix(), set(), triangles)
        triangles.sort()
        scene_reports.append(
            {
                "index": scene_index,
                "name": scene.get("name") or "",
                "triangleCount": len(triangles),
                "geometryDigest": sha256_bytes(canonical_bytes(triangles)),
            }
        )

    if not all_points:
        raise AssetError("asset contains no reachable triangle positions")
    bounds = {
        "min": [min(point[axis] for point in all_points) for axis in range(3)],
        "max": [max(point[axis] for point in all_points) for axis in range(3)],
    }
    semantic = {
        "format": "axm-asset-semantics/1",
        "sceneCount": len(scene_reports),
        "triangleCount": total_triangles,
        "bounds": bounds,
        "namedNodes": {name: named_nodes[name] for name in sorted(named_nodes)},
        "scenes": scene_reports,
    }
    semantic["semanticDigest"] = "assetsem1_" + sha256_bytes(canonical_bytes(semantic))
    return semantic


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", type=Path)
    parser.add_argument("--json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = semantic_report(args.asset)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: {args.asset} -> {result['semanticDigest']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
