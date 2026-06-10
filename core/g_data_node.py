"""
GDataNode - 几何数据节点

对应 C++ 版 GDataNode，负责封装几何数据及其处理逻辑。
每个节点可以是根节点、STEP 文件节点或几何实体节点，
包含对应的 TopoDS_Shape、AIS 交互对象、颜色、材料等信息。
"""

from enum import Enum
from typing import Optional, List

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.AIS import AIS_Shape
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from PyQt6.QtCore import QObject, pyqtSignal


class NodeType(Enum):
    """节点类型，对应 C++ GEODATACENTER::NodeType"""
    DONT_CARE = 0
    ROOT_NODE = 1
    STEP_FILE = 2
    GEO_NODE = 3


class GDataNode(QObject):
    """
    几何数据节点

    封装几何树中的一个节点，包含形状数据、AIS对象、颜色、材料等信息。
    节点可以包含子节点，形成树形结构。
    """

    # 信号：节点数据发生变化
    data_changed = pyqtSignal()

    def __init__(self, node_type: NodeType = NodeType.DONT_CARE, name: str = ""):
        """
        初始化几何数据节点

        Args:
            node_type: 节点类型
            name: 节点名称
        """
        super().__init__()
        self._node_type = node_type
        self._name = name
        self._shape: Optional[TopoDS_Shape] = None
        self._ais_shape: Optional[AIS_Shape] = None
        self._color: Optional[Quantity_Color] = None
        self._entry_id: str = ""
        self._material_name: str = ""
        self._mesh_file_name: str = ""
        self._parent: Optional['GDataNode'] = None
        self._children: List['GDataNode'] = []
        self._visible: bool = True

    # ---- 属性 ----

    @property
    def node_type(self) -> NodeType:
        return self._node_type

    @node_type.setter
    def node_type(self, val: NodeType):
        self._node_type = val

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, val: str):
        self._name = val

    @property
    def shape(self) -> Optional[TopoDS_Shape]:
        """获取几何形状"""
        return self._shape

    @shape.setter
    def shape(self, val: Optional[TopoDS_Shape]):
        self._shape = val

    @property
    def ais_shape(self) -> Optional[AIS_Shape]:
        """获取 AIS 可交互形状"""
        return self._ais_shape

    @ais_shape.setter
    def ais_shape(self, val: Optional[AIS_Shape]):
        self._ais_shape = val

    @property
    def color(self) -> Optional[Quantity_Color]:
        return self._color

    @color.setter
    def color(self, val: Optional[Quantity_Color]):
        self._color = val

    @property
    def entry_id(self) -> str:
        """获取实体 ID，全局唯一标识"""
        return self._entry_id

    @entry_id.setter
    def entry_id(self, val: str):
        self._entry_id = val

    @property
    def material_name(self) -> str:
        return self._material_name

    @material_name.setter
    def material_name(self, val: str):
        self._material_name = val

    @property
    def mesh_file_name(self) -> str:
        return self._mesh_file_name

    @mesh_file_name.setter
    def mesh_file_name(self, val: str):
        self._mesh_file_name = val

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, val: bool):
        self._visible = val

    # ---- 树操作 ----

    @property
    def parent(self) -> Optional['GDataNode']:
        return self._parent

    @property
    def children(self) -> List['GDataNode']:
        return self._children.copy()

    def add_child(self, child: 'GDataNode'):
        """添加子节点"""
        child._parent = self
        self._children.append(child)

    def remove_child(self, child: 'GDataNode'):
        """移除子节点"""
        if child in self._children:
            self._children.remove(child)
            child._parent = None

    def get_child_count(self) -> int:
        """获取子节点数量"""
        return len(self._children)

    def is_leaf(self) -> bool:
        """是否为叶子节点"""
        return len(self._children) == 0

    def get_all_descendants(self) -> List['GDataNode']:
        """递归获取所有子孙节点"""
        result = []
        for child in self._children:
            result.append(child)
            result.extend(child.get_all_descendants())
        return result

    def get_leaf_nodes(self) -> List['GDataNode']:
        """递归获取所有叶子节点"""
        result = []
        for child in self._children:
            if child.is_leaf():
                result.append(child)
            else:
                result.extend(child.get_leaf_nodes())
        return result

    def set_color_from_qcolor(self, qcolor):
        """
        从 QColor 设置 OCCT 颜色

        Args:
            qcolor: PyQt6 QColor 对象
        """
        r = qcolor.redF()
        g = qcolor.greenF()
        b = qcolor.blueF()
        self._color = Quantity_Color(r, g, b, Quantity_TOC_RGB)

    def __repr__(self) -> str:
        return f"GDataNode(name='{self._name}', type={self._node_type}, entry_id='{self._entry_id}')"
