#!/usr/bin/env python3
"""Per-chunk SHA-256 manifest of an image, for tools/dreamlte/flash-chunks.ps1.

  chunk-manifest.py IMAGE OUT.json [CHUNK_MIB]

Each entry: index, sha256 of the chunk, and whether it is all zeros (those
are written with /dev/zero on the phone instead of being transferred).
"""
import hashlib
import json
import sys

img, out = sys.argv[1], sys.argv[2]
mib = int(sys.argv[3]) if len(sys.argv) > 3 else 32
size = mib << 20
zero = bytes(size)
zero_sha = hashlib.sha256(zero).hexdigest()
chunks = []
with open(img, 'rb') as f:
    i = 0
    while True:
        b = f.read(size)
        if not b:
            break
        if len(b) != size:
            raise SystemExit('image size is not a multiple of the chunk size')
        is_zero = b == zero
        chunks.append({'i': i, 'sha': zero_sha if is_zero else hashlib.sha256(b).hexdigest(),
                       'zero': is_zero})
        i += 1
json.dump({'image': img, 'chunk_mib': mib, 'chunks': chunks,
           'zero_sha': zero_sha}, open(out, 'w'))
nz = sum(not c['zero'] for c in chunks)
print(f'{len(chunks)} chunks of {mib} MiB, {nz} with data ({nz * mib / 1024:.1f} GiB)')
