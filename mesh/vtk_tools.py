"""
vtk_tools.py -- VTK I/O and "reassignment" needed by assembly conformal meshing.

In assembly mode gmsh writes **one single** VTK (all solids meshed in the same
session), while GDML requires one <tessellated> per solid, so every triangle has
to be assigned back to its original solid.

This module is a port of exampleSTEP/merge_demo/tools/{report.py,make_gdml.py}.
Two pitfalls were already hit there (see merge_demo/README.md):

Pitfall 1: the ownership test must not use the "triangle centroid".
    For a chord triangle on a cylindrical face, all three vertices lie on the
    r=5 cylinder, but the centroid falls inside the chord plane (r<5), so its
    distance to that cylinder is 5-r instead of 0. Using the centroid drops the
    facets on bolt/hole-wall cylindrical contact faces; measured on 18 solids,
    17 of them immediately ended up with open edges.
    Correct test: **all three vertices** lie on some solid's boundary
    (distance to that solid <= tol).

Pitfall 2: the winding order has to be recomputed.
    gmsh assigns one fixed winding per **face**. A contact face is one face
    shared by two solids, so it points outward for one side and inward for the
    other. Copying it as-is makes G4TessellatedSolid report a pile of false
    Overlaps (measured: solid11 "overlaps" solid10 by 5.1 mm) even though the
    original STEP solids have 0 volumetric overlap. See orient_outward().

Note: a facet on a contact face has distance 0 to both boundaries, so **both
sides get it** -- which is exactly the conformal interface Geant4 needs (both
sides receive the same batch of triangles with identical vertex coordinates).
"""

import math
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.gp import gp_Pnt
from OCC.Core.TopoDS import TopoDS_Shape

Point = Tuple[float, float, float]
Tri = Tuple[int, int, int]
Mesh = Tuple[List[Point], List[Tri]]


# ────────────────────────── basic geometry ──────────────────────────


def bbox_of(shape: TopoDS_Shape) -> Tuple[float, float, float, float, float, float]:
    """Return (xmin, ymin, zmin, xmax, ymax, zmax)."""
    b = Bnd_Box()
    brepbndlib.Add(shape, b)
    return b.Get()


def boxes_touch(a, b, tol: float) -> bool:
    """Whether the three axis intervals overlap within tol -- coarse contact pre-filter."""
    return (a[0] - tol <= b[3] and a[3] + tol >= b[0] and
            a[1] - tol <= b[4] and a[4] + tol >= b[1] and
            a[2] - tol <= b[5] and a[5] + tol >= b[2])


def min_distance(sa: TopoDS_Shape, sb: TopoDS_Shape) -> float:
    """Minimum distance between two solids; returns inf on failure."""
    d = BRepExtrema_DistShapeShape(sa, sb)
    d.Perform()
    if not d.IsDone():
        return float("inf")
    return d.Value()


def mesh_diagonal(pts: Sequence[Point]) -> float:
    if not pts:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


# ────────────────────────── VTK I/O ──────────────────────────


def read_vtk(path: str) -> Mesh:
    """Read a legacy ASCII VTK (UNSTRUCTURED_GRID), keeping only type 5 (triangles).

    Deliberately does not use the vtk package: no need to pull in another
    dependency inside the reassignment thread, and gmsh writes plain ASCII
    legacy format anyway.
    """
    pts: List[Point] = []
    cells: List[List[int]] = []
    types: List[int] = []
    mode, left = None, 0

    with open(path, "r", errors="replace") as f:
        for line in f:
            t = line.split()
            if not t:
                continue
            if mode:
                if mode == "P":
                    for k in range(0, len(t) - 2, 3):
                        pts.append((float(t[k]), float(t[k + 1]), float(t[k + 2])))
                    left -= len(t) // 3
                elif mode == "C":
                    cells.append([int(x) for x in t[1:]])
                    left -= 1
                else:
                    types.extend(int(x) for x in t)
                    left -= len(t)
                if left <= 0:
                    mode = None
                continue
            h = t[0].upper()
            if h == "POINTS":
                mode, left = "P", int(t[1])
            elif h == "CELLS":
                mode, left = "C", int(t[1])
            elif h == "CELL_TYPES":
                mode, left = "T", int(t[1])

    tris = [tuple(c[:3]) for c, ty in zip(cells, types) if ty == 5 and len(c) >= 3]
    return pts, tris


def write_vtk(path: str, pts: Sequence[Point], tris: Sequence[Tri],
              title: str = "cad2gdml") -> None:
    """Write a legacy ASCII VTK (UNSTRUCTURED_GRID + CELL_TYPES=5).

    It must be UNSTRUCTURED_GRID: core/gdml_generator.py uses
    vtkUnstructuredGridReader + vtkGeometryFilter.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("# vtk DataFile Version 3.0\n")
        f.write(f"{title}\n")
        f.write("ASCII\n")
        f.write("DATASET UNSTRUCTURED_GRID\n")
        f.write(f"POINTS {len(pts)} float\n")
        for x, y, z in pts:
            f.write(f"{x:.9g} {y:.9g} {z:.9g}\n")
        f.write(f"CELLS {len(tris)} {len(tris) * 4}\n")
        for a, b, c in tris:
            f.write(f"3 {a} {b} {c}\n")
        f.write(f"CELL_TYPES {len(tris)}\n")
        for _ in tris:
            f.write("5\n")


# ──────────────────── reassignment: triangle -> solid ────────────────────


def assign_owners(
    pts: Sequence[Point],
    tris: Sequence[Tri],
    solids: Sequence[TopoDS_Shape],
    boxes: Sequence[tuple],
    tol: float,
    progress_cb=None,
    cancel_cb=None,
) -> List[Tuple[int, ...]]:
    """owners[i] = indices of the solids owning triangle i (ascending tuple).

    Test: a triangle belongs to a solid when **all three vertices** lie on that
    solid's boundary (distance <= tol). Solids on both sides of a contact face
    match the same triangle -- that is exactly the conformal interface.

    Cost: every distinct vertex requires one point-to-BREP distance per bbox
    candidate solid, measured at about 0.5 ms each. The 18-solid demo with a few
    thousand vertices takes about 10 s; a mesh with 100k facets needs minute-level
    time, hence the cancel support.
    """
    cache: Dict[int, Tuple[int, ...]] = {}

    def hits_of_vertex(vi: int) -> Tuple[int, ...]:
        if vi in cache:
            return cache[vi]
        x, y, z = pts[vi]
        hits, vertex = [], None
        for i, (x0, y0, z0, x1, y1, z1) in enumerate(boxes):
            if not (x0 - tol <= x <= x1 + tol and
                    y0 - tol <= y <= y1 + tol and
                    z0 - tol <= z <= z1 + tol):
                continue
            if vertex is None:
                vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Vertex()
            if BRepExtrema_DistShapeShape(vertex, solids[i]).Value() <= tol:
                hits.append(i)
        res = tuple(sorted(hits))
        cache[vi] = res
        return res

    owners: List[Tuple[int, ...]] = []
    total = max(1, len(tris))
    step = max(1, total // 100)
    for k, (a, b, c) in enumerate(tris):
        ha = hits_of_vertex(a)
        if not ha:
            owners.append(())
        else:
            owners.append(tuple(sorted(set(ha) & set(hits_of_vertex(b))
                                       & set(hits_of_vertex(c)))))
        if progress_cb and k % step == 0:
            progress_cb(k, total)
        if cancel_cb and k % step == 0 and cancel_cb():
            raise InterruptedError("reassignment cancelled")
    return owners


def orient_outward(verts: Sequence[Point], tris: Sequence[Tri]) -> List[Tri]:
    """Make the winding of a closed facet set uniformly "counter-clockwise seen
    from outside".

    1. Propagation: in a closed manifold every edge is shared by exactly 2
       triangles, and when their winding agrees the two triangles traverse that
       edge in opposite directions. A BFS over this rule fixes every triangle's
       flip bit.
    2. Orientation: compute the signed volume (1/6)Σ a·(b×c) of each connected
       component. A negative value means the whole block points inward, so flip
       it as a whole.

    Step 2 is a single global decision that does not depend on eps, which is more
    robust than "offset a little along the normal and classify inside/outside".
    """
    edge = defaultdict(list)
    for ti, (a, b, c) in enumerate(tris):
        for p, q in ((a, b), (b, c), (c, a)):
            edge[(min(p, q), max(p, q))].append((ti, 1 if p < q else -1))

    flip: List[Optional[bool]] = [None] * len(tris)
    comps: List[List[int]] = []
    for seed in range(len(tris)):
        if flip[seed] is not None:
            continue
        flip[seed] = False
        comp, stack = [seed], [seed]
        while stack:
            ti = stack.pop()
            a, b, c = tris[ti]
            for p, q in ((a, b), (b, c), (c, a)):
                si = 1 if p < q else -1
                for tj, sj in edge[(min(p, q), max(p, q))]:
                    if tj == ti:
                        continue
                    if flip[tj] is None:
                        flip[tj] = flip[ti] ^ (si == sj)
                        comp.append(tj)
                        stack.append(tj)
        comps.append(comp)

    out = [(a, c, b) if flip[ti] else (a, b, c)
           for ti, (a, b, c) in enumerate(tris)]

    for comp in comps:
        v6 = 0.0
        for ti in comp:
            a, b, c = out[ti]
            ax, ay, az = verts[a]
            bx, by, bz = verts[b]
            cx, cy, cz = verts[c]
            v6 += (ax * (by * cz - bz * cy)
                   - ay * (bx * cz - bz * cx)
                   + az * (bx * cy - by * cx))
        if v6 < 0.0:
            for ti in comp:
                a, b, c = out[ti]
                out[ti] = (a, c, b)
    return out


def check_closed(tris: Sequence[Tri]) -> Tuple[int, int]:
    """Return (open edges, total edges). Closed means every edge is shared by
    exactly 2 triangles."""
    cnt = defaultdict(int)
    for a, b, c in tris:
        for p, q in ((a, b), (b, c), (c, a)):
            cnt[(min(p, q), max(p, q))] += 1
    open_edges = sum(1 for k in cnt if cnt[k] != 2)
    return open_edges, len(cnt)


def build_parts(
    pts: Sequence[Point],
    tris: Sequence[Tri],
    owners: Sequence[Tuple[int, ...]],
    names: Sequence[str],
) -> List[Tuple[str, List[Point], List[Tri]]]:
    """Split the assembly mesh into one local mesh per solid by ownership, and
    fix the winding."""
    parts = []
    for si, nm in enumerate(names):
        sel = [t for t, ow in zip(tris, owners) if si in ow]
        if not sel:
            parts.append((nm, [], []))
            continue
        used = sorted({v for t in sel for v in t})
        remap = {v: k for k, v in enumerate(used)}
        verts = [pts[v] for v in used]
        local = [(remap[a], remap[b], remap[c]) for a, b, c in sel]
        parts.append((nm, verts, orient_outward(verts, local)))
    return parts


# ──────────────────── coincident facet detection ────────────────────


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _inside(p, a, b, c, tol) -> bool:
    """Whether point p lies on triangle abc (including interior, tolerance tol)."""
    n = _cross(_sub(b, a), _sub(c, a))
    nn = _dot(n, n)
    if nn < 1e-18:
        return False
    if abs(_dot(_sub(p, a), n) / math.sqrt(nn)) > tol:
        return False
    w = (_dot(_cross(_sub(b, p), _sub(c, p)), n) / nn,
         _dot(_cross(_sub(c, p), _sub(a, p)), n) / nn,
         _dot(_cross(_sub(a, p), _sub(b, p)), n) / nn)
    return min(w) > 1e-9


def count_coincident_facets(
    mesh_a: Mesh,
    mesh_b: Mesh,
    tol: float,
    budget: int = 400_000,
) -> Tuple[int, bool]:
    """Count triangle pairs between two meshes that are "coincident in space but
    unrelated in topology".

    This is the root cause of the Geant4 navigation errors and the direct evidence
    for conformality. A uniform grid hash keeps candidate pairs near the contact
    face, avoiding O(N^2). Returns (coincident pairs, truncated by budget).
    """
    pa, ta = mesh_a
    pb, tb = mesh_b
    if not ta or not tb:
        return 0, False

    def tri_bbox(p, t):
        a, b, c = p[t[0]], p[t[1]], p[t[2]]
        return (min(a[0], b[0], c[0]), min(a[1], b[1], c[1]), min(a[2], b[2], c[2]),
                max(a[0], b[0], c[0]), max(a[1], b[1], c[1]), max(a[2], b[2], c[2]))

    def centroid(p, t):
        a, b, c = p[t[0]], p[t[1]], p[t[2]]
        return ((a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3,
                (a[2] + b[2] + c[2]) / 3)

    bba = [tri_bbox(pa, t) for t in ta]
    bbb = [tri_bbox(pb, t) for t in tb]

    # Cell size = average triangle scale, so a triangle lands in only a few cells
    spans = []
    for bb in bba[:200] + bbb[:200]:
        spans.append(max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]))
    cell = max(sum(spans) / len(spans) if spans else 1.0, tol * 10, 1e-6)

    def cells_of(bb):
        i0 = int(math.floor(bb[0] / cell)); i1 = int(math.floor(bb[3] / cell))
        j0 = int(math.floor(bb[1] / cell)); j1 = int(math.floor(bb[4] / cell))
        k0 = int(math.floor(bb[2] / cell)); k1 = int(math.floor(bb[5] / cell))
        # Oversized triangle collapses to a single cell key to avoid an explosion
        if (i1 - i0) * (j1 - j0) * (k1 - k0) > 4096:
            return [("big", i0, j0, k0)]
        return [(i, j, k) for i in range(i0, i1 + 1)
                for j in range(j0, j1 + 1) for k in range(k0, k1 + 1)]

    bucket_b = defaultdict(list)
    for ti, bb in enumerate(bbb):
        for key in cells_of(bb):
            bucket_b[key].append(ti)

    seen = set()
    count = 0
    tested = 0
    truncated = False

    for ai, bb in enumerate(bba):
        ca = centroid(pa, ta[ai])
        cand: List[int] = []
        for key in cells_of(bb):
            cand.extend(bucket_b.get(key, ()))
        for bj in set(cand):
            pair = (ai, bj)
            if pair in seen:
                continue
            seen.add(pair)
            tested += 1
            if tested > budget:
                truncated = True
                break
            if _inside(ca, pb[tb[bj][0]], pb[tb[bj][1]], pb[tb[bj][2]], tol) or \
               _inside(centroid(pb, tb[bj]), pa[ta[ai][0]], pa[ta[ai][1]],
                       pa[ta[ai][2]], tol):
                count += 1
        if truncated:
            break

    return count, truncated
