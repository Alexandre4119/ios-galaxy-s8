#!/usr/bin/env python3
"""Linux/adb port of flash-chunks.ps1: write an image to a by-name partition
of the phone in TWRP, in chunks, with no PowerShell/Windows/WSL needed.

  flash-chunks.py IMAGE MANIFEST.json [--partition USERDATA] [--progress PATH]

Same approach as the PowerShell version: push a chunk to /tmp on the phone,
dd it at its offset, then check the SHA-256 of what is now on the partition.
All-zero chunks are written straight from /dev/zero on the phone, no push.
Verified chunk indexes are appended to the progress file, so a USB drop only
costs a rerun (already-verified chunks are skipped). Writes nothing outside
the named partition.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RETRIES = 8


def adb_shell(cmd, check=True):
    r = subprocess.run(["adb", "shell", cmd], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"adb shell {cmd!r} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def adb_alive():
    r = subprocess.run(["adb", "get-state"], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "device"


def wait_for_device(seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if adb_alive():
            return True
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("manifest")
    ap.add_argument("--partition", default="USERDATA")
    ap.add_argument("--progress", default=None)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    mib = int(manifest["chunk_mib"])
    size = mib << 20
    chunks = manifest["chunks"]

    progress_path = Path(args.progress) if args.progress else Path(__file__).resolve().parents[2] / "research" / "flash-progress.txt"
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    dev = adb_shell(f"readlink -f /dev/block/platform/*/by-name/{args.partition}")
    if not __import__("re").match(r"^/dev/block/sd[a-z][0-9]+$", dev):
        raise SystemExit(f"partition {args.partition} not found ({dev})")
    psize = int(adb_shell(f"blockdev --getsize64 {dev}"))
    if psize < len(chunks) * size:
        raise SystemExit(f"{dev} is {psize} bytes, image does not fit")
    print(f"target {args.partition} = {dev} ({psize} bytes), {len(chunks)} chunks of {mib} MiB")
    adb_shell("umount /data 2>/dev/null; umount /sdcard 2>/dev/null; true", check=False)

    done = set()
    if progress_path.exists():
        done = {int(l) for l in progress_path.read_text().splitlines() if l.strip()}

    with open(args.image, "rb") as f, tempfile.NamedTemporaryFile(prefix="s8chunk-", suffix=".bin") as tmp:
        for c in chunks:
            i, sha, is_zero = int(c["i"]), c["sha"], bool(c["zero"])
            if i in done:
                continue
            for attempt in range(1, RETRIES + 1):
                try:
                    if is_zero:
                        adb_shell(f"dd if=/dev/zero of={dev} bs=1048576 seek={i * mib} count={mib} conv=notrunc 2>/dev/null")
                    else:
                        f.seek(i * size)
                        buf = f.read(size)
                        if len(buf) != size:
                            raise RuntimeError("short read from image")
                        tmp.seek(0)
                        tmp.truncate()
                        tmp.write(buf)
                        tmp.flush()
                        r = subprocess.run(["adb", "push", tmp.name, "/tmp/c.bin"], capture_output=True, text=True)
                        if r.returncode != 0:
                            raise RuntimeError(f"push failed: {r.stderr.strip()}")
                        adb_shell(f"dd if=/tmp/c.bin of={dev} bs=1048576 seek={i * mib} conv=notrunc 2>/dev/null; rm -f /tmp/c.bin")
                    got = adb_shell(f"dd if={dev} bs=1048576 skip={i * mib} count={mib} 2>/dev/null | sha256sum").split()[0]
                    if got != sha:
                        raise RuntimeError(f"verify mismatch ({got})")
                    with open(progress_path, "a") as p:
                        p.write(f"{i}\n")
                    break
                except Exception as e:
                    print(f"chunk {i} try {attempt} failed: {e}")
                    if attempt >= RETRIES:
                        raise
                    wait_for_device()
            if i % 16 == 0:
                print(f"chunk {i + 1}/{len(chunks)}")

    adb_shell("sync")
    print(f"all {len(chunks)} chunks written and verified on {dev}")


if __name__ == "__main__":
    sys.exit(main())
