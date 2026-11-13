#!/usr/bin/env python3
"""Pack an A50 boot.img (Android header v1/v2, no DTB) for the XNU loader.

The SM-A505F stock boot partition is a header-v1 Android boot image: page size
2048, a raw arm64 Image, a gzip ramdisk, no second stage, no recovery DTBO and
no separate DTB (the bootloader uses the dtbo partition).  Reuse the stock
header's addresses, page size, os_version and command line, replace the kernel
and ramdisk, and recompute the v1 id.

  mkboot_a50.py STOCK_BOOT.img KERNEL RAMDISK OUT.img
"""
import hashlib
import struct
import sys

HDR_ID = 0x240
HDR_ID_LEN = 32
REC_DTBO_SIZE = 1632
REC_DTBO_OFFSET = 1636
HEADER_SIZE = 1644
DTB_SIZE = 1648
DTB_ADDR = 1652


def pages(n, page):
    return (n + page - 1) // page * page


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    stock_path, kernel_path, ramdisk_path, out_path = sys.argv[1:]
    stock = open(stock_path, 'rb').read()
    kernel = open(kernel_path, 'rb').read()
    ramdisk = open(ramdisk_path, 'rb').read()

    assert stock[:8] == b'ANDROID!', 'not an Android boot image'
    (ksz, kaddr, rsz, raddr, ssz, saddr, tags, page, hver, osver) = \
        struct.unpack_from('<10I', stock, 8)
    assert hver in (1, 2), f'unsupported boot header version {hver}'
    assert page >= 2048 and page <= 65536 and page & (page - 1) == 0
    rec_size = struct.unpack_from('<I', stock, REC_DTBO_SIZE)[0]
    dtb_size = struct.unpack_from('<I', stock, DTB_SIZE)[0]
    assert rec_size == 0, 'stock has a recovery DTBO; use a no-DTBO A50 image'
    assert dtb_size == 0, 'stock has a DTB; use a no-DTB A50 image'

    hdr = bytearray(stock[:page])
    struct.pack_into('<10I', hdr, 8, len(kernel), kaddr, len(ramdisk), raddr,
                     0, 0, tags, page, hver, osver)
    # Keep the stock name, cmdline, extra_cmdline and header_size.  The A50
    # bootloader has no DTBO/DTB to consume here.
    struct.pack_into('<I', hdr, REC_DTBO_SIZE, 0)
    struct.pack_into('<Q', hdr, REC_DTBO_OFFSET, 0)
    struct.pack_into('<I', hdr, DTB_SIZE, 0)
    struct.pack_into('<Q', hdr, DTB_ADDR, 0)

    sha = hashlib.sha1()
    blobs = [kernel, ramdisk, b'', b'']  # kernel, ramdisk, second, recovery_dtbo
    if hver >= 2:
        blobs.append(b'')               # dtb
    for blob in blobs:
        sha.update(blob)
        sha.update(struct.pack('<I', len(blob)))
    hdr[HDR_ID:HDR_ID + HDR_ID_LEN] = sha.digest() + b'\0' * 12

    out = bytearray(hdr)
    for blob in (kernel, ramdisk):
        out += blob
        out += b'\0' * (pages(len(blob), page) - len(blob))
    # Samsung's bootloader recognises this marker on unsigned boot images.
    out += b'SEANDROIDENFORCE'
    open(out_path, 'wb').write(out)
    print(f'{out_path}: {len(out)} bytes (kernel {len(kernel)}, ramdisk {len(ramdisk)}, '
          f'pagesize {page}, header v{hver}, id {sha.hexdigest()})')


if __name__ == '__main__':
    main()
