"""
GDML Generator — converts meshed (VTK) geometry parts + materials into a valid
GDML XML file suitable for Geant4 / SERad simulation.

References
----------
- sourcecode/GenGDML/GenGDML.cpp   (original C++ implementation)
- refergdml/tessellated.gdml       (GDML template using <tessellated> solids)
"""

import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, List, Optional, Tuple

import vtk

from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.TopoDS import TopoDS_Shape

from core.g_data_node import GDataNode
from core.materials_lib import MaterialsLib, CompoundMaterial, MixtureMaterial


def _make_safe_name(raw: str) -> str:
    """Replace characters unsafe for GDML attribute values."""
    return raw.replace(":", "_").replace("/", "_").replace("\\", "_").replace(" ", "_")


def compute_global_bbox(solid_nodes: List[GDataNode]) -> Tuple[float, float, float]:
    """Compute the axis-aligned bounding box spanning all solid shapes.

    Returns (max_edge, _, _) where max_edge is the largest span of the
    entire assembly.  All three values are set to max_edge for convenience.
    """
    bbox = Bnd_Box()
    for node in solid_nodes:
        shape = node.shape
        if shape is not None and not shape.IsNull():
            brepbndlib.Add(shape, bbox)

    if bbox.IsVoid():
        return (10.0, 10.0, 10.0)

    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    dx = xmax - xmin
    dy = ymax - ymin
    dz = zmax - zmin
    max_edge = max(dx, dy, dz)
    return (max_edge, max_edge, max_edge)


def _read_vtk_triangles(
    vtk_path: str,
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    """Read an ASCII VTK UnstructuredGrid file and return surface triangles.

    Returns
    -------
    vertices   : list of (x, y, z)
    triangles  : list of (i, j, k)  — zero-based vertex indices
    """
    reader = vtk.vtkUnstructuredGridReader()
    reader.SetFileName(vtk_path)
    reader.Update()

    geo = vtk.vtkGeometryFilter()
    geo.SetInputData(reader.GetOutput())
    geo.Update()

    poly = geo.GetOutput()

    # vertices
    pts = poly.GetPoints()
    n_pts = pts.GetNumberOfPoints() if pts else 0
    vertices: List[Tuple[float, float, float]] = []
    for i in range(n_pts):
        p = pts.GetPoint(i)
        vertices.append((float(p[0]), float(p[1]), float(p[2])))

    # triangles
    polys = poly.GetPolys()
    triangles: List[Tuple[int, int, int]] = []
    if polys:
        id_list = vtk.vtkIdList()
        polys.InitTraversal()
        while polys.GetNextCell(id_list):
            if id_list.GetNumberOfIds() == 3:
                triangles.append((
                    int(id_list.GetId(0)),
                    int(id_list.GetId(1)),
                    int(id_list.GetId(2)),
                ))

    return vertices, triangles


def _material_to_gdml(mat_lib: MaterialsLib, mat_name: str) -> Optional[ET.Element]:
    """Look up *mat_name* and return a GDML <material> or <element> element.

    Returns None for NIST / unknown materials — caller creates a density stub.
    """
    if not mat_name or mat_name.startswith("G4_"):
        return None

    # Custom element
    for ele in mat_lib.get_all_custom_elements():
        if ele.name == mat_name or ele.symbol == mat_name:
            elem = ET.Element("element", {
                "name": ele.name,
                "formula": ele.symbol,
                "Z": str(int(ele.number)),
            })
            ET.SubElement(elem, "atom", {"value": str(ele.quality)})
            return elem

    # Compound
    for mat in mat_lib.get_all_compounds():
        if mat.mat_name == mat_name:
            return _compound_to_gdml(mat)

    # Mixture
    for mat in mat_lib.get_all_mixtures():
        if mat.mat_name == mat_name:
            return _mixture_to_gdml(mat)

    return None


def _compound_to_gdml(mat: CompoundMaterial) -> ET.Element:
    """CompoundMaterial → GDML <material>."""
    me = ET.Element("material", {"name": mat.mat_name})
    ET.SubElement(me, "D", {"value": f"{mat.density:.4f}"})
    for item in mat.items:
        ET.SubElement(me, "composite", {
            "n": str(item.ratio),
            "ref": item.element_name,
        })
    return me


def _mixture_to_gdml(mat: MixtureMaterial) -> ET.Element:
    """MixtureMaterial → GDML <material>."""
    me = ET.Element("material", {"name": mat.mat_name})
    ET.SubElement(me, "D", {"value": f"{mat.density:.4f}"})
    for item in mat.items:
        ET.SubElement(me, "fraction", {
            "n": f"{item.ratio:.4f}",
            "ref": item.element_name,
        })
    return me


def generate_gdml(
    solid_nodes: List[GDataNode],
    meshed_nodes: Dict[str, str],
    mat_lib: MaterialsLib,
    output_path: str,
    world_factor: float = 5.0,
    world_material_name: str = "G4_Galactic",
) -> bool:
    """Generate a complete GDML file covering all meshed solid parts.

    Parameters
    ----------
    solid_nodes : list of GDataNode
        All solid leaf nodes in the geometry tree.
    meshed_nodes : dict (entry_id -> vtk_path)
        Mapping from node entry_id to its VTK mesh file path.
    mat_lib : MaterialsLib
        Material library for material lookups.
    output_path : str
        Full path for the output .gdml file (overwritten if exists).
    world_factor : float
        Multiplier applied to the global bounding-box max-edge to obtain
        the world-box half-size.
    Returns
    -------
    bool
        True on success.
    """
    # ---- 1. parts that have a mesh file ----
    part_list: List[Tuple[GDataNode, str]] = []
    for node in solid_nodes:
        vtk_path = meshed_nodes.get(node.entry_id, "")
        if vtk_path and os.path.isfile(vtk_path):
            part_list.append((node, vtk_path))

    if not part_list:
        return False

    # ---- 2. world box ----
    max_edge, _, _ = compute_global_bbox(solid_nodes)
    half = max_edge * world_factor / 2.0

    # ---- 3. collect used materials (deduplicated) ----
    # NIST globals (G4_*) are built into Geant4 and must NOT appear in
    # <materials>.  Only local / custom materials (those returned by
    # _material_to_gdml) go there.
    used_materials: Dict[str, ET.Element] = {}
    mat_order: List[str] = []

    def _ensure_local_mat(name: str):
        if name not in used_materials:
            me = _material_to_gdml(mat_lib, name)
            if me is not None:          # local material → include in <materials>
                used_materials[name] = me
                mat_order.append(name)

    for node, _ in part_list:
        mn = node.material_name.strip() if node.material_name else ""
        if not mn:
            mn = "G4_Galactic"
        _ensure_local_mat(mn)

    # World material: if it's a local material, include it in <materials>;
    # if it's NIST (G4_*), _ensure_local_mat skips it automatically.
    _ensure_local_mat(world_material_name)

    # ---- 4. build XML ----
    gdml = ET.Element("gdml", {
        "xmlns:gdml": "http://cern.ch/2001/Schemas/GDML",
        "xmlns:xsi" : "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:noNamespaceSchemaLocation" : "gdml.xsd",
    })

    define_elem = ET.SubElement(gdml, "define")

    materials_elem = ET.SubElement(gdml, "materials")
    for mn in mat_order:
        materials_elem.append(used_materials[mn])

    solids_elem = ET.SubElement(gdml, "solids")

    # World box
    ET.SubElement(solids_elem, "box", {
        "lunit": "mm",
        "name": "WorldBox",
        "x": f"{half * 2:.6f}",
        "y": f"{half * 2:.6f}",
        "z": f"{half * 2:.6f}",
    })

    # Part solids
    part_info: List[Tuple[str, str, str]] = []  # (safe_name, vol_ref, mat_ref)
    name_counter: Dict[str, int] = {}

    for node, vtk_path in part_list:
        base = _make_safe_name(node.name) if node.name else "Part"
        name_counter.setdefault(base, 0)
        name_counter[base] += 1
        safe = f"{base}_{name_counter[base]}" if name_counter[base] > 1 else base
        safe = _make_safe_name(safe)

        verts, tris = _read_vtk_triangles(vtk_path)
        if not verts or not tris:
            continue

        # Positions
        for vi, (vx, vy, vz) in enumerate(verts):
            ET.SubElement(define_elem, "position", {
                "name": f"{safe}_v{vi}",
                "unit": "mm",
                "x": f"{vx:.6f}",
                "y": f"{vy:.6f}",
                "z": f"{vz:.6f}",
            })

        # Tessellated
        tess = ET.SubElement(solids_elem, "tessellated", {"name": safe})
        for i1, i2, i3 in tris:
            ET.SubElement(tess, "triangular", {
                "vertex1": f"{safe}_v{i1}",
                "vertex2": f"{safe}_v{i2}",
                "vertex3": f"{safe}_v{i3}",
                "type": "ABSOLUTE",
            })

        mn = node.material_name.strip() if node.material_name else "G4_Galactic"
        part_info.append((safe, f"{safe}_vol", mn))

    # ---- structure ----
    struct_elem = ET.SubElement(gdml, "structure")

    for safe, vol_name, mat_name in part_info:
        vol = ET.SubElement(struct_elem, "volume", {"name": vol_name})
        ET.SubElement(vol, "materialref", {"ref": mat_name})
        ET.SubElement(vol, "solidref", {"ref": safe})

    world_vol = ET.SubElement(struct_elem, "volume", {"name": "worldVOL"})
    ET.SubElement(world_vol, "materialref", {"ref": world_material_name})
    ET.SubElement(world_vol, "solidref", {"ref": "WorldBox"})
    for safe, vol_name, _ in part_info:
        pv = ET.SubElement(world_vol, "physvol")
        ET.SubElement(pv, "volumeref", {"ref": vol_name})
        #ET.SubElement(pv, "position", {   "name": f"{safe}_pos",  "unit": "mm", "x": "0", "y": "0", "z": "0",})

    # ---- setup ----
    setup_el = ET.SubElement(gdml, "setup", {"name": "Default", "version": "1.0"})
    ET.SubElement(setup_el, "world", {"ref": "worldVOL"})

    # ---- 5. write file ----
    try:
        rough = ET.tostring(gdml, encoding="unicode")
        pretty = minidom.parseString(rough).toprettyxml(indent="  ")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(pretty)
        return True
    except Exception:
        return False
