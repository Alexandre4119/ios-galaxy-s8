#pragma once
#include <stdint.h>

void smp_probe(void (*kv)(const char *, uint64_t), void (*out)(const char *));
