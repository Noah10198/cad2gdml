# CAD2GDML

**CAD 转 GDML 几何转换工具** —— 把 CAD 模型转换为 Geant4 仿真几何（GDML），并使用 GMSH 生成网格。

> **版本 2.0.0** ｜ 最后更新 2026-09-30 ｜ 英文版：[README.md](README.md)


## 概述

CAD2GDML 是一个桌面 GUI 程序，连接 CAD 设计与粒子物理仿真：导入 CAD 装配体文件，在 OpenCASCADE 3D 视图中显示，使用 GMSH 生成有限元网格，并导出为 Geant4 系列仿真工具可用的 GDML 几何格式。

> **平台说明**：目前仅在 **Windows** 上开发和测试，Linux 支持会在后续版本中验证。


## 功能特性

- **CAD 导入** —— 加载 `.step` / `.stp` / `.brep` 装配体，支持层级树展示与跨会话累积导入（`.iges` / `.igs` 与 `.stl` 也可导入，但功能有限）
- **3D CAD 视图** —— 基于 PythonOCC 的交互式 3D 显示，实体按 Lego 配色着色
- **Interference 1** —— 全量两两 B-Rep 干涉检查（OBB 预筛 + `BRepExtrema_DistShapeShape`），结果分为 Safe / Contact / Hard 三类，可内嵌 OCC 视图预览选中的零件对
- **Interference 2** —— 面向大型装配体的快速启发式扫描：先用 OBB + 空间网格枚举候选对，再对采样出的最可疑零件对做精确检查（结果标注为 *sampled · for reference only*）
- **位移编辑** —— 以几何中心或世界原点为参考，对单个零件或整个导入结果做平移 / 旋转
- **材料赋值** —— 全局与逐零件材料库，内置 NIST 参考材料，可自定义元素、化合物与混合物；支持多选批量赋值
- **GMSH 网格生成** —— 后台非阻塞生成网格，可配置算法、单元尺寸系数、平滑步数、单元阶次，并按包围盒自适应尺寸；工具栏 Mesh 按钮在 **Mesh / Re-mesh / Cancel** 三态间切换，Re-mesh 可对选定的零件组重新划分
- **网格检查** —— 基于 VTK 的网格查看器，提供重叠区域提取（Interference1）与距离热力图工具
- **GDML 导出** —— 把带网格的几何转换为 Geant4 GDML（tessellated 实体、world volume、NIST / 自定义材料）
- **VTK / MSH 导出** —— 导出生成的网格文件
- **深色 / 浅色主题** —— 全局主题切换
- **帮助** —— 内置帮助 / About 对话框

### 支持的格式

| 格式 | 扩展名 | 支持程度 |
|--------|-----------|--------------|
| STEP | `.step` / `.stp` | **完整** —— 导入、显示、网格、导出 |
| BREP | `.brep` | **完整** —— 导入、显示、网格、导出 |
| IGES | `.iges` / `.igs` | **部分** —— 仅导入与显示，网格生成未完全验证 |
| STL | `.stl` | **有限** —— 仅导入与显示，可直接提取网格 |


## 运行要求

| 依赖 | 版本 |
|---|---|
| Python | >= 3.10 |
| PyQt6 | >= 6.4 |
| pythonocc-core | >= 7.6 |
| VTK | >= 9.2 |
| numpy | >= 1.21 |
| GMSH | >= 4.10 —— 已随包提供 `gmsh/gmsh.exe`，无需另行安装 |


## 安装

详细安装步骤见 **[doc/installation.md](doc/installation.md)**。


## 使用流程

整体流程与管线顺序一致：导入 → 检查 → 赋材料 → 划网格 → 导出。

1. **导入** —— 点击 **📂 Import CAD**，装配体出现在项目树与 OCC 视图中（多次导入会累积）。
2. **干涉检查** —— **🔌 Interference 1** 执行全量 B-Rep 检查，**⚡ Interference 2** 对大型装配体做快速采样扫描；两者均可把结果表导出为 CSV。
3. **材料** —— **🧪 Material** 可按零件（多选）或全局赋值 NIST / 自定义材料。
4. **网格** —— **🔧 Mesh** 对整个模型划分网格，**🔁 Re-mesh** 对选定的零件组重新划分，**⏹ Cancel** 终止正在运行的任务；**👁 View Mesh** 打开 VTK 网格查看器进行检查。
5. **导出** —— **📦 Export GDML** 写出 tessellated GDML（world volume + 材料），**📤 Export Mesh** 写出 `.vtk` / `.msh` 网格文件。

双击零件可查看属性，右键可进行位移编辑；**❓ Help** 打开 About 对话框。


## 项目结构

```
  app/
    main_window.py          — 主窗口、信号 / 槽连接
  core/
    cad_reader.py           — 多格式 CAD 导入（STEP/IGES/BREP/STL）
    cad_process.py          — OCC 形状处理辅助
    conformity.py           — 网格与导出共用的贴合性判定
    g_data_node.py          — 几何数据节点树模型
    geo_data_agent.py       — 模块间通信用的几何数据代理
    gdml_generator.py       — 由带网格几何生成 GDML XML
    import_worker.py        — 后台 CAD 导入线程
    lego_color_singleton.py — 实体的 Lego 配色
    materials_lib.py        — NIST + 自定义元素 / 化合物 / 混合物库
    node_transform.py       — 节点位移（平移 / 旋转）支持
  data/
    element.xml             — 元素周期表（103 个元素）
    nist.txt                — NIST 材料列表
  doc/
    assembly_fragment_gdml.md  — 贴合式（BooleanFragments）网格 + GDML 方案
    assembly_fragment_ui.md    — Re-mesh 范围选择的界面设计说明
    export_gdml.md          — GDML 导出指南
    import_geometry.md      — CAD 导入指南
    installation.md         — 安装指南
    interference_dialog.md  — 干涉检查对话框使用说明
    interference1_algorithm.md — Interference1 算法细节
    interference2_algorithm.md — Interference2 算法细节
    material_assignment.md  — 材料赋值指南
    mesh.md                 — 网格生成指南
    mesh_viewer.md          — 网格查看器使用说明
  exampleSTEP/              — 示例 STEP 装配体与演示脚本
  fileio/                   — 文件 I/O（占位）
  gmsh/                     — 随包提供的 gmsh.exe
  icon/                     — 应用图标（cad2gdml.svg）
  mesh/
    assembly_analysis.py    — 导入后的后台接触分析
    gmsh_dialog.py          — 网格参数配置对话框
    mesh_runner.py          — GMSH 后台线程（QProcess + .geo 脚本）
    mesh_viewer.py          — 基于 VTK 的 3D 网格查看器（非模态）
    remesh_scope_dialog.py  — 范围面板：分组、参数、运行进度
    scope.py                — 接触图分组（Re-mesh 的单位）
    vtk_tools.py            — 网格查看器共用的 VTK 辅助
  outputfile/               — 生成的文件（VTK、MSH、GDML）
  test/                     — 网格操作基准测试
  ui/
    toolbar.py              — Office 风格 Ribbon 工具栏
    project_tree.py         — 几何层级树（带可见性勾选）
    occ_widget.py           — PythonOCC 3D 显示控件
    occ_preview.py          — 干涉对话框中内嵌的 OCC 预览
    geo_param_widget.py     — 属性查看面板
    import_progress.py      — 导入进度对话框
    assign_material_dialog.py   — 逐零件 / 批量材料赋值
    local_material_dialog.py    — 自定义元素 / 化合物 / 混合物编辑器
    export_gdml_dialog.py       — GDML 导出配置对话框
    export_mesh_dialog.py       — 网格文件导出对话框
    interference_dialog.py      — Interference 1 对话框（内嵌 OCC 视图）
    interference_dialog_v2.py   — Interference 2：采样式启发式扫描
    mesh_group_dialog.py        — Re-mesh 分组选择
    transform_dialog.py         — 平移 / 旋转对话框
  utils/
    logger.py               — 基于信号槽的异步日志
    occ_quiet.py            — 屏蔽 OCC 控制台输出
    task_manager.py         — 后台任务生命周期管理
  environment.yml           — conda 环境（名称 pyoccenv）
  main.py                   — 程序入口
  README.md                 — 英文说明
  README.zh.md              — 本文件
```


## 架构

软件采用管线式架构，CAD 几何依次经过四个阶段：导入 → 材料 → 网格 → 导出。

```
┌──────────────────────────────────────────────────────────────────────┐
│                          MainWindow                                   │
│  ┌──────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌───────┐ │
│  │  Ribbon  │ │  Project   │ │    OCC     │ │Interfere │ │Property│ │
│  │  Toolbar │ │   Tree     │ │  Viewer    │ │  Dialog  │ │ Panel  │ │
│  └──────────┘ └────────────┘ └────────────┘ └──────────┘ └───────┘ │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     System Log                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

  Pipeline Stages (non-blocking, background threads):

  ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌───────────┐
  │  Import   │───▶│  Material    │───▶│   Mesh   │───▶│  Export   │
  │  Worker   │    │  Assignment  │    │  Runner  │    │  Dialog   │
  └──────────┘    └──────────────┘    └──────────┘    └───────────┘
       │                 │                 │                 │
       ▼                 ▼                 ▼                 ▼
  CAD File→OCC    NIST / Custom       GMSH .exe         GDML XML
   B-Rep tree     material lib        (QProcess)        tessellated
```

所有网格生成都在后台 `QThread` 中执行，以保证界面响应；材料、网格、导出等对话框均以非模态方式打开。

### 模块划分

```
                ┌───────────────────┐
                │   app/main_window │  ← Signal/slot orchestration
                └────────┬──────────┘
                         │
      ┌──────────────────┼──────────────────────┐
      ▼                  ▼                      ▼
┌──────────┐    ┌──────────────┐       ┌──────────────┐
│   core/  │    │     ui/      │       │    mesh/     │
│ data     │    │ Qt dialogs   │       │ GMSH process │
│ models   │    │ OCC viewer   │       │ VTK viewer   │
│ materials│    │ project tree │       │ mesh preview │
└──────────┘    └──────────────┘       └──────────────┘
                     │                       │
                     ▼                       ▼
              ┌──────────────┐       ┌──────────────┐
              │ interference │       │  outputfile/  │
              │  dialogs     │       │ .vtk/.msh/.gdml
              └──────────────┘       └──────────────┘
```

### 处理管线

```
STEP / IGES / BREP / STL
        │
        ▼
   cad_reader.py — OCC B-Rep extraction
        │
        ▼
   Project Tree — geometry hierarchy (GDataNode)
        │
        ├──► OCC Viewer (3D display, lego coloring)
        ├──► Interference Check (OBB pre-filter + BRepExtrema)
        ├──► Material Assignment (NIST library / custom composition)
        ├──► MeshRunner → GMSH (.geo script → .vtk)
        │       └──► MeshViewer (VTK 3D preview, validation tools)
        └──► GDML Generator (tessellated solids → .gdml)
                └──► Export dialog (world box, material config)
```


## 已知限制

- **IGES** 为部分支持，其网格生成路径尚未完全验证；**STL** 仅能显示与直接提取网格：
  STL 没有 B-Rep 拓扑，整个文件会被合并为单个三角面片壳。
- 未知扩展名会在导入阶段直接被拒绝。
- 上述 IGES / STL 的限制在 `core/cad_reader.py` 中实现。
- 装配体（贴合式）网格依赖一次 `BooleanFragments` 布尔运算；若该作业失败会降级为
  逐实体网格，此时接触面上的重合面片可能被 Geant4 判定为 Overlap。
- 网格重叠提取最多报告 8 对重叠实体。
- 网格生成依赖随包提供的 `gmsh/gmsh.exe`，仅探测模块目录内的相对路径与 `PATH`，
  因此需保持目录结构不变。
- 4 MB 及以上的 CAD 文件会在子进程中读取，超时时间为 15 分钟。
- `fileio/` 目前是空的占位包。

## 开发说明

- **线程模型**：CAD 导入用 `ImportWorker(QThread)`，网格生成用 `MeshRunner(QThread)`，
  大 CAD 文件则用 spawn 子进程（`core/cad_process.py`），因为 `TransferRoots()` 持有
  GIL 会冻结界面；接触分析（`mesh/assembly_analysis.py`）同样在 spawn 子进程中运行，
  由 `QTimer` 轮询结果。
- **GMSH 调用**：`QProcess` 执行 `gmsh.exe <geo> -1`（非交互模式），使用
  `MergedChannels` 合并输出并逐行解析进度；`.geo` 脚本由模板 + 对话框参数生成。
  等待循环按 200 ms 切片轮询而非一次性 `waitForFinished`，以保证 **Cancel** 响应及时。
- **Mesh 按钮状态机**：mesh / re-mesh / cancel 三态由 `RibbonToolbar.set_mesh_state()`
  驱动，运行期间其余按钮禁用。
- **单例**：`TaskManager` 与 `LegoColorSingleton`。
- **OCC 控制台静音**：`utils/occ_quiet.py` 在创建视图前后把 stdout 重定向到
  `os.devnull`。

## 相关文档

- **模块文档（`doc/`）**：[安装](doc/installation.md) ｜ [几何导入](doc/import_geometry.md) ｜ [网格生成](doc/mesh.md) ｜ [网格查看器](doc/mesh_viewer.md) ｜ [材料赋值](doc/material_assignment.md) ｜ [GDML 导出](doc/export_gdml.md) ｜ [干涉检查对话框](doc/interference_dialog.md) ｜ [Interference 1 算法](doc/interference1_algorithm.md) ｜ [Interference 2 算法](doc/interference2_algorithm.md) ｜ [贴合式网格方案](doc/assembly_fragment_gdml.md) ｜ [Re-mesh 范围界面](doc/assembly_fragment_ui.md)
- **示例装配体演示**：[exampleSTEP/merge_demo/README.md](exampleSTEP/merge_demo/README.md)
- 本文件的英文版：[README.md](README.md)


## 许可

[MIT](LICENSE) © ready2run

## 致谢

- [OpenCASCADE Technology](https://dev.opencascade.org/) —— CAD 内核
- [GMSH](https://gmsh.info/) —— 有限元网格生成器
- [VTK](https://vtk.org/) —— 可视化工具包
- [PythonOCC](https://github.com/tpaviot/pythonocc-core) —— OCC 的 Python 绑定
- [Geant4](https://geant4.web.cern.ch/) —— GDML 几何格式
- [CodeBuddy](https://www.codebuddy.ai/) 与 [DeepSeek](https://deepseek.com/) —— 本项目开发过程中的 AI 辅助
