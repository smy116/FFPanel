# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS web-build
WORKDIR /src/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM debian:bookworm AS media-build
ARG FFMPEG_ROCKCHIP_REF=d90e3a1c18d7929383cf88c1b3da2e2d1c966cbf
ARG MPP_REF=a9380ef333102ac318628f83b5f7a460d377749e
ARG RGA_REF=1d330cc28551943bed3380261a5a9c6fbd58ff53
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake build-essential ca-certificates cmake git libdrm-dev libx264-dev libx265-dev \
    meson nasm ninja-build pkg-config yasm && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git clone https://gitee.com/nyanmisaka/mpp.git && cd mpp && git checkout "$MPP_REF" && \
    cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DBUILD_TEST=OFF && \
    cmake --build build -j"$(nproc)" && DESTDIR=/opt/media cmake --install build
RUN git clone https://gitee.com/nyanmisaka/rga.git rkrga && cd rkrga && git checkout "$RGA_REF" && cd .. && \
    meson setup rkrga rkrga_build --prefix=/usr --libdir=lib --buildtype=release --default-library=shared \
      -Dcpp_args=-fpermissive -Dlibdrm=false -Dlibrga_demo=false && \
    DESTDIR=/opt/media ninja -C rkrga_build install
ENV PKG_CONFIG_PATH=/opt/media/usr/lib/pkgconfig:/opt/media/usr/lib/aarch64-linux-gnu/pkgconfig
RUN git clone https://github.com/nyanmisaka/ffmpeg-rockchip.git ffmpeg && cd ffmpeg && git checkout "$FFMPEG_ROCKCHIP_REF" && \
    ./configure --prefix=/usr --enable-gpl --enable-version3 --enable-libdrm --enable-rkmpp --enable-rkrga \
      --enable-libx264 --enable-libx265 --extra-cflags=-I/opt/media/usr/include \
      --extra-ldflags=-L/opt/media/usr/lib && \
    make -j"$(nproc)" && make DESTDIR=/opt/media install

FROM python:3.12-slim-bookworm AS python-build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY ffpanel ./ffpanel
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime
ARG RCLONE_VERSION=1.75.0
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libdrm2 libx264-164 libx265-199 unzip && \
    curl -fsSLO "https://downloads.rclone.org/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-arm64.zip" && \
    unzip "rclone-v${RCLONE_VERSION}-linux-arm64.zip" && \
    install -m 0755 "rclone-v${RCLONE_VERSION}-linux-arm64/rclone" /usr/local/bin/rclone && \
    rm -rf "rclone-v${RCLONE_VERSION}-linux-arm64"* /var/lib/apt/lists/*
COPY --from=media-build /opt/media/usr/ /usr/
COPY --from=python-build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
WORKDIR /opt/ffpanel
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/ffpanel-entrypoint
COPY --from=web-build /src/web/dist /usr/local/lib/python3.12/site-packages/ffpanel/static
RUN chmod +x /usr/local/bin/ffpanel-entrypoint && ldconfig
ENV FFPANEL_CONFIG_DIR=/config FFPANEL_CACHE_DIR=/cache FFPANEL_LOCAL_ROOTS=/media \
    FFPANEL_RCLONE_CONFIG=/config/rclone/rclone.conf PYTHONUNBUFFERED=1
VOLUME ["/config", "/cache", "/media"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["ffpanel-entrypoint"]
