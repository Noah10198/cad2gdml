"""
MaterialsLib - 材料库管理

对应 C++ 版 MaterialsLib，管理全局材料库和局部材料库。
支持 NIST 标准材料、自定义化合物/混合物材料，
提供材料的增删改查、序列化等功能。
"""

from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import Enum


class MatCategory(Enum):
    """材料类别，对应 C++ EMaterial::MatCate"""
    CUSTOM = "Custom"       # 自定义元素
    COMPOUND = "Compound"   # 化合物（原子比）
    MIXTURE = "Mixture"     # 混合物（质量比）
    NO_CATE = "NoCate"      # 未分类


@dataclass
class CompoundItem:
    """化合物组成元素项，对应 C++ CompoundItem"""
    ratio: int              # 原子个数比
    element_name: str       # 元素名称/符号
    z: float                # 原子序数
    atom: float             # 原子量

    @staticmethod
    def from_dict(data: dict) -> 'CompoundItem':
        return CompoundItem(
            ratio=data.get('ratio', 0),
            element_name=data.get('eleName', ''),
            z=data.get('z', 0.0),
            atom=data.get('atom', 0.0)
        )

    def to_dict(self) -> dict:
        return {
            'ratio': self.ratio,
            'eleName': self.element_name,
            'z': self.z,
            'atom': self.atom
        }


@dataclass
class MixtureItem:
    """混合物组成元素项，对应 C++ MixtureItem"""
    ratio: float            # 质量比（浮点数）
    element_name: str       # 元素名称/符号
    z: float                # 原子序数
    atom: float             # 原子量

    @staticmethod
    def from_dict(data: dict) -> 'MixtureItem':
        return MixtureItem(
            ratio=data.get('ratio', 0.0),
            element_name=data.get('eleName', ''),
            z=data.get('z', 0.0),
            atom=data.get('atom', 0.0)
        )

    def to_dict(self) -> dict:
        return {
            'ratio': self.ratio,
            'eleName': self.element_name,
            'z': self.z,
            'atom': self.atom
        }


@dataclass
class CustomElement:
    """自定义元素，对应 C++ CustomElement"""
    mat_id: str             # 唯一标识符
    name: str               # 元素名称，如"Hydrogen"
    symbol: str             # 元素符号，如"H"
    number: int             # 原子序数 Z
    quality: float          # 原子质量

    def __post_init__(self):
        self._mat_cate = MatCategory.CUSTOM

    @property
    def mat_cate(self) -> MatCategory:
        return self._mat_cate

    @staticmethod
    def from_dict(data: dict) -> 'CustomElement':
        return CustomElement(
            mat_id=data.get('id', ''),
            name=data.get('name', ''),
            symbol=data.get('symbol', ''),
            number=data.get('number', 0),
            quality=data.get('quality', 0.0)
        )

    def to_dict(self) -> dict:
        return {
            'id': self.mat_id,
            'matCate': self.mat_cate.value,
            'name': self.name,
            'symbol': self.symbol,
            'number': self.number,
            'quality': self.quality,
        }


@dataclass
class CompoundMaterial:
    """化合物材料，对应 C++ CompoundMaterial"""
    mat_id: str             # 唯一标识符
    mat_name: str           # 材料名称
    density: float          # 密度
    unit: str = "g/cm3"     # 密度单位
    items: List[CompoundItem] = field(default_factory=list)  # 组成元素（原子比）

    def __post_init__(self):
        self._mat_cate = MatCategory.COMPOUND

    @property
    def mat_cate(self) -> MatCategory:
        return self._mat_cate

    @staticmethod
    def from_dict(data: dict) -> 'CompoundMaterial':
        return CompoundMaterial(
            mat_id=data.get('id', ''),
            mat_name=data.get('matName', ''),
            density=data.get('density', 0.0),
            unit=data.get('unit', 'g/cm3'),
            items=[CompoundItem.from_dict(item) for item in data.get('itemList', [])]
        )

    def to_dict(self) -> dict:
        return {
            'id': self.mat_id,
            'matCate': self.mat_cate.value,
            'matName': self.mat_name,
            'density': self.density,
            'unit': self.unit,
            'itemList': [item.to_dict() for item in self.items],
        }


@dataclass
class MixtureMaterial:
    """混合物材料，对应 C++ MixtureMaterial"""
    mat_id: str             # 唯一标识符
    mat_name: str           # 材料名称
    density: float          # 密度
    unit: str = "g/cm3"     # 密度单位
    items: List[MixtureItem] = field(default_factory=list)  # 组成元素（质量比）

    def __post_init__(self):
        self._mat_cate = MatCategory.MIXTURE

    @property
    def mat_cate(self) -> MatCategory:
        return self._mat_cate

    @staticmethod
    def from_dict(data: dict) -> 'MixtureMaterial':
        return MixtureMaterial(
            mat_id=data.get('id', ''),
            mat_name=data.get('matName', ''),
            density=data.get('density', 0.0),
            unit=data.get('unit', 'g/cm3'),
            items=[MixtureItem.from_dict(item) for item in data.get('itemList', [])]
        )

    def to_dict(self) -> dict:
        return {
            'id': self.mat_id,
            'matCate': self.mat_cate.value,
            'matName': self.mat_name,
            'density': self.density,
            'unit': self.unit,
            'itemList': [item.to_dict() for item in self.items],
        }


class MaterialsLib:
    """
    材料库管理器（单例）

    对应 C++ MaterialsLib，管理：
    - 自定义元素 (CustomElement)
    - 化合物材料 (CompoundMaterial) -- 原子比
    - 混合物材料 (MixtureMaterial) -- 质量比
    - NIST 全局材料选择状态

    控制标记：
    - GDML_OUTPUT_ENABLED: 设为 False 可关闭保存时 GDML 打印输出
    """

    # ---- 控制标记 ----
    GDML_OUTPUT_ENABLED: bool = True

    _instance: Optional['MaterialsLib'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # ---- 局部材料库 ----
        self._cust_ele_list: Dict[str, CustomElement] = {}      # id -> CustomElement
        self._comp_list: Dict[str, CompoundMaterial] = {}       # id -> CompoundMaterial
        self._mix_list: Dict[str, MixtureMaterial] = {}         # id -> MixtureMaterial

        # ---- 全局材料库选择状态 ----
        self._ele_left_list: List[str] = []     # 全局所有可用元素名称
        self._ele_right_list: List[str] = []    # 已选中的元素名称
        self._nist_left_list: List[str] = []    # 全局所有 NIST 材料名称
        self._nist_right_list: List[str] = []   # 已选中的 NIST 材料名称

        # ---- 内部状态跟踪 ----
        self._counter_id = 0
        self._curr_mat_id: str = ""
        self._curr_mat_cate: MatCategory = MatCategory.NO_CATE
        self._add_flag: bool = True
        self._add_item_flag: bool = False

        # 初始化默认数据
        self._init_default_materials()
        self._init_default_local_materials()

    # ========== ID 生成 ==========

    def _next_id(self) -> str:
        self._counter_id += 1
        return f"mat_{self._counter_id}"

    # ========== 自定义元素 CRUD ==========

    def get_custom_element(self, mat_id: str) -> Optional[CustomElement]:
        return self._cust_ele_list.get(mat_id)

    def get_all_custom_elements(self) -> List[CustomElement]:
        return list(self._cust_ele_list.values())

    def add_custom_element(self, elem: CustomElement) -> bool:
        if elem.mat_id in self._cust_ele_list:
            return False
        if not elem.mat_id:
            elem.mat_id = self._next_id()
        self._cust_ele_list[elem.mat_id] = elem
        return True

    def delete_custom_element(self, mat_id: str) -> bool:
        return self._cust_ele_list.pop(mat_id, None) is not None

    # ========== 化合物 CRUD ==========

    def get_compound(self, mat_id: str) -> Optional[CompoundMaterial]:
        return self._comp_list.get(mat_id)

    def get_all_compounds(self) -> List[CompoundMaterial]:
        return list(self._comp_list.values())

    def add_compound(self, mat: CompoundMaterial) -> bool:
        if mat.mat_id in self._comp_list:
            return False
        if not mat.mat_id:
            mat.mat_id = self._next_id()
        self._comp_list[mat.mat_id] = mat
        return True

    def delete_compound(self, mat_id: str) -> bool:
        return self._comp_list.pop(mat_id, None) is not None

    # ========== 混合物 CRUD ==========

    def get_mixture(self, mat_id: str) -> Optional[MixtureMaterial]:
        return self._mix_list.get(mat_id)

    def get_all_mixtures(self) -> List[MixtureMaterial]:
        return list(self._mix_list.values())

    def add_mixture(self, mat: MixtureMaterial) -> bool:
        if mat.mat_id in self._mix_list:
            return False
        if not mat.mat_id:
            mat.mat_id = self._next_id()
        self._mix_list[mat.mat_id] = mat
        return True

    def delete_mixture(self, mat_id: str) -> bool:
        return self._mix_list.pop(mat_id, None) is not None

    # ========== 通用材料操作 ==========

    def get_all_local_materials(self) -> List[object]:
        """获取所有局部材料（用于 UI 列表展示）"""
        result: List[object] = []
        result.extend(self._cust_ele_list.values())
        result.extend(self._comp_list.values())
        result.extend(self._mix_list.values())
        return result

    def get_local_material_names(self) -> List[str]:
        """获取所有局部材料名称"""
        names = []
        for ele in self._cust_ele_list.values():
            names.append(ele.name)
        for mat in self._comp_list.values():
            names.append(mat.mat_name)
        for mat in self._mix_list.values():
            names.append(mat.mat_name)
        return names

    def delete_material(self, mat_id: str) -> bool:
        """按 ID 删除任意类型的材料"""
        return (self._cust_ele_list.pop(mat_id, None) is not None
                or self._comp_list.pop(mat_id, None) is not None
                or self._mix_list.pop(mat_id, None) is not None)

    @staticmethod
    def to_gdml_string(mat) -> str:
        """
        将局部材料转换为验证用 GDML 格式字符串。

        格式参考：
          化合物: <material name="Water" formula="H2O"><D value="1.0"/><composite n="2" ref="H"/><composite n="1" ref="O"/></material>
          混合物: <material name="Air"><D value="0.00129"/><fraction n="0.7" ref="N"/><fraction n="0.3" ref="O"/></material>
        """
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        if isinstance(mat, CustomElement):
            elem = ET.Element("element", {
                "name": mat.name,
                "formula": mat.symbol,
                "Z": str(int(mat.number)),
            })
            ET.SubElement(elem, "atom", {"value": str(mat.quality)})
            return minidom.parseString(ET.tostring(elem, encoding="unicode")).toprettyxml(indent="  ")

        elif isinstance(mat, CompoundMaterial):
            # Derive chemical formula from items, in user-specified order
            # e.g. items=[O(1), H(2)] → "OH2"; items=[H(2), O(1)] → "H2O"
            formula_parts = []
            for item in mat.items:
                if item.ratio == 1:
                    formula_parts.append(item.element_name)
                else:
                    formula_parts.append(f"{item.element_name}{item.ratio}")
            formula = "".join(formula_parts) if formula_parts else mat.mat_name
            mat_elem = ET.Element("material", {"name": mat.mat_name, "formula": formula})
            ET.SubElement(mat_elem, "D", {
                "value": f"{mat.density:.4f}",
            })
            for item in mat.items:
                ET.SubElement(mat_elem, "composite", {
                    "n": str(int(item.ratio)),
                    "ref": item.element_name,
                })
            return minidom.parseString(ET.tostring(mat_elem, encoding="unicode")).toprettyxml(indent="  ")

        elif isinstance(mat, MixtureMaterial):
            mat_elem = ET.Element("material", {"name": mat.mat_name})
            ET.SubElement(mat_elem, "D", {
                "value": f"{mat.density:.4f}",
                "unit": mat.unit,
            })
            for item in mat.items:
                ET.SubElement(mat_elem, "fraction", {
                    "n": f"{item.ratio:.4f}",
                    "ref": item.element_name,
                })
            return minidom.parseString(ET.tostring(mat_elem, encoding="unicode")).toprettyxml(indent="  ")

        return ""

    # ========== JSON 持久化 ==========

    def save_local_materials_to_json(self, filepath: str) -> bool:
        """将所有的局部材料保存为 JSON 文件。"""
        import json
        data = {
            "custom_elements": [e.to_dict() for e in self._cust_ele_list.values()],
            "compounds": [c.to_dict() for c in self._comp_list.values()],
            "mixtures": [m.to_dict() for m in self._mix_list.values()],
        }
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def load_local_materials_from_json(self, filepath: str) -> int:
        """从 JSON 文件加载局部材料，覆盖当前库。"""
        import json
        self._cust_ele_list.clear()
        self._comp_list.clear()
        self._mix_list.clear()
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            count = 0
            for d in data.get("custom_elements", []):
                e = CustomElement.from_dict(d)
                self._cust_ele_list[e.mat_id] = e
                count += 1
            for d in data.get("compounds", []):
                c = CompoundMaterial.from_dict(d)
                self._comp_list[c.mat_id] = c
                count += 1
            for d in data.get("mixtures", []):
                m = MixtureMaterial.from_dict(d)
                self._mix_list[m.mat_id] = m
                count += 1
            return count
        except Exception:
            return 0

    def get_mat_cate_by_id(self, mat_id: str) -> MatCategory:
        """根据 ID 获取材料分类"""
        if mat_id in self._cust_ele_list:
            return MatCategory.CUSTOM
        if mat_id in self._comp_list:
            return MatCategory.COMPOUND
        if mat_id in self._mix_list:
            return MatCategory.MIXTURE
        return MatCategory.NO_CATE

    # ========== 全局库选择状态 ==========

    def get_ele_left_list(self) -> List[str]:
        return self._ele_left_list

    def set_ele_left_list(self, names: List[str]):
        self._ele_left_list = names[:]

    def get_ele_right_list(self) -> List[str]:
        return self._ele_right_list

    def set_ele_right_list(self, names: List[str]):
        self._ele_right_list = names[:]

    def get_nist_left_list(self) -> List[str]:
        return self._nist_left_list

    def set_nist_left_list(self, names: List[str]):
        self._nist_left_list = names[:]

    def get_nist_right_list(self) -> List[str]:
        return self._nist_right_list

    def set_nist_right_list(self, names: List[str]):
        self._nist_right_list = names[:]

    # ========== 内部状态 ==========

    def set_curr_mat_id(self, mat_id: str):
        self._curr_mat_id = mat_id

    def get_curr_mat_id(self) -> str:
        return self._curr_mat_id

    def set_add_flag(self, flag: bool):
        self._add_flag = flag

    def get_add_flag(self) -> bool:
        return self._add_flag

    # ========== 元素数据 ==========

    # 从 element.xml 加载的全部元素数据：symbol -> (Z, atom)
    _ELEMENT_DB: Dict[str, Tuple[float, float]] = {}

    @classmethod
    def load_elements_from_xml(cls, xml_path: str) -> int:
        """从 element.xml 加载元素数据。"""
        import xml.etree.ElementTree as ET
        count = 0
        cls._ELEMENT_DB.clear()
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for elem in root.iter('element'):
                formula = elem.get('formula', '')
                z_str = elem.get('Z', '0')
                atom_elem = elem.find('atom')
                atom_str = atom_elem.get('value', '0') if atom_elem is not None else '0'
                try:
                    z = float(z_str)
                    atom = float(atom_str)
                except ValueError:
                    continue
                cls._ELEMENT_DB[formula] = (z, atom)
                count += 1
        except Exception:
            pass
        return count

    @staticmethod
    def get_z_and_atom_by_element_name(name: str) -> Tuple[float, float]:
        """根据元素名称查询原子序数和原子量"""
        return MaterialsLib._ELEMENT_DB.get(name, (0, 0.0))

    @classmethod
    def get_all_element_symbols(cls) -> List[str]:
        """获取所有可用元素符号（按原子序数排序）"""
        return sorted(cls._ELEMENT_DB.keys(), key=lambda s: cls._ELEMENT_DB[s][0])

    # ========== 材料查找 ==========

    def get_material_by_name(self, mat_name: str):
        """根据名称查找材料（NIST / 自定义元素 / 化合物 / 混合物）"""
        # 查找局部库
        for ele in self._cust_ele_list.values():
            if ele.name == mat_name or ele.symbol == mat_name:
                return ele
        for mat in self._comp_list.values():
            if mat.mat_name == mat_name:
                return mat
        for mat in self._mix_list.values():
            if mat.mat_name == mat_name:
                return mat
        # 查找 NIST 列表
        if mat_name in self._nist_right_list:
            return {"name": mat_name, "category": "NIST"}
        return None

    def get_all_global_materials(self):
        """获取所有选中的 NIST 材料名称列表（兼容旧接口）"""
        return self._nist_right_list[:]

    # ========== 默认 NIST 材料 ==========

    def _init_default_materials(self):
        """初始化默认 NIST 材料（7 种常用材料作为 fallback）"""
        defaults = [
            ("G4_AIR", 0.001205, "Air (dry, near sea level)"),
            ("G4_Al", 2.699, "Aluminum"),
            ("G4_Cu", 8.96, "Copper"),
            ("G4_Si", 2.329, "Silicon"),
            ("G4_WATER", 1.0, "Water"),
            ("G4_POLYETHYLENE", 0.94, "Polyethylene"),
            ("G4_Galactic", 1e-25, "Galactic vacuum"),
        ]
        self._nist_left_list = [name for name, _, _ in defaults]
        # 默认全部选中
        self._nist_right_list = self._nist_left_list[:]

    def _init_default_local_materials(self):
        """Add default local materials matching C++ initLocalMaterial()."""
        # Default compound: water (H2O)
        h_z, h_atom = self.get_z_and_atom_by_element_name("H")
        o_z, o_atom = self.get_z_and_atom_by_element_name("O")
        water = CompoundMaterial(
            mat_id=self._next_id(),
            mat_name="water",
            density=1.0,
            unit="g/cm3",
            items=[
                CompoundItem(ratio=2, element_name="H", z=h_z, atom=h_atom),
                CompoundItem(ratio=1, element_name="O", z=o_z, atom=o_atom),
            ],
        )
        self.add_compound(water)

        # Default mixture: air (N 0.7, O 0.3)
        n_z, n_atom = self.get_z_and_atom_by_element_name("N")
        air = MixtureMaterial(
            mat_id=self._next_id(),
            mat_name="air_user",
            density=0.00129,
            unit="g/cm3",
            items=[
                MixtureItem(ratio=0.7, element_name="N", z=n_z, atom=n_atom),
                MixtureItem(ratio=0.3, element_name="O", z=o_z, atom=o_atom),
            ],
        )
        self.add_mixture(air)

    def load_nist_from_file(self, filepath: str) -> int:
        """从 nist.txt 加载所有 G4_ 材料到全局 NIST 列表。

        Args:
            filepath: nist.txt 文件路径。

        Returns:
            加载的材料数量。
        """
        loaded = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if name and name.startswith("G4_"):
                        loaded.append(name)
        except (FileNotFoundError, IOError):
            print(f"Warning: Could not load NIST file: {filepath}")
            return 0

        if loaded:
            self._nist_left_list = loaded[:]
            self._nist_right_list = loaded[:]

        return len(loaded)

    # ========== 序列化 ==========

    def clear(self):
        """清空所有材料数据"""
        self._cust_ele_list.clear()
        self._comp_list.clear()
        self._mix_list.clear()
        self._ele_left_list.clear()
        self._ele_right_list.clear()
        self._nist_left_list.clear()
        self._nist_right_list.clear()
        self._init_default_materials()
        self._init_default_local_materials()

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            'customElements': {k: v.to_dict() for k, v in self._cust_ele_list.items()},
            'compounds': {k: v.to_dict() for k, v in self._comp_list.items()},
            'mixtures': {k: v.to_dict() for k, v in self._mix_list.items()},
            'eleLeft': self._ele_left_list,
            'eleRight': self._ele_right_list,
            'nistLeft': self._nist_left_list,
            'nistRight': self._nist_right_list,
        }

    def from_dict(self, data: dict):
        """从字典恢复数据"""
        self.clear()
        for k, v in data.get('customElements', {}).items():
            self._cust_ele_list[k] = CustomElement.from_dict(v)
        for k, v in data.get('compounds', {}).items():
            self._comp_list[k] = CompoundMaterial.from_dict(v)
        for k, v in data.get('mixtures', {}).items():
            self._mix_list[k] = MixtureMaterial.from_dict(v)
        self._ele_left_list = data.get('eleLeft', [])
        self._ele_right_list = data.get('eleRight', [])
        self._nist_left_list = data.get('nistLeft', [])
        self._nist_right_list = data.get('nistRight', [])
