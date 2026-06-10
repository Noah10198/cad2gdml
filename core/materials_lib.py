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
    """

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

    # ========== 元素查询 ==========

    @staticmethod
    def get_z_and_atom_by_element_name(name: str) -> Tuple[float, float]:
        """根据元素名称查询原子序数和原子量"""
        # NIST 标准原子量
        element_data = {
            'H': (1, 1.008), 'He': (2, 4.003), 'Li': (3, 6.941), 'Be': (4, 9.012),
            'B': (5, 10.811), 'C': (6, 12.011), 'N': (7, 14.007), 'O': (8, 15.999),
            'F': (9, 18.998), 'Ne': (10, 20.180), 'Na': (11, 22.990), 'Mg': (12, 24.305),
            'Al': (13, 26.982), 'Si': (14, 28.086), 'P': (15, 30.974), 'S': (16, 32.065),
            'Cl': (17, 35.453), 'Ar': (18, 39.948), 'K': (19, 39.098), 'Ca': (20, 40.078),
            'Fe': (26, 55.845), 'Cu': (29, 63.546), 'Zn': (30, 65.380),
            'Ag': (47, 107.868), 'Sn': (50, 118.710), 'Au': (79, 196.967),
        }
        return element_data.get(name, (0, 0.0))

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
        """初始化默认 NIST 材料"""
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
