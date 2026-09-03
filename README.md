# FFPanel

[![Docker image build](https://github.com/smy116/FFPanel/actions/workflows/docker-image.yml/badge.svg)](https://github.com/smy116/FFPanel/actions/workflows/docker-image.yml)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org/)

面向 Rockchip RK3588 的自托管批量视频转码工作台。

FFPanel 将本地目录与已有的 [rclone](https://rclone.org/) remote 统一为任务输入/输出，使用 [ffmpeg-rockchip](https://github.com/nyanmisaka/ffmpeg-rockchip) 提供硬件编解码能力，并通过 SQLite 保存文件级状态与可恢复检查点。它适合部署在家庭服务器、NAS 或边缘设备上，通过浏览器完成任务创建、实时监控、停止和 Retry。

## 核心能力

- 四步任务向导：输入/输出位置、编解码方案、画质策略、扫描确认。
- 支持本地目录和 rclone remote 的任意输入/输出组合，递归扫描并保留相对目录结构。
- Rockchip MPP/RGA、CPU + MPP、纯 CPU 三档编解码模式，可按策略自动退回。
- 智能分辨率与码率决策：不放大低规格源视频，并可按源码率限制目标码率。
- 字幕、封面、NFO 等伴随文件的三档复制策略：不复制、仅复制字幕、复制全部非视频文件。
- 固定一个 FFmpeg 转码槽位和一个传输槽位；远程输出上传时可与下一文件转码流水线并行。
- SQLite 任务历史、启动恢复、文件级检查点、Retry、Stop、Delete，以及最近 300 条诊断日志。
- REST Snapshot + SSE 增量状态；可选 HTTP Basic Auth 同时保护 WebUI 与 API。

## 工作流与架构

```text
浏览器 WebUI
   ├─ REST：创建任务、读取 Snapshot、Stop、Retry、Delete
   └─ SSE ：任务状态、文件状态、结构化转码进度、诊断日志
                    │
              FastAPI + Scheduler
          ┌─────────┼─────────┐
       SQLite     FFmpeg     rclone
    /config/     ffprobe    local/remote
     ffpanel.db
```

单个远程文件的典型流程如下：

```text
扫描 → 下载到缓存 → ffprobe 预检 → 参数决策 → FFmpeg 转码
                                           └→ 本地原子提交 / rclone 临时上传后提交
```

正式输出先写入 `.part` 临时文件，成功并完成文件大小检查后再提交到目标路径；已有目标文件不会被静默覆盖。容器或进程异常退出后，正在运行的任务会标记为 `interrupted`，可从文件级安全检查点 Retry。Retry 不是从 FFmpeg 中间帧继续编码。

## 快速开始：RK3588 Docker 部署

### 环境要求

- Linux ARM64 主机，推荐 Rockchip RK3588 设备及厂商 BSP/内核。
- Docker Engine 与 Docker Compose Plugin。
- 宿主机能够提供 `/dev/dri`、`/dev/dma_heap`、`/dev/rga`、`/dev/mpp_service` 等设备节点。
- 如果需要远程存储，准备好宿主机侧的 `rclone.conf`。

Docker 镜像面向 `linux/arm64` 构建。首次构建会编译 MPP、RGA 和 ffmpeg-rockchip，耗时可能较长；不依赖宿主机安装 FFmpeg。

仓库的 GitHub Actions 会在 push 和 Pull Request 时构建 `linux/arm64` 镜像，并在默认分支或 `v*` 版本标签上发布镜像。

### 启动

在 RK3588 主机上执行：

```bash
git clone https://github.com/smy116/FFPanel.git
cd FFPanel

mkdir -p config/rclone cache media
# 可选：启用 rclone remote 时复制已有配置
cp /path/to/rclone.conf config/rclone/rclone.conf

docker compose up -d --build
docker compose ps
```

打开 `http://<设备地址>:8090`。容器内的本地媒体根目录是 `/media`，因此向导中应填写例如 `/media/incoming` 和 `/media/encoded`。

常用运维命令：

```bash
docker compose logs -f ffpanel
docker compose restart ffpanel
docker compose down
```

### 启用认证

编辑 `docker-compose.yml` 中的 `environment`，再启动或重启容器：

```yaml
FFPANEL_AUTH_ENABLED: "true"
FFPANEL_AUTH_USERNAME: "operator"
FFPANEL_AUTH_PASSWORD: "change-this-before-start"
```

Basic Auth 会保护 WebUI、API 和 SSE；`/healthz` 为容器健康检查保留为免认证端点。不要把服务直接暴露到公网，生产环境建议在反向代理后启用 HTTPS，并使用更安全的凭据管理方式。

### rclone remote

FFPanel 只读取已有的 rclone 配置，不负责创建 remote、修改配置、OAuth 登录或凭据管理。未挂载配置文件或 rclone 不可用时，远程存储会被禁用，但本地转码仍可使用。

默认挂载路径为 `./config/rclone/rclone.conf` → `/config/rclone/rclone.conf`。升级容器前请备份 `./config`；容器启动时会自动执行 Alembic 数据库迁移。`./cache` 只保存下载缓存和临时产物，清理它可能使未完成任务回退到重新下载或转码，不能替代数据库备份。

## 本地开发

本地开发可在非 RK3588 平台进行 API/UI 开发和测试；MPP/RGA 能力验证必须在目标设备上完成。

### 安装依赖

```bash
git clone https://github.com/smy116/FFPanel.git
cd FFPanel

python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

cd web
npm ci
cd ..
```

非容器运行时需要自行安装并确保 `ffmpeg`、`ffprobe` 在 `PATH` 中；使用 rclone remote 时还需要安装 `rclone` 并设置配置文件路径。

### 启动开发服务

后端默认使用容器路径。开发时建议将数据目录指向仓库内的本地目录：

```bash
# Linux/macOS
export FFPANEL_CONFIG_DIR="$PWD/config"
export FFPANEL_CACHE_DIR="$PWD/cache"
export FFPANEL_LOCAL_ROOTS="$PWD/media"

# Windows PowerShell 对应写法：
# $env:FFPANEL_CONFIG_DIR = "$PWD\config"
# $env:FFPANEL_CACHE_DIR = "$PWD\cache"
# $env:FFPANEL_LOCAL_ROOTS = "$PWD\media"
```

分别在两个终端启动后端和前端：

```bash
# 终端一：仓库根目录
uvicorn ffpanel.main:app --reload --port 8090

# 终端二：web 目录
cd web
npm run dev
```

开发页面地址为 `http://127.0.0.1:5173`，后端 API 文档为 `http://127.0.0.1:8090/docs`，ReDoc 地址为 `http://127.0.0.1:8090/redoc`。开发/测试不需要真实媒体工具时，可设置 `FFPANEL_MOCK_MEDIA=true` 使用模拟媒体能力。

## 配置参考

所有配置项均使用 `FFPANEL_` 前缀，可通过环境变量或仓库根目录的 `.env` 设置。Compose 部署建议直接修改 `docker-compose.yml` 的 `environment` 区块。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `FFPANEL_HOST` | `0.0.0.0` | HTTP 监听地址 |
| `FFPANEL_PORT` | `8090` | HTTP 监听端口 |
| `FFPANEL_CONFIG_DIR` | `/config` | SQLite、锁文件和持久化配置目录 |
| `FFPANEL_CACHE_DIR` | `/cache` | 远程输入缓存、临时输出和任务缓存 |
| `FFPANEL_LOCAL_ROOTS` | `/media` | 逗号分隔的本地路径白名单；WebUI 不能访问白名单之外的路径 |
| `FFPANEL_DATABASE_URL` | 未设置 | 默认使用 `config_dir/ffpanel.db`，可覆盖 SQLAlchemy 数据库 URL |
| `FFPANEL_RCLONE_CONFIG` | `/config/rclone/rclone.conf` | rclone 配置文件路径 |
| `FFPANEL_FFMPEG_PATH` | `ffmpeg` | FFmpeg 可执行文件路径 |
| `FFPANEL_FFPROBE_PATH` | `ffprobe` | ffprobe 可执行文件路径 |
| `FFPANEL_RCLONE_PATH` | `rclone` | rclone 可执行文件路径 |
| `FFPANEL_AUTH_ENABLED` | `false` | 是否启用 HTTP Basic Auth |
| `FFPANEL_AUTH_USERNAME` | 空 | Basic Auth 用户名；启用认证时必填 |
| `FFPANEL_AUTH_PASSWORD` | 空 | Basic Auth 密码；启用认证时必填，不会写入任务数据库 |
| `FFPANEL_LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING` 或 `ERROR` |
| `FFPANEL_MOCK_MEDIA` | `false` | 开发/测试用模拟媒体执行模式 |
| `FFPANEL_SCAN_TTL_SECONDS` | `900` | 扫描令牌有效期，范围 `60–3600` 秒 |
| `FFPANEL_PROGRESS_PERSIST_SECONDS` | `3.0` | 结构化进度写入数据库的间隔，范围 `1–10` 秒 |
| `FFPANEL_STOP_TIMEOUT_SECONDS` | `8.0` | Stop 后等待子进程退出的时间，范围 `1–30` 秒 |

### 本地路径安全边界

`FFPANEL_LOCAL_ROOTS` 是本地文件访问白名单，不是展示用配置。输入、输出和浏览操作都必须位于白名单目录内；Docker 部署时需要同时保证宿主机目录挂载到对应的容器路径。

## 任务状态与恢复

任务级状态包括：`queued`、`running`、`completed`、`partial_failed`、`failed`、`stopped`、`interrupted`。

文件级处理阶段包括：

```text
pending → downloading → probing → transcoding → upload_queued → uploading → completed
```

本地输出在转码完成后直接原子提交，不经过 `upload_queued`。远程输出使用独立的单传输槽位，因此可能出现“文件 A 上传 + 文件 B 转码”；系统始终最多只有一个 FFmpeg 转码进程和一个传输进程。

Retry 的行为：

- 已完成文件保持完成，不重复处理。
- 转码阶段中断或产物大小检查失败的文件重新执行 ffprobe、参数决策和转码。
- 已有完整本地转码产物的远程文件只重新进入上传队列。
- `.part` 等不完整产物会被清理；正式输出不会因为删除任务而删除。
- 自动硬件退回记录在文件参数决策和诊断日志中，不计入任务 Retry 次数。

## API 与 OpenAPI 契约

完整契约见 [`openapi.json`](openapi.json)，运行服务后也可访问 `/docs` 和 `/redoc`。

| 用途 | 方法与路径 |
| --- | --- |
| 健康检查 | `GET /healthz` |
| 读取系统与任务快照 | `GET /api/v1/snapshot` |
| 读取已配置 remote | `GET /api/v1/remotes` |
| 浏览存储位置 | `POST /api/v1/storage/browse` |
| 扫描输入并生成令牌 | `POST /api/v1/storage/scan` |
| 创建任务 | `POST /api/v1/tasks` |
| 查询任务、文件、伴随文件、日志 | `GET /api/v1/tasks/{task_id}/*` |
| Stop / Retry / Delete | `POST /api/v1/tasks/{task_id}/stop`、`POST /api/v1/tasks/{task_id}/retry`、`DELETE /api/v1/tasks/{task_id}` |
| 实时事件流 | `GET /api/v1/events`（SSE） |

修改公开 API 后，按以下顺序更新契约和前端类型：

```bash
python scripts/export_openapi.py
cd web
npm run api:generate
```

`web/src/generated/openapi.ts` 是生成文件，不要手动编辑。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `ffpanel/` | FastAPI 后端、调度器、存储、媒体探测与数据库模型 |
| `web/src/` | Vue 3 + TypeScript WebUI |
| `tests/` | 后端 API、媒体决策、存储和恢复测试 |
| `alembic/versions/` | 数据库迁移 |
| `scripts/` | OpenAPI 导出与 RK3588 能力验证脚本 |
| `docker/` | 容器入口脚本 |
| `docs/` | [功能需求](docs/FFPanel功能需求.md) 与 [前端设计](docs/FFPanel前端设计.md) |
| `openapi.json` | 提交到仓库的 API 契约 |

## 验证与贡献

提交前建议运行：

```bash
pytest
ruff check .
mypy ffpanel

cd web
npm test
npm run build
```

在 RK3588 宿主机上可运行：

```bash
sh scripts/verify-rk3588.sh
```

该脚本会检查 `ffmpeg`、`ffprobe`、`rclone`、设备节点、MPP/RGA 能力，并执行一次硬件转码验证。涉及 API 变更时，需同时提交 `openapi.json` 和生成后的前端类型文件。

欢迎提交 Issue 和 Pull Request。请在 PR 描述中说明变更动机、验证命令，以及是否涉及迁移或部署配置；界面改动请附截图。

## 设计边界

- 当前并发度固定为单转码、单传输，不提供运行时并发度调节。
- 当前没有 FFmpeg 中间帧暂停/续传；Retry 以文件级检查点为粒度。
- FFPanel 不管理 rclone remote 或云端凭据。
- Docker 镜像和硬件验证目标为 `linux/arm64` / RK3588；其他架构需要自行适配媒体栈和设备映射。
- HTTP Basic Auth 只提供基础访问控制，不替代 HTTPS、反向代理或完整的身份管理系统。

## 许可证

当前仓库尚未包含 `LICENSE` 文件。正式发布或对外分发前，请补充明确的开源许可证及第三方依赖的许可证说明。
