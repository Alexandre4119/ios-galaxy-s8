#!/usr/bin/env python3
"""Apply the Galaxy A50 (SM-A505F, Exynos 9610) hardware layer to an
A5XELTE + DREAMLTE patched xnu tree (xnu/patches/0001..0128).

The A5XELTE machine config and its guards are reused. A50 builds select the
new macros with MACHINE_CONFIG=A50 (-DA50_BUILD, still
-DARM64_BOARD_CONFIG_A5XELTE), so patch 0124's S8 defaults stay intact for
MACHINE_CONFIG=A5XELTE.

Every replacement asserts its expected match count. Usage:
    apply-a50.py XNU_TREE
Then tools/a50/make-patch.py turns the result into 0129-a50.patch.
"""
import sys
from pathlib import Path

tree = Path(sys.argv[1])
here = Path(__file__).resolve().parent


def edit(rel, pairs):
    path = tree / rel
    text = path.read_text()
    for old, new, count in pairs:
        found = text.count(old)
        if found != count:
            raise SystemExit(f'{rel}: expected {count}x {old!r}, found {found}')
        text = text.replace(old, new)
    path.write_text(text)
    print(f'edited {rel}')


# ---- board selection in the shared A5XELTE header ------------------------
edit('pexpert/pexpert/arm64/A5XELTE.h', [(
    '''/*
 * Samsung Galaxy S8 (SM-G950F, dreamlte, Exynos 8895) build of this port.
 * Same Samsung S-Boot handoff, GIC-400, 26 MHz timer and Cortex-A53 boot
 * cluster as the A5; the board facts that differ are below.
 */
#define DREAMLTE                      1
#if defined(DREAMLTE)
''',
    '''/*
 * Samsung Galaxy A50 (SM-A505F, a50, Exynos 9610) build of this port.
 * Same Samsung S-Boot handoff, GIC-400, 26 MHz physical timer and 4 KiB
 * pages as the A5/S8. MACHINE_CONFIG=A50 adds -DA50_BUILD (and still
 * -DARM64_BOARD_CONFIG_A5XELTE, so every A5XELTE guard applies).
 */
#if defined(A50_BUILD)
#define A50                           1
#define A5_FB_PHYS                    0           /* loader reads DECON IDMA0 */
#define A5_FB_WIDTH                   1080
#define A5_FB_HEIGHT                  2340
#define A5_FB_STRIDE                  4320        /* bytes per row */
#define A5_FB_2M_BLOCKS               5
#define A5_ENTRY_MARKER_PHYS          0           /* no pstore address known */
#define A5_BOOT_MPIDR                 0           /* A53 boot cluster */
#define A5_KEYS_DEFAULT               1           /* GPA1 keys, no Home key */
#define A5_TOUCH_DEFAULT              0           /* MMS100 starts separately */
#define A5_DECON_BASE                 0x148b0000
#define A5_UFS_NODE                   "/a50-ufs"
/* Samsung's A50 DT says "use-physical-timer": PPI 14 = INTID 30. */
#define A5_USE_PHYS_TIMER             1
#undef A5XELTE_VTIMER_INTID
#define A5XELTE_VTIMER_INTID         30
#else
#define DREAMLTE                      1
#endif
#if defined(DREAMLTE)
#define A5_DECON_BASE                 0x12860000
#define A5_UFS_NODE                   "/dreamlte-ufs"
''', 1),
    ('#else\n#define A5_FB_PHYS                    0x67000000\n',
     '#elif !defined(A50)\n#define A5_FB_PHYS                    0x67000000\n', 1),
])

# ---- machine config: A50 shares the A5XELTE source, different flags ------
edit('makedefs/MakeInc.def', [(
    'SUPPORTED_ARM64_MACHINE_CONFIGS = BCM2837 T6000 T8101 T8103 VMAPPLE SWEET A5XELTE\n',
    'SUPPORTED_ARM64_MACHINE_CONFIGS = BCM2837 T6000 T8101 T8103 VMAPPLE SWEET A5XELTE A50\n', 1),
    ('MACHINE_FLAGS_ARM64_A5XELTE = -DARM64_BOARD_CONFIG_A5XELTE            -mcpu=cortex-a53 -march=armv8-a+crypto\n',
     'MACHINE_FLAGS_ARM64_A5XELTE = -DARM64_BOARD_CONFIG_A5XELTE            -mcpu=cortex-a53 -march=armv8-a+crypto\n'
     'MACHINE_FLAGS_ARM64_A50 = -DARM64_BOARD_CONFIG_A5XELTE -DA50_BUILD=1  -mcpu=cortex-a53 -march=armv8-a+crypto\n', 1),
    # A50 must stay plain arm64 (no arm64e/PAC) like the other Exynos boards.
    ('ifeq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE),)\n',
     'ifeq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE A50),)\n', 1),
    # 4 KiB pages: TTBR1 has a 39-bit range, so use the compact kernel VA
    # layout instead of the macOS -2 TiB ARM_LARGE_MEMORY layout.
    ('ifeq ($(CURRENT_MACHINE_CONFIG),A5XELTE)\nLARGE_MEMORY_DEFINE=-UARM_LARGE_MEMORY\n',
     'ifneq ($(filter $(CURRENT_MACHINE_CONFIG),A5XELTE A50),)\nLARGE_MEMORY_DEFINE=-UARM_LARGE_MEMORY\n', 1),
])

# These two components are selected by machine-config name, not by the
# A5XELTE preprocessor macro: without A50 they are silently left out.
edit('bsd/conf/Makefile.template', [(
    'ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE),)\n',
    'ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE A50),)\n', 1),
])
edit('libkern/conf/Makefile.template', [(
    'ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE),)\n',
    'ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE A50),)\n', 1),
])

# doconf picks config/MASTER.arm64.$(SOC_CONFIG); SOC_CONFIG is the lowercased
# MACHINE_CONFIG. Without this file A50 silently falls back to generic MASTER.
cfg = tree / 'config/MASTER.arm64.a50'
if cfg.exists():
    raise SystemExit('config/MASTER.arm64.a50 already exists')
src_cfg = (tree / 'config/MASTER.arm64.a5xelte').read_text()
cfg.write_text(src_cfg.replace(
    '# a5xelte (SM-A510F, Exynos7580): donor configuration plus the open-source\n'
    '# arm64 assembly and pmap',
    '# a50 (SM-A505F, Exynos9610): same kernel options as the a5xelte board:\n'
    '# open-source arm64 assembly and pmap'))
print('added config/MASTER.arm64.a50')

# ---- early assembly: the A50 framebuffer address is only known at boot ---
# A5_FB_PHYS is 0 for A50, so the two S8-only early draws (pstore marker and
# the DECON entry block) must not run. The kernel's C console maps the real
# address from the ADT after start_first_cpu.
edit('osfmk/arm64/start.s', [(
    '#if defined(A5XELTE)\n\t/* Earliest XNU-owned physical marker in preserved Samsung log RAM. */\n',
    '#if defined(A5XELTE) && !defined(A50_BUILD)\n\t/* Earliest XNU-owned physical marker in preserved Samsung log RAM. */\n', 1),
    ('#if defined(A5XELTE)\n\t/* A5_FB_2M_BLOCKS 2 MiB blocks map the scanout buffer VA=PA.\n',
     '#if defined(A5XELTE) && !defined(A50_BUILD)\n\t/* A5_FB_2M_BLOCKS 2 MiB blocks map the scanout buffer VA=PA.\n', 1),
])

# ---- framebuffer: boot_args.Video (filled by the A50 loader) -------------
edit('iokit/Kernel/arm/SweetFramebuffer.cpp', [(
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\t/* The loader\'s DECON handoff scans out this physical XRGB8888 buffer.\n',
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE) && !defined(A50_BUILD)\n\t/* The loader\'s DECON handoff scans out this physical XRGB8888 buffer.\n', 1),
    ('sweet_fb_decon = ml_io_map(0x12860000, 0x1000);',
     'sweet_fb_decon = ml_io_map(A5_DECON_BASE, 0x1000);', 1),
])

# ---- early C console: map the A50 ADT node the loader patched -----------
edit('pexpert/arm/pe_serial.c', [(
    '\t#if defined(A5XELTE)\n\tif (SecureDTFindEntry("name", "a5xelte-fbcon", &entry) != kSuccess ||\n',
    '\t#if defined(A50_BUILD)\n\tif (SecureDTFindEntry("name", "a50-fbcon", &entry) != kSuccess ||\n'
    '\t#elif defined(A5XELTE)\n\tif (SecureDTFindEntry("name", "a5xelte-fbcon", &entry) != kSuccess ||\n', 1),
])

# ---- keys: GPA1 (ALIVE + 0x040), pins 7/5/6, no Home key ----------------
edit('bsd/dev/a5xelte_keys.c', [(
    '#if defined(DREAMLTE)\n#define A5_ALIVE_PA 0x164b0000u            /* Exynos 8895 pinctrl ALIVE */\n#else\n',
    '#if defined(DREAMLTE)\n#define A5_ALIVE_PA 0x164b0000u            /* Exynos 8895 pinctrl ALIVE */\n'
    '#elif defined(A50_BUILD)\n#define A5_ALIVE_PA 0x11850000u            /* Exynos 9610 pinctrl ALIVE */\n#else\n', 1),
    ('#if defined(DREAMLTE)\n/*\n * Galaxy S8 (mainline exynos8895-dreamlte.dts gpio-keys, all active low):\n',
     '#if defined(A50_BUILD)\n'
     '/*\n'
     ' * Galaxy A50 (Samsung a50 DT gpio-keys, all active low): Power GPA1-7,\n'
     ' * Volume Up GPA1-5, Volume Down GPA1-6. GPA1 bank at ALIVE + 0x040,\n'
     ' * DAT at +4. The A50 has no Bixby/Home key, so key 3 is absent.\n'
     ' */\n'
     'typedef uint8_t keys_t;\n'
     '#define KEYS_SAMPLE() ((keys_t)a5_keys_read(0x44))\n'
     '#define KEYS_PINS { 7, 5, 6, 0xff }\n'
     '#elif defined(DREAMLTE)\n'
     '/*\n'
     ' * Galaxy S8 (mainline exynos8895-dreamlte.dts gpio-keys, all active low):\n', 1),
    ('\t\t\tfor (unsigned key = 0; key < 4; key++) {\n\t\t\t\tkeys_t bit = (keys_t)(1u << pins[key]);\n',
     '\t\t\tfor (unsigned key = 0; key < 4; key++) {\n'
     '\t\t\t\tif (pins[key] == 0xff) {\n'
     '\t\t\t\t\tcontinue;       /* the A50 has no fourth key */\n'
     '\t\t\t\t}\n'
     '\t\t\t\tkeys_t bit = (keys_t)(1u << pins[key]);\n', 1),
])

# ---- touch: append the A50 MMS100 driver and start it -------------------
touch = (here / 'a50_touch.c').read_text()
edit('bsd/dev/a5xelte_touch.c', [(
    '\nvoid\na5xelte_touch_probe(void)\n{',
    '\n' + touch + '\nvoid\na5xelte_touch_probe(void)\n{', 1),
    ('#if defined(DREAMLTE)\n\tdreamlte_touch_start();   /* the A5 path below stays off */\n#endif\n',
     '#if defined(DREAMLTE)\n\tdreamlte_touch_start();   /* the A5 path below stays off */\n'
     '#elif defined(A50_BUILD)\n\ta50_touch_start();        /* MMS100 on bit-banged I2C4 */\n#endif\n', 1),
])

# ---- clock: the A50 RTC is a separate block, passed as a50rtc -----------
edit('iokit/Kernel/IOPlatformExpert.cpp', [(
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tuint64_t s8rtc = 0;\n'
    '\tif (*secs == 0 && PE_parse_boot_argn("s8rtc", &s8rtc, sizeof(s8rtc)) && s8rtc) {\n'
    '\t\tuint64_t ns;\n'
    '\t\tabsolutetime_to_nanoseconds(mach_absolute_time(), &ns);\n'
    '\t\t*secs = (clock_sec_t)(s8rtc + ns / NSEC_PER_SEC);\n',
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tuint64_t rtcboot = 0;\n'
    '\tbool have_rtc = PE_parse_boot_argn("a50rtc", &rtcboot, sizeof(rtcboot)) ||\n'
    '\t    PE_parse_boot_argn("s8rtc", &rtcboot, sizeof(rtcboot));\n'
    '\tif (*secs == 0 && have_rtc && rtcboot) {\n'
    '\t\tuint64_t ns;\n'
    '\t\tabsolutetime_to_nanoseconds(mach_absolute_time(), &ns);\n'
    '\t\t*secs = (clock_sec_t)(rtcboot + ns / NSEC_PER_SEC);\n', 1),
])

# ---- battery: no A50 fuel gauge yet, keep a truthful static source ------
edit('iokit/Kernel/arm/SweetBattery.cpp', [(
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n/* Galaxy S8: MAX77865 fuel gauge (bsd/dev/a5xelte_touch.c). */\n',
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE) && !defined(A50_BUILD)\n/* Galaxy S8: MAX77865 fuel gauge (bsd/dev/a5xelte_touch.c). */\n', 1),
    ('#define SWEET_BAT_MAH 3000u\n#else\n',
     '#define SWEET_BAT_MAH 3000u\n'
     '#elif defined(A50_BUILD)\n'
     '/* Galaxy A50: S2MPU09 gauge not wired up yet; static fallback. */\n'
     'static inline int sweet_spmi_init(void) { return -1; }\n'
     'static inline int sweet_spmi_read(unsigned, unsigned, uint8_t *) { return -1; }\n'
     '#define SWEET_BAT_MAH 4000u\n'
     '#else\n', 1),
    ('#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tunsigned pct = 0, s8mv = 0;\n',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE) && !defined(A50_BUILD)\n\tunsigned pct = 0, s8mv = 0;\n', 1),
    ('\t\tpublish(100, 4200, 0, true, true, false, true, false, false);\n\t}\n#else\n',
     '\t\tpublish(100, 4200, 0, true, true, false, true, false, false);\n\t}\n'
     '#elif defined(A50_BUILD)\n'
     '\tpublish(100, 4200, 0, true, true, false, true, false, false);\n'
     '#else\n', 1),
    ('#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tint real = 1;\n#else\n\tint real = 0;\n#endif\n',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE) && !defined(A50_BUILD)\n\tint real = 1;\n#else\n\tint real = 0;\n#endif\n', 1),
    ('#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n\tfReal = real == 1;\n#else\n\tfReal = real == 1 && sweet_spmi_init() == 0;\n#endif\n',
     '#if defined(ARM64_BOARD_CONFIG_A5XELTE) && !defined(A50_BUILD)\n\tfReal = real == 1;\n'
     '#elif defined(A50_BUILD)\n\tfReal = false;\n'
     '#else\n\tfReal = real == 1 && sweet_spmi_init() == 0;\n#endif\n', 1),
])

# ---- UFS: select the ADT node per board ---------------------------------
edit('bsd/dev/sweet_ufs.c', [(
    '#include <pexpert/pexpert.h>\n#include <pexpert/device_tree.h>\n',
    '#include <pexpert/pexpert.h>\n'
    '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
    '#include <pexpert/arm64/board_config.h>\n'
    '#endif\n'
    '#include <pexpert/device_tree.h>\n', 1),
    ('#define UFS_ADT_NODE            "/dreamlte-ufs"\n',
     '#define UFS_ADT_NODE            A5_UFS_NODE\n', 1),
])

# ---- IOKit personalities: match the A50 DT names ------------------------
edit('iokit/KernelConfigTables.cpp', [(
    '''    "     'IONameMatch'     = ('samsung,a5xelte', 'samsung,dreamlte');"\n''',
    '''    "     'IONameMatch'     = ('samsung,a5xelte', 'samsung,dreamlte', 'samsung,a50');"\n''', 1),
    ('''    "     'IONameMatch'     = ('samsung,a5xelte-display', 'samsung,dreamlte-display');"\n''',
     '''    "     'IONameMatch'     = ('samsung,a5xelte-display', 'samsung,dreamlte-display', 'samsung,a50-display');"\n''', 1),
])

print('A50 layer applied')
