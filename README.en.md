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
Skill Generation (foundation)
  ├─ Doc Compilation  — Documentation available → Compile into Skill
  ├─ Video Learning   — Record operation video → Identify intent → Generate Skill
  └─ Free Exploration — No docs → Explore → Generate docs → Compile into Skill
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

#### Foundation: Learning Mode

Users start a screen recording, operate desktop applications normally, and RegionCUA learns from the operation video to automatically generate a Skill.

**Core mechanism:**
1. Analyze the recording frame-by-frame to identify the active application and window switches
2. Detect mouse clicks, keyboard input, scrolling via frame-diff analysis
3. Use the vision model to understand each operation's intent ("click the File menu", "type a keyword in the search box", etc.)
4. Support multi-app collaboration: automatically track cross-app switches (e.g., copying data from browser to Excel) and integrate the cross-app workflow into a single Skill

**Generated Skills are independent of:**
- **Desktop resolution** — Uses semantic element descriptions instead of absolute coordinates
- **Window position and size** — Locates elements by semantic meaning, not window geometry
- **Application version** — Extracts operation intent and functional paths, not version-specific UI details

**Input:** Screen recording (MP4 / AVI / MKV) or live recording
**Output:** Reusable semantic Skill + operation replay document
**Use cases:** Convert manual operations to automation, capture cross-app workflows, preserve expert workflows

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

### 4.3 Operation Backends

RegionCUA supports multiple operation backends, split into "base capture backends" and "CUA execution backends":

#### Base Backend: Foreground / Background (`--backend`)

| Backend | Capture | Action | Steals Cursor | Obscured / Locked |
|---------|---------|--------|---------------|-------------------|
| `foreground` (default) | pyautogui full-screen | pyautogui mouse/keyboard | Yes | Fails |
| `background` | PrintWindow per-window | UIA / PostMessage | **No** | **Still works** |

The background mode borrows the core idea of trycua/cua — the agent operates applications in the background without disturbing the user. It uses the Win32 PrintWindow API to capture the target window (even when obscured) and UI Automation / PostMessage to click and type (without moving the real mouse).

#### CUA Execution Backend (`--cua-backend`)

The benchmark (`region-cua bench`) and unified execution path support pluggable CUA execution backends, switched through the unified `cua/factory.py` interface:

| Backend | Locating | Executing | Notes |
|---------|----------|-----------|-------|
| `trycua` | **UIA control-tree text matching** (structured, stable, no VLM) | cua-driver (PostMessage background, no cursor steal) | Alibaba cua-driver CLI adapter; control-tree first, pixel/VLM fallback |
| `qwen-ui` | **VLM looks at the screenshot and outputs coordinates** (Qwen-UI-Agent grounding) | reuses cua-driver (same executor as trycua) | end-to-end VLM locating; Ollama ROCm GPU-accelerated vision |

```bash
# Benchmark with a specific CUA execution backend
uv run region-cua bench --all --cua-backend trycua
uv run region-cua bench --all --cua-backend qwen-ui
```

The two CUA backends differ only in the "vision locating" strategy — trycua uses the UIA control tree (structured, stable), qwen-ui uses VLM grounding (end-to-end visual locating); they share the same cua-driver executor so A/B benchmarks keep execution identical.

#### Vision Fallback Chain

Locating order: **OmniParser (YOLO+OCR text matching) → EasyOCR raw-text precise locating → CUA backend UIA / VLM → region-ai cloud VLM fallback**. Text targets prefer OmniParser+EasyOCR (measured most accurate); icons/non-text targets use SAM3 segmentation or VLM. Pixel-determinable attributes such as colors use deterministic RGB matching rather than the vision model.

### 4.4 AI Agent Integration

RegionCUA provides a `region-cua` Skill. Agents auto-detect and install it when reading this repository, after which they can execute desktop automation through natural language conversation:

| Agent | Installation | Example Dialogue |
|-------|-------------|-----------------|
| **opencode** | Auto-detects skill config on `opencode .` | "Open Excel and create a sales spreadsheet" |
| **openclaw** | Auto-installs skill from README | "Open Calculator and compute 1024x768" |
| **hermes** | Register the region-cua tool | "Explore Notepad++ features" |

After installation, users describe tasks in natural language and the agent automatically invokes RegionCUA to complete them.

### 4.5 Skill Auto-Install Manifest

The following metadata is used by agents for auto-discovery and registration:

```yaml
# opencode / openclaw / hermes auto-install manifest
name: region-cua
description: Desktop automation agent powered by local vision models
version: 0.1.0
commands:
  run: uv run region-cua run
  explore: uv run region-cua explore
  compile: uv run region-cua compile
  learn: uv run region-cua learn
  list-models: uv run region-cua list-models
  info: uv run region-cua info
install:
  windows: |
    pip install uv
    git clone https://github.com/Region-AI/region-cua.git
    cd region-cua
    uv sync
  model: ollama pull qwen3.8-flash:latest
```

## 5. Quick Start

```bash
# 1. Install uv
pip install uv

# 2. Clone and install dependencies
git clone https://github.com/Region-AI/region-cua.git
cd region-cua
uv sync

# 3. Start the backend (choose one)

# Option A: Ollama (default)
ollama serve
# Recommended vision models (choose one):
#   qwen3.8-flash                 - lightweight local vision, fast, daily tasks
#   deepseek-v4-flash-vision-exp  - stronger vision for complex UIs
ollama pull qwen3.8-flash:latest
# ollama pull deepseek-v4-flash-vision-exp:latest

# Option B: vLLM (OpenAI-compatible API)
vllm serve qwen3.8-flash:latest --port 8000

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

### 6.5 Learning Mode

Learn from screen recordings and generate semantic Skills:

```bash
# Learn from an existing video file
uv run region-cua learn "recordings/my_operation.mp4"

# Live recording (press Ctrl+C to stop, auto-analyzes after)
uv run region-cua learn --record

# Also generate a replay document
uv run region-cua learn "recordings/demo.mp4" --replay-doc
```

Skills generated by learning mode are independent of desktop resolution, window position/size, and application version, making them reusable across different environments.

### 6.6 Preview Mode

Generate an operation plan without executing:

```bash
uv run region-cua run "Create a sales spreadsheet in Excel" --dry-run
```

### 6.7 Specify Model

```bash
uv run region-cua run "Describe current desktop" --model qwen3.8-flash:latest
```

### 6.8 Disable Recording

```bash
uv run region-cua run "Draw a circle in Paint" --no-video
```

### 6.9 Specify Backend Provider

Default is Ollama. Switch to vLLM via environment variable or `--provider` flag:

```bash
# Environment variable (global)
export PROVIDER=vllm

# Or per-command
uv run region-cua run "Open Excel" --provider vllm
```

### 6.10 Allow Screen Lock During Tasks

By default, RegionCUA prevents the system from locking or sleeping during task execution (Windows uses `SetThreadExecutionState`, Linux uses `systemd-inhibit`, macOS uses `caffeinate`). This is because a locked screen means the desktop agent cannot capture screen content. To explicitly allow screen lock:

```bash
uv run region-cua run "..." --allow-lock
```

### 6.11 Management Commands

```bash
uv run region-cua list-models    # List available models (supports --provider)
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

### 7.4 Learning Mode

Learning mode generates a semantic Skill and operation replay document:

```
outputs/{timestamp}_learn_{app_name_or_multi}/
├── skill/                # Semantic Skill (resolution/window/version independent)
│   ├── SKILL.md          # Skill definition
│   └── steps.json        # Structured operation steps (with semantic descriptions)
├── replay.md             # Operation replay document (with keyframe screenshots)
├── frames/               # Keyframe screenshots (before/after comparison)
└── analysis.log          # Video analysis log
```

## 8. Out of Scope

- **Cross-platform support** — Currently Windows only (macOS/Linux in future releases)
- **Model training** — No model training or fine-tuning involved
- **Cloud inference** — Main flow runs locally via Ollama; only when local vision locating fails, an optional region-ai cloud VLM fallback is used (`qwen3.x-27b`, requires `REGION_AI_API_KEY`)
- **Mobile support** — No Android/iOS plans at this time

## 9. Dependencies & Risks

### Dependencies

| Dependency | Description |
|-----------|-------------|
| Python 3.11+ | Runtime environment |
| uv | Dependency management & runner (`pip install uv`) |
| Ollama **or** vLLM | Local vision model inference engine (choose one) |
| Windows 10/11 | Currently supported desktop platform |
| Qwen3.8-Flash (recommended) | Lightweight local vision model; planning and vision can share one model to avoid cold-start latency |
| DeepSeek-V4-Flash-Vision-Exp (optional) | Stronger vision understanding/element locating for complex UIs and icon recognition |

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
