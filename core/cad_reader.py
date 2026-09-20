"""
CADReader - Multi-format CAD geometry file reader.

Supports STEP (.step/.stp), IGES (.igs/.iges), BREP (.brep), and STL (.stl).
All formats are converted to TopoDS_Shape and organized into the same
GDataNode tree structure for downstream processing.
"""

from typing import List, Optional, Callable
from pathlib import Path

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IGESControl import IGESControl_Reader
from OCC.Core.StlAPI import StlAPI_Reader
from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Iterator
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_COMPOUND, TopAbs_FACE, TopAbs_EDGE
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

from .g_data_node import GDataNode, NodeType


class CADReader:
    """
    Multi-format CAD file reader.

    Supports STEP, IGES, BREP, and STL formats. Dispatches to the correct
    OCC reader based on file extension and returns a uniform GDataNode tree.
    """

    # Supported extensions mapped to human-readable names
    FORMATS = {
        ".step": "STEP",
        ".stp": "STEP",
        ".igs": "IGES",
        ".iges": "IGES",
        ".brep": "BREP",
        ".stl": "STL",
    }

    def __init__(self):
        self._file_paths: List[str] = []

    def set_file_list(self, file_paths: List[str]):
        """Set the list of files to read."""
        self._file_paths = file_paths

    def read_file(self, file_path: str, error_info: List[str],
                  progress_callback=None) -> Optional[GDataNode]:
        """
        Read a single CAD file. Format is auto-detected from the extension.

        Args:
            file_path: Path to the CAD file.
            error_info: List to append error messages to.
            progress_callback: Optional callable(current_step, total_steps)
                               called after each root/shape transfer.

        Returns:
            File node (with all child geometry nodes), or None on failure.
        """
        ext = Path(file_path).suffix.lower()
        fmt = self.FORMATS.get(ext)
        if fmt is None:
            error_info.append(f"Unsupported format: {file_path}")
            return None

        try:
            if fmt == "STEP":
                return self._read_step(file_path, error_info, progress_callback)
            elif fmt == "IGES":
                return self._read_iges(file_path, error_info, progress_callback)
            elif fmt == "BREP":
                return self._read_brep(file_path, error_info, progress_callback)
            elif fmt == "STL":
                return self._read_stl(file_path, error_info, progress_callback)
        except Exception as e:
            error_info.append(f"Error reading {file_path}: {str(e)}")
            return None

        return None

    # ── Format-specific readers ────────────────────────────────────────

    def _read_step(self, file_path: str, error_info: List[str],
                   progress_callback=None) -> Optional[GDataNode]:
        """Read a STEP (.step/.stp) file using STEPControl_Reader.

        Uses TransferRoots() (bulk transfer) for maximum speed — this is much
        faster than per-root TransferRoot(i) + per-leaf AIS_Shape creation
        inside the callback.  After building the tree, the final callback
        reports the total leaf count to the caller.
        """
        reader = STEPControl_Reader()
        if reader.ReadFile(file_path) != 1:  # IFSelect_RetDone
            error_info.append(f"Failed to read STEP file: {file_path}")
            return None

        total_roots = reader.NbRootsForTransfer()
        if total_roots == 0:
            error_info.append(f"No transferable roots in STEP file: {file_path}")
            return None

        file_name = Path(file_path).stem
        file_node = GDataNode(NodeType.STEP_FILE, file_name)

        # Bulk transfer — one fast call, much cheaper than per-root loops
        reader.TransferRoots()
        nb_shapes = reader.NbShapes()
        for i in range(1, nb_shapes + 1):
            shape = reader.Shape(i)
            if shape.IsNull():
                continue
            self._add_shape_to_node(shape, file_node, file_name, i)
            # Keep the caller's progress box alive while the tree is built:
            # this loop is where most of the wall-clock time goes on big files.
            if progress_callback is not None:
                progress_callback(i, nb_shapes)

        # Report progress once with all leaf nodes for rendering
        if progress_callback is not None:
            leaves = file_node.get_leaf_nodes()
            progress_callback(1, 1, leaves)

        return file_node

    def _read_iges(self, file_path: str, error_info: List[str],
                   progress_callback=None) -> Optional[GDataNode]:
        """Read an IGES (.igs/.iges) file."""
        reader = IGESControl_Reader()
        if reader.ReadFile(file_path) != 1:  # IFSelect_RetDone
            error_info.append(f"Failed to read IGES file: {file_path}")
            return None
        reader.TransferRoots()
        file_node = self._build_multi_shape_node(file_path, reader.NbShapes(),
                                                 lambda i: reader.Shape(i))
        if progress_callback is not None and file_node is not None:
            progress_callback(1, 1, file_node.get_leaf_nodes())
        return file_node

    def _read_brep(self, file_path: str, error_info: List[str],
                   progress_callback=None) -> Optional[GDataNode]:
        """Read a BREP (.brep) file.

        A BREP file contains a single TopoDS_Shape which may be a COMPOUND
        with multiple SOLIDs. It goes through _add_shape_to_node to expand
        the hierarchy (same as STEP/IGES), so each solid appears as a
        separate tree node.
        """
        shape = TopoDS_Shape()
        builder = BRep_Builder()
        if not breptools.Read(shape, file_path, builder):
            error_info.append(f"Failed to read BREP file: {file_path}")
            return None
        file_name = Path(file_path).stem
        file_node = GDataNode(NodeType.STEP_FILE, file_name)
        if not shape.IsNull():
            self._add_shape_to_node(shape, file_node, file_name, 1)
        if progress_callback is not None and file_node is not None:
            progress_callback(1, 1, file_node.get_leaf_nodes())
        return file_node

    def _read_stl(self, file_path: str, error_info: List[str],
                  progress_callback=None) -> Optional[GDataNode]:
        """Read an STL (.stl) file.

        STL is a mesh format with no B-Rep topology — the entire file
        represents a single triangle mesh (all parts merged into one shell).
        It is wrapped as a single child node.
        """
        shape = TopoDS_Shape()
        reader = StlAPI_Reader()
        if not reader.Read(shape, file_path):
            error_info.append(f"Failed to read STL file: {file_path}")
            return None
        file_node = self._build_single_shape_node(file_path, shape)
        if progress_callback is not None and file_node is not None:
            progress_callback(1, 1, file_node.get_leaf_nodes())
        return file_node

    # ── Tree builders ─────────────────────────────────────────────────

    def _build_multi_shape_node(self, file_path: str, shape_count: int,
                                get_shape_fn) -> GDataNode:
        """
        Build a file node with multiple child shapes (STEP, IGES).

        Each root-level shape from the reader becomes a child tree
        (potentially a compound with sub-shapes), using the same recursive
        _add_shape_to_node logic as the original STEP reader.
        """
        file_name = Path(file_path).stem
        file_node = GDataNode(NodeType.STEP_FILE, file_name)

        for i in range(1, shape_count + 1):
            shape = get_shape_fn(i)
            if shape.IsNull():
                continue
            self._add_shape_to_node(shape, file_node, file_name, i)

        return file_node

    def _build_single_shape_node(self, file_path: str,
                                 shape: TopoDS_Shape) -> GDataNode:
        """
        Build a file node from a single shape (BREP, STL).

        The single shape is wrapped as one child GEO_NODE.
        """
        file_name = Path(file_path).stem
        file_node = GDataNode(NodeType.STEP_FILE, file_name)

        if not shape.IsNull():
            baked = self._bake_location(shape, None)
            node_name = f"{file_name}_Shape_1"
            geo_node = GDataNode(NodeType.GEO_NODE, node_name)
            geo_node.shape = baked
            file_node.add_child(geo_node)

        return file_node

    def read_files(self, file_paths: List[str], error_info: List[str],
                   progress_callback=None) -> List[GDataNode]:
        """
        Batch-read multiple CAD files.

        Args:
            file_paths: List of file paths to read.
            error_info: List to append error messages to.
            progress_callback: Optional callable(current_step, total_steps)
                               forwarded to each individual read_file call.

        Returns:
            List of file nodes (one per successfully read file).
        """
        self._file_paths = file_paths
        file_nodes = []
        for fp in file_paths:
            node = self.read_file(fp, error_info, progress_callback)
            if node is not None:
                file_nodes.append(node)
        return file_nodes

    # ── Shape tree helpers (inherited from original STEPReader) ────────

    @staticmethod
    def _bake_location(shape: TopoDS_Shape,
                       accum_location: Optional[TopLoc_Location]) -> TopoDS_Shape:
        """
        Bake accumulated location transforms into the geometry so that
        all coordinates are in world space.
        """
        if accum_location is None or accum_location.IsIdentity():
            return shape
        trsf = accum_location.Transformation()
        shape_cleared = shape.Located(TopLoc_Location())
        transformer = BRepBuilderAPI_Transform(shape_cleared, trsf, True)
        return transformer.Shape()

    @staticmethod
    def _accumulate_locations(compound: TopoDS_Shape,
                              child: TopoDS_Shape,
                              parent_accum: Optional[TopLoc_Location]
                              ) -> TopLoc_Location:
        child_loc = child.Location()
        if parent_accum is not None:
            return parent_accum.Multiplied(child_loc)
        return child_loc

    def _add_shape_to_node(self, shape: TopoDS_Shape, parent_node: GDataNode,
                           file_name: str, index: int, depth: int = 0,
                           parent_accum: Optional[TopLoc_Location] = None):
        """
        Recursively add a shape to the node tree, preserving COMPOUND
        hierarchy and baking locations into leaf geometry.
        """
        shape_type = shape.ShapeType()

        if shape_type == TopAbs_COMPOUND:
            it = TopoDS_Iterator(shape)
            child_index = 0
            has_visible_children = False
            while it.More():
                child_index += 1
                child_shape = it.Value()
                child_type = child_shape.ShapeType()

                child_accum = self._accumulate_locations(shape, child_shape,
                                                         parent_accum)
                baked_child = self._bake_location(child_shape, child_accum)

                if child_type == TopAbs_COMPOUND:
                    compound_node = GDataNode(
                        NodeType.GEO_NODE,
                        f"{file_name}_Assembly_{index}_{child_index}"
                    )
                    compound_node.shape = baked_child
                    parent_node.add_child(compound_node)
                    self._add_shape_to_node(baked_child, compound_node,
                                            file_name, index, depth + 1,
                                            parent_accum=None)
                    has_visible_children = True

                elif child_type in (TopAbs_SOLID, TopAbs_SHELL):
                    type_name = "Solid" if child_type == TopAbs_SOLID else "Shell"
                    node_name = f"{file_name}_{type_name}_{child_index}"
                    geo_node = GDataNode(NodeType.GEO_NODE, node_name)
                    geo_node.shape = baked_child
                    parent_node.add_child(geo_node)
                    has_visible_children = True

                elif child_type in (TopAbs_FACE, TopAbs_EDGE):
                    pass

                else:
                    node_name = f"{file_name}_Shape_{child_index}"
                    geo_node = GDataNode(NodeType.GEO_NODE, node_name)
                    geo_node.shape = baked_child
                    parent_node.add_child(geo_node)
                    has_visible_children = True

                it.Next()

            if not has_visible_children:
                baked = self._bake_location(shape, parent_accum)
                node_name = f"{file_name}_Compound_{index}"
                geo_node = GDataNode(NodeType.GEO_NODE, node_name)
                geo_node.shape = baked
                parent_node.add_child(geo_node)

        elif shape_type in (TopAbs_SOLID, TopAbs_SHELL):
            baked = self._bake_location(shape, parent_accum)
            type_name = "Solid" if shape_type == TopAbs_SOLID else "Shell"
            node_name = f"{file_name}_{type_name}_{index}"
            geo_node = GDataNode(NodeType.GEO_NODE, node_name)
            geo_node.shape = baked
            parent_node.add_child(geo_node)

        else:
            baked = self._bake_location(shape, parent_accum)
            node_name = f"{file_name}_Shape_{index}"
            geo_node = GDataNode(NodeType.GEO_NODE, node_name)
            geo_node.shape = baked
            parent_node.add_child(geo_node)
