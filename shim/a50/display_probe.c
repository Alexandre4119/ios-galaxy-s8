/* SPDX-License-Identifier: GPL-2.0-only
 * Galaxy A50 display handoff probe, run by the loader (MMU off).
 *
 * Samsung's A50 DT (exynos9610.dts): DECON_F at 0x148B0000, DPP G0/IDMA at
 * 0x14891000/0x14881000, panel EA8076 1080x2340 in MIPI command mode. S-Boot
 * leaves DECON scanning the boot logo out of a buffer it allocated; the IDMA
 * Y address register (DPP IDMA + 0x40) is therefore the only place the
 * framebuffer address exists. No address is hard-coded here.
 *
 * The register offsets match the Exynos 8895 DPU the S8 port probed
 * (shim/dreamlte/display_probe.c), which is the same Exynos9 DECON/DPP IP.
 */
#include <stdint.h>
#include "display_probe.h"

#define DECON		0x148B0000UL
#define IDMA0		0x14881000UL
#define DPP0		0x14891000UL
#define FB_MAX		0x100000000UL	/* anything above is not DDR */
#define XNU_BASE	0x880000000UL
#define XNU_END		0x900000000UL
#define FB_W		1080u
#define FB_H		2340u
#define FB_STRIDE	(FB_W * 4u)

static inline uint32_t rd(uintptr_t a) { return *(volatile uint32_t *)a; }

uintptr_t display_probe(void (*kv)(const char *, uint64_t), void (*out)(const char *))
{
	uint32_t en = rd(IDMA0 + 0x00);
	uint32_t in = rd(IDMA0 + 0x08);
	uint32_t src = rd(IDMA0 + 0x10);
	uint32_t img = rd(IDMA0 + 0x18);
	uint64_t y = rd(IDMA0 + 0x40);

	out("DISPLAY: DECON_F 0x148b0000, DPP G0/IDMA 0x14891000/0x14881000\n");
	kv("decon ctl", rd(DECON + 0x00));
	kv("decon pend", rd(DECON + 0x4c));
	kv("dpp ctl", rd(DPP0 + 0x00));
	kv("idma en", en);
	kv("in_con", in);
	kv("src", src);
	kv("img", img);
	kv("fb", y);
	out("\n");

	/* S-Boot's buffer must be 4-byte aligned, inside DDR, and outside the
	 * bank XNU will own. 10.1 MB of console at an unmapped address would
	 * abort with the MMU off, so reject anything suspicious. */
	if (!y || (y & 3) || y >= FB_MAX || y + (uint64_t)FB_STRIDE * FB_H > FB_MAX ||
	    (y < XNU_END && y + (uint64_t)FB_STRIDE * FB_H > XNU_BASE)) {
		out("DISPLAY: no usable S-Boot scanout, screen console off\n");
		return 0;
	}
	return (uintptr_t)y;
}
