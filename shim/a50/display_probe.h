#pragma once
#include <stdint.h>

/*
 * Read DECON_F/IDMA0 (Exynos 9610) and return the physical address S-Boot
 * scans out, or 0 if it cannot be identified. The loader uses it for its
 * screen console, boot_args.Video and the ADT "a50-fbcon" reg.
 */
uintptr_t display_probe(void (*kv)(const char *, uint64_t), void (*out)(const char *));
