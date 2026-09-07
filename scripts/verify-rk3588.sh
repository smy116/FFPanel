#!/bin/sh
set -eu
exec python "$(dirname "$0")/verify_hardware.py" --backend rockchip "$@"
