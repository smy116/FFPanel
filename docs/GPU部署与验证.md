# GPU 部署与验证

FFPanel 保留 RK3588 的默认部署入口。统一发布标签同时包含 `linux/arm64` 和
`linux/amd64`：ARM64 使用现有 ffmpeg-rockchip、MPP/RGA；AMD64 使用上游 FFmpeg，
包含 NVIDIA NVENC/NVDEC、Intel QSV/VAAPI 和 CPU 编码器，不包含 Rockchip 库。

## 选择部署配置

在仓库根目录执行，四个入口均使用服务名 `ffpanel`、端口 8090 和相同的数据卷。
同一目录只启动一个配置；切换硬件配置前先用原配置执行 `down`。
`docker-compose.common.yml` 是被引用的公共配置，不单独启动。

| 主机 | 构建并启动 | 设备要求 |
| --- | --- | --- |
| RK3588 / ARM64 | `docker compose up -d --build` | 保留 `/dev/dri`、`/dev/dma_heap`、`/dev/rga`、`/dev/mpp_service` 与特权模式 |
| Intel / AMD64 | `docker compose -f docker-compose.intel.yml up -d --build` | `/dev/dri`、Intel 内核驱动 |
| NVIDIA / AMD64 | `docker compose -f docker-compose.nvidia.yml up -d --build` | NVIDIA 驱动与 Container Toolkit |
| CPU / AMD64 | `docker compose -f docker-compose.cpu.yml up -d --build` | 无 GPU 要求 |

使用发布镜像时，设置 `FFPANEL_IMAGE=ghcr.io/smy116/ffpanel:latest` 或固定版本标签，
执行所选配置的 `pull`，再执行 `up -d --no-build`。RK 默认本地镜像名仍为
`ffpanel:1.0.0-rk3588`；镜像地址可通过 `FFPANEL_IMAGE` 覆盖。

ARM64 纯 CPU 部署使用 `FFPANEL_PLATFORM=linux/arm64` 和 `FFPANEL_DOCKERFILE=Dockerfile`，
再运行 CPU 配置。没有映射 Rockchip 设备时不会尝试硬件初始化。

## Intel

```bash
export FFPANEL_INTEL_RENDER_DEVICE=/dev/dri/renderD128
docker compose -f docker-compose.intel.yml up -d --build
```

多个 GPU 的机器可选择 `renderD129` 等实际 Intel 节点。FFPanel 读取
`/sys/class/drm/<render节点>/device/vendor`，要求厂商为 `0x8086`，再验证设备读写权限。
不要屏蔽该 sysfs 路径；仅有 `/dev/dri` 并不代表存在 Intel GPU。

AMD64 镜像安装 Bookworm 的 `libvpl2`、`libmfx-gen1.2` 和完整
`intel-media-va-driver-non-free`（iHD）。oneVPL GPU runtime 与 iHD 是不同组件，
QSV 和 VAAPI 分别探测。基线面向 Tiger Lake、Alder/Raptor Lake、Arc Alchemist 等
该版本驱动支持的设备；不包含旧 i965/Media SDK 兼容栈，也不承诺 Bookworm 驱动支持
所有更新的 Intel GPU。实际支持范围以容器内运行时探测和严格转码验证为准。

Intel 配置设置 `LIBVA_DRIVER_NAME=iHD`，程序也在 VAAPI 初始化参数中明确选择 iHD。
若自行改为非 root 容器用户，需添加设备对应的宿主机 render/video 数字 GID 权限。
QSV 初始化失败、VAAPI 正常时，界面仍可选择 VAAPI；无需启用特权模式。

## NVIDIA

宿主机先安装兼容 NVIDIA 驱动和 NVIDIA Container Toolkit，并为 Docker 配置 NVIDIA
运行时。镜像不打包宿主机内核驱动；相关用户态驱动库由 Toolkit 注入。

```bash
export NVIDIA_GPU_ID=0              # 宿主机 GPU 序号，也可使用 GPU UUID
export FFPANEL_NVIDIA_DEVICE=0      # 容器可见 GPU 的 CUDA 序号
docker compose -f docker-compose.nvidia.yml up -d --build
```

默认仅映射一个 GPU，因此容器内选择 `0`。不要把宿主机 UUID 填入
`FFPANEL_NVIDIA_DEVICE`。需要多张可见 GPU 时修改 Compose 的 `device_ids`，
并使用容器内实际枚举的 CUDA 序号。GPU reservation 明确要求 `capabilities: [gpu]`，
驱动能力为 `compute,video,utility`。

构建固定使用 FFmpeg `n7.1.3`、`nv-codec-headers n12.2.72.0`，后者要求
Linux NVIDIA 驱动至少 `550.54.14`。GPU 本身还必须支持所选编码：例如 H.264 可用
而 HEVC 不可用时，状态显示 Partial，不会把 HEVC 视为可用。
CUDA 缩放使用 LLVM 编译的 `scale_cuda`，不依赖 NPP 或 FFmpeg `--enable-nonfree`。

官方资料：[NVIDIA headers 驱动要求](https://github.com/FFmpeg/nv-codec-headers/blob/n12.2.72.0/README)、
[Container Toolkit 安装](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)、
[Compose GPU 配置](https://docs.docker.com/compose/how-tos/gpu-support/)。

## 方案、状态与回退

| 起始方案 | 自动回退链 |
| --- | --- |
| MPP 硬件编解码 | `mpp_mpp → cpu_mpp → cpu_cpu` |
| NVDEC + NVENC | `nvdec_nvenc → cpu_nvenc → cpu_cpu` |
| Intel QSV | `qsv_qsv → cpu_qsv → vaapi_vaapi → cpu_vaapi → cpu_cpu` |
| Intel VAAPI | `vaapi_vaapi → cpu_vaapi → cpu_cpu` |

从中间档位开始时只执行其后续链路。关闭自动回退时只尝试指定方案。不会跨 NVIDIA、
Intel、Rockchip 厂商切换。每次尝试的失败与最终参数可在文件详情查看。

新增 GPU 硬解方案使用硬件帧与硬件缩放。旋转、无法支持的输入像素格式或滤镜会触发
显式回退，由 CPU 解码和软件滤镜处理，再使用硬件编码；严格模式报错。
输出保持现有 8-bit 4:2:0 能力范围，不提供 HDR 色调映射。硬件支持会随输入编码、
profile、位深和分辨率变化，基础探测成功不等于所有视频都可硬解。

QSV 通过平均码率与峰值码率的关系选择 VBR/CBR。VBR 平均码率使用上限的 90%，
峰值保持用户上限；CBR 二者相等。该差异会记录在参数决策说明中。

状态栏按检测到的设备动态显示 MPP、NVENC、Intel QSV/VAAPI；点击可展开 RGA、
NVDEC、QSV、VAAPI 和失败原因。无 GPU 时显示 CPU。Ready 表示相应基础能力可用，
Partial 表示部分能力成功，Unavailable 表示不可用；Detecting 仅用于检测未完成。
MPP/RGA 保持原有节点与编译清单检测规则，新增 GPU 能力要求运行时检查成功。

探测在启动时执行一次，后续状态广播复用结果。修改驱动、设备映射或设备环境变量后
重启容器。每项 GPU 探测默认最多 10 秒，可通过
`FFPANEL_HARDWARE_PROBE_TIMEOUT_SECONDS` 调整（1–60 秒）；超时会终止并回收子进程。
无 GPU 的部署不会因镜像包含 GPU 编码器而显示 Ready。

## 验证

仓库 `scripts` 以只读方式挂入运行容器，使用应用同一套参数规划和命令生成执行验证：

```bash
# NVIDIA：H.264、HEVC；缺失任何所需能力都返回非零
docker compose -f docker-compose.nvidia.yml run --rm --no-deps \
  -v "$PWD/scripts:/verification:ro" --entrypoint sh ffpanel /verification/verify-nvidia.sh

# Intel：同时严格验证 QSV、VAAPI 的硬解及软解+硬编
docker compose -f docker-compose.intel.yml run --rm --no-deps \
  -v "$PWD/scripts:/verification:ro" --entrypoint sh ffpanel /verification/verify-intel.sh

# RK3588 保留原脚本入口
docker compose run --rm --no-deps -v "$PWD/scripts:/verification:ro" \
  --entrypoint sh ffpanel /verification/verify-rk3588.sh

# 单独验证 VAAPI 或仅支持 H.264 的设备
docker compose -f docker-compose.intel.yml run --rm --no-deps \
  -v "$PWD/scripts:/verification:ro" --entrypoint python ffpanel \
  /verification/verify_hardware.py --backend vaapi --codec h264
```

脚本生成临时素材，对所选后端的硬解和软件解码方案分别执行原尺寸与缩放转码，
检查目标编码、尺寸、非空文件和实际可解码性，退出后清理临时目录。硬件验证没有
自动回退；CPU 转码成功不能冒充硬件成功。`--codec h264` 只证明该编码的验证结果。

CI 在原生 ARM64/AMD64 runner 上执行 `verify-image.sh <架构>`：检查工具、动态库、
编解码器与滤镜清单，以及实际 CPU 转码和应用健康。GPU 实机结果必须另行记录，
包括硬件型号、内核、驱动、镜像 digest、命令、输出及退出码。

本次实现环境为 Windows，未提供 Docker Engine 和 Linux GPU 设备；双架构镜像构建、
RK3588/Intel/NVIDIA 实机验证标记为**待验证**。自动化测试通过不能替代这些检查。

## 升级与排障

- 升级前备份 `config`。容器入口执行 Alembic 迁移，为能力快照增加 `hardware_json`。
  旧任务和旧快照继续可读；非容器升级先执行 `alembic upgrade head`，再启动服务。
- `hardwareMode` 的旧值和 API 默认值保持兼容；新版前端会按目标编码选择可用方案。
  新版创建的 GPU 任务不应直接交给不认识新方案的旧版本应用执行，回滚应使用备份。
- 驱动初始化失败：展开状态详情，检查 GPU 映射、驱动库和 Toolkit；编码器清单只说明
  FFmpeg 编译支持，不能证明设备可用。
- Intel 节点选错或权限不足：核对 render 节点的 sysfs 厂商信息和读写权限。
- 部分编码不可用：选择已验证编码或启用自动回退，查文件详情中的每次失败原因。
- 健康检查失败：查看 `docker compose -f <所选配置> logs ffpanel`；首次 GPU 探测需要
  时间。增加探测超时时也应相应增加 Compose 的健康检查启动宽限。
