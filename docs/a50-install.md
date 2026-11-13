# Installing the Galaxy A50 port

> **Read this first:** the A50 target has not booted on hardware. This guide
> describes the build and flash steps so the port can be tested; it is not a
> promise that the image works. Keep a full TWRP backup and do not overwrite
> the bootloaders.

## 0. What you need

- Samsung Galaxy A50 **SM-A505F** (Exynos 9610). Other A50 variants use
  different panels/touch parts and are not covered.
- Unlocked bootloader, TWRP for `a50`, and a full backup of at least BOOT,
  DTBO, EFS and USERDATA.
- A Linux host (or WSL) with `aarch64-linux-gnu-gcc`, `python3`, `patch`,
  `git`, and enough disk for an XNU tree.
- The iPhone X 16.7.16 IPSW, downloaded by you (not distributed here), for
  the iOS root filesystem. The S8 guide's root-image steps apply; see
  [s8-install.md](s8-install.md) sections 2–4.

## 1. Build the A50 XNU kernel

The kernel is built by the GitHub Actions workflow `xnu` with
`MACHINE_CONFIG=A50`:

1. Push this tree to your fork.
2. Actions → **xnu** → Run workflow:
   - `macos_version`: `13.5`
   - `kernel_config`: `DEVELOPMENT`
   - `machine_config`: `A50`
3. Download the `xnu-kernel` artifact and take `kernel.development.*`.

The A50 job uses `-mcpu=cortex-a53 -march=armv8-a+crypto` (no LSE), like the
S8 job. Patch `0129-a50.patch` is applied by the normal patch replay.

## 2. Build the loader and BOOT image

On Linux:

```sh
cd shim/a50
./build.sh                       # needs aarch64-linux-gnu-gcc
```

To pack a BOOT image you also need a stock A50 BOOT image (for the Samsung
header/DTBH) and a kernel:

```sh
tools/a50/make-boot.sh \
  /path/to/kernel.development.a50 \
  /path/to/stock-a50-boot.img \
  /tmp/a50-boot.img \
  debug=0xc serial=3 cpus=1 keepsyms=1 wdt=-1
```

`make-boot.sh` runs `mkadt_a50.py`, `mkpayload.py` and
`shim/a50/build.sh`, then prints the image header. The default boot-args
have no root device, so the first trial is expected to end in a root-mount
panic; that still proves the loader, display and XNU entry work.

## 3. Flash

In TWRP:

1. Confirm the BOOT partition name before writing anything:
   ```sh
   ls -l /dev/block/by-name/
   ```
   The S8 uses `sda7`; **do not assume the A50 uses the same number**.
2. Back up the current BOOT image.
3. Write `a50-boot.img` to the BOOT partition (TWRP Install → Install Image,
   or `dd` to the verified block device).
4. Reboot. The loader draws its console on the panel using the DECON scanout
   address it read at runtime.

If the screen stays black, restore the BOOT backup from TWRP. There is no
pstore on this board yet, so the loader cannot leave a crash log.

## 4. iOS root filesystem

The A50 port uses the same iPhone X 16.7.16 root image as the S8. Follow
[s8-install.md](s8-install.md) to build it, then write it to the A50's
USERDATA partition. Verify the partition name in TWRP first; the S8's
`sda24` is not guaranteed on the A50.

The kernel's default `ufsroot=USERDATA` expects a GPT partition named
`USERDATA`. Check it from TWRP:

```sh
sgdisk -p /dev/block/sda    # or: parted /dev/block/sda print
```

If the name differs, add `ufsroot=<name>` to the boot-args. Writes stay
disabled unless `ufsrw=1` is also passed.

## 5. First-boot expectations

- Start with `cpus=1`. The A73 cluster power/L2 bring-up is not implemented.
- The display is presented at 1080×2340 (360×780 pt), not the iPhone X's
  1125×2436. Layout may be wrong even if the kernel boots.
- Touch starts automatically (`a50touch=0` disables it). It uses a polled
  bit-banged i2c_4; check the log for `A50 TOUCH: MMS100`.
- Battery is a static 100% source until the S2MPU09 gauge is written.

## Recovery

- Power + Volume Down, then Power + Volume Up → TWRP (same key combination
  as the S8 guide).
- Restore BOOT from the backup. Do not flash the A50 bootloader or EFS.
