#!/bin/bash
# Build the Galaxy A50 XNU loader (Samsung S-Boot "kernel" Image).
# Optionally pack a BOOT image: build.sh STOCK_BOOT.img PAYLOAD.bin OUT.img
# (PAYLOAD from tools/mkpayload.py; STOCK_BOOT supplies header and DTBH).
set -euo pipefail
cd "$(dirname "$0")"
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -fno-tree-loop-distribute-patterns -march=armv8-a -Wall -Wextra -Werror"
mkdir -p out
$CC $CFLAGS -c start.S -o out/start.o
$CC $CFLAGS -c loader.c -o out/loader.o
$CC $CFLAGS -c ../fdt.c -o out/fdt.o
$CC $CFLAGS -c ufs_probe.c -o out/ufs_probe.o
$CC $CFLAGS -c smp_probe.c -o out/smp_probe.o
$CC $CFLAGS -c display_probe.c -o out/display_probe.o
objs="out/loader.o out/fdt.o out/ufs_probe.o out/smp_probe.o out/display_probe.o"
# Runs wherever S-Boot puts it with no relocation pass.
abs=$(aarch64-linux-gnu-readelf -r $objs | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations" >&2; exit 1; }
$CC $CFLAGS -static -T loader.ld -Wl,--build-id=none -Wl,-N \
	out/start.o $objs -o out/loader.elf
$OBJCOPY -O binary out/loader.elf out/Image
end_hex=$(aarch64-linux-gnu-nm out/loader.elf | awk '$3=="_end"{print $1}')
[ -n "$end_hex" ] || { echo "error: _end symbol not found" >&2; exit 1; }
size=$((0x$end_hex))
truncate -s "$size" out/Image
echo "out/Image: $(stat -c %s out/Image) bytes"
if [ $# = 3 ]; then
	PY=python3
	python3 -c '' >/dev/null 2>&1 || PY=python
	$PY ../../tools/dreamlte_mkboot.py "$1" out/Image "$2" "$3"
	sha256sum "$3"
fi
