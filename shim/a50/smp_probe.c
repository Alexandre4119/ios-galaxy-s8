/* SPDX-License-Identifier: GPL-2.0-only
 * Galaxy A50 secondary-CPU probe, run by the loader (MMU off).
 *
 * Samsung's A50 device tree enables all eight cores with PSCI
 * (enable-method = "psci"): four Cortex-A53 at MPIDR 0x0-0x3 (boot cluster)
 * and four Cortex-A73 at MPIDR 0x100-0x103. Unlike the S8's Mongoose
 * cluster, no Samsung PMU power sequencing is described, so CPU_ON is tried
 * directly. A started core marks its slot and turns itself off again
 * (start.S: smp_entry).
 */
#include <stdint.h>
#include "smp_probe.h"

#define PSCI_CPU_ON	0xc4000003UL
#define TIMER_HZ	26000000UL

extern char smp_entry[];
extern volatile uint64_t smp_flags[8];

static inline uint32_t rd(uintptr_t a) { return *(volatile uint32_t *)a; }

static uint64_t ticks(void)
{
	uint64_t v;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
	return v;
}

static int64_t smc3(uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3)
{
	register uint64_t x0 __asm__("x0") = fn;
	register uint64_t x1 __asm__("x1") = a1;
	register uint64_t x2 __asm__("x2") = a2;
	register uint64_t x3 __asm__("x3") = a3;
	__asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : :
			 "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
			 "x14", "x15", "x16", "x17", "memory");
	return (int64_t)x0;
}

static int wait_flag(unsigned slot, unsigned ms)
{
	uint64_t end = ticks() + TIMER_HZ / 1000 * ms;
	while (ticks() < end)
		if (smp_flags[slot])
			return 1;
	return 0;
}

void smp_probe(void (*kv)(const char *, uint64_t), void (*out)(const char *))
{
	static const uint64_t targets[] = { 0x1, 0x100 };
	uint64_t self = 0;
	__asm__ volatile("mrs %0, mpidr_el1" : "=r"(self));
	out("SMP probe (PSCI, A53 0x1 / A73 0x100)\n");
	kv("boot mpidr", self & 0xffffff);
	kv("pmu alive", rd(0x11860000UL));
	out("\n");
	for (unsigned t = 0; t < sizeof(targets) / sizeof(targets[0]); t++) {
		uint64_t m = targets[t];
		unsigned slot = (((m >> 8) & 1) << 2) | (m & 3);
		smp_flags[slot] = 0;
		int64_t rc = smc3(PSCI_CPU_ON, m, (uintptr_t)smp_entry, slot);
		int up = wait_flag(slot, 300);
		kv("target", m);
		kv("rc", (uint64_t)rc);
		kv("started", up);
		out("\n");
	}
	out("SMP probe done\n");
}
