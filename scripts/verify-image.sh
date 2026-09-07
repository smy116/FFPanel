#!/bin/sh
# GPU-free build acceptance. Real GPU checks are deliberately separate.
set -eu
arch="${1:?expected arm64 or amd64}"
test "$(dpkg --print-architecture)" = "$arch"
for binary in ffmpeg ffprobe rclone; do command -v "$binary" >/dev/null; done
ffmpeg -version
ffprobe -version
rclone version
if ldd "$(command -v ffmpeg)" | grep -q 'not found'; then exit 1; fi
encoders="$(ffmpeg -hide_banner -encoders 2>&1)"
filters="$(ffmpeg -hide_banner -filters 2>&1)"
decoders="$(ffmpeg -hide_banner -decoders 2>&1)"
hwaccels="$(ffmpeg -hide_banner -hwaccels 2>&1)"
for encoder in libx264 libx265; do printf '%s\n' "$encoders" | grep -w "$encoder"; done
case "$arch" in
  arm64)
    for encoder in h264_rkmpp hevc_rkmpp; do printf '%s\n' "$encoders" | grep -w "$encoder"; done
    printf '%s\n' "$decoders" | grep -w h264_rkmpp
    printf '%s\n' "$filters" | grep -w scale_rkrga
    ;;
  amd64)
    for encoder in h264_nvenc hevc_nvenc h264_qsv hevc_qsv h264_vaapi hevc_vaapi; do
      printf '%s\n' "$encoders" | grep -w "$encoder"
    done
    for filter in scale_cuda scale_qsv scale_vaapi hwupload; do printf '%s\n' "$filters" | grep -w "$filter"; done
    for accel in cuda qsv vaapi; do printf '%s\n' "$hwaccels" | grep -w "$accel"; done
    for decoder in h264_cuvid hevc_cuvid h264_qsv hevc_qsv; do printf '%s\n' "$decoders" | grep -w "$decoder"; done
    if printf '%s\n' "$encoders" "$decoders" "$filters" | grep -E 'rkmpp|rkrga'; then exit 1; fi
    test -f /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so
    # oneVPL's modern runtime excludes legacy Jasper Lake/N5105. The oneVPL
    # dispatcher falls back to this Media SDK implementation on those devices.
    test -f /usr/lib/x86_64-linux-gnu/libmfxhw64.so.1
    if ldd /usr/lib/x86_64-linux-gnu/dri/iHD_drv_video.so | grep -q 'not found'; then exit 1; fi
    ;;
  *) exit 1 ;;
esac
python "$(dirname "$0")/verify_hardware.py" --backend cpu
