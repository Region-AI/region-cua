# RegionCUA Bench 改进方案

## 当前状态
- 平均分 0.31，1/13 通过（click-button 1.0）
- 6 个 0.5 分，6 个 0 分

## 失败根因分析

### 根因 1：planner target 匹配到页面标题（影响 4 个 0 分任务）
click-icon/color-picker/date-picker/select-dropdown 的 planner 生成了 `click "Click the icon"` / `click "Pick a color"` 等——这些是页面 `<h1>` 标题文字，不是可交互控件。OmniParser 正确匹配到了标题坐标，但点击标题没有效果。

**修复方案**：在 bench_runner 给 planner 的元素列表中，过滤掉标题元素（h1/h2/h3），或在 planner 提示词中明确"不要点击页面标题"。

### 根因 2：planner 不知道页面已打开（影响 3 个 0 分任务）
right-click-menu 生成 `open_app 'Task: right-click-menu'`，spreadsheet-cell 生成 `open_app 'browser'`，video-player 只生成 screenshot。planner 没理解"页面已在浏览器中打开"。

**修复方案**：在 bench_runner 的 context 中更明确地告知"页面已打开，直接操作页面元素，不要启动应用"。

### 根因 3：planner 步骤不完整（影响 2 个 0 分任务）
select-dropdown 只生成 click+wait 两步，缺少第 3 步 click 选项。date-picker 缺少展开日历和选日期的步骤。知识库里有指南但 planner 没遵循。

**修复方案**：在 context 中附加具体控件的操作步骤模板，而不只是通用知识库。

### 根因 4：OmniParser 匹配到 label 而非输入框（影响 fill-form 0 分）
fill-form 里 "Enter your full name" 是 placeholder 文字，匹配到了输入框附近但不是输入框本身。点击后没有聚焦。

**修复方案**：当 click target 是输入框 label 时，点击坐标向下偏移到输入框区域（label 在输入框上方）。

### 根因 5：typing-input 输入法问题（0.5→1.0）
click Username + type Hello World 都成功了，但 `window.__inputValue` 没变 true。可能是输入法切换干扰了输入。

**修复方案**：改进输入法切换逻辑，确保 type 前切换到英文。

## 实施计划

### 第一批：修复 planner context（预期提升 4 个 0→0.5+）
1. 过滤元素列表中的标题元素
2. 更明确的 context 措辞
3. 附加控件操作步骤模板

### 第二批：修复定位偏移（预期提升 fill-form 和 0.5 分任务）
4. label 匹配时向下偏移到输入框
5. 改进 find_element 的优先级（控件 > 标题）
