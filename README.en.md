# RegionCUA

## 1. Executive Summary

RegionCUA is a desktop automation agent powered by local Ollama vision models. Through natural language descriptions, it autonomously explores desktop application workflows, generates step-by-step documentation with screenshots, screencast recordings, and reusable Python scripts — significantly reducing the人力 cost of desktop automation and documentation.

## 2. Problem Statement

### Who Has This Problem?

- **End users** — Need to perform frequent desktop operations but lack time or willingness to write automation scripts
- **Support & implementation teams** — Need to create operation manuals for internal business systems; screenshotting, annotating, and formatting is painfully slow
- **AI Agent developers** — Need operation skills for specific systems to improve task success rates
- **DevOps & productivity engineers** — Want to automate repetitive desktop tasks but lack a universal tool

### What's the Pain?

- Manual operation documentation is time-consuming and must be recreated with every version update
- Existing desktop automation tools (UI Path, Power Automate) are complex to configure with steep learning curves
- AI agents lack the ability to operate specific desktop applications, resulting in low task success rates
- No mode exists for "given an app, explore it autonomously and produce a usage guide"

## 3. Target Users

| User Type | Typical Scenario |
|-----------|-----------------|
| **Productivity Engineer** | Automate repetitive desktop tasks, generate operation manuals |
| **Support / Implementation** | Create operation documentation for internal business systems |
| **AI Agent User** | Control desktop via natural language through opencode/openclaw/hermes agents |
| **Office Worker** | Describe needs in natural language, let RegionCUA handle the rest |

## 4. Solution

### 4.1 Core Pipeline

```
Natural Language → TaskPlanner → TaskExecutor → Monitor → Docs/Scripts/Recording
                                         ↑
                                    Ollama Vision
                              (Local vision model analyzes screenshots)
```

### 4.2 Three-Tier Capability Model

```
Skill Compilation (foundation)
  ├─ Documentation available → Compile into Skill
  └─ No documentation     → Explore → Generate docs → Compile into Skill
                               │
Task Mode (has Skill)
  ├─ Has Skill  → Execute efficiently based on Skill
  └─ No Skill   → Explore only what's needed to complete the task
                               │
Free Exploration Mode (no Skill, no preset task)
  └─ Comprehensively explore all features → Generate full docs + Skill
```

#### Foundation: Skill Compilation

Compile system documentation (user manuals, help docs, operation guides) into one or more operation Skills. Compiled Skills can be directly referenced by subsequent tasks, greatly improving execution success rate and efficiency.

- **Input:** System documentation (PDF / Markdown / HTML / mixed media)
- **Output:** Structured Skill (operation steps, UI elements, caveats, etc.)
- **Use case:** Internal business systems with existing docs, automation of mature software

Documentation generated during free exploration or task execution can also be compiled into Skills for future reuse.

#### Execution: Task Mode

**With documentation / With Skill:** Execute tasks directly based on the compiled Skill — clear path, high success rate.

**Without documentation / Without Skill:** Explore only the relevant UI surfaces and features needed to complete the task. No need to traverse the entire system. Easier, suitable for one-shot operations.

#### Exploration: Free Exploration Mode

**The most complex mode.** Facing a completely unfamiliar application with no preset task, it must comprehensively explore all features and ultimately produce a complete usage guide (introduction, quick start, feature deep-dive, etc.) which can then be compiled into a Skill.

Pre-exploration work:
- Automatically search the web for the app's origin, official introduction, competitor comparisons, etc.
- Gather as many clues as possible to form an initial understanding of the system
- Devise an exploration strategy based on this information, determining exploration paths and priorities

Post-exploration:
- Generate a complete system usage guide
- Compile into a Skill for efficient use in subsequent task mode

### 4.3 AI Agent Integration

RegionCUA provides a `region-cua` Skill that can be integrated into mainstream AI agents to execute desktop automation through natural language conversation:

- **opencode / openclaw** — Install the `region-cua` skill, then have the agent invoke RegionCUA to control the desktop via dialogue
- **hermes** — Describe the task in natural language, Hermes automatically orchestrates RegionCUA execution steps
- Supports all CLI capabilities: `run`, `--dry-run` preview, `--model` selection, etc.

After integration, users can simply say "Open Excel and create a sales spreadsheet" and the agent will automatically invoke RegionCUA to complete the operation.

## 5. Quick Start

```bash
# 1. Ensure Ollama is running
ollama serve

# 2. Pull a vision model (recommended: qwen3.6:latest, 36B MoE, native vision/tools/thinking support)
ollama pull qwen3.6:latest

# 3. Install dependencies (uses uv — no poetry, no manual venv setup)
git clone https://github.com/Region-AI/region-cua.git
cd region-cua
uv sync

# 4. Run
uv run region-cua run "Open Calculator and compute 1024 times 768"
```

> All commands use the `uv run` prefix. UV automatically creates and reuses the project virtual environment (`.venv/`) — no manual activation needed.
> To install uv: `pip install uv` or see https://docs.astral.sh/uv/

## 6. Usage Guide

### 6.1 Task Mode (With Skill)

With a compiled Skill, execute tasks efficiently:

```bash
# Assuming an Excel Skill has been compiled
uv run region-cua run "Create a sales spreadsheet"
```

### 6.2 Task Mode (Without Skill)

Without a Skill, explore just enough to complete the task:

```bash
uv run region-cua run "Write a work plan in Notepad"
```

### 6.3 Free Exploration Mode

For unfamiliar applications, search the web for background info first, then comprehensively explore all features:

```bash
uv run region-cua explore "Notepad++"
```

### 6.4 Skill Compilation

Compile existing system documentation into a Skill:

```bash
uv run region-cua compile "path/to/manual.pdf" --app "ERP System"
```

### 6.5 Preview Mode

Generate an operation plan without executing:

```bash
uv run region-cua run "Create a sales spreadsheet in Excel" --dry-run
```

### 6.6 Specify Model

```bash
uv run region-cua run "Describe current desktop" --model minicpm-v
```

### 6.7 Disable Recording

```bash
uv run region-cua run "Draw a circle in Paint" --no-video
```

### 6.8 Allow Screen Lock During Tasks

By default, RegionCUA prevents the system from locking or sleeping during task execution (Windows uses `SetThreadExecutionState`, Linux uses `systemd-inhibit`, macOS uses `caffeinate`). This is because a locked screen means the desktop agent cannot capture screen content. To explicitly allow screen lock:

```bash
uv run region-cua run "..." --allow-lock
```

### 6.9 Management Commands

```bash
uv run region-cua list-models    # List available Ollama models
uv run region-cua info           # View configuration
```

## 7. Output

### 7.1 Task Execution

Each task creates a directory under `outputs/` named `{timestamp}_{task_name}/`:

```
outputs/{timestamp}_{task_name}/
├── task.md               # Step-by-step documentation (with embedded screenshot paths)
├── operation.log         # Real-time operation log (each step start/end/vision analysis/error, line-buffered)
├── screenshots/          # Step screenshots
├── recordings/           # Screen recording (preserved on success/failure/error; encoding failures produce a .txt diagnostic)
└── scripts/              # Reusable Python scripts
```

`operation.log` and `recording.mp4` are enabled by default and can be disabled with `--no-log` / `--no-video` respectively. Both are failure-tolerant: logs are flushed line-by-line so partial data survives process interruption; recordings encode whatever frames were captured at stop() time, so a crash mid-step doesn't lose everything.

### 7.2 Free Exploration

Free exploration mode additionally generates an application usage guide and compiles it into a Skill:

```
outputs/{timestamp}_explore_{app_name}/
├── usage-guide.md        # Complete usage documentation (introduction, quick start, feature deep-dive)
├── skill/                # Compiled operation Skill (referenceable by future tasks)
├── screenshots/          # Feature exploration screenshots
└── recordings/           # Exploration screen recording
```

### 7.3 Skill Compilation

Compile existing system documentation:

```
outputs/{timestamp}_compile_{app_name}/
├── skill/                # Compiled operation Skill
└── sources/              # Source documents
```

## 8. Out of Scope

- **Cross-platform support** — Currently Windows only (macOS/Linux in future releases)
- **Model training** — No model training or fine-tuning involved
- **Cloud inference** — All inference runs locally via Ollama, no cloud API dependency
- **Mobile support** — No Android/iOS plans at this time

## 9. Dependencies & Risks

### Dependencies

| Dependency | Description |
|-----------|-------------|
| Python 3.11+ | Runtime environment |
| uv | Dependency management & runner (`pip install uv`) |
| Ollama | Local vision model inference engine |
| Windows 10/11 | Currently supported desktop platform |
| Qwen3.6:latest (recommended) | 36B MoE model; planning and vision share one model to avoid 30s+ cold-start latency from Ollama model switching |

### Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Vision model accuracy insufficient | Support model switching, `--dry-run` preview available |
| Complex UI operation failure | Skill compilation injects domain knowledge upfront; free exploration pre-searches web for background context |
| Recording file too large | `--no-video` option to skip recording |
| Screen lock during tasks breaks screenshot capture | Default prevents lock/sleep (native APIs on Windows/Linux/macOS); use `--allow-lock` to override |

## 10. Open Questions

- Exploration strategy optimization for free exploration mode (discovery-driven vs. structured traversal)
- Fallback and recovery mechanism for multi-step complex tasks
- macOS / Linux platform adaptation
- Quality evaluation criteria for exploration results
