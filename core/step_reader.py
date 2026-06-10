"""
STEPReader - STEP 几何文件读取器

对应 C++ 版 GEODATACENTER::STEPReader。
使用 pythonocc 的 STEP 读取接口，读取 STEP 文件
并构建 GDataNode 树形结构。
"""

from typing import List, Optional
from pathlib import Path

from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopoDS import TopoDS_Shape, TopoDS_Iterator
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_COMPOUND, TopAbs_FACE, TopAbs_EDGE
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_Transform

from .g_data_node import GDataNode, NodeType


class STEPReader:
    """
    STEP 文件读取器

    支持读取 STEP 文件并解析为几何树结构，
    每个文件可能包含多个几何实体。
    """

    def __init__(self):
        self._file_paths: List[str] = []

    def set_file_list(self, file_paths: List[str]):
        """设置要读取的文件列表"""
        self._file_paths = file_paths

    def read_file(self, file_path: str, error_info: List[str]) -> Optional[GDataNode]:
        """
        读取单个 STEP 文件

        Args:
            file_path: STEP 文件路径
            error_info: 错误信息列表

        Returns:
            文件节点（包含所有子几何节点），失败返回 None
        """
        try:
            # 创建 STEP 读取器
            step_reader = STEPControl_Reader()
            read_status = step_reader.ReadFile(file_path)

            if read_status != 1:  # IFSelect_RetDone
                error_info.append(f"Failed to read STEP file: {file_path}")
                return None

            # 传输全部几何数据
            step_reader.TransferRoots()

            # 创建文件节点
            file_name = Path(file_path).stem
            file_node = GDataNode(NodeType.STEP_FILE, file_name)

            # 获取形状数量
            shape_count = step_reader.NbShapes()

            for i in range(1, shape_count + 1):
                shape = step_reader.Shape(i)
                if shape.IsNull():
                    continue

                # 递归添加形状及其子形状
                self._add_shape_to_node(shape, file_node, file_name, i)

            return file_node

        except Exception as e:
            error_info.append(f"Error reading {file_path}: {str(e)}")
            return None

    def read_files(self, file_paths: List[str], error_info: List[str]) -> List[GDataNode]:
        """
        批量读取 STEP 文件

        Args:
            file_paths: 文件路径列表
            error_info: 错误信息列表

        Returns:
            文件节点列表
        """
        self._file_paths = file_paths
        file_nodes = []

        for fp in file_paths:
            node = self.read_file(fp, error_info)
            if node is not None:
                file_nodes.append(node)

        return file_nodes

    @staticmethod
    def _bake_location(shape: TopoDS_Shape,
                       accum_location: Optional[TopLoc_Location]) -> TopoDS_Shape:
        """
        将累积位置变换"烘焙"进几何体，移除 shape 上的 Location 元数据，
        使几何体坐标直接处于世界坐标系。

        Args:
            shape: 原始形状（可能有 Location）
            accum_location: 累积的父级位置变换（None = 不处理）

        Returns:
            位置已烘焙进几何体的新形状（Location = identity）
        """
        if accum_location is None or accum_location.IsIdentity():
            return shape
        trsf = accum_location.Transformation()
        # 先清除形状自带的 Location，再应用变换到几何 TShape
        shape_cleared = shape.Located(TopLoc_Location())
        transformer = BRepBuilderAPI_Transform(shape_cleared, trsf, True)
        result = transformer.Shape()
        return result

    @staticmethod
    def _accumulate_locations(compound: TopoDS_Shape,
                              child: TopoDS_Shape,
                              parent_accum: Optional[TopLoc_Location]
                              ) -> TopLoc_Location:
        """
        计算子形状的累积位置。

        注意：TopoDS_Iterator 在遍历 COMPOUND 时已自动将 compound 的 Location
        与 child 的 Location 相乘。因此 child.Location() 直接返回累积后的位置。
        不需要手动乘以 compound.Location()。

        Args:
            compound: 父 COMPOUND（用于递归上下文，不使用其 Location）
            child: 子形状（其 Location 已包含父级累积）
            parent_accum: 上层累积位置（None = 不累加）

        Returns:
            子形状的绝对位置 TopLoc_Location
        """
        child_loc = child.Location()
        if parent_accum is not None:
            return parent_accum.Multiplied(child_loc)
        return child_loc

    def _add_shape_to_node(self, shape: TopoDS_Shape, parent_node: GDataNode,
                           file_name: str, index: int, depth: int = 0,
                           parent_accum: Optional[TopLoc_Location] = None):
        """
        递归地将形状添加到节点树，保留 COMPOUND 层次结构。
        自动累积父级 Location，确保叶子形状的几何体处于世界坐标系。

        Args:
            shape: 几何形状
            parent_node: 父节点
            file_name: 文件名
            index: 形状索引
            depth: 递归深度
            parent_accum: 来自上层 COMPOUND 的累积位置（None = 顶层）
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

                # 计算子形状的累积位置
                child_accum = self._accumulate_locations(shape, child_shape,
                                                         parent_accum)
                # 将累积位置烘焙进几何体（移除外层 Location 元数据）
                baked_child = self._bake_location(child_shape, child_accum)

                if child_type == TopAbs_COMPOUND:
                    compound_node = GDataNode(
                        NodeType.GEO_NODE,
                        f"{file_name}_Assembly_{index}_{child_index}"
                    )
                    # Compound 节点本身的形状用烘焙后的几何体（子形状几何已含变换）
                    compound_node.shape = baked_child
                    parent_node.add_child(compound_node)
                    # 递归处理子形状
                    # 注意：baked_child 的几何已包含 child_accum 变换，
                    # 其子形状（通过 TopoDS_Iterator 获得）的几何也已变换到位。
                    # 因此递归时 parent_accum=None，避免子形状被加倍变换。
                    self._add_shape_to_node(baked_child, compound_node,
                                            file_name, index, depth + 1,
                                            parent_accum=None)
                    has_visible_children = True

                elif child_type == TopAbs_SOLID:
                    node_name = f"{file_name}_Solid_{child_index}"
                    solid_node = GDataNode(NodeType.GEO_NODE, node_name)
                    solid_node.shape = baked_child
                    parent_node.add_child(solid_node)
                    has_visible_children = True

                elif child_type == TopAbs_SHELL:
                    node_name = f"{file_name}_Shell_{child_index}"
                    shell_node = GDataNode(NodeType.GEO_NODE, node_name)
                    shell_node.shape = baked_child
                    parent_node.add_child(shell_node)
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
