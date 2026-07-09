# 控件交互知识库

> 本文件是 RegionCUA planner 的外部知识库，描述各类 GUI 控件的正确交互方式。
> 代码在 `control_kb.py` 的 `build_planner_kb_prompt()` 中加载本文件并注入 planner system prompt。
> **修改本文件不需要改代码**——planner 下次调用时自动读取最新内容。

## 基础控件

### 按钮（button / submit / cancel / link / menu）
- 单击即可触发
- 生成1步：`click` 按钮文字
- 提交按钮点击后等页面响应，不要重复点击
- 按钮文字必须精确匹配页面上显示的文字（如 "Submit Form" 不是 "Submit"）

### 输入框（input / textarea）
- 需要2步：
  1. `click` 输入框的 label 文字（如 "Username"）
  2. `type` 要输入的内容
- 输入英文前确保英文输入法
- 如果 label 文字不在页面上，点击输入框的 placeholder 文字

### 搜索框（search）
- 需要3步：
  1. `click` "Search" 或搜索框
  2. `type` 搜索关键词
  3. `hotkey` "enter"

### 表格单元格（cell）
- 需要2步：
  1. `click` 单元格位置（如 "A1" 或具体坐标）
  2. `type` 要输入的数据

## 选择控件

### 下拉菜单（dropdown / select）
- **需要3步，不能直接点选项**：
  1. `click` 下拉框本身（不是选项文字，是下拉框控件）
  2. `wait` 0.5（等下拉列表展开渲染）
  3. `click` 要选择的选项文字
- 必须先展开再选，不能直接点击选项

### 复选框（checkbox）
- 单击切换勾选状态
- 生成1步：`click` 复选框的 label 文字

### 单选按钮（radio）
- 单击选中，同组只能选一个
- 生成1步：`click` 选项的 label 文字

## 开关与滑块

### 开关（toggle / switch）
- 单击切换开/关状态
- 生成1步：`click` 开关旁边的 label 文字或开关本身

### 滑块（slider）
- 需要拖拽，生成1步：`click` 滑块控件
- executor 自动处理拖拽（长按 → 移动 → 松开）：
  - 目标值比当前值大 → 向右拖
  - 目标值比当前值小 → 向左拖
  - 拖拽距离根据差值比例估算

## 拖拽元素（drag）
- 拖拽是连续动作，不是简单 click：
  1. 在源元素上**长按鼠标按钮**（大多数情况左键，中键右键也有可能）
  2. **移动到目标位置**（移动过程中保持鼠标按钮按下）
  3. 在目标位置**松开鼠标按钮**
- 生成1步：`click` 源元素（value 可指定目标位置或描述）
- executor 自动处理：按下 → 移动 → 松开
- 注意：拖拽方向和距离取决于目标值与当前值的关系

## 日期选择器（date_picker）
- **<input type="date"> 是浏览器原生控件**，点击后弹出日期选择器
- Chrome 日期选择器的布局（从上到下）：
  - 年月显示区：显示 "2026年07月"，右侧有上下箭头按钮（↑上月 ↓下月）
  - 星期表头：一二三四五六日
  - 日期网格：7列，显示当月日期
  - 底部："清除" 和 "今天" 按钮
- **年月是一起选的**，不是分开的：
  1. `click` 日期输入框 → `hotkey` "alt+down" 弹出日历
  2. **重新截图**，`click` 顶部年月文字（如 "2026年07月"），展开年月选择视图
  3. 年月选择视图：上方是年份列表（可滚动），下方是 12 个月份按钮（4列x3行网格）
  4. **重新截图**，在年份列表中找目标年份（可能需要向上/向下滚动）→ `click`
  5. 选完年份后回到月历视图，**重新点击年月文字**再次展开年月选择视图
  6. **重新截图**，在月份网格中找目标月份 → `click`
  7. 回到日历视图，**重新截图**，在日期网格中找目标日期 → `click`
- 每一步都重新截图，因为每步选择后界面都会变化
- 截图前把光标移开，避免遮挡日历

## 颜色选择器（color_picker）
- 生成1步：`click` 目标颜色区域
- 颜色方块通常没有文字标签
- 根据颜色名称描述定位（如 "red" → 红色方块的位置）
- 如果 OCR 没识别到颜色文字，VLM 会尝试识别图标区域

## 右键菜单（context_menu）
- **需要3步**：
  1. 右键单击目标区域（用 `click`，`value="right"`）
  2. `wait` 0.5（等右键菜单展开）
  3. `click` 菜单中的目标选项文字
- 右键菜单可能是浏览器原生菜单或网页自定义菜单
- 如果菜单选项找不到，可能需要用键盘快捷键（如 Ctrl+C 替代右键→复制）

## 图标按钮（icon_button）
- 纯图标按钮没有文字，OmniParser 会用 VLM 识别图标含义
- 生成1步：`click` 图标名称（如 "Home"、"Settings"、"Play"）
- 常见图标名：home（房子）、settings（齿轮）、profile（人像）、bell（铃铛）、email（信封）、star（星标）、play（播放）、pause（暂停）、volume（音量）、search（放大镜）

## 视频播放器

### 播放/暂停按钮（video_play）
- 单击切换播放状态
- 生成1步：`click` "play" 或 "pause"（根据任务描述）

### 静音按钮（video_mute）
- 单击切换静音
- 生成1步：`click` "mute" 或 "volume" 按钮

### 音量控制（video_volume）
- 可能需要2步：
  1. `click` 音量按钮（展开音量滑块）或悬停
  2. `click` 或拖拽音量滑块到目标位置
- 有些播放器单击音量按钮直接切换静音

## 滚动条（scrollbar）
- **有滚动条时必须先滚动到底，分页识别界面全貌后再规划操作步骤**
- 纯视觉分页滚动策略（不依赖 JS，适用于网页和桌面 App）：
  1. 截图当前页面 → OmniParser 解析元素
  2. 向下滚动约一屏的 80%（留 20% 重叠确保不漏内容）
  3. 重新截图 → 解析 → 与已有元素去重合并
  4. 如果没有新元素出现 = 已到底，停止滚动
  5. 滚回顶部再开始操作
- 每次滚动后等 0.5 秒让页面渲染完成再截图
- 截图前把光标移到屏幕角落，避免遮挡界面元素
- **如果目标元素不在可视区域，先滚动再操作**

## 通用规则

1. 如果页面内容显示不完整（元素被截断或不在可视区域），先 `scroll` 滚动再操作
2. **有滚动条时必须先滚动到底，分页识别界面全貌后再规划操作步骤**
3. 每次操作后如果需要确认结果，可以加 `screenshot` 步骤
4. `click` 的 target 必须是页面上实际显示的文字，精确匹配
5. `type` 的 target 必须是要输入的具体文字内容，不能为空
6. 如果任务涉及多个控件，按逻辑顺序生成步骤
7. 如果首次操作没找到目标元素，重新截图后再试（页面可能刚加载完）
8. 不要点击页面标题（h1/h2 标题文字通常不是可交互控件）

---

## 常见应用操作指南

### Windows 文件资源管理器（Explorer）
- 打开：`open_app` "explorer"
- 导航到路径：在地址栏 `click` 地址栏文字 → `type` 路径 → `hotkey` "enter"
- 新建文件夹：`hotkey` "ctrl+shift+n" → `type` 文件夹名 → `hotkey` "enter"
- 复制文件：选中文件 → `hotkey` "ctrl+c" → 导航到目标 → `hotkey` "ctrl+v"
- 移动文件：选中文件 → `hotkey` "ctrl+x" → 导航到目标 → `hotkey` "ctrl+v"
- 重命名：选中文件 → `hotkey` "f2" → `type` 新名称 → `hotkey` "enter"
- 删除：选中文件 → `hotkey` "delete"
- 搜索：`click` 搜索框 → `type` 关键词
- 切换视图：`click` "查看" 选项卡 → `click` "大图标"/"列表"/"详细信息"

### WPS Office / Microsoft Word
- 打开：`open_app` "wps" 或 "winword"
- 新建文档：`click` "新建" → `click` "空白文档"
- 输入文字：直接 `type`（文档已聚焦）
- 保存：`hotkey` "ctrl+s"（首次保存需选择路径）
- 另存为：`hotkey` "f12" → `type` 文件名 → `hotkey` "enter"
- 加粗：选中文本 → `hotkey` "ctrl+b"
- 查找替换：`hotkey` "ctrl+h"
- 插入图片：`click` "插入" → `click` "图片" → 选择文件
- 插入表格：`click` "插入" → `click` "表格" → 选择行列数
- 设置字体大小：`click` 字体大小框 → `type` 数字 → `hotkey` "enter"

### WPS Office / Microsoft Excel
- 打开：`open_app` "et" 或 "excel"
- 输入数据：`click` 单元格 → `type` 数据 → `hotkey` "enter"
- 公式：`click` 单元格 → `type` "=SUM(A1:A10)" → `hotkey` "enter"
- 选择区域：`click` 起始单元格 → 按住 Shift `click` 结束单元格
- 排序：选中数据 → `click` "数据" → `click` "排序"
- 筛选：选中表头 → `click` "数据" → `click` "筛选"

### 微信（WeChat）
- 打开：`open_app` "wechat"
- 发送消息：`click` 联系人 → `click` 输入框 → `type` 消息 → `hotkey` "enter"
- 发送文件：`click` 联系人 → `click` "发送文件"按钮 → 选择文件
- 搜索联系人：`click` 搜索框 → `type` 联系人名
- 截图：`hotkey` "alt+a"（微信内置截图）
- 表情：`click` 表情按钮 → `click` 表情

### 浏览器（Chrome / Edge）
- 打开：`open_app` "chrome" 或 "msedge"
- 新建标签页：`hotkey` "ctrl+t"
- 关闭标签页：`hotkey` "ctrl+w"
- 切换标签页：`hotkey` "ctrl+tab" 或 `click` 标签
- 地址栏：`hotkey` "ctrl+l" 或 `click` 地址栏 → `type` URL → `hotkey` "enter"
- 刷新：`hotkey` "f5" 或 `click` 刷新按钮
- 后退/前进：`hotkey` "alt+left" / `hotkey` "alt+right"
- 搜索：`hotkey` "ctrl+f" → `type` 关键词
- 下载：`hotkey` "ctrl+j" 查看下载列表
- 开发者工具：`hotkey` "f12"
- 隐私模式：`hotkey` "ctrl+shift+n"

### Windows 系统设置
- 打开设置：`open_app` "设置" 或 `hotkey` "win+i"
- 蓝牙：`click` "蓝牙和其他设备" → `click` 蓝牙开关
- WiFi：`click` "网络和 Internet" → `click` "WiFi" → `click` 开关
- 显示：`click` "系统" → `click` "显示"
- 音量：`click` 任务栏音量图标 → 拖拽滑块
- 通知：`click` "系统" → `click` "通知"
- 更新：`click` "Windows 更新" → `click` "检查更新"

### 命令行 / 终端
- 打开 CMD：`open_app` "cmd"
- 打开 PowerShell：`open_app` "powershell"
- 执行命令：直接 `type` 命令 → `hotkey` "enter"
- 复制输出：选中文字 → `hotkey` "ctrl+c"（CMD 需右键复制）
- 粘贴：`hotkey` "ctrl+v" 或右键粘贴
- 清屏：`type` "cls" → `hotkey` "enter"（CMD）或 `type` "clear" → `hotkey` "enter"（bash）

### 记事本（Notepad）
- 打开：`open_app` "notepad"
- 输入：直接 `type`
- 保存：`hotkey` "ctrl+s"（首次需 `type` 文件名 → `hotkey` "enter"）
- 查找：`hotkey` "ctrl+f" → `type` 关键词
- 替换：`hotkey` "ctrl+h"
- 自动换行：`click` "格式" → `click` "自动换行"
