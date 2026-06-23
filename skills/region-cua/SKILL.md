---
name: region-cua
description: 桌面自动化 Agent，通过本地视觉模型操控 Windows 应用。安装后可通过自然语言让 Agent 执行桌面操作。
metadata:
  emoji: 🖥️
  category: automation
  platforms: [windows]
  source: https://github.com/Region-AI/region-cua
---

# RegionCUA

桌面自动化 Agent，通过本地 Ollama / vLLM 视觉模型实时分析桌面截图，自主操作 Windows 应用。

## 安装

此 Skill 需配合 RegionCUA 项目使用。Agent 检测到本 Skill 后自动执行以下安装步骤：

```powershell
# 1. 安装 uv（如未安装）
pip install uv

# 2. 克隆仓库
git clone https://github.com/Region-AI/region-cua.git
cd region-cua

# 3. 安装依赖
uv sync

# 4. 拉取视觉模型
ollama pull qwen3.6:latest
```

## 可用命令

所有命令通过 `uv run` 执行，uv 自动管理虚拟环境。

### 执行任务

```
uv run region-cua run "<自然语言任务描述>"
```

选项：
- `--dry-run` — 仅生成计划，不实际执行
- `--model <模型名>` — 指定视觉模型
- `--provider ollama|vllm` — 指定后端提供者
- `--no-video` — 不录屏
- `--no-log` — 不写操作日志
- `--allow-lock` — 允许任务期间锁屏

### 自由探索

```
uv run region-cua explore "<应用名>"
```

自主摸索应用的所有功能，生成完整使用说明文档并编译为 Skill。

### Skill 编译

```
uv run region-cua compile "<文档路径>" --app "<应用名>"
```

将已有的系统说明文档编译为操作 Skill。

### 学习模式

```
# 从已有视频文件学习
uv run region-cua learn "recordings/my_operation.mp4"

# 实时录屏学习（按 Ctrl+C 结束后自动分析）
uv run region-cua learn --record

# 指定涉及的应用（提升识别准确率）
uv run region-cua learn "recordings/demo.mp4" --apps "Excel,Chrome,Notepad"
```

从录屏视频学习操作并生成语义化 Skill。生成的 Skill 不依赖桌面分辨率、窗口位置/大小和应用版本，支持多应用协同工作流。

### 管理

```
uv run region-cua list-models     # 列出可用模型
uv run region-cua info            # 查看配置
```

## 使用示例

| 用户说 | Agent 执行 |
|--------|-----------|
| "帮我打开计算器计算 1024 乘以 768" | `uv run region-cua run "打开计算器，计算 1024 乘以 768"` |
| "在 Excel 里创建一个销售表格" | `uv run region-cua run "打开 Excel 创建销售表格"` |
| "探索一下 Notepad++ 的功能" | `uv run region-cua explore "Notepad++"` |
| "把这个操作手册编译成 Skill" | `uv run region-cua compile "manual.pdf" --app "ERP系统"` |
| "学习这个操作视频生成 Skill" | `uv run region-cua learn "demo.mp4" --apps "Excel,Chrome"` |
| "录屏学习我的操作" | `uv run region-cua learn --record` |

## 工作流

1. 用户用自然语言描述桌面操作任务
2. Agent 调用 `region-cua run` 传给 RegionCUA
3. RegionCUA 规划步骤 → 视觉分析截图 → 执行操作 → 验证结果
4. 返回执行结果和产物路径给用户

## 注意事项

- 当前仅支持 Windows 10/11
- 需要 Ollama 或 vLLM 作为视觉模型推理后端
- 推荐使用 qwen3.6:latest 模型（35B MoE，原生支持 vision/tools/thinking）
- 默认阻止任务期间锁屏（可用 `--allow-lock` 关闭）
