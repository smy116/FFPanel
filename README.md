# FFPanel

FFPanel 是面向 RK3588 的批量视频转码工作台。它把本地目录和已有的 rclone remote 统一为任务输入/输出，使用 SQLite 保存文件级检查点，并以一个 FFmpeg 槽位和一个传输槽位组成可恢复的流水线。

## 功能

- 4 步任务向导：存储路径、硬件/编码方案、画质策略、扫描确认。
- CPU/MPP/RGA 参数决策，自动避免放大分辨率和无意义提升码率。
- 本地与 rclone 任意组合，保留目录结构并保守处理输出冲突。
- 转码与上传并行，严格限制为 `Transcode 1/1`、`Upload 1/1`。
- SQLite 任务历史、启动恢复、文件级 Retry、Stop 和 Delete。
- REST Snapshot + SSE 增量状态；可选 HTTP Basic Auth 同时保护 UI 与 API。

## API 契约

修改公开 API 后，先运行 `python scripts/export_openapi.py`，再在 `web` 目录运行
`npm run api:generate`。后端测试会检查提交的 OpenAPI 契约是否与应用一致。

## RK3588 部署

1. 将 `.env.example` 复制为 `.env`，按需启用认证。
2. 把已有 `rclone.conf` 放到宿主机 `./config/rclone/rclone.conf`。
3. 确认宿主机 vendor/BSP 内核提供 Compose 中列出的 MPP/RGA 设备节点。
4. 执行 `docker compose -f docker-compose.yml up -d --build`。
5. 打开 `http://设备地址:8080`。

镜像固定构建 MPP、RGA、ffmpeg-rockchip 与 rclone 版本，不依赖宿主机 FFmpeg。若部分兼容设备节点不存在，可从 Compose 删除对应映射；`/dev/dri`、`/dev/dma_heap`、`/dev/rga`、`/dev/mpp_service` 是 RK3588 的主要节点。

升级前停止容器并备份 `./config`。Alembic 会在启动时升级 `/config/ffpanel.db`；`./cache` 仅保存可恢复或可清理的中间产物，不能代替数据库备份。

## 配置

所有变量以 `FFPANEL_` 开头。关键配置见 [.env.example](.env.example)：本地根目录、数据库与缓存目录、rclone 配置、工具路径、认证和日志级别。

`FFPANEL_LOCAL_ROOTS` 是逗号分隔的容器内路径白名单。WebUI 不能浏览或处理白名单之外的本地路径。FFPanel 只读取已有 rclone remote，不管理凭据或 OAuth。

## 验证

```bash
pytest
cd web && npm test && npm run build
```

在 RK3588 上执行 `scripts/verify-rk3588.sh` 检查二进制、设备节点和硬件编解码能力。
