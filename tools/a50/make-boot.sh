#!/bin/bash
# Kernel Mach-O -> Galaxy A50 BOOT image.
#   make-boot.sh KERNEL STOCK_BOOT.img OUT.img [boot-args...]
# Default boot-args: one CPU, verbose console, no watchdog; no root device
# yet, so the first trials end in a root-mount panic by design.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
kernel=$(realpath "$1"); stock=$(realpath "$2"); out=$(realpath -m "$3")
shift 3
args=${*:-debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress wdt=-1 wdt_test=no_user_checkin}
work=$repo/shim/a50/out
mkdir -p "$work"
PY=python3
python3 -c '' >/dev/null 2>&1 || PY=python
# The ADT canvas must match the size SweetFramebuffer presents. The A50 panel
# is 1080x2340, which is also the iPhone 12 mini's pixel size; the loader
# fills in the real DECON scanout address, so no framebuffer constant is
# needed here. --canvas only changes the advertised size.
canvas=1080x2340
[[ " $args " == *" sweetfb_native=1 "* ]] && canvas=1080x2340
$PY "$repo/tools/mkadt_a50.py" "$work/a50.adt" --canvas "$canvas"
$PY "$repo/tools/mkpayload.py" "$kernel" "$work/a50.adt" "$work/payload.bin" --cmdline "$args"
bash "$repo/shim/a50/build.sh" "$stock" "$work/payload.bin" "$out"
$PY "$repo/tools/dreamlte_bootimg_info.py" "$out" | head -4
