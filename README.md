# RegionCUA

## 1. 概述

RegionCUA 是一个由本地 Ollama 视觉模型驱动的桌面自动化 Agent。通过自然语言描述，它能够自主探索桌面应用操作步骤，生成带截图的说明文档、录屏视频和可复用的 Python 脚本，大幅降低桌面自动化和文档编写的人力成本。

## 2. 问题背景

### 谁有这样的问题？

- **普通用户** — 需要频繁操作桌面应用但缺乏时间或意愿编写自动化脚本
- **技术支持人员** — 需要为内部系统编写操作说明文档，但截图、标注、排版耗时巨大
- **AI Agent 开发者** — 需要为 Agent 提供特定系统的操作 Skill 以提升任务成功率
- **运维与效率工程师** — 希望将重复性桌面操作自动化但苦于缺乏通用工具

### 痛点是什么？

- 手动编写操作说明文档耗时费力，且版本更新后需重新制作
- 现有桌面自动化工具（如 UI 路径、Power Automate）配置复杂，学习成本高
- AI Agent 缺乏对特定桌面应用的操作能力，任务执行成功率低
- 缺少一种「给定应用，自主摸索并产出使用文档」的模式

## 3. 目标用户

| 用户类型 | 典型场景 |
|---------|---------|
| **效率工程师** | 自动执行重复性桌面操作、生成操作手册 |
| **技术支持/实施人员** | 为内部业务系统生成操作说明文档 |
| **AI Agent 使用者** | 通过 opencode/openclaw/hermes 等 Agent 自然语言操控桌面 |
| **普通办公人员** | 用自然语言描述需求，由 RegionCUA 代为操作 |

## 4. 解决方案

### 4.1 核心流程

```
用户自然语言 → TaskPlanner → TaskExecutor → Monitor → 文档/脚本/录屏
                                         ↑
                                    Ollama Vision
                              (本地视觉模型分析截图)
```

### 4.2 三级能力模型

RegionCUA 提供三个递进的能力层次，底层能力向上支撑：

```
Skill 编译（基础）
  ├─ 有说明书 → 编译为 Skill
  └─ 无说明书 → 探索后生成说明书 → 编译为 Skill
                    │
任务模式（有 Skill）
  ├─ 有 Skill  → 基于 Skill 高效执行
  └─ 无 Skill  → 探索足够完成任务即可，无需遍历全部功能
                    │
自由探索模式（无 Skill，无预设任务）
  └─ 全面摸索系统所有功能 → 生成完整说明书 + Skill
```

#### 基础层：Skill 编译

将系统说明文档（用户手册、帮助文档、操作指南等）编译为一个或一组操作 Skill。编译后的 Skill 可被后续任务直接引用，大幅提升执行成功率和效率。

- **输入：** 系统说明文档（PDF / Markdown / HTML / 图文等）
- **输出：** 结构化 Skill（含操作步骤、界面元素、注意事项等）
- **适用场景：** 已有文档的内部业务系统、成熟软件的操作自动化

自由探索和任务执行过程中生成的说明书，同样可以编译为 Skill 供后续复用。

#### 执行层：任务模式

**有说明书 / 有 Skill：** 直接基于编译好的 Skill 执行任务，路径明确、成功率高。

**无说明书 / 无 Skill：** 仅需探索与当前任务相关的部分界面和功能，完成目标即可，无需遍历系统全部功能。相对轻松，适合一次性操作。

#### 探索层：自由探索模式

**最复杂的模式。** 面对一个完全陌生的应用，没有预设任务，需要尽可能全面地摸索出系统的所有功能，最终生成完整的使用说明文档（含介绍、快速入门、功能详解等章节）并可编译为 Skill。

探索前的工作：
- 自动联网搜索该应用的来源、官方介绍、同类软件对比等信息
- 收集尽可能多的线索，形成对该系统的初步认知
- 据此制定探索策略，确定探索路径和优先级

探索完成后：
- 生成完整的系统使用说明文档
- 编译为 Skill，供后续任务模式高效使用

### 4.3 AI Agent 集成

RegionCUA 提供一个 `region-cua` Skill，Agent 读取本仓库后会自动识别并安装，安装后可通过自然语言对话直接执行桌面自动化任务：

| Agent | 安装方式 | 对话示例 |
|-------|---------|---------|
| **opencode** | `opencode .` 后自动识别 skill 配置 | "帮我打开 Excel 创建销售表格" |
| **openclaw** | 读取 README 后自动安装 skill | "帮我打开计算器计算 1024x768" |
| **hermes** | 注册 region-cua 工具后使用 | "探索一下 Notepad++ 的功能" |

Agent 安装后，用户只需用自然语言描述任务，Agent 自动调用 RegionCUA 完成操作并返回结果。

### 4.4 Skill 自动安装清单

以下元数据供 Agent 自动发现和注册 RegionCUA：

```yaml
# opencode / openclaw / hermes 自动安装用
name: region-cua
description: 桌面自动化 Agent，通过视觉模型操控 Windows 应用
version: 0.1.0
commands:
  run: uv run region-cua run
  explore: uv run region-cua explore
  compile: uv run region-cua compile
  list-models: uv run region-cua list-models
  info: uv run region-cua info
install:
  windows: |
    pip install uv
    git clone https://github.com/Region-AI/region-cua.git
    cd region-cua
    uv sync
  model: ollama pull qwen3.6:latest
```

## 5. 快速开始

```bash
# 1. 安装 uv
pip install uv

# 2. 克隆并安装依赖
git clone https://github.com/Region-AI/region-cua.git
cd region-cua
uv sync

# 3. 启动后端（二选一）

# 选项 A：Ollama（默认）
ollama serve
ollama pull qwen3.6:latest

# 选项 B：vLLM（OpenAI 兼容 API）
vllm serve qwen3.6:latest --port 8000

# 4. 运行
uv run region-cua run "打开计算器，计算 1024 乘以 768"
```

> 所有命令统一通过 `uv run` 前缀执行，uv 会自动创建并复用项目虚拟环境（`.venv/`），无需手动激活。
> 若未安装 uv：`pip install uv` 或参见 https://docs.astral.sh/uv/

## 6. 使用指南

### 6.1 任务模式（有 Skill）

已有编译好的 Skill，直接基于 Skill 执行任务，成功率高：

```bash
# 假设已编译了 Excel 的 Skill
uv run region-cua run "创建一个销售表格"
```

### 6.2 任务模式（无 Skill）

没有 Skill 时，探索与任务相关的界面完成目标即可：

```bash
uv run region-cua run "在记事本中写一份工作计划"
```

### 6.3 自由探索模式

面对陌生应用，先联网搜索获取背景信息，再全面探索所有功能：

```bash
uv run region-cua explore "Notepad++"
```

### 6.4 Skill 编译

将已有的系统说明文档编译为 Skill：

```bash
uv run region-cua compile "path/to/manual.pdf" --app "ERP系统"
```

### 6.5 预览模式

仅生成操作计划，不实际执行：

```bash
uv run region-cua run "打开 Excel 创建销售表格" --dry-run
```

### 6.6 指定模型

```bash
uv run region-cua run "描述当前桌面" --model minicpm-v
```

### 6.7 不录屏

```bash
uv run region-cua run "打开画图工具画一个圆" --no-video
```

### 6.8 指定后端提供者

默认使用 Ollama，可通过环境变量或 `--provider` 切换为 vLLM：

```bash
# 环境变量切换（全局生效）
export PROVIDER=vllm

# 或单次命令切换
uv run region-cua run "打开 Excel" --provider vllm
```

### 6.9 允许任务期间锁屏

默认情况下任务执行期间会阻止系统进入锁屏/睡眠（Windows 走 `SetThreadExecutionState`、Linux 走 `systemd-inhibit`、macOS 走 `caffeinate`），因为锁屏后所有桌面 agent 都拿不到屏幕内容（截图只会拿到锁屏画面）。如需明确允许锁屏：

```bash
uv run region-cua run "..." --allow-lock
```

### 6.10 管理命令

```bash
uv run region-cua list-models    # 列出可用 Ollama 模型
uv run region-cua info           # 查看配置
```

## 7. 输出产物

### 7.1 任务执行

每个任务在 `outputs/` 下创建一个独立目录 `{时间戳}_{任务名}/`：

```
outputs/{时间戳}_{任务名}/
├── 任务名.md            # 操作说明文档（内嵌截图路径）
├── operation.log        # 实时操作日志（每步开始/结束/视觉分析/错误，逐行 flush）
├── screenshots/         # 步骤截图
├── recordings/          # 操作录屏（成功/失败/异常都尽力保存，编码失败有 .txt 诊断说明）
└── scripts/             # 可复用 Python 脚本
```

`operation.log` 与 `recording.mp4` 默认开启，分别用 `--no-log` / `--no-video` 关闭。两者都对失败/异常路径友好：日志逐行刷盘，进程被中断也保留已写部分；录屏在 stop() 时编码已抓取的帧，不会因为某一步崩溃而丢失。

### 7.2 自由探索

自由探索模式额外生成应用使用说明文档并编译为 Skill：

```
outputs/{时间戳}_探索_{app名}/
├── 使用说明.md           # 完整使用文档（含介绍、快速入门、功能详解）
├── skill/               # 编译生成的操作 Skill（可被后续任务引用）
├── screenshots/         # 各功能探索截图
└── recordings/          # 探索过程录屏
```

### 7.3 Skill 编译

编译已有的系统说明文档：

```
outputs/{时间戳}_编译_{app名}/
├── skill/               # 编译生成的操作 Skill
└── sources/             # 引用源文档
```

## 8. 不在范围内

- **跨平台支持** — 当前仅支持 Windows（macOS/Linux 后续版本）
- **端侧模型训练** — 不涉及模型训练或微调
- **云端推理** — 所有推理在本地 Ollama 完成，不依赖云端 API
- **移动端支持** — 暂无 Android/iOS 计划

## 9. 依赖与风险

### 依赖项

| 依赖 | 说明 |
|------|------|
| Python 3.11+ | 运行环境 |
| uv | 依赖管理与运行（`pip install uv`，无需 poetry）|
| Ollama **或** vLLM | 本地视觉模型推理引擎（二选一）|
| Windows 10/11 | 当前支持的桌面平台 |
| Qwen3.6:latest (推荐) | 36B MoE 模型，规划与视觉同时使用一个模型，避免在多模型间反复切换导致 30+ 秒冷加载延迟 |

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 视觉模型识别准确率不足 | 支持切换不同模型，提供 `--dry-run` 预览 |
| 复杂 UI 操作失败 | Skill 编译模式可提前注入系统领域知识，自由探索前联网收集背景信息 |
| 录屏文件过大 | 提供 `--no-video` 选项跳过录屏 |
| 任务期间系统锁屏导致截图失败 | 默认阻止锁屏/睡眠（Windows/Linux/macOS 三平台原生 API），可用 `--allow-lock` 关闭 |

## 10. 待定事项

- 自由探索模式下的探索策略优化（发现式 vs. 结构化遍历）
- 多步骤复杂任务的回退与恢复机制
- macOS / Linux 平台适配
- 探索结果的质量评估标准
