# AB 实验工作流 — 开发文档

> 分支: `ds_0515_log` | 版本: v1.0 | 日期: 2025-06

---

## 1. 概述

AudioForge 当前支持单一 `AudioProject` 的编辑与全量/增量导出。本需求在其上层引入 **实验工作区(Experiment Workspace)** 概念，允许策划在同一底板工程上创建多个实验任务，每个任务可包含多个方案（Variant），通过增量 JSON 导出供 Unity 端实现 AB 实验。

### 1.1 核心目标

1. **不侵入现有 `AudioProject` 模型**——实验工作区作为套壳层，复用现有编辑器全部能力
2. **增量导出**——只输出差异 Event/参数，Unity 端通过 JSON overlay 合成运行时数据
3. **编辑隔离**——不同实验方案可独立编辑同一底板工程的不同 Event，互不干扰
4. **完整生命周期**——draft → active → archived → merged

### 1.2 术语约定

| 术语 | 含义 |
|---|---|
| **底板工程 (Base Project)** | 常规 `.afproj` 工程，所有实验共享的基准数据 |
| **实验工作区 (ExperimentWorkspace)** | `.afws` 文件，管理底板引用 + 任务列表 + 激活状态 |
| **实验任务 (ExperimentTask)** | 策划视角的实验单元，如"点击音效测试" |
| **方案 (ExperimentVariant)** | 导出增量的最小单元，每个方案拥有一份独立的底板 `.afproj` 副本 |
| **增量 JSON (Delta JSON)** | 对比底板，只包含差异 Event 的导出文件 |
| **Op 字段** | `add` / `modify` / `delete`，标注每个 Event 的变更类型 |

---

## 2. 确认的设计决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | 实验能否新增底板不存在的 Event？ | ✅ 可以，Op=add |
| 2 | 全局参数（GameParameter/StateGroup/SwitchGroup）| 定义底板独占不可改，使用（RTPC 曲线/State 效果）实验可自由修改 |
| 3 | 生命周期 | draft → active → archived → merged |
| 4 | Unity 端合并 | Unity 自行控制，本工具只导出增量 JSON |
| 5 | Event 覆盖 key | 使用 event name 自然匹配 |
| 6 | 实验结构 | Task → Variant 两层，单方案时 Variant 列表长度=1 |
| 7 | 多人协作 | 有需求，本期不实现，预留扩展点 |
| 8 | 底板修改同步 | 不自动同步到实验副本，由用户手动触发 |
| 9 | 多实验叠加 | Unity 端控制，本期不涉及 |

---

## 3. 数据模型设计

### 3.1 新增模型

文件: `audioforge/app/models/experiment_workspace.py`

```python
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

class ExperimentLifecycle(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    MERGED = "merged"

@dataclass(slots=True)
class ExperimentVariant:
    """实验方案——独立拥有一份底板工程副本"""
    id: str                          # variant_xxxx
    name: str                        # 方案名，如 "a1"、default"
    lifecycle: ExperimentLifecycle = ExperimentLifecycle.DRAFT
    base_project_copy_path: str = "" # 该方案的 .afproj 副本路径（相对于 workspace 目录）
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

@dataclass(slots=True)
class ExperimentTask:
    """实验任务——策划视角的实验单元"""
    id: str                          # task_xxxx
    name: str                        # 如 "A组 - click音效测试"
    variants: list[ExperimentVariant] = field(default_factory=list)
    active_variant_index: int = 0    # 当前激活的方案索引
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

@dataclass(slots=True)
class ExperimentWorkspace:
    """实验工作区——套壳工程"""
    name: str                        # 工作区名称
    file_path: str = ""              # .afws 文件路径
    base_project_path: str = ""      # 底板工程 .afproj 相对路径
    source_audio_root: str = ""      # 共享源音频根目录
    tasks: list[ExperimentTask] = field(default_factory=list)
    active_task_index: int = 0
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
```

### 3.2 与现有模型的关系

```
ExperimentWorkspace (.afws)
├── base_project_path → 底板 AudioProject (.afproj)
├── ExperimentTask
│   └── ExperimentVariant
│       └── base_project_copy_path → 副本 AudioProject (.afproj)
└── source_audio_root → 共享（所有副本引用同一个源音频目录）
```

- **不修改** `AudioProject`、`EventModel`、`AudioObjectModel` 等现有模型
- 每个 `ExperimentVariant` 持有一份底板 `.afproj` 的文件副本
- 编辑某个方案时，实际加载并编辑该方案的副本 `.afproj`

---

## 4. 文件格式

### 4.1 工作区文件 `.afws`

```json
{
  "SchemaVersion": 1,
  "Type": "ExperimentWorkspace",
  "Name": "AB_ClickSFX",
  "BaseProjectPath": "base_project.afproj",
  "SourceAudioRoot": "../AudioSources",
  "Tasks": [
    {
      "Id": "task_a1b2c3",
      "Name": "A组 - click音效测试",
      "ActiveVariantIndex": 0,
      "Variants": [
        {
          "Id": "variant_d4e5f6",
          "Name": "调小音量",
          "Lifecycle": "active",
          "BaseProjectCopyPath": "variants/task_a1b2c3/variant_d4e5f6.afproj",
          "Notes": "",
          "CreatedAt": "2025-06-01T10:00:00Z",
          "UpdatedAt": "2025-06-01T12:00:00Z"
        },
        {
          "Id": "variant_g7h8i9",
          "Name": "换音源",
          "Lifecycle": "draft",
          "BaseProjectCopyPath": "variants/task_a1b2c3/variant_g7h8i9.afproj",
          "Notes": "",
          "CreatedAt": "2025-06-01T10:00:00Z",
          "UpdatedAt": "2025-06-01T11:30:00Z"
        }
      ],
      "Notes": "",
      "CreatedAt": "2025-06-01T10:00:00Z",
      "UpdatedAt": "2025-06-01T12:00:00Z"
    }
  ],
  "ActiveTaskIndex": 0,
  "Notes": "click 音效 AB 实验",
  "CreatedAt": "2025-06-01T09:00:00Z",
  "UpdatedAt": "2025-06-01T12:00:00Z"
}
```

### 4.2 工作区目录结构

```
my_experiment.afws           ← 工作区文件
base_project.afproj          ← 底板工程
variants/                    ← 各方案副本
  task_a1b2c3/
    variant_d4e5f6.afproj    ← 方案副本
    variant_g7h8i9.afproj
  task_x7y8z9/
    variant_default.afproj
```

> `.afws` 实质是一个 JSON 文件，关联目录下的各 `.afproj` 副本。

### 4.3 增量导出 JSON 格式

文件: `Experiment_<TaskId>_<VariantId>.json`

```json
{
  "SchemaVersion": 3,
  "ExportType": "ExperimentDelta",
  "ExperimentId": "variant_d4e5f6",
  "TaskId": "task_a1b2c3",
  "TaskName": "A组 - click音效测试",
  "VariantName": "调小音量",
  "BaseProjectHash": "sha256:abc123...",
  "ExportTimestamp": "2025-06-01T12:30:00Z",
  "Events": {
    "sfx_click": {
      "Op": "modify",
      "Audio": {
        "VolumeDb": -8.0,
        "PitchCents": 0,
        "Clips": []
      },
      "MaxInstances": 3
    },
    "sfx_new_achievement": {
      "Op": "add",
      "Audio": {
        "Bus": "SFX",
        "PlayMode": "OneShot",
        "VolumeDb": -6.0,
        "PitchCents": 0,
        "Clips": [
          {
            "ClipId": "clip_new_001",
            "AssetKey": "sfx_new_achievement_001",
            "Weight": 100
          }
        ]
      },
      "MaxInstances": 2
    },
    "sfx_old_alert": {
      "Op": "delete"
    }
  },
  "Assets": [
    {
      "AssetKey": "sfx_new_achievement_001",
      "ExportPath": "Assets/sfx_new_achievement_001.ogg",
      "SourcePath": "new_achievement.wav"
    }
  ]
}
```

**三种子格式说明:**

| 场景 | Op | Clips 字段 | 说明 |
|---|---|---|---|
| 调参 | `modify` | `[]` (空数组) | 只改参数，Unity 复用底板 ogg |
| 替换音源 | `modify` | `[新Clip]` | 换音频文件，新 ogg 随增量包一起导出 |
| 新增音效 | `add` | `[Clip]` | 全新 Event，所有字段必填 |
| 删除音效 | `delete` | 无 | 仅标记删除 |

---

## 5. 功能架构

### 5.1 模块依赖图

```
┌──────────────────────────────────────────────────┐
│                    UI Layer                       │
│  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ TopBar       │  │ ExperimentPanel (Sidebar)│   │
│  │ Experiment   │  │ Task/Variant 切换        │   │
│  │ Switcher     │  │ 任务管理/方案管理         │   │
│  └──────┬───────┘  └───────────┬─────────────┘   │
│         │                      │                  │
│  ┌──────┴──────────────────────┴─────────────┐   │
│  │          MainWindow (扩展)                 │   │
│  │  - 新增 mode: "experiment"                │   │
│  │  - Transport 区 A/B 对比预览              │   │
│  └──────────────────┬────────────────────────┘   │
└─────────────────────┼────────────────────────────┘
                      │
┌─────────────────────┼────────────────────────────┐
│                  Controller                       │
│  ┌──────────────────┴────────────────────────┐   │
│  │  ExperimentController                     │   │
│  │  - 管理工作区/任务/方案切换                │   │
│  │  - 委托 MainController 加载方案副本       │   │
│  │  - 协调增量导出                           │   │
│  └──────────────────┬────────────────────────┘   │
│                     │                             │
│  ┌──────────────────┴────────────────────────┐   │
│  │       MainController (不修改)             │   │
│  │  - 正常加载/编辑/保存 .afproj             │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
                      │
┌─────────────────────┼────────────────────────────┐
│                  Services                         │
│  ┌──────────────────┴────────────┐                │
│  │ ExperimentWorkspaceSerializer │                │
│  │ .afws 文件的读写/方案副本管理  │                │
│  └───────────────────────────────┘                │
│  ┌───────────────────────────────┐                │
│  │ ExperimentExporter            │                │
│  │ 增量导出：对比底板→方案差异    │                │
│  └───────────────────────────────┘                │
│  ┌───────────────────────────────┐                │
│  │ RuntimeExporter (不修改)      │                │
│  │ 底板全量/增量导出              │                │
│  └───────────────────────────────┘                │
└───────────────────────────────────────────────────┘
                      │
┌─────────────────────┼────────────────────────────┐
│                  Models                           │
│  ┌──────────────┐   ┌────────────────────────┐   │
│  │ AudioProject │   │ ExperimentWorkspace    │   │
│  │ (不修改)     │   │ ExperimentTask         │   │
│  │              │   │ ExperimentVariant      │   │
│  └──────────────┘   └────────────────────────┘   │
└───────────────────────────────────────────────────┘
```

### 5.2 核心交互流程

#### 5.2.1 创建实验工作区

```
用户 → TopBar "新建实验" → 弹窗选择底板 .afproj
→ ExperimentWorkspaceSerializer.create(workspace_path, base_project_path)
  → 复制底板 .afproj → 生成 .afws
  → workspace 目录初始化（variants/ 子目录）
→ 切换到 experiment 模式
```

#### 5.2.2 创建实验任务与方案

```
用户 → ExperimentPanel "新建任务"
→ workspace.tasks.append(ExperimentTask(name=...))
→ 默认创建 1 个 "default" variant
  → 复制底板 .afproj 作为副本到 variants/<task_id>/<variant_id>.afproj
→ 保存 .afws
```

#### 5.2.3 编辑实验方案

```
用户 → ExperimentPanel 选中某 variant → 双击
→ ExperimentController.load_variant(workspace, task_id, variant_id)
  → MainController.open_project(variant.base_project_copy_path)
  → 进入 events 模式正常编辑
→ 编辑的工程就是那份 .afproj 副本
```

#### 5.2.4 增量导出

```
用户 → Build 页面选择 "增量导出" + 选择 Task/Variant
→ ExperimentExporter.export_delta(workspace, task_id, variant_id, export_root)
  → 加载底板 AudioProject (base_project.afproj)
  → 加载方案 AudioProject (variant.afproj)
  → 逐 Event 对比差异：
    - 方案有而底板无 → Op: add
    - 底板有而方案无 → Op: delete
    - 两边都有但数据不同 → Op: modify
  → 生成增量 JSON（含 Op 字段）
  → 导出新增/变更的 ogg 资源
→ 输出: ExperimentDelta_<taskId>_<variantId>.json + Assets/
```

#### 5.2.5 A/B 对比预览（Transport 区域）

```
用户 → Transport 区域 "A/B 对比" 按钮
→ 加载底板对应 Event 的播放参数 (A)
→ 加载方案对应 Event 的播放参数 (B)
→ 点击 Play A / Play B 快速切换试听
```

---

## 6. 实现计划 — 文件变更清单

### Phase 1: 数据模型 & 序列化

| 操作 | 文件 | 说明 |
|---|---|---|
| **新建** | `app/models/experiment_workspace.py` | `ExperimentWorkspace`, `ExperimentTask`, `ExperimentVariant`, `ExperimentLifecycle` |
| **新建** | `app/services/experiment_serializer.py` | `ExperimentWorkspaceSerializer` — `.afws` 读写、方案副本创建/管理 |
| **新建** | `app/controllers/experiment_controller.py` | `ExperimentController(QObject)` — 管理工作区状态、任务/方案切换 |
| **修改** | `app/utils/constants.py` | 新增 `WORKSPACE_EXTENSION = ".afws"` |

### Phase 2: 编辑隔离 & 底板同步

| 操作 | 文件 | 说明 |
|---|---|---|
| **新建** | `app/services/edit_lock_service.py` | `EditLockService` — 记录哪些 Event 正被哪个 Variant 编辑，防止冲突 |
| **修改** | `app/controllers/experiment_controller.py` | 集成 EditLockService，切换方案时加锁/解锁 |

### Phase 3: 导出管线

| 操作 | 文件 | 说明 |
|---|---|---|
| **新建** | `app/services/experiment_exporter.py` | `ExperimentExporter` — 对比底板与方案，生成增量 JSON + 导出资源 |

### Phase 4: UI 集成

| 操作 | 文件 | 说明 |
|---|---|---|
| **新建** | `app/widgets/experiment_switcher.py` | TopBar 中的实验切换下拉框 |
| **新建** | `app/widgets/experiment_panel.py` | 左侧 ExperimentPanel — 任务列表/方案列表/状态管理 |
| **修改** | `app/views/main_window.py` | 新增 `"experiment"` mode page，TopBar 集成 ExperimentSwitcher |
| **修改** | `app/views/shell_components.py` | TaskSidebar 新增 "实验" 按钮 |
| **修改** | `app/controllers/main_controller.py` | 与 ExperimentController 协作，Build 页面增加增量导出入口 |

### Phase 5: 验收测试

| 操作 | 文件 | 说明 |
|---|---|---|
| **新建** | `tests/test_experiment_models.py` | 数据模型单元测试 |
| **新建** | `tests/test_experiment_serializer.py` | 序列化/反序列化测试 |
| **新建** | `tests/test_experiment_exporter.py` | 增量导出测试 |

---

## 7. 关键接口设计

### 7.1 ExperimentWorkspaceSerializer

```python
class ExperimentWorkspaceSerializer:
    @staticmethod
    def save(workspace: ExperimentWorkspace, path: Path | None = None) -> None:
        """保存 .afws 文件"""

    @staticmethod
    def load(path: Path) -> ExperimentWorkspace:
        """加载 .afws 文件"""

    @staticmethod
    def create(workspace_path: Path, base_project_path: Path, name: str) -> ExperimentWorkspace:
        """创建新工作区：初始化目录、复制底板"""

    @staticmethod
    def create_variant_copy(workspace: ExperimentWorkspace, task_index: int, variant_index: int) -> None:
        """为指定方案创建底板副本"""

    @staticmethod
    def sync_variant_from_base(workspace: ExperimentWorkspace, task_index: int, variant_index: int) -> None:
        """手动从底板同步到方案（可选覆盖策略：全部覆盖/仅新增 Event）"""
```

### 7.2 ExperimentExporter

```python
@dataclass(slots=True)
class ExperimentDeltaResult:
    delta_file: Path          # ExperimentDelta_<taskId>_<variantId>.json
    assets_dir: Path          # Assets/ 目录
    report: dict[str, object] # 导出报告

class ExperimentExporter:
    def export_delta(
        self,
        base_project: AudioProject,
        variant_project: AudioProject,
        task: ExperimentTask,
        variant: ExperimentVariant,
        export_root: Path,
    ) -> ExperimentDeltaResult:
        """对比底板和方案，生成增量导出"""

    def _compute_event_deltas(
        self,
        base_project: AudioProject,
        variant_project: AudioProject,
    ) -> dict[str, dict[str, object]]:
        """计算 Event 差异，返回 {event_name: {Op: ..., ...}}"""

    def _serialize_delta_event(
        self,
        op: str,
        event: EventModel | None,  # add/modify 时有值
    ) -> dict[str, object]:
        """序列化单个增量 Event"""
```

### 7.3 ExperimentController

```python
class ExperimentController(QObject):
    # Signals
    workspaceChanged = Signal(object)           # ExperimentWorkspace | None
    activeTaskChanged = Signal(object)          # ExperimentTask | None
    activeVariantChanged = Signal(object)       # ExperimentVariant | None
    variantProjectLoaded = Signal(object)       # 加载了方案的 .afproj

    def __init__(self, main_controller: MainController):
        ...

    def create_workspace(self, workspace_path: str, base_project_path: str) -> None: ...
    def open_workspace(self, path: str) -> None: ...
    def close_workspace(self) -> None: ...
    def save_workspace(self) -> None: ...

    def create_task(self, name: str) -> None: ...
    def delete_task(self, task_index: int) -> None: ...
    def create_variant(self, task_index: int, name: str) -> None: ...
    def delete_variant(self, task_index: int, variant_index: int) -> None: ...
    def duplicate_variant(self, task_index: int, variant_index: int, new_name: str) -> None: ...

    def activate_variant(self, task_index: int, variant_index: int) -> None:
        """激活方案 → 加载该方案的 .afproj 副本"""

    def set_task_lifecycle(self, task_index: int, lifecycle: ExperimentLifecycle) -> None: ...
    def sync_from_base(self, task_index: int, variant_index: int) -> None: ...

    def export_delta(self, task_index: int, variant_index: int, export_root: str) -> None: ...
```

---

## 8. UI 设计

### 8.1 TopBar — 实验切换器

在 TopBar 右侧（`save_project_button` 之后），新增 `ExperimentSwitcher`：

```
[ 工程: MyProject ] [ 💡实验: A组 / 调小音量 ▼ ] [ 保存 ]
```

- 下拉框展示: `任务名 / 方案名`
- 点击弹出菜单: 切换任务、切换方案、管理任务…
- 未打开实验工作区时显示 `[ 实验模式未开启 ]` 并置灰

### 8.2 TaskSidebar — 新增"实验"按钮

在现有模式列表中新增一行：

```
home        → 首页
resources   → 资源整理
events      → 事件设计
gamesync    → GameSync
buses       → Bus 混音台
validation  → 校验修复
build       → 构建交付
results     → 结果中心
experiment  → AB 实验    ← 新增
```

### 8.3 实验模式页面 (experiment mode)

```
┌─────────────────────────────────────────────────────┐
│  AB 实验                                             │
├───────────────────────┬─────────────────────────────┤
│  实验任务面板          │  方案详情 & 编辑区            │
│                       │                             │
│  任务列表:             │  当前方案: 调小音量           │
│  ● A组-click测试 (2)  │  状态: active                │
│  ○ B组-BGM测试 (1)    │  编辑底板副本 →              │
│                       │  增量预览 →                  │
│  [+ 新建任务]         │  [导出增量] [同步底板]        │
│                       │                             │
│                       │  ─── 增量预览 ───            │
│                       │  sfx_click: modify           │
│                       │    VolumeDb: -8.0            │
│                       │  sfx_new: add                │
│                       │    Bus: SFX ...              │
└───────────────────────┴─────────────────────────────┘
```

### 8.4 构建交付页面 — 增量导出入口

在现有 `build` 模式的构建页面中，新增一个 Tab "实验增量导出"：

```
[ 全量构建 | 选区构建 | 实验增量导出 ← 新增 ]
```

点击后展示：
- 选择任务 + 方案
- 预览增量差异（Event 列表 + Op 标签）
- 导出按钮

### 8.5 Transport — A/B 对比

在 Transport 区域新增 A/B 切换按钮（仅实验模式可见）：

```
[A▶ 底板] [B▶ 方案] [🔄 对比]
```

---

## 9. 增量差异计算算法

```python
def _compute_event_deltas(
    self,
    base_project: AudioProject,
    variant_project: AudioProject,
) -> dict[str, dict[str, object]]:
    """核心对比逻辑"""

    base_events = {e.name: e for e in base_project.events.values()}
    variant_events = {e.name: e for e in variant_project.events.values()}

    deltas: dict[str, dict[str, object]] = {}

    # 方案有而底板无 → add
    for name in set(variant_events) - set(base_events):
        deltas[name] = {
            "Op": "add",
            **self._serialize_full_event(variant_events[name]),
        }

    # 底板有而方案无 → delete
    for name in set(base_events) - set(variant_events):
        deltas[name] = {"Op": "delete"}

    # 两边都有 → 检测是否有差异
    for name in set(base_events) & set(variant_events):
        base_event = base_events[name]
        variant_event = variant_events[name]
        diff = self._diff_event(base_event, variant_event)
        if diff:
            deltas[name] = {"Op": "modify", **diff}

    return deltas

def _diff_event(self, base: EventModel, variant: EventModel) -> dict | None:
    """对比两个 Event 的差异，返回差异字段字典，无差异返回 None"""
    # 对比 MaxInstances, CooldownSeconds, StealPolicy
    # 对比 Audio 的 VolumeDb, PitchCents, PlayMode, Clips 等
    # 只有不同的字段才包含在返回值中
```

---

## 10. 验收标准

### 10.1 功能验收

| # | 验收项 | 预期行为 |
|---|---|---|
| F1 | 创建实验工作区 | 选择底板 .afproj → 生成 .afws + 目录结构 |
| F2 | 创建实验任务 | 任务出现在任务列表，默认含 1 个 "default" 方案 |
| F3 | 创建新增方案 | 基于底板创建副本，方案列表刷新 |
| F4 | 编辑方案 | 双击方案 → 底板副本加载到编辑器 → 正常编辑 → 保存 |
| F5 | 增量导出 — 调参 | 修改 VolumeDb → 导出 → JSON 仅含 Op:modify + VolumeDb |
| F6 | 增量导出 — 替换音源 | 换 clip → 导出 → JSON 含 Op:modify + Clips + ogg 资源 |
| F7 | 增量导出 — 新增 Event | 新增底板没有的 Event → 导出 → JSON 含 Op:add + 完整数据 |
| F8 | 增量导出 — 删除 Event | 删除底板已有的 Event → 导出 → JSON 含 Op:delete |
| F9 | 多任务/多方案 | 创建 2+ 任务，每任务 2+ 方案，独立编辑不影响 |
| F10 | 底板同步 | 手动触发同步 → 方案副本 Event 被底板更新覆盖（可撤销） |
| F11 | 生命周期 | draft → active（导出时自动）→ archived → merged |
| F12 | A/B 对比预览 | Transport 区可切换底板/方案试听 |

### 10.2 非功能验收

| # | 验收项 | 标准 |
|---|---|---|
| N1 | 不影响现有功能 | 无实验模式时，所有现有功能完全不受影响 |
| N2 | 导出性能 | 增量导出 ≤ 3s（100 Event 以内） |
| N3 | 文件兼容性 | 现有 `.afproj` 文件无需任何变更即可作为底板 |

---

## 11. 测试计划

### 11.1 单元测试

- `test_experiment_models.py`: 数据模型构造、序列化、默认值
- `test_experiment_serializer.py`: `.afws` 读写、方案副本创建
- `test_experiment_exporter.py`: 增量计算正确性（add/modify/delete 各场景）

### 11.2 集成测试

- 创建工作区 → 创建任务 → 编辑方案 → 增量导出 → 验证 JSON 内容
- 多方案并发编辑互不干扰

### 11.3 手工验收

- 完整用户流程走一遍
- Transport A/B 对比试听

---

## 12. 里程碑

| 阶段 | 内容 | 预计文件数 |
|---|---|---|
| **Phase 1** | 数据模型 + 序列化 + Controller 骨架 | 新建 3 文件，修改 1 文件 |
| **Phase 2** | 编辑隔离 + 底板同步 | 新建 1 文件 |
| **Phase 3** | 增量导出管线 | 新建 1 文件 |
| **Phase 4** | UI 集成 | 新建 2 文件，修改 3 文件 |
| **Phase 5** | 测试 + 验收修复 | 新建 3+ 文件 |

---

*文档结束。开始实施请从 Phase 1 着手。*

---

## 附录：实施状态 (截至当前提交)

### Phase 1: 数据模型 & 序列化 — ✅ 完成
- `experiment_workspace.py` — 数据模型 + 序列化 round-trip 通过
- `experiment_serializer.py` — CRUD 全部测试通过 (create/save/load/task/variant/duplicate/delete)
- `experiment_controller.py` — 控制器骨架完成
- `constants.py` — `WORKSPACE_EXTENSION` 已添加

### Phase 2: 编辑隔离 — ⏳ 延期
- `edit_lock_service.py` — 优先级较低，用户可手动管理，暂不实现

### Phase 3: 导出管线 — ✅ 完成
- `experiment_exporter.py` — 增量导出 (Delta JSON + 资源 materialization) 完成
- 支持事件级别 diff (add/modify/delete)

### Phase 4: UI 集成 — ✅ 完成
- `experiment_switcher.py` — 顶部栏实验方案切换下拉框 ✅
- `experiment_panel.py` — 左侧面板 (任务/方案树, 增量预览) ✅
- `main_window.py` — experiment 模式页面注册, ExperimentSwitcher 挂载到 TopBar ✅
- `shell_components.py` — 侧栏 "AB 实验" 按钮 ✅
- `main_controller.py` — ExperimentController 实例化, 信号绑定, 增量导出协调 ✅

### Phase 5: 验收测试 — 🔄 待用户验收
- 应用可正常启动，无报错 ✅
- 集成 smoke test 通过 ✅
- 手动 GUI 验收待进行
