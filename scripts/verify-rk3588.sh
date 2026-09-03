#!/bin/sh
set -eu

echo "== FFPanel RK3588 verification =="
for binary in ffmpeg ffprobe rclone; do
  command -v "$binary" >/dev/null || { echo "missing: $binary"; exit 1; }
done

required="/dev/dri /dev/dma_heap /dev/rga /dev/mpp_service"
for device in $required; do
  if [ ! -e "$device" ]; then echo "missing device: $device"; exit 1; fi
done

ffmpeg -hide_banner -encoders 2>&1 | grep -q h264_rkmpp
ffmpeg -hide_banner -encoders 2>&1 | grep -q hevc_rkmpp
ffmpeg -hide_banner -decoders 2>&1 | grep -q h264_rkmpp
ffmpeg -hide_banner -filters 2>&1 | grep -q scale_rkrga

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=1280x720:rate=30 -t 2 -c:v libx264 "$workdir/source.mp4"
ffmpeg -hide_banner -loglevel error -hwaccel rkmpp -hwaccel_output_format drm_prime -afbc rga \
  -i "$workdir/source.mp4" -vf scale_rkrga=w=640:h=360:format=nv12 -c:v h264_rkmpp \
  -b:v 1M -maxrate 1M -bufsize 2M -an "$workdir/h264.mp4"
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -of default=nw=1 "$workdir/h264.mp4"
echo "RK3588 hardware verification passed"

