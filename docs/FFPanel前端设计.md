# FFPanel 前端详细设计规范 (Frontend Design Specification for Vibe Coding)

> **目标定位**：专为 RK3588 边缘设备打造的轻量级、高颜值、极简直观的批量视频硬件转码 WebUI（FFPanel）。
> **核心原则**：明亮干净（Clean Light Theme）、高信息密度、零心智负担向导式流程、响应敏捷、与后端状态无缝同步。

---

## 1. 技术栈选型与工程规范 (Tech Stack & Architecture)

为了兼顾在开发工具中进行 AI/Vibe Coding 的快速迭代、极低运行时内存开销（匹配 RK3588 资源限制）以及出色的视觉表现力，选定以下技术栈：

- **框架核心**：`Vue 3 (Composition API + <script setup>)` + `Vite`
  - _选型理由_：极速 HMR、TS 原生支持、体积极小、对现代微前端和单页组件生成极为友好。
- **语言**：`TypeScript (strict: true)`
  - _选型理由_：提供强类型转码参数契约定义（DTOs），AI 辅助补全代码时零类型混淆。
- **CSS 方案**：`Tailwind CSS v3` + `@tailwindcss/forms`
  - _选型理由_：纯原子化 CSS，零样式包袱，极其适合提示词驱动（Vibe Coding）快速调整间距、配色与流式响应。
- **图标库**：`Lucide Vue Next`
  - _选型理由_：现代扁平线性图标风格，契合纯净明亮主题。
- **组件原语/工具库**：
  - `@tanstack/vue-virtual`：任务列表海量文件日志与多条目渲染时保证 60fps。
  - `Pinia`：轻量状态管理（存储全局系统状态、通知、任务列表缓存）。
  - `Axios` / 原生 `Fetch` 封装：带拦截器处理 HTTP Basic Auth 401 提示与错误 Toast。
  - `EventSource (SSE)`：第一版统一使用单向 SSE 接收任务状态与结构化 FFmpeg 进度（FPS、剩余时长、码率等）；断线后通过 REST Snapshot + SSE 重连恢复。暂不引入 WebSocket，降低连接与状态同步复杂度。

---

## 2. 设计语言与视觉系统 (Design Tokens & Light Theme)

专为**明亮主题**量身定制，以干净冷白底色为基调，搭配现代科技感的翡翠青/蓝靛蓝作为点缀，营造专业工作站质感：

- **色彩系统 (Color Tokens)**：
  - **背景底色 (Surface)**：
    - `bg-canvas`: `#F8FAFC` (Slate 50 - 页面全局底色，柔和不刺眼)
    - `bg-card`: `#FFFFFF` (纯白，用于卡片与容器)
    - `bg-card-hover`: `#F1F5F9` (Slate 100)
  - **边框与分割线 (Borders)**：
    - `border-subtle`: `#E2E8F0` (Slate 200)
    - `border-focus`: `#3B82F6` (Blue 500)
  - **文字阶梯 (Typography)**：
    - `text-primary`: `#0F172A` (Slate 900 - 核心标题、正文)
    - `text-secondary`: `#475569` (Slate 600 - 说明文字、副标题)
    - `text-muted`: `#94A3B8` (Slate 400 - 占位符、时间戳、次要单位)
  - **主题强调色 (Brand & Status)**：
    - `Primary (主色)`: `#2563EB` (Blue 600) / 悬停 `#1D4ED8` (Blue 700)
    - `Hardware Boost (RK-MPP 硬件加速)`: `#059669` (Emerald 600) + `#ECFDF5` (Emerald 50 徽标底色)
    - `Warning / Copying`: `#D97706` (Amber 600)
    - `Error / Stopped`: `#DC2626` (Red 600)
    - `Processing (转码中)`: 渐变动态流光 `bg-gradient-to-r from-blue-500 to-indigo-500 animate-pulse`
- **卡片与阴影**：
  - `shadow-card`: `0 1px 3px 0 rgb(0 0 0 / 0.05), 0 1px 2px -1px rgb(0 0 0 / 0.05)`
  - `shadow-hover`: `0 4px 6px -1px rgb(0 0 0 / 0.07), 0 2px 4px -2px rgb(0 0 0 / 0.07)`
  - 圆角采用统一规整的 `rounded-xl` (12px) 与按钮 `rounded-lg` (8px)。

---

## 3. 全局页面骨架与导航布局 (Layout Architecture)

页面采用通用的工作台布局，顶部固顶轻量 Header，中间自适应主体容器：

```
+-------------------------------------------------------------------------------+
| [LOGO: FFPanel]  |  [新建转码任务 (+)]   [任务清单 (Badge: 2)]  |  [SysInfo]  |
+-------------------------------------------------------------------------------+
|                                                                               |
|   Main Content Container (max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8)        |
|                                                                               |
|   - 路由 1: /new   -> 向导式任务创建卡片 (Stepper Container)                  |
|   - 路由 2: /tasks -> 任务卡片队列与控制面板 (Task Dashboard)                  |
|                                                                               |
+-------------------------------------------------------------------------------+
| 底部极简状态栏: MPP: Ready | RGA: Ready | Rclone: 3 Remotes | FFPanel v1.0.0      |
+-------------------------------------------------------------------------------+
```

### 3.1 顶部导航栏 (Navbar)

- **左侧**：FFPanel 品牌标识（内置芯片小图标），后接徽章标签 `RK3588 Accelerated`（绿底 Emerald-100/Emerald-700 强调硬件特性）。
- **中间 Tab 切换**：
  - `新建转码任务`（含快捷指示器）
  - `任务清单`（右侧显示待处理任务角标 Badge；后端只有 1 个 FFmpeg 转码槽位，但另有 1 个上传槽位，因此可能同时存在“任务 A 上传 + 任务 B 转码”的两条活动链路）。
- **右侧状态栏**：简要系统心跳（通过 SSE 推送 MPP 硬件编解码状态、RGA 状态、CPU 与内存占用率）。

---

## 4. 页面 1：向导式创建新任务 (`/new`)

采用分步向导（Stepper），分为 4 个清晰步骤，支持上下步自由切换与表单校验缓存。

### Step 1: 路径与存储选择 (Path & Storage)

针对需求集成的 `rclone` 与本地存储，提供统一的存储选择。rclone 的 remote 由用户在宿主机预先配置，并通过 Docker 挂载 `rclone.conf` 到容器；前端仅读取和使用已有 remote，不提供 remote 新增、修改、OAuth 或凭据管理功能。

- **源目录/目标目录选择组件**：
  - **存储来源单选 Switch**：`本地存储 (Local)` vs `远程存储 (Rclone Remote)`。选择远程存储后，从后端返回的已配置 remote 列表中选择，例如 `nas:`、`webdav:`、`s3:`。
  - **源路径 (Source Path)**：
    - 支持单文件或多层级文件夹递归输入（匹配脚本 `lm_traverse_dir` 与单文件逻辑）。
    - 内置“智能目录浏览器 Modal”或快速路径测试按钮（检验目录可读性与文件总数统计）。
  - **目标路径 (Destination Path)**：
    - 目标输出根目录输入框。
    - 附带防护警示：校验源目录与目标目录是否相同（严格防止覆盖原文件）。
  - **伴随文件复制策略**：
    - 使用单选 Radio Card / Segmented Control，禁止拆成两个可独立组合的开关。
    - 三档选项：
      1. `不复制`：仅转码视频，不复制外部字幕或其他伴随文件；
      2. `仅复制字幕` `[默认]`：复制 `.srt / .ass / .ssa / .vtt` 等字幕文件；
      3. `复制其他文件`：复制全部非视频文件，包含字幕、NFO、封面、图片、章节、文本等伴随文件。
    - 选项下方使用弱提示说明：`复制时保持输入目录的相对目录结构；已有目标文件不会静默覆盖。`
    - 前端提交枚举值：`companionFilePolicy: 'none' | 'subtitles' | 'all_non_video'`。

### Step 2: 硬件加速与编解码方案 (Transcode Profile)

专为 RK3588 定制，将底层复杂的 ffmpeg 命令映射为可视化的硬件加速档位卡片：

- **方案选择（三选一高亮卡片）**：
  1.  **RockChip MPP 硬件编解码** `[默认推荐]`
      - _标签_：性能最高、发热极低、优先使用硬件帧链路并尽量减少内存拷贝。
  2.  **CPU 软解 + MPP 硬件编码**
      - _标签_：高兼容性（适合部分特殊封装或破损旧视频源）。
  3.  **CPU 软件编解码**
      - _标签_：通用降级方案，速度较慢。
- **转码自动退回开关**：默认开启。
  - 从 Rockchip MPP 硬件编解码开始时，失败后依次尝试 `CPU 软解 + MPP 编码`、`CPU 软件编解码`。
  - 从 `CPU 软解 + MPP 编码` 开始时，只继续退回 `CPU 软件编解码`；纯 CPU 不再退回。
  - MPP/RGA 当前不可用但开关开启时允许提交硬件起始档位，并提示任务会尝试可用的后续档位；关闭开关时仍阻止不可用的硬件方案。
  - 每次退回都显示在文件参数决策原因和诊断日志中，不作为任务 Retry 次数。
- **输出视频编码格式 (Video Codec)**：
  - 单选 Segmented Control：`HEVC / H.265 (推荐, 极致体积)` vs `H.264 / AVC (广泛兼容)`。
- **输出封装格式 (Container)**：
  - 单选 Segmented Control：`MP4 (通用兼容)` vs `MKV (多音轨/字幕友好)`。封装格式与视频编码格式分开配置。

### Step 3: 智能分辨率与码率策略 (Resolution & Smart Bitrate)

严格落地脚本中的**智能降级机制（源视频质量更低时不反向放大）**：

- **目标分辨率高度设定 (Video Height)**：
  - 预设 Pill 按钮组：`保持原高度 (-1)`、`4K (2160p)`、`1080p`、`720p (默认)`、`480p`、`360p`。
  - _智能规则提示_：根据源视频实际宽高、旋转信息及宽高比计算目标尺寸，在保持原始宽高比的前提下不进行分辨率放大；需要硬件缩放且链路允许时优先采用 `scale_rkrga`。
- **目标码率控制 (Bitrate Allocation)**：
  - 预设档位切换：`1000 kbps`、`2000 kbps (推荐)`、`4000 kbps`、`6000 kbps`、`自定义输入`。
  - _智能码率防护开关 (Smart Bitrate Cap)_：默认开启。
    - _说明_：“Worker 实际处理文件时调用 ffprobe 获取原视频实际码率；远程文件需先下载到本地缓存再执行 ffprobe。若原码率低于目标设定，则以原码率作为实际目标参考值，防止无意义放大文件体积。”
  - 高级设置折叠面板（Accordion）：GOP 大小（默认 120）、音频流策略（默认 Copy 音轨 `-c:a copy`）、字幕处理策略。字幕编码/封装方式根据目标容器动态决定，不将 `-c:s mov_text` 作为所有容器的固定规则。

### Step 4: 预检确认与启动 (Pre-flight Summary)

- **信息总览卡片 (Summary Card)**：
  - 列出源路径、输出路径、伴随文件复制策略、加速引擎、自动退回策略、目标封装格式、目标分辨率与码率上限。
  - 明确标注这里展示的是“用户目标参数 (Requested Params)”，不是每个文件最终的实际参数；实际参数需要等 Worker 对单文件 ffprobe 后由参数决策器生成。
- **扫描与统计按钮 (Scan & Estimate)**：
  - 点击后后端仅进行快速轻量的文件扫描，返回视频文件数量、字幕文件数、其他非视频文件数、预计总体积等基础信息。远程目录通过 rclone 获取文件列表、大小、修改时间等元数据，此阶段不批量执行 ffprobe。
  - 根据当前 `companionFilePolicy` 在统计结果中明确显示 `将复制 N 个伴随文件`；选择 `不复制` 时显示 `伴随文件：不复制`，避免用户误以为扫描到的字幕一定会被复制。
  - 实际媒体预检由 Worker 在处理单个文件时执行：远程文件先通过 rclone 下载到本地缓存，再由 ffprobe 获取编码、分辨率、码率、帧率、时长及音视频流信息，计算最终参数后调用 ffmpeg-rockchip 转码；远程输出在转码成功后再通过 rclone 上传。
- **操作按钮组**：
  - `返回上一步`
  - `立即加入转码队列`（主按钮，高亮蓝色，带加载过渡态）。

---

## 5. 页面 2：任务清单与实时监控 (`/tasks`)

以“**任务 (Task Job)**”为最小聚合单元，每个任务管理一批视频文件或一个输入目录，包含完整的生命周期控制。

### 5.1 顶部数据看板 (Metrics Header)

- 五张轻量统计指标卡片：
  - **转码槽位**：显示 `Transcode 0/1` 或 `1/1`、当前任务与文件、即时速度（如 `4.2x / 125 fps`）；任何时候只允许一个 FFmpeg 转码。
  - **上传槽位**：显示 `Upload 0/1` 或 `1/1`、当前上传文件，以及 `待上传 N`；上传可以与下一文件转码并行。
  - **排队任务**：Queued 数量，并区分“等待转码”和“仅等待上传”。
  - **已完成任务**：成功数、处理总视频量。
  - **节省存储统计**：转码前体积 vs 转码后体积，计算总节省百分比（如 `48.5 GB -> 19.2 GB, 节省 60.4%`）。

### 5.2 任务卡片设计 (Task Card Hierarchy)

每个任务为一个高辨识度的独立白底卡片，分为：

1.  **卡片头部 (Task Header)**：
    - 任务唯一 ID、创建时间、源目录与输出目录简写路径（悬停显示全路径）。
    - 硬件加速模式标签（如 `MPP Hardware / HEVC` 绿标）。
    - 状态徽章（Badge）：任务级状态使用 `队列中 (Queued)`、`运行中 (Running)`、`已完成 (Completed)`、`部分失败 (Partial Failed)`、`已失败 (Failed)`、`已停止 (Stopped)`、`已中断 (Interrupted)`；`Interrupted` 使用 Amber 警示态，并显示“检测到上次进程/容器中断，可 Retry”。文件阶段增加 `待上传 (Upload Queued)`，完整阶段包括 `下载中 (Downloading)`、`预检中 (Probing)`、`转码中 (Transcoding)`、`待上传 (Upload Queued)`、`上传中 (Uploading)`。同一任务卡片可能同时出现一个转码文件和另一个上传文件。
2.  **卡片主体 (Progress & Current File)**：
    - **总体进度条 (Task Level)**：清晰的百分比进度条（如 `7 / 24 视频完成 - 35%`），附带成功/失败/跳过的微型色彩段；启用伴随文件复制时，在旁边补充 `伴随文件 18/20` 等独立计数，不把非视频文件混入“视频完成数”。
    - **活动流水线详情 (Active Pipeline)**：允许同时展示两个并列/上下排列的子卡片：
      - **转码子卡片**：当前转码链路文件名与阶段；进入 `Transcoding` 后展示细分进度条、瞬时码率、当前帧数 (Frame)、编码速度 (Speed, 如 `3.8x`)、已处理媒体时间、预估剩余时间 (ETA)。这些字段只读取后端结构化 Progress DTO，不解析 FFmpeg stderr。
      - 如果媒体时长缺失或后端返回 `percent/eta = null`，转码进度条切换为不确定进度样式，只展示 Frame/FPS/Speed/已处理时间，禁止前端自行猜测百分比。
      - **上传子卡片**：当前上传文件、目标 remote、`Uploading` 状态，以及后端能够提供时的已上传字节/百分比；若另有已完成转码但等待上传的文件，显示 `待上传 1`。
      - 智能决策提示：若当前转码文件触发原码率保护，显示 `[智能限码率: 1.4 Mbps < 2.0 Mbps]` 标识。
      - 当上传与转码同时发生时，在两张子卡片之间显示轻量 `Pipeline` 标识，明确它们是两个独立槽位，而不是两个并发 FFmpeg。
3.  **可折叠文件清单、参数决策与日志面板 (Collapsible Details)**：
    - 点击展开后查看任务内包含的所有文件详细状态表（例如：等待 / 下载 / 预检 / 转码 / 待上传 / 上传 / 已完成 / 失败 / 中断 / 跳过）。
    - 每个已完成 ffprobe 的文件提供 `参数决策 (Parameter Decision)` 抽屉，采用三列对比：`源参数 Source` / `用户参数 Requested` / `实际参数 Effective`。
    - 对发生自动调整的字段显示原因标签，例如 `不放大 720p → 720p`、`Smart Bitrate Cap`、`容器兼容性调整`、`RGA 硬件缩放`；支持展开 `decision_log` 查看完整原因。
    - 高级诊断区可显示后端返回的实际 FFmpeg argv（路径按后端策略脱敏），便于复现问题。
    - 内置微型控制台视图（只读日志流）显示 stderr 日志，最多保留最近 300 条；日志只用于诊断，不作为进度来源。
4.  **操作动作栏 (Action Bar)**：
    - **停止按钮 (Stop)**：向后端请求停止任务；如果该任务同时占用转码槽位和上传槽位，后端分别终止属于该任务的 ffmpeg/rclone 子进程并停止领取新工作；不得影响另一槽位中属于其他任务的进程。第一版不提供暂停/恢复状态。
    - **重新开始 (Retry)**：对 `Interrupted / Failed / Partial Failed` 任务一键重试；弹窗明确提示“已成功文件不会重复处理，未完成文件会从文件级安全检查点重新开始，不能从 FFmpeg 中间帧续传”。
    - **删除任务 (Delete)**：弹窗二次确认。默认删除任务记录并清理任务缓存、`.part` 等未完成临时文件；不得默认删除已经成功生成或上传的正式输出文件。

---

## 6. 异常处理、认证与网络交互设计 (Resilience & Auth)

1.  **HTTP Basic Auth 优雅处理**：
    - Axios Response 拦截器监听 `401 Unauthorized` 状态码。
    - 弹出简洁的登录认证抽屉（Modal），提示输入用户名和密码，或交由浏览器原生 Auth 对话框。
2.  **容器重启/异常退出恢复**：
    - 页面初始化必须先调用任务 Snapshot API，不依赖浏览器内存恢复任务状态。
    - 后端启动恢复后，如果存在 `Interrupted` 任务，在 `/tasks` 顶部显示一次非阻塞恢复提示：`检测到 N 个上次未完成任务，可选择 Retry`。
    - 任务卡片保留中断阶段、上次错误、最近一次进度时间与 Retry 次数；刷新页面或重启浏览器不会丢失。
3.  **SSE 重连与状态校准**：
    - EventSource 断线使用指数退避重连（1s -> 2s -> 5s -> 10s，最高保持 10s）。
    - 每次 SSE 重连成功后主动重新拉取一次当前任务 Snapshot，再继续消费增量事件，避免断线窗口漏事件造成前端状态漂移。
    - 所有事件按 `task_id + file_id + updated_at/version` 合并，旧事件不得覆盖更新状态。
4.  **日志与进度严格分离**：
    - 结构化转码进度来自后端 FFmpeg `-progress` 解析后的 DTO；前端不解析 stderr 文本。
    - stderr 仅进入诊断日志面板，最多渲染最近 300 条（滚动缓冲区），防止长时间运行占用宿主机浏览器过多内存。
5.  **双槽位流水线可视化**：
    - 系统状态区分别显示 `Transcode: 0/1 | Upload: 0/1`，Tooltip 明确：`FFmpeg 严格单并发；上传可与下一文件转码并行`。
    - 当两个槽位同时工作时，允许任务列表同时存在两个 `Running` 卡片，或同一卡片内同时存在转码/上传两个活动子卡片。
    - Queued 任务分别显示 `等待转码`、`待上传` 或对应队列位置，不使用一个“唯一活动任务”概念误导用户。

---

## 7. 前后端状态契约与结构化进度 DTO (State & Progress Contracts)

前端 TypeScript 类型应与后端 DTO 一一对应，禁止在组件内部使用自由字符串拼接状态。

```ts
type TaskStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial_failed'
  | 'failed'
  | 'stopped'
  | 'interrupted'

type FileStage =
  | 'pending'
  | 'downloading'
  | 'probing'
  | 'transcoding'
  | 'upload_queued'
  | 'uploading'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'skipped'

interface TranscodeProgress {
  taskId: string
  fileId: string
  stage: 'transcoding'
  frame: number | null
  fps: number | null
  bitrateKbps: number | null
  outTimeMs: number | null
  totalSizeBytes: number | null
  speed: number | null
  percent: number | null
  etaSeconds: number | null
  progress: 'continue' | 'end'
  updatedAt: string
}
```

`percent` 与 `etaSeconds` 允许为 `null`，组件必须正确处理未知时长媒体。

### 7.1 任务创建参数中的伴随文件策略

```ts
type CompanionFilePolicy = 'none' | 'subtitles' | 'all_non_video'

interface CreateTaskRequest {
  // ...其他任务参数
  companionFilePolicy: CompanionFilePolicy
}
```

前端仅提交枚举值，不根据文件扩展名自行决定最终复制集合；实际扫描、过滤、冲突检测和复制结果以后端为准。`all_non_video` 包含字幕文件，因此三个选项是严格互斥且递进的。

### 7.2 参数决策 DTO

```ts
interface ParameterDecision {
  source: Record<string, unknown>
  requested: Record<string, unknown>
  effective: Record<string, unknown>
  reasons: Array<{
    field: string
    code: string
    message: string
  }>
  ffmpegArgv?: string[]
}
```

UI 不直接从 `source/requested` 推导 `effective`，只展示后端参数决策器返回的结果，保证前后端判断完全一致。

### 7.3 SSE 事件类型

第一版建议固定使用以下事件：

- `task.state`：任务级状态变化；
- `file.state`：文件阶段变化；
- `transcode.progress`：FFmpeg 结构化进度；
- `task.metrics`：任务总体统计变化；
- `system.status`：MPP/RGA/rclone/CPU/内存、`transcodeSlot 0/1`、`uploadSlot 0/1`、`uploadQueued` 状态；
- `log.append`：诊断日志增量。

所有事件 payload 至少包含 `updated_at` 或单调递增 `version`。前端 Pinia Store 先按版本去旧，再更新页面。

---

## 8. 重启恢复与 Retry 交互细节 (Recovery UX)

### 8.1 Interrupted 任务卡片

`Interrupted` 不等同于普通 `Failed`：

- Badge 使用 Amber 而不是 Red；
- 主文案：`上次运行被中断`；
- 次要信息显示：`中断链路：转码 / 上传`、`最后更新时间`、`已完成 X/Y`；若容器退出时两个槽位都在工作，可同时列出两个中断文件；
- 主操作为 `继续 Retry`；
- 可展开查看后端提供的 `interrupted_reason` 和残留文件处理结果。

### 8.2 Retry 确认弹窗

确认弹窗至少说明：

- 已成功文件保持完成，不会重新转码；
- 转码阶段未完成的文件会重新 ffprobe、重新运行参数决策器并重新转码；
- 已经进入 `upload_queued`，或上传中断但本地完整转码产物校验通过的文件，只重新排队上传，不重复 FFmpeg；
- `.part` 等不完整 FFmpeg 输出会被清理；完整待上传产物在远程提交成功前保留；
- 如果发现最终输出文件已存在但无法确认是否由上次任务完整提交，任务会报告输出冲突，不会自动覆盖。

Retry 请求成功后，任务根据文件检查点进入对应队列：需要重转码的等待 `Transcode 0/1` 槽位；可复用完整转码产物的直接等待 `Upload 0/1` 槽位。卡片展示 `Retry #N`。

### 8.3 参数决策对比组件

建议实现独立 `ParameterDecisionPanel.vue`：

- Desktop 使用三列表格：Source / Requested / Effective；
- 自动改变的字段高亮 Effective 单元格，并在右侧显示 reason icon；
- 未变化字段使用弱化样式，减少视觉噪声；
- 支持“只看有变化项”；
- 对硬件模式、encoder、scale filter、container/audio/subtitle strategy 提供易读标签，同时保留原始技术值供复制。

---

## 9. 单转码 + 单上传流水线表现 (Pipeline Queue UX)

后端具有两个固定槽位：`Transcode 0/1` 与 `Upload 0/1`。前端不提供并发度设置入口，因为 FFmpeg 永远严格单并发，上传也固定最多一个；但必须明确表达两个槽位可以同时工作。

### 9.1 典型流水线

```text
时间 ─────────────────────────────────────────────>

视频 A: [下载][预检][====== 转码 ======][---- 上传 ----]
视频 B:                         [下载][预检][====== 转码 ======][---- 上传 ----]
视频 C:                                                [下载][预检][====== 转码 ======]
```

前端语义：

- A 进入 `upload_queued` 后立即释放转码槽位；
- A `Uploading` 时，B 可以处于 `Downloading / Probing / Transcoding`；
- 同时最多一个 `Transcoding`、一个 `Uploading`；
- 如果已有 `1 Uploading + 1 Upload Queued`，后端会对新的远程输出转码施加背压，前端可显示 `等待上传缓冲释放`，避免用户误认为系统卡死；
- 本地输出不经过上传槽位。

### 9.2 任务排序与跨任务并行

任务列表排序建议：

1. Running（优先当前占用 Transcode 槽位的任务，其次仅占用 Upload 槽位的任务）；
2. Queued（按转码/上传各自队列顺序）；
3. Interrupted / Partial Failed / Failed；
4. Completed / Stopped。

可能出现 `任务 A：Uploading` 与 `任务 B：Transcoding` 同时为 Running，这是正常流水线行为。任务 A 只有在所有文件远程提交成功后才进入 Completed；其最后一个文件上传期间，不阻塞任务 B 使用空闲 FFmpeg 转码槽位。

Queued 卡片不要只显示一个模糊的 `队列第 N 位`，而应显示具体原因，例如：

- `等待转码 · 第 2 位`
- `待上传 · 第 1 位`
- `等待上传缓冲释放`

这样 UI 与后端双槽位调度模型保持一致，同时仍然明确“没有两个 FFmpeg 在并发转码”。

