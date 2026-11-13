#!/usr/bin/env python3
"""Emit xnu/patches/0129-a50.patch from a pristine tree and an A50 tree.
Usage: make-patch.py PRISTINE_XNU A50_XNU OUTPUT.patch
"""
import difflib
import sys
from pathlib import Path

FILES = [
    'pexpert/pexpert/arm64/A5XELTE.h',
    'makedefs/MakeInc.def',
    'bsd/conf/Makefile.template',
    'libkern/conf/Makefile.template',
    'config/MASTER.arm64.a50',
    'osfmk/arm64/start.s',
    'iokit/Kernel/arm/SweetFramebuffer.cpp',
    'pexpert/arm/pe_serial.c',
    'bsd/dev/a5xelte_keys.c',
    'bsd/dev/a5xelte_touch.c',
    'iokit/Kernel/IOPlatformExpert.cpp',
    'iokit/Kernel/arm/SweetBattery.cpp',
    'bsd/dev/sweet_ufs.c',
    'iokit/KernelConfigTables.cpp',
]

base, new, out = (Path(a) for a in sys.argv[1:4])


def lines(path):
    # Patches must be LF-only: prep-xnu-tree.sh applies them with `patch -p1`.
    return path.read_bytes().replace(b'\r\n', b'\n').decode().splitlines()


patch = []
for rel in FILES:
    old_path = base / rel
    new_path = new / rel
    if not new_path.exists():
        raise SystemExit(f'{rel}: missing from the A50 tree')
    if old_path.exists():
        old = lines(old_path)
        if 'A50_BUILD' in '\n'.join(old):
            raise SystemExit(f'{rel}: pristine tree already has A50 edits')
        fromfile = f'a/{rel}'
    else:
        old = []
        fromfile = '/dev/null'
    if fromfile == '/dev/null':
        # git apply needs this header to create a file; patch ignores it.
        patch.extend([f'diff --git a/{rel} b/{rel}', 'new file mode 100644'])
    diff = list(difflib.unified_diff(
        old, lines(new_path), fromfile=fromfile, tofile=f'b/{rel}', n=3,
        lineterm=''))
    if not diff:
        raise SystemExit(f'{rel}: no changes')
    patch.extend(diff)

out.write_text('\n'.join(patch) + '\n', newline='\n')
print(f'{out}: {len(patch)} lines, {len(FILES)} files')
