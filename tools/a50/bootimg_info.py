#!/usr/bin/env python3
"""Print and verify an A50 Android boot image (v1/v2, no DTB).

  bootimg_info.py BOOT.img
"""
import hashlib
import struct
import sys


def pages(n, page):
    return (n + page - 1) // page * page


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    img = open(sys.argv[1], 'rb').read()
    assert img[:8] == b'ANDROID!', 'not an Android boot image'
    (ksz, kaddr, rsz, raddr, ssz, saddr, tags, page, hver, osver) = \
        struct.unpack_from('<10I', img, 8)
    assert hver in (1, 2), f'unsupported boot header version {hver}'
    header_size = struct.unpack_from('<I', img, 1644)[0]
    dtb_size = struct.unpack_from('<I', img, 1648)[0]
    off = page
    kernel = img[off:off + ksz]
    off += pages(ksz, page)
    ramdisk = img[off:off + rsz]
    off += pages(rsz, page)
    second = img[off:off + ssz]
    off += pages(ssz, page)

    sha = hashlib.sha1()
    blobs = [kernel, ramdisk, second]
    if hver >= 1:
        rec_size = struct.unpack_from('<I', img, 1632)[0]
        rec = img[off:off + rec_size]
        off += pages(rec_size, page)
        blobs.append(rec)
    if hver >= 2:
        dtb = img[off:off + dtb_size]
        off += pages(dtb_size, page)
        blobs.append(dtb)
    for blob in blobs:
        sha.update(blob)
        sha.update(struct.pack('<I', len(blob)))
    calc = sha.digest() + b'\0' * 12
    stored = img[576:608]
    name = img[0x30:0x40].split(b'\0')[0]
    cmdline = img[0x40:0x240].split(b'\0')[0]

    print(f'name={name!r} cmdline={cmdline!r}')
    print(f'kernel size={ksz:#x} addr={kaddr:#x} pagesize={page} header_v={hver} '
          f'header_size={header_size} dtb_size={dtb_size:#x}')
    print(f'ramdisk size={rsz:#x} addr={raddr:#x}')
    print(f'id={stored.hex()} id_ok={calc == stored}')
    if len(kernel) > 0x40:
        print(f'kernel arm64 magic={kernel[0x38:0x3c]!r}')
    if len(ramdisk) >= 2:
        print(f'ramdisk magic={ramdisk[:2].hex()}')
    print(f'payload ends at {off:#x}; trailing={img[off:off + 32]!r}')
    if calc != stored:
        sys.exit(1)


if __name__ == '__main__':
    main()
