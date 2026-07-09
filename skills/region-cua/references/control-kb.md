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
- 保存：`hotkey` "ctrl+s"（首次需 `type` 文件名 -> `hotkey` "enter"）
- 查找：`hotkey` "ctrl+f" -> `type` 关键词
- 替换：`hotkey` "ctrl+h"
- 自动换行：`click` "格式" -> `click` "自动换行"

---

## 复合控件

### 标签页（tabs）
- 点击标签标题切换到对应标签页
- 生成1步：`click` 标签标题文字
- 标签页切换后内容区域会变化，需要重新截图
- 关闭标签页：`click` 标签上的关闭按钮（通常是 x 图标）

### 对话框/模态框（dialog/modal）
- 对话框弹出后背景通常变暗，需要先处理对话框才能操作其他区域
- 确认对话框：`click` "确定"/"OK"/"确认"
- 取消对话框：`click` "取消"/"Cancel" 或 `hotkey` "escape"
- 对话框中可能有多个输入框，按 Tab 键切换焦点

### 树形菜单（tree_view）
- 展开/折叠节点：`click` 节点前的展开箭头（▶/▼）
- 选择节点：`click` 节点文字
- 嵌套层级：逐层展开到目标节点
- 文件资源管理器的左侧导航树就是树形菜单

### Toast 通知（toast/notification）
- Toast 通知通常出现在屏幕右上角或右下角，几秒后自动消失
- 如果需要操作 Toast 中的按钮，要快速 `click`
- 关闭 Toast：`click` Toast 上的关闭按钮 或等待自动消失

### 上下文菜单/弹出菜单（popup_menu）
- 和右键菜单类似，但可能由左键点击触发
- 菜单项是 DOM 元素，OmniParser 能检测到
- 菜单弹出后需要重新截图才能定位菜单项
- 关闭菜单：`hotkey` "escape" 或点击空白区域

### 分页器（pagination）
- 翻页：`click` "下一页"/"›" 或 `click` 页码数字
- 跳转到指定页：`click` 页码输入框 -> `type` 页码 -> `hotkey` "enter"
- 每页翻页后需要重新截图

### 手风琴/折叠面板（accordion）
- `click` 面板标题展开/折叠内容
- 展开后内容区域出现新元素，需要重新截图
- 同时只有一个面板展开时，展开新面板会自动折叠旧面板

### 工具提示（tooltip）
- 鼠标悬停在元素上时显示提示文字
- Tooltip 不是可交互元素，不要点击它
- 如果需要读取 tooltip 中的信息，先 `move_to` 目标元素 -> `screenshot`

### 进度条/加载状态（progress_bar）
- 等待进度完成：`wait` 2 秒 -> `screenshot` 检查是否完成
- 如果进度条还在动，继续 `wait`
- 如果进度条消失或显示完成，继续下一步操作

---

## 更多常见应用操作指南

### Windows 任务管理器
- 打开：`hotkey` "ctrl+shift+esc" 或 `hotkey` "ctrl+alt+delete" -> `click` "任务管理器"
- 结束进程：`click` 进程名 -> `click` "结束任务"
- 切换到详细信息：`click` "详细信息" 选项卡
- 查看性能：`click` "性能" 选项卡
- 查看启动项：`click` "启动" 选项卡

### Windows 控制面板
- 打开：`open_app` "control"
- 程序和功能：`click` "程序" -> `click` "程序和功能"
- 卸载程序：`click` 程序名 -> `click` "卸载"
- 电源选项：`click` "硬件和声音" -> `click` "电源选项"
- 设备管理器：`click` "硬件和声音" -> `click` "设备管理器"

### Windows 截图工具
- 截图工具：`hotkey` "win+shift+s"（选择截图区域）
- 全屏截图：`hotkey` "prtscn"
- 当前窗口截图：`hotkey` "alt+prtscn"
- 截图后自动复制到剪贴板，可 `hotkey` "ctrl+v" 粘贴

### 画图（Paint）
- 打开：`open_app` "mspaint"
- 画线：`click` "直线" 工具 -> 拖拽画线
- 画矩形：`click` "矩形" 工具 -> 拖拽画矩形
- 填充颜色：`click` "填充" 工具 -> `click` 颜色 -> `click` 填充区域
- 选择颜色：`click` 颜色块
- 调整画布大小：`click` "调整大小" -> `type` 宽度和高度 -> `click` "确定"
- 保存：`hotkey` "ctrl+s"

### 计算器
- 打开：`open_app` "calc"
- 输入数字：`type` 数字 或 `click` 计算器按钮
- 运算：`type` 运算符 或 `click` 运算符按钮
- 等于：`hotkey` "enter" 或 `click` "="
- 清除：`hotkey` "escape" 或 `click` "C"
- 切换模式：`click` 菜单 -> `click` "科学"/"程序员"

### 时钟/闹钟
- 打开：`open_app` "时钟"
- 设置闹钟：`click` "闹钟" -> `click` "+" -> 设置时间 -> `click` "保存"
- 计时器：`click` "计时器" -> `click` 设置时间 -> `click` "开始"
- 秒表：`click` "秒表" -> `click` "开始"

### Chrome 下载管理
- 查看下载：`hotkey` "ctrl+j"
- 暂停下载：`click` 下载项的暂停按钮
- 取消下载：`click` 下载项的取消按钮
- 打开下载文件：`click` 下载项 -> `click` "打开"
- 在文件夹中显示：`click` 下载项 -> `click` "在文件夹中显示"

### Chrome 标签页管理
- 固定标签页：右键标签 -> `click` "固定标签页"
- 标签页分组：右键标签 -> `click` "将标签页添加到新组"
- 恢复关闭的标签页：`hotkey` "ctrl+shift+t"
- 标签页静音：右键标签 -> `click` "将标签页静音"

### VS Code
- 打开：`open_app` "code"
- 打开文件：`hotkey` "ctrl+o" -> 选择文件
- 打开文件夹：`hotkey` "ctrl+k ctrl+o"
- 搜索文件：`hotkey` "ctrl+p" -> `type` 文件名
- 全局搜索：`hotkey` "ctrl+shift+f" -> `type` 关键词
- 命令面板：`hotkey` "ctrl+shift+p" -> `type` 命令
- 终端：`hotkey` "ctrl+`"
- 格式化代码：`hotkey` "shift+alt+f"
- 注释切换：`hotkey` "ctrl+/"
- 保存：`hotkey` "ctrl+s"
- 关闭标签：`hotkey` "ctrl+w"

### 7-Zip / WinRAR（压缩工具）
- 解压：右键压缩文件 -> `click` "解压到..." -> 选择路径 -> `click` "确定"
- 压缩：右键文件/文件夹 -> `click` "添加到压缩文件..." -> `click` "确定"
- 打开压缩文件：`open_app` "7z" -> `hotkey` "ctrl+o" -> 选择文件

### Windows 搜索（Cortana/Search）
- 打开搜索：`hotkey` "win+s" 或 `click` 任务栏搜索框
- 搜索应用/文件：`type` 关键词 -> `hotkey` "enter" 或 `click` 结果
- 搜索设置：`type` "设置:" + 关键词
- 搜索文件：`type` "文件:" + 关键词

### Windows 剪贴板历史
- 打开：`hotkey` "win+v"
- 粘贴历史项：`click` 历史项
- 固定剪贴板项：`click` 项的固定按钮
- 清除剪贴板：`click` "全部清除"

---

## 扩展应用操作指南

### 微信（WeChat）详细操作

#### 聊天操作
- 发送消息：`click` 联系人/群 -> `click` 输入框 -> `type` 消息 -> `hotkey` "enter"
- 发送换行消息：`hotkey` "shift+enter"（输入框内换行）
- 撤回消息：右键消息 -> `click` "撤回"（2分钟内）
- 转发消息：右键消息 -> `click` "转发" -> `click` 联系人 -> `click` "发送"
- 回复消息：右键消息 -> `click` "回复" -> `type` 回复内容
- 引用消息：右键消息 -> `click` "引用"
- @某人（群聊）：`type` "@" -> `click` 联系人名
- 发送文件：`click` 聊天窗口 -> 将文件拖入聊天窗口 或 `click` 文件传输按钮 -> `click` 文件
- 发送图片：`click` 图片按钮 或拖入图片
- 截图发送：`hotkey` "alt+a" -> 框选区域 -> `click` "完成" -> 自动粘贴到输入框 -> `hotkey` "enter"

#### 联系人管理
- 添加联系人：`click` "+" -> `click` "添加联系人" -> `type` 微信号/手机号 -> `hotkey` "enter"
- 搜索联系人：`click` 搜索框 -> `type` 联系人名/备注
- 修改备注：`click` 联系人 -> 右键 -> `click` "备注" -> `type` 新备注
- 创建群聊：`click` "+" -> `click` "发起群聊" -> `click` 多个联系人 -> `click` "确定"

#### 朋友圈
- 打开朋友圈：`click` "发现" -> `click` "朋友圈"
- 发朋友圈：`click` 相机图标 -> `type` 内容 -> `click` "发表"
- 点赞/评论：`click` 消息下方的心形/评论图标

#### 设置
- 打开设置：`click` "更多"（...） -> `click` "设置"
- 修改字体大小：设置 -> `click` "通用" -> `click` "字体大小" -> 拖拽滑块
- 消息提醒：设置 -> `click` "新消息提醒"

### WPS Office 详细操作

#### WPS 文字（文档）
- 打开：`open_app` "wps"
- 字体设置：`click` 字体下拉框 -> `type` 字体名 -> `hotkey` "enter"
- 字号设置：`click` 字号下拉框 -> `type` 数字 -> `hotkey` "enter"
- 段落格式：`click` "开始" -> `click` 对齐方式（左/中/右/两端）
- 插入页眉页脚：`click` "插入" -> `click` "页眉" 或 "页脚"
- 插入目录：`click` "引用" -> `click` "目录"
- 插入分页符：`hotkey` "ctrl+enter"
- 查找替换：`hotkey` "ctrl+f"（查找）或 `hotkey` "ctrl+h"（替换）
- 审阅修订：`click` "审阅" -> `click` "修订"
- 字数统计：`click` "审阅" -> `click` "字数统计"
- 导出PDF：`click` "文件" -> `click` "输出为PDF"
- 打印预览：`hotkey` "ctrl+p"

#### WPS 表格（ET）
- 打开：`open_app` "et"
- 选定单元格：`click` 单元格
- 输入公式：`click` 单元格 -> `type` "=SUM(A1:A10)" -> `hotkey` "enter"
- 自动填充：`click` 单元格右下角拖拽手柄
- 条件格式：`click` "开始" -> `click` "条件格式" -> 选择规则
- 冻结窗格：`click` "视图" -> `click` "冻结窗格"
- 数据透视表：`click` "插入" -> `click` "数据透视表"
- 图表：`click` "插入" -> `click` "图表" -> 选择图表类型
- 排序：选中数据列 -> `click` "数据" -> `click` "升序"/"降序"
- 筛选：选中表头 -> `click` "数据" -> `click` "筛选"
- 合并单元格：选中区域 -> `click` "开始" -> `click` "合并居中"
- 保护工作表：`click` "审阅" -> `click` "保护工作表"

#### WPS 演示（PPT）
- 打开：`open_app` "wpp"
- 新建幻灯片：`hotkey` "ctrl+m" 或 `click` "新建幻灯片"
- 插入文本框：`click` "插入" -> `click` "文本框" -> 拖拽绘制
- 插入图片：`click` "插入" -> `click` "图片" -> 选择文件
- 幻灯片切换效果：`click` "切换" -> `click` 效果
- 动画效果：选中对象 -> `click` "动画" -> `click` 效果
- 放映：`hotkey` "f5"（从头）或 `hotkey` "shift+f5"（从当前）
- 排练计时：`click` "幻灯片放映" -> `click` "排练计时"

### Windows 文件资源管理器详细操作

#### 导航
- 打开：`open_app` "explorer" 或 `hotkey` "win+e"
- 地址栏输入路径：`hotkey` "ctrl+l" 或 `click` 地址栏 -> `type` 路径 -> `hotkey` "enter"
- 前进/后退：`hotkey` "alt+right" / `hotkey` "alt+left"
- 向上一级：`hotkey` "alt+up"
- 最近访问：`click` "快速访问" -> `click` 最近文件

#### 文件操作
- 新建文件夹：`hotkey` "ctrl+shift+n" -> `type` 名称 -> `hotkey` "enter"
- 复制：选中 -> `hotkey` "ctrl+c"
- 粘贴：`hotkey` "ctrl+v"
- 剪切：`hotkey` "ctrl+x"
- 重命名：选中 -> `hotkey` "f2" -> `type` 新名 -> `hotkey` "enter"
- 删除到回收站：选中 -> `hotkey` "delete"
- 永久删除：选中 -> `hotkey` "shift+delete"
- 属性：选中 -> `hotkey` "alt+enter"
- 全选：`hotkey` "ctrl+a"

#### 搜索与筛选
- 搜索当前文件夹：`click` 搜索框 -> `type` 关键词
- 按类型搜索：搜索框输入 `type:pdf` 或 `ext:.docx`
- 按日期搜索：搜索框输入 `datemodified:today`
- 按大小搜索：搜索框输入 `size:>10MB`

#### 视图设置
- 大图标视图：`click` "查看" -> `click` "大图标"
- 详细信息视图：`click` "查看" -> `click` "详细信息"
- 排序：`click` 列标题（名称/修改日期/类型/大小）
- 分组：右键空白 -> `click` "分组依据" -> 选择分组字段
- 隐藏文件：`click` "查看" -> 勾选 "隐藏的项目"

### 浏览器详细操作（Chrome / Edge）

#### 标签页管理
- 新建标签页：`hotkey` "ctrl+t"
- 关闭标签页：`hotkey` "ctrl+w"
- 恢复关闭的标签页：`hotkey` "ctrl+shift+t"
- 切换标签页：`hotkey` "ctrl+tab" / `hotkey` "ctrl+shift+tab"
- 跳转到第N个标签页：`hotkey` "ctrl+N"（N=1-8）
- 跳转到最后一个标签页：`hotkey` "ctrl+9"
- 固定标签页：右键标签 -> `click` "固定标签页"
- 标签页分组：右键标签 -> `click` "将标签页添加到新组"

#### 地址栏与导航
- 聚焦地址栏：`hotkey` "ctrl+l" 或 `hotkey` "f6"
- 搜索：在地址栏 `type` 关键词 -> `hotkey` "enter"
- 打开网站：地址栏 `type` URL -> `hotkey` "enter"
- 在新标签页打开链接：`hotkey` "ctrl+click" 链接
- 后退/前进：`hotkey` "alt+left" / `hotkey` "alt+right"
- 刷新：`hotkey` "f5" 或 `hotkey` "ctrl+r"
- 强制刷新（绕过缓存）：`hotkey` "ctrl+shift+r" 或 `hotkey` "ctrl+f5"
- 停止加载：`hotkey` "escape"

#### 页面操作
- 页面搜索：`hotkey` "ctrl+f" -> `type` 关键词
- 放大/缩小：`hotkey` "ctrl+=" / `hotkey` "ctrl+-"
- 恢复缩放：`hotkey` "ctrl+0"
- 全屏：`hotkey` "f11"
- 打印：`hotkey` "ctrl+p"
- 保存网页：`hotkey` "ctrl+s"
- 查看源码：`hotkey` "ctrl+u"
- 开发者工具：`hotkey` "f12" 或 `hotkey` "ctrl+shift+i"

#### 书签管理
- 添加书签：`hotkey` "ctrl+d" -> `hotkey` "enter"
- 书签栏：`hotkey` "ctrl+shift+b" 显示/隐藏书签栏
- 书签管理器：`hotkey` "ctrl+shift+o"

#### 下载管理
- 查看下载：`hotkey` "ctrl+j"
- 暂停下载：`click` 下载项的暂停按钮
- 取消下载：`click` 下载项的取消按钮
- 打开下载文件：`click` 下载项 -> `click` "打开"
- 在文件夹中显示：`click` 下载项 -> `click` "在文件夹中显示"

#### 隐私与安全
- 隐私模式：`hotkey` "ctrl+shift+n"（Chrome）/ `hotkey` "ctrl+shift+p"（Edge）
- 清除浏览数据：`hotkey` "ctrl+shift+delete"
- 查看Cookie：开发者工具 -> Application -> Cookies

### Windows 系统设置详细操作

#### 打开方式
- 设置：`hotkey` "win+i"
- 控制面板：`open_app` "control"
- 设备管理器：`hotkey` "win+x" -> `hotkey` "m"

#### 常用设置
- WiFi：设置 -> `click` "网络和 Internet" -> `click` "WiFi"
- 蓝牙：设置 -> `click` "蓝牙和其他设备"
- 显示：设置 -> `click` "系统" -> `click` "显示"
- 音量：`click` 任务栏音量图标 -> 拖拽滑块
- 亮度：设置 -> 系统 -> 显示 -> 亮度和颜色滑块
- 夜间模式：设置 -> 系统 -> 显示 -> `click` "夜间模式" 开关
- 飞行模式：设置 -> `click` "网络和 Internet" -> `click` "飞行模式"
- 日期时间：设置 -> `click` "时间和语言"
- 语言：设置 -> `click` "时间和语言" -> `click` "语言和区域"
- 输入法：设置 -> `click` "时间和语言" -> `click` "输入"
- 通知：设置 -> `click` "系统" -> `click` "通知"
- 电源：设置 -> `click` "系统" -> `click` "电源"
- 存储：设置 -> `click` "系统" -> `click` "存储"
- 应用管理：设置 -> `click` "应用" -> `click` "已安装的应用"
- 更新：设置 -> `click` "Windows 更新" -> `click` "检查更新"
- 账户：设置 -> `click` "账户"
- 隐私：设置 -> `click` "隐私和安全性"

### 命令行 / 终端详细操作

#### CMD
- 打开：`open_app` "cmd"
- 执行命令：`type` 命令 -> `hotkey` "enter"
- 复制输出：选中文本 -> `hotkey` "ctrl+c" 或右键复制
- 粘贴：`hotkey` "ctrl+v" 或右键粘贴
- 清屏：`type` "cls" -> `hotkey` "enter"
- 查看目录：`type` "dir" -> `hotkey` "enter"
- 切换目录：`type` "cd 路径" -> `hotkey` "enter"
- 查看IP：`type` "ipconfig" -> `hotkey` "enter"
- 查看进程：`type` "tasklist" -> `hotkey` "enter"
- 结束进程：`type` "taskkill /im 进程名 /f" -> `hotkey` "enter"

#### PowerShell
- 打开：`open_app` "powershell"
- 执行命令：`type` 命令 -> `hotkey` "enter"
- 清屏：`type` "clear" -> `hotkey` "enter"
- 查看服务：`type` "Get-Service" -> `hotkey` "enter"
- 启动服务：`type` "Start-Service 服务名" -> `hotkey` "enter"

#### Windows Terminal
- 打开：`hotkey` "win+t" 或 `open_app` "wt"
- 新建标签页：`hotkey` "ctrl+shift+t"
- 关闭标签页：`hotkey` "ctrl+shift+w"
- 拆分窗格：`hotkey` "alt+shift+d"
- 切换窗格：`hotkey` "alt+方向键"

### 系统快捷键速查

#### 窗口管理
- 切换窗口：`hotkey` "alt+tab"
- 关闭窗口：`hotkey` "alt+f4"
- 最小化：`hotkey` "win+down"
- 最大化：`hotkey` "win+up"
- 左半屏：`hotkey` "win+left"
- 右半屏：`hotkey` "win+right"
- 多桌面：`hotkey` "win+tab" -> `click` "新建桌面"
- 切换桌面：`hotkey` "ctrl+win+left" / `hotkey` "ctrl+win+right"

#### 文件操作通用
- 复制：`hotkey` "ctrl+c"
- 粘贴：`hotkey` "ctrl+v"
- 剪切：`hotkey` "ctrl+x"
- 撤销：`hotkey` "ctrl+z"
- 重做：`hotkey` "ctrl+y"
- 全选：`hotkey` "ctrl+a"
- 保存：`hotkey` "ctrl+s"
- 打开：`hotkey` "ctrl+o"
- 新建：`hotkey` "ctrl+n"
- 打印：`hotkey` "ctrl+p"
- 查找：`hotkey` "ctrl+f"
- 替换：`hotkey` "ctrl+h"

#### 截图
- 全屏截图：`hotkey` "prtscn"
- 当前窗口截图：`hotkey` "alt+prtscn"
- 截图工具：`hotkey` "win+shift+s" -> 框选区域
- 截图后自动复制到剪贴板，`hotkey` "ctrl+v" 粘贴

#### 输入法
- 切换中英文：`hotkey` "shift"
- 切换输入法：`hotkey` "ctrl+shift" 或 `hotkey` "win+space"
- 中英文标点切换：`hotkey` "ctrl+."

### QQ（腾讯QQ）
- 打开：`open_app` "qq"
- 发送消息：`click` 联系人 -> `click` 输入框 -> `type` 消息 -> `hotkey` "enter"
- 发送文件：`click` 联系人 -> `click` 文件传输图标 -> 选择文件
- 截图：`hotkey` "ctrl+alt+a"（QQ截图）
- 搜索联系人：`click` 搜索框 -> `type` 联系人名
- 创建群聊：`click` "+" -> `click` "创建群聊" -> 选择联系人
- 查看聊天记录：`click` 联系人 -> 右键 -> `click` "消息记录"

### 钉钉（DingTalk）
- 打开：`open_app` "dingtalk"
- 发送消息：`click` 联系人/群 -> `click` 输入框 -> `type` 消息 -> `hotkey` "enter"
- 发送文件：`click` 文件图标 -> 选择文件
- 打电话：`click` 电话图标 -> `click` 联系人
- 视频会议：`click` "会议" -> `click` "发起会议"
- 审批：`click` "工作" -> `click` "审批" -> `click` 待审批项
- 打卡：`click` "工作" -> `click` "考勤打卡"

### 飞书（Lark/Feishu）
- 打开：`open_app` "feishu" 或 `open_app` "lark"
- 发送消息：`click` 联系人/群 -> `click` 输入框 -> `type` 消息 -> `hotkey` "enter"
- @某人：`type` "@" -> `click` 联系人名
- 发送文件：`click` "+" -> `click` "文件" -> 选择文件
- 创建文档：`click` "云文档" -> `click` "+" -> `click` "文档"
- 创建表格：`click` "云文档" -> `click` "+" -> `click` "表格"
- 视频会议：`click` "视频会议" -> `click` "发起会议"
- 日历：`click` "日历" -> `click` 时间段 -> `type` 会议标题
- 任务：`click` "任务" -> `click` "新建任务"

### 网易云音乐 / QQ音乐
- 打开：`open_app` "cloudmusic" 或 `open_app` "qqmusic"
- 搜索歌曲：`click` 搜索框 -> `type` 歌名 -> `hotkey` "enter"
- 播放/暂停：`click` 播放按钮 或 `hotkey` "space"
- 上一首/下一首：`click` 上一首/下一首按钮 或 `hotkey` "ctrl+left" / `hotkey` "ctrl+right"
- 音量：`click` 音量图标 -> 拖拽滑块
- 添加到歌单：右键歌曲 -> `click` "添加到歌单" -> `click` 歌单名
- 下载：右键歌曲 -> `click` "下载"

### 系统工具

#### 注册表编辑器
- 打开：`hotkey` "win+r" -> `type` "regedit" -> `hotkey` "enter"
- 导航：左侧树展开 -> `click` 注册表项
- 搜索：`hotkey` "ctrl+f" -> `type` 关键词 -> `hotkey` "enter"
- 新建项：右键父项 -> `click` "新建" -> `click` "项"
- 修改值：双击值名 -> `type` 新值 -> `click` "确定"
- 导出：`hotkey` "ctrl+e" 或 `click` "文件" -> `click` "导出"

#### 服务管理器
- 打开：`hotkey` "win+r" -> `type` "services.msc" -> `hotkey` "enter"
- 启动服务：右键服务 -> `click` "启动"
- 停止服务：右键服务 -> `click` "停止"
- 设置自动启动：右键服务 -> `click` "属性" -> `click` "启动类型" -> `click` "自动"
- 重启服务：右键服务 -> `click` "重新启动"

#### 磁盘管理
- 打开：`hotkey` "win+x" -> `click` "磁盘管理" 或 `hotkey` "win+r" -> `type` "diskmgmt.msc"
- 格式化分区：右键分区 -> `click` "格式化" -> `click` "确定"
- 压缩卷：右键分区 -> `click` "压缩卷" -> `type` 压缩大小 -> `click` "压缩"
- 扩展卷：右键分区 -> `click` "扩展卷" -> `click` "下一步" -> `click` "完成"

#### 事件查看器
- 打开：`hotkey` "win+r" -> `type` "eventvwr.msc" -> `hotkey` "enter"
- 查看应用程序日志：`click` "Windows 日志" -> `click` "应用程序"
- 查看系统日志：`click` "Windows 日志" -> `click` "系统"
- 筛选日志：右键日志 -> `click` "筛选当前日志" -> 选择级别

### 压缩工具

#### 7-Zip
- 打开：`open_app` "7z"
- 解压：右键压缩文件 -> `click` "7-Zip" -> `click` "解压到..."
- 压缩：右键文件/文件夹 -> `click` "7-Zip" -> `click` "添加到压缩包..."
- 设置密码：压缩对话框 -> `type` 密码 -> `click` "确定"
- 分卷压缩：压缩对话框 -> `click` "分卷大小" -> `type` 大小

#### WinRAR
- 打开：`open_app` "winrar"
- 解压：右键压缩文件 -> `click` "解压到..."
- 压缩：右键文件 -> `click` "添加到压缩文件..."
- 设置密码：压缩对话框 -> `click` "设置密码" -> `type` 密码

### PDF阅读器

#### Adobe Acrobat / Reader
- 打开：`open_app` "acrobat" 或 `open_app` "acrord32"
- 打开文件：`hotkey` "ctrl+o" -> 选择PDF文件
- 翻页：`hotkey` "page down" / `hotkey` "page up"
- 放大/缩小：`hotkey` "ctrl+=" / `hotkey` "ctrl+-"
- 搜索文字：`hotkey` "ctrl+f" -> `type` 关键词
- 高亮：`click` 高亮工具 -> 拖选文字
- 添加注释：`click` 注释工具 -> `click` 页面位置 -> `type` 注释
- 打印：`hotkey` "ctrl+p"

#### Edge PDF阅读
- 用Edge打开PDF：右键PDF文件 -> `click` "打开方式" -> `click` "Microsoft Edge"
- 翻页：`hotkey` "page down" / `hotkey` "page up" 或滚动
- 搜索：`hotkey` "ctrl+f" -> `type` 关键词
- 旋转：`hotkey` "ctrl+]" 顺时针 / `hotkey` "ctrl+[" 逆时针
- 打印：`hotkey` "ctrl+p"

### 远程桌面

#### Windows 远程桌面（RDP）
- 打开：`hotkey` "win+r" -> `type` "mstsc" -> `hotkey` "enter"
- 连接：`type` 计算机名/IP -> `click` "连接" -> `type` 用户名 -> `type` 密码 -> `hotkey` "enter"
- 全屏切换：`hotkey` "ctrl+alt+break"
- 发送Ctrl+Alt+Del：`hotkey` "ctrl+alt+end"
- 断开：关闭窗口 或 `hotkey` "alt+f4"

#### TeamViewer / 向日葵
- 打开：`open_app` "teamviewer" 或 `open_app` "sunlogin"
- 远程控制：`type` 对方ID -> `click` "连接" -> `type` 密码 -> `hotkey` "enter"
- 文件传输：`click` "文件传输" -> 选择文件 -> `click` "发送"
