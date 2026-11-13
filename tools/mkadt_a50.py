#!/usr/bin/env python3
"""Build the Galaxy A50 (SM-A505F, a50, Exynos 9610) ADT.

Board facts from Samsung's own A50 device tree (android_kernel_samsung_
exynos9610, arch/arm64/boot/dts/{exynos/universal9610,samsung/a50}) and the
mainline exynos9610 pinctrl data:

  - XNU RAM: the 2 GiB bank at 0x880000000 (the same A5XELTE-proven 512 MiB
    window is used by the kernel; the low banks hold firmware carve-outs)
  - GIC-400: GICD 0x12301000, GICC 0x12302000; physical timer PPI 14 =
    INTID 30 (the A50 DT says "use-physical-timer", like the S8)
  - timer 26 MHz (CNTFRQ_EL0 is 0 after S-Boot)
  - CPUs: logical 0-3 = Cortex-A53 MPIDR 0x0-0x3 (the boot cluster),
    logical 4-7 = Cortex-A73 MPIDR 0x100-0x103
  - display: DECON_F 0x148B0000, DPP/IDMA G0 at 0x14881000/0x14891000,
    panel 1080x2340 (EA8076, MIPI command mode)
  - UFS: UFSHCI 0x13520000, Exynos vendor HCI 0x13521100 (same layout as
    the S8's 0x11120000 pair)
  - RTC: separate "samsung,exynos8-rtc" block at 0x11A20000 (not in the
    PMIC as on the S8)

The framebuffer address is not in the device tree: S-Boot allocates it and
only DECON knows it. The loader reads the IDMA0 base and patches the
"a50-fbcon" reg property before jumping here, so the placeholder below is
never used with a running display.

The identity stays the donor's iPhone X (D22AP), as on the S8: the A50 has
no Home key either.
"""
import argparse
import os
from pathlib import Path

import adt
import mkadt

DRAM_BASE = 0x880000000
DRAM_SIZE = 0x20000000
FB_PHYS_PLACEHOLDER = 0x0
FB_W, FB_H = 1080, 2340
FB_STRIDE = FB_W * 4
TIMEBASE = 26000000


def set_prop(node, name, value):
    for i, (key, flags, _) in enumerate(node.props):
        if key == name:
            node.props[i] = (key, flags, value)
            return
    node.props.append((name, 0, value))


def child(node, name):
    for candidate in node.children:
        if candidate.prop('name') == mkadt.cstr(name):
            return candidate
    raise ValueError(f'missing donor ADT node {name}')


def cpu_node(logical):
    a53 = logical < 4
    mpidr = logical if a53 else 0x100 + logical - 4
    cluster = 0 if a53 else 1
    return [
        ('device_type', mkadt.cstr('cpu')),
        ('compatible', mkadt.cstr('arm,cortex-a53' if a53 else 'arm,cortex-a73') +
         mkadt.cstr('ARM,v8')),
        ('reg', mkadt.u32(mpidr)),
        ('cpu-id', mkadt.u32(logical)),
        ('cluster-id', mkadt.u32(cluster)),
        ('cluster-type', mkadt.u32(0)),
        ('die-cluster-id', mkadt.u32(cluster)),
        ('cluster-core-id', mkadt.u32(logical % 4)),
        ('l2-cache-id', mkadt.u32(cluster)),
        ('l3-cache-id', mkadt.u32(0)),
        ('state', mkadt.cstr('running' if logical == 0 else 'stopped')),
        ('timebase-frequency', mkadt.u32(TIMEBASE)),
        ('clock-frequency', mkadt.u32(2300000000 if not a53 else 1700000000)),
        ('bus-frequency', mkadt.u32(100000000)),
        ('memory-frequency', mkadt.u32(1794000000)),
        ('peripheral-frequency', mkadt.u32(TIMEBASE)),
        ('fixed-frequency', mkadt.u32(TIMEBASE)),
    ]


def build(canvas=(FB_W, FB_H)):
    root = mkadt.build(seed=os.urandom(64), qemu=True)
    # SweetPlatformExpert's personality list is extended for A50 in patch
    # 0129; 'samsung,a5xelte' stays so an unpatched kernel still finds one.
    set_prop(root, 'compatible', mkadt.cstr('samsung,a50') +
             mkadt.cstr('samsung,a5xelte') + mkadt.cstr('samsung,exynos9610') +
             mkadt.cstr('AppleARM'))
    chosen = child(root, 'chosen')
    set_prop(chosen, 'dram-base', mkadt.u64(DRAM_BASE))
    set_prop(chosen, 'dram-size', mkadt.u64(DRAM_SIZE))
    set_prop(chosen, 'firmware-version', mkadt.cstr('a50-entry'))
    set_prop(chosen, 'system-firmware-version', mkadt.cstr('a50-entry'))
    cpus = child(root, 'cpus')
    cpu0 = child(cpus, 'cpu0')
    for key, value in cpu_node(0):
        if key != 'cpu-id':
            set_prop(cpu0, key, value)
    for logical in range(1, 8):
        cpus.children.append(mkadt.node(f'cpu{logical}', cpu_node(logical)))
    arm_io = child(root, 'arm-io')
    set_prop(arm_io, 'device_type', mkadt.cstr('a50-io'))
    set_prop(arm_io, 'compatible', mkadt.cstr('samsung,exynos9610-io') +
             mkadt.cstr('arm-io'))
    set_prop(arm_io, 'ranges', mkadt.u64(0, 0x10000000, 0xf0000000))
    arm_io.children = [n for n in arm_io.children if n.prop('name') == mkadt.cstr('wdt')]
    arm_io.children.append(mkadt.node('gic', [
        ('compatible', mkadt.cstr('arm,cortex-a15-gic')),
        ('interrupt-controller', mkadt.cstr('master')),
        ('virtual-timer-intid', mkadt.u32(30)),
        ('reg', mkadt.u64(0x02301000, 0x1000, 0x02302000, 0x1000)),
    ]))
    arm_io.children.append(mkadt.node('disp0', [
        ('device_type', mkadt.cstr('display-subsystem')),
        ('compatible', mkadt.cstr('samsung,a50-display') +
         mkadt.cstr('samsung,a5xelte-display')),
        ('canvas-width', mkadt.u32(canvas[0])),
        ('canvas-height', mkadt.u32(canvas[1])),
    ]))
    root.children = [n for n in root.children if n.prop('name') not in
                     (mkadt.cstr('sweet-fbcon'), mkadt.cstr('sweet-ufs'))]
    # pe_serial.c maps this node's reg at early serial_init. The loader fills
    # in the real DECON scanout address (and size) before starting XNU.
    root.children.append(mkadt.node('a50-fbcon', [
        ('reg', mkadt.u64(FB_PHYS_PLACEHOLDER, FB_W * FB_H * 4)),
        ('width', mkadt.u32(FB_W)),
        ('height', mkadt.u32(FB_H)),
        ('stride', mkadt.u32(FB_STRIDE)),
    ]))
    # bsd/dev/sweet_ufs.c (A5XELTE config, EXYNOS_UFS): UFSHCI standard
    # registers, then the Exynos vendor HCI block.
    root.children.append(mkadt.node('a50-ufs', [
        ('reg', mkadt.u64(0x13520000, 0x200, 0x13521100, 0x200)),
    ]))
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--canvas', default=f'{FB_W}x{FB_H}',
                        help='display size presented to iOS, WxH')
    parser.add_argument('--dump', action='store_true')
    args = parser.parse_args()
    blob = adt.serialize(build(tuple(int(v) for v in args.canvas.split('x'))))
    args.output.write_bytes(blob)
    if args.dump:
        adt.dump(adt.parse(blob)[0])
    print(f'{args.output}: {len(blob)} bytes')
