"""
GeoDataAgent - 几何数据代理

对应 C++ 版 GEODATACENTER::GeoDataAgent，采用单例模式。
作为几何数据模块对外的统一接口，接受用户请求，
调用 GDataNode 和 STEPReader 进行数据处理。
负责管理所有几何数据节点的生命周期。
"""

from typing import List, Optional, Dict, Tuple
import uuid

from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.AIS import AIS_Shape

from .g_data_node import GDataNode, NodeType
from .cad_reader import CADReader


class GeoDataAgent:
    """几何数据代理（单例），统一管理几何数据的加载、查询、修改和保存。"""

    _instance: Optional['GeoDataAgent'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._root_node = GDataNode(NodeType.ROOT_NODE, "Geometry Root")
        self._entry_id_map: Dict[str, GDataNode] = {}
        self._cad_reader = CADReader()

    def read_step_files(self, file_paths: List[str], error_info: List[str]) -> bool:
        try:
            file_nodes = self._cad_reader.read_files(file_paths, error_info)
            for file_node in file_nodes:
                entry_id = self._generate_entry_id()
                file_node.entry_id = entry_id
                self._entry_id_map[entry_id] = file_node
                self._root_node.add_child(file_node)
                for child in file_node.get_all_descendants():
                    child.entry_id = self._generate_entry_id()
                    self._entry_id_map[child.entry_id] = child
            return len(error_info) == 0
        except Exception as e:
            error_info.append(str(e))
            return False

    def get_all_geo_file_nodes(self) -> List[GDataNode]:
        return [c for c in self._root_node.children
                if c.node_type in (NodeType.STEP_FILE, NodeType.GEO_FILE)]

    def get_all_solid_nodes(self) -> List[GDataNode]:
        solids = []
        for file_node in self.get_all_geo_file_nodes():
            for node in file_node.get_leaf_nodes():
                if node.shape is not None:
                    solids.append(node)
        return solids

    def get_all_solid_nodes_by_entry_id(self, entry_id: str) -> List[GDataNode]:
        node = self._entry_id_map.get(entry_id)
        if node is None:
            return []
        if node.is_leaf() and node.shape is not None:
            return [node]
        return [n for n in node.get_leaf_nodes() if n.shape is not None]

    def get_node_list_by_node_point(self, node: GDataNode) -> List[GDataNode]:
        return [node] + node.get_all_descendants()

    def convert_entry_id_to_node(self, entry_id: str) -> Optional[GDataNode]:
        return self._entry_id_map.get(entry_id)

    def remove_node(self, entry_id: str) -> bool:
        node = self._entry_id_map.get(entry_id)
        if node is None:
            return False
        if node.parent:
            node.parent.remove_child(node)
        self._entry_id_map.pop(entry_id, None)
        for desc in node.get_all_descendants():
            self._entry_id_map.pop(desc.entry_id, None)
        return True

    def get_root_node(self) -> GDataNode:
        return self._root_node

    def _generate_entry_id(self) -> str:
        return f"GEO_{uuid.uuid4().hex[:12].upper()}"

    def write(self, stream) -> bool:
        try:
            data = self._serialize_node(self._root_node)
            import json
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            stream.write(json_str.encode('utf-8'))
            return True
        except Exception as e:
            print(f"Write error: {e}")
            return False

    def read(self, stream) -> bool:
        try:
            import json
            json_str = stream.read().decode('utf-8')
            data = json.loads(json_str)
            self._deserialize_node(data, self._root_node)
            return True
        except Exception as e:
            print(f"Read error: {e}")
            return False

    def _serialize_node(self, node: GDataNode) -> dict:
        return {
            'name': node.name,
            'nodeType': node.node_type.value,
            'entryId': node.entry_id,
            'materialName': node.material_name,
            'meshFileName': node.mesh_file_name,
            'children': [self._serialize_node(c) for c in node.children],
        }

    def _deserialize_node(self, data: dict, parent: GDataNode):
        for child_data in data.get('children', []):
            child = GDataNode(
                NodeType(child_data.get('nodeType', NodeType.DONT_CARE.value)),
                child_data.get('name', '')
            )
            child.entry_id = child_data.get('entryId', '')
            child.material_name = child_data.get('materialName', '')
            child.mesh_file_name = child_data.get('meshFileName', '')
            self._entry_id_map[child.entry_id] = child
            parent.add_child(child)
            self._deserialize_node(child_data, child)
