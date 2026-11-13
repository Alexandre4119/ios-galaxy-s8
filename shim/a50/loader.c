/* SPDX-License-Identifier: GPL-2.0-only
 * Galaxy A50 (SM-A505F, Exynos 9610) XNU loader.
 *
 * S-Boot hands us the BOOT ramdisk as /chosen/linux,initrd-{start,end}; it
 * holds a tools/mkpayload.py "SWEETXNU" v1 container (Mach-O segments, ADT,
 * boot-args). We copy it into the kernel-managed RAM window the ADT names
 * (the 2 GiB bank at 0x880000000), build boot_args and jump to XNU's
 * physical entry with the MMU off, as the S8 loader does.
 *
 * A50 differences from shim/dreamlte:
 *   - the display base is not a board constant: DECON knows it, so
 *     display_probe() reads IDMA0's Y address and that becomes the screen
 *     console, boot_args.Video and the ADT "a50-fbcon" reg;
 *   - the RTC is the separate exynos8-rtc block at 0x11A20000 (BCD
 *     registers, not S2MPS17 over SPEEDY);
 *   - UFS is at 0x13520000/0x13521100;
 *   - there is no known pstore/ramoops address on this board yet, so the
 *     loader and kernel log to the panel only.
 */
#include <stdint.h>
#include <stddef.h>
#include "../fdt.h"
#include "../font.h"
#include "ufs_probe.h"
#include "smp_probe.h"
#include "display_probe.h"

#define UFS_PROBE_DMA		0x8f000000UL	/* low bank, outside XNU's window */
#define FB_W			1080u
#define FB_H			2340u
#define FB_STRIDE		(FB_W * 4u)
#define RTC_PA			0x11A20000UL
#define LOW_RAM_BASE		0x80000000UL
#define LOW_RAM_END		0xbc800000UL
#define XNU_RAM_BASE		0x880000000UL
#define XNU_RAM_END		0x900000000UL
#define PAGE_SIZE		4096UL
#define BOOT_LINE_LENGTH	608

/* ---- screen console ---- */
static volatile uint32_t *fb;
static uintptr_t fb_base;
#define SCALE	2
#define CELL_W	(8 * SCALE)
#define CELL_H	(16 * SCALE + 4)
#define COLS	((FB_W - 16) / CELL_W)
#define ROWS	((FB_H - 100) / CELL_H)
static int row, col;
static uint32_t fg = 0xffffffffU;

static void fill(int x0, int y0, int w, int h, uint32_t c)
{
	if (fb == 0)
		return;
	for (int y = y0; y < y0 + h && y < (int)FB_H; y++)
		for (int x = x0; x < x0 + w && x < (int)FB_W; x++)
			fb[y * (FB_STRIDE / 4) + x] = c;
}

static void scr_ch(char c)
{
	if (fb == 0)
		return;
	if (c == '\n' || col >= (int)COLS) {
		col = 0;
		row = (row + 1) % ROWS;
		fill(0, 60 + row * CELL_H, FB_W, CELL_H, 0xff000000U);
		if (c == '\n')
			return;
	}
	if (c < 0x20 || c > 0x7e)
		c = '?';
	const unsigned char *g = font8x16[c - 0x20];
	int x0 = 8 + col * CELL_W, y0 = 60 + row * CELL_H;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++)
			fill(x0 + gx * SCALE, y0 + gy * SCALE, SCALE, SCALE,
			     (g[gy] & (0x80 >> gx)) ? fg : 0xff000000U);
	col++;
}

static void out(const char *s)
{
	while (*s)
		scr_ch(*s++);
}

static void hex(uint64_t v)
{
	static const char digits[] = "0123456789abcdef";
	char b[19] = "0x";
	int n = 2, started = 0;
	for (int i = 60; i >= 0; i -= 4) {
		int d = (v >> i) & 0xf;
		if (d || started || i == 0) {
			b[n++] = digits[d];
			started = 1;
		}
	}
	b[n] = 0;
	out(b);
}

static void kv(const char *k, uint64_t v)
{
	out(k);
	out("=");
	hex(v);
	out(" ");
}

/* ---- payload (tools/mkpayload.py v1) ---- */
struct payload_seg {
	uint64_t vmaddr, vmsize, file_off, file_size;
};
struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};
struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};
struct boot_args {
	uint16_t Revision, Version;
	uint64_t virtBase, physBase, memSize, topOfKernelData;
	struct boot_video Video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char CommandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags, memSizeActual;
};
_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload layout");
_Static_assert(__builtin_offsetof(struct boot_args, CommandLine) == 108, "boot_args layout");
_Static_assert(__builtin_offsetof(struct boot_args, Video) == 40, "boot_args video");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args size");

uint64_t dl_boot_args;	/* read by start.S */

/* MMU off: everything is Device memory, keep accesses naturally aligned. */
static void copy(uintptr_t dst, uintptr_t src, uint64_t n)
{
	if (!((dst | src) & 7)) {
		for (; n >= 8; n -= 8, dst += 8, src += 8)
			*(volatile uint64_t *)dst = *(volatile uint64_t *)src;
	}
	for (; n; n--, dst++, src++)
		*(volatile uint8_t *)dst = *(volatile uint8_t *)src;
}

static void zero(uintptr_t dst, uint64_t n)
{
	for (; n && (dst & 7); n--, dst++)
		*(volatile uint8_t *)dst = 0;
	for (; n >= 8; n -= 8, dst += 8)
		*(volatile uint64_t *)dst = 0;
	for (; n; n--, dst++)
		*(volatile uint8_t *)dst = 0;
}

static void clean(uintptr_t start, uintptr_t end)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
	uintptr_t line = 4UL << ((ctr >> 16) & 0xf);
	for (uintptr_t p = start & ~(line - 1); p < end; p += line)
		__asm__ volatile("dc civac, %0" : : "r"(p) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");
}

static int magic_ok(const volatile char *m)
{
	const char *want = "SWEETXNU";
	for (int i = 0; i < 8; i++)
		if (m[i] != want[i])
			return 0;
	return 1;
}

static uint64_t fail(const char *why)
{
	fg = 0xffff4040U;
	out("FAIL: ");
	out(why);
	out("\nPower + Volume Down, then Power + Volume Up -> TWRP\n");
	for (;;)
		__asm__ volatile("wfe");
	return 0;
}

/* ---- Apple Device Tree: patch the a50-fbcon reg property ---- */
static uint32_t ld32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
	       (uint32_t)p[3] << 24;
}

static void st64(uint8_t *p, uint64_t v)
{
	for (int i = 0; i < 8; i++)
		p[i] = (uint8_t)(v >> (8 * i));
}

static int str_eq(const char *a, const char *b)
{
	while (*a && *a == *b) {
		a++;
		b++;
	}
	return *a == *b;
}

static uint8_t *adt_skip(uint8_t *p, uint8_t *end, int depth)
{
	if (depth > 32 || p + 8 > end)
		return NULL;
	uint32_t nprops = ld32(p), nchildren = ld32(p + 4);
	uint8_t *q = p + 8;
	for (uint32_t i = 0; i < nprops; i++) {
		if (q + 36 > end)
			return NULL;
		uint32_t sz = ld32(q + 32) & 0x7fffffffU;
		q += 36 + ((sz + 3) & ~3U);
		if (q > end)
			return NULL;
	}
	for (uint32_t i = 0; i < nchildren; i++) {
		q = adt_skip(q, end, depth + 1);
		if (q == NULL)
			return NULL;
	}
	return q;
}

static int adt_patch(uint8_t *p, uint8_t *end, const char *want,
		     uint64_t base, uint64_t size, int depth)
{
	if (depth > 32 || p + 8 > end)
		return 0;
	uint32_t nprops = ld32(p), nchildren = ld32(p + 4);
	uint8_t *q = p + 8, *reg = NULL;
	uint32_t regsz = 0;
	const char *name = NULL;
	for (uint32_t i = 0; i < nprops; i++) {
		if (q + 36 > end)
			return 0;
		uint32_t sz = ld32(q + 32) & 0x7fffffffU;
		uint8_t *val = q + 36;
		if (val + sz > end)
			return 0;
		if (i == 0)
			name = (const char *)q;
		if (str_eq((const char *)q, "reg")) {
			reg = val;
			regsz = sz;
		}
		q = val + ((sz + 3) & ~3U);
	}
	if (name && str_eq(name, want) && reg && regsz >= 16) {
		st64(reg, base);
		st64(reg + 8, size);
		return 1;
	}
	for (uint32_t i = 0; i < nchildren; i++) {
		uint8_t *child_end = adt_skip(q, end, depth + 1);
		if (child_end == NULL)
			return 0;
		if (adt_patch(q, child_end, want, base, size, depth + 1))
			return 1;
		q = child_end;
	}
	return 0;
}

/* ---- RTC: Samsung exynos8-rtc, BCD counters ---- */
static unsigned bcd(unsigned v)
{
	return (v >> 4) * 10 + (v & 0xf);
}

/* Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant). */
static int64_t days_from_civil(int64_t y, unsigned m, unsigned d)
{
	y -= m <= 2;
	int64_t era = (y >= 0 ? y : y - 399) / 400;
	unsigned yoe = (unsigned)(y - era * 400);
	unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
	unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
	return era * 146097 + (int64_t)doe - 719468;
}

static int64_t rtc_unix(void)
{
	volatile uint32_t *rtc = (volatile uint32_t *)RTC_PA;
	uint32_t ctl = rtc[0x40 / 4];
	if (!(ctl & 1))
		rtc[0x40 / 4] = ctl | 1;	/* RTCEN */
	uint32_t sec = rtc[0x70 / 4], min = rtc[0x74 / 4];
	uint32_t hour = rtc[0x78 / 4], day = rtc[0x7c / 4];
	uint32_t mon = rtc[0x80 / 4], year = rtc[0x84 / 4];
	unsigned s = bcd(sec & 0x7f), m = bcd(min & 0x7f);
	unsigned h = bcd(hour & 0x3f), d = bcd(day & 0x3f);
	unsigned mo = bcd(mon & 0x1f), y = 2000 + bcd(year);
	if (s > 59 || m > 59 || h > 23 || !d || mo < 1 || mo > 12 || y < 2024)
		return 0;
	int64_t t = days_from_civil(y, mo, d) * 86400 + h * 3600 + m * 60 + s;
	uint64_t cnt;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(cnt));
	t -= (int64_t)(cnt / 26000000);
	return t;
}

static void append_arg(volatile struct boot_args *ba, const char *key, uint64_t v)
{
	char num[24];
	int n = 0, at = 0;
	while (at < BOOT_LINE_LENGTH && ba->CommandLine[at])
		at++;
	do {
		num[n++] = (char)('0' + v % 10);
		v /= 10;
	} while (v && n < 20);
	int need = 0;
	while (key[need])
		need++;
	if (at + need + 1 + n >= BOOT_LINE_LENGTH)
		return;
	for (int i = 0; key[i]; i++)
		ba->CommandLine[at++] = key[i];
	while (n)
		ba->CommandLine[at++] = num[--n];
	ba->CommandLine[at] = 0;
}

uint64_t dl_main(uintptr_t dtb, uint64_t el, uint64_t sctlr)
{
	fb_base = display_probe(kv, out);
	fb = (volatile uint32_t *)fb_base;
	if (fb) {
		fill(0, 0, FB_W, FB_H, 0xff000000U);
		fg = 0xffffff00U;
		out("A50LOADER BEGIN  (ios-a50 a50 XNU loader)\n");
		fg = 0xffffffffU;
		kv("fb", fb_base);
		kv("size", (uint64_t)FB_STRIDE * FB_H);
		out("\n");
	} else {
		fg = 0xffffffffU;
	}
	kv("EL", el);
	kv("SCTLR", sctlr);
	kv("DTB", dtb);
	out("\n");
	if (el != 1)
		return fail("not entered at EL1");

	uint64_t rd_start, rd_end;
	if (!fdt_chosen_u64(dtb, "linux,initrd-start", &rd_start) ||
	    !fdt_chosen_u64(dtb, "linux,initrd-end", &rd_end))
		return fail("no initrd in /chosen");
	kv("initrd", rd_start);
	kv("end", rd_end);
	out("\n");
	if (rd_start < LOW_RAM_BASE || rd_end > LOW_RAM_END || rd_end <= rd_start)
		return fail("initrd outside low RAM");

	const volatile struct payload *p = (const volatile struct payload *)rd_start;
	uint64_t length = rd_end - rd_start;
	if (length < sizeof(struct payload) || !magic_ok(p->magic) || p->version != 1)
		return fail("initrd is not a SWEETXNU v1 payload");
	uint64_t nsegs = p->nsegs;
	kv("segs", nsegs);
	kv("virt", p->virt_base);
	kv("entry", p->entry_va);
	out("\n");
	kv("phys", p->phys_base);
	kv("mem", p->mem_size);
	kv("adt", p->adt_size);
	out("\n");
	if (!nsegs || nsegs > 32 ||
	    __builtin_offsetof(struct payload, segs) + nsegs * sizeof(struct payload_seg) > length ||
	    p->adt_off > length || p->adt_size > length - p->adt_off)
		return fail("bad payload header");
	if (p->phys_base < XNU_RAM_BASE || p->phys_base >= XNU_RAM_END || !p->mem_size ||
	    p->mem_size > XNU_RAM_END - p->phys_base ||
	    p->entry_va < p->virt_base || p->kernel_end < p->virt_base)
		return fail("payload RAM outside the 0x880000000 bank");
	uintptr_t mem_end = p->phys_base + p->mem_size;
	uintptr_t kernel_end = p->phys_base + (p->kernel_end - p->virt_base);
	if (kernel_end >= mem_end)
		return fail("kernel larger than RAM window");

	out("zeroing XNU RAM...\n");
	zero(p->phys_base, p->mem_size);
	out("zeroed\n");

	for (uint64_t i = 0; i < nsegs; i++) {
		const volatile struct payload_seg *s = &p->segs[i];
		if (s->vmaddr < p->virt_base || s->file_size > s->vmsize ||
		    s->file_off > length || s->file_size > length - s->file_off ||
		    s->vmsize > p->mem_size || s->vmaddr - p->virt_base > p->mem_size - s->vmsize)
			return fail("bad segment");
		uintptr_t dst = p->phys_base + (s->vmaddr - p->virt_base);
		copy(dst, rd_start + s->file_off, s->file_size);
		zero(dst + s->file_size, s->vmsize - s->file_size);
		clean(dst, dst + s->vmsize);
	}

	uintptr_t adt_pa = kernel_end;
	uintptr_t ba_pa = (adt_pa + p->adt_size + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1);
	if (ba_pa + PAGE_SIZE > mem_end)
		return fail("no room for ADT/boot_args");
	copy(adt_pa, rd_start + p->adt_off, p->adt_size);
	if (fb && !adt_patch((uint8_t *)adt_pa, (uint8_t *)(adt_pa + p->adt_size),
			     "a50-fbcon", fb_base, (uint64_t)FB_STRIDE * FB_H, 0))
		out("warning: a50-fbcon not patched in the ADT\n");
	zero(ba_pa, PAGE_SIZE);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->Revision = 2;
	ba->Version = 2;
	ba->virtBase = p->virt_base;
	ba->physBase = p->phys_base;
	ba->memSize = p->mem_size;
	ba->topOfKernelData = ba_pa + PAGE_SIZE;
	ba->deviceTreeP = p->virt_base + (adt_pa - p->phys_base);
	ba->deviceTreeLength = (uint32_t)p->adt_size;
	for (int i = 0; i < BOOT_LINE_LENGTH; i++)
		ba->CommandLine[i] = p->cmdline[i];
	if (fb) {
		ba->Video.v_baseAddr = fb_base;
		ba->Video.v_rowBytes = FB_STRIDE;
		ba->Video.v_width = FB_W;
		ba->Video.v_height = FB_H;
		ba->Video.v_depth = 32;
		append_arg(ba, " a50fb=", fb_base);
	}
	int64_t now = rtc_unix();
	if (now > 0) {
		kv("rtc unix", (uint64_t)now);
		out("\n");
		append_arg(ba, " a50rtc=", (uint64_t)now);
	} else {
		out("RTC: no valid time\n");
	}
	ba->memSizeActual = p->mem_size;
	clean(adt_pa, ba_pa + PAGE_SIZE);

	uintptr_t entry_pa = p->phys_base + (p->entry_va - p->virt_base);
	if (entry_pa >= kernel_end)
		return fail("entry outside kernel");
	dl_boot_args = ba_pa;
	kv("adt_pa", adt_pa);
	kv("boot_args", ba_pa);
	out("\n");
	kv("entry_pa", entry_pa);
	out("\ncmdline: ");
	for (int i = 0; i < BOOT_LINE_LENGTH && p->cmdline[i]; i++) {
		char c[2] = { p->cmdline[i], 0 };
		out(c);
	}
	out("\n");
	ufs_probe(kv, out, UFS_PROBE_DMA);
	smp_probe(kv, out);
	fg = 0xff40ff40U;
	out("\nJUMP TO XNU\n");
	if (fb)
		clean((uintptr_t)fb_base, fb_base + (uint64_t)FB_STRIDE * FB_H);
	return entry_pa;
}

void dl_exception(uint64_t slot)
{
	uint64_t esr, elr, far;
	__asm__ volatile("mrs %0, esr_el1" : "=r"(esr));
	__asm__ volatile("mrs %0, elr_el1" : "=r"(elr));
	__asm__ volatile("mrs %0, far_el1" : "=r"(far));
	fg = 0xffff4040U;
	out("\nLOADER EXCEPTION ");
	kv("slot", slot);
	kv("ESR", esr);
	kv("ELR", elr);
	kv("FAR", far);
	out("\n");
	for (;;)
		__asm__ volatile("wfe");
}

/* gcc may emit calls for struct copies; keep the image self-contained. */
void *memset(void *d, int c, unsigned long n)
{
	unsigned char *q = d;
	while (n--)
		*q++ = (unsigned char)c;
	return d;
}

void *memcpy(void *d, const void *s, unsigned long n)
{
	unsigned char *q = d;
	const unsigned char *r = s;
	while (n--)
		*q++ = *r++;
	return d;
}
