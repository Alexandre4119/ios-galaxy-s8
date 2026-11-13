# Galaxy A50 port log

Target: SM-A505F (`a50`, Exynos 9610), ported from the Galaxy S8 tree.
Status: **scaffold complete, not booted**. This file records what was
derived, added and actually checked, so the next session does not redo it.

## 2026-11-13 — initial port

### Hardware facts (Samsung public device trees)

- `arch/arm64/boot/dts/exynos/universal9610/exynos9610.dts` and
  `arch/arm64/boot/dts/samsung/a50/*`:
  - CPU: A53 cluster logical 0–3 (MPIDR 0x0–0x3), A73 cluster 4–7
    (MPIDR 0x100–0x103); `enable-method = "psci"`.
  - Timer: 26 MHz, `use-physical-timer`, PPI 14 → INTID 30.
  - GIC-400: `0x12301000` / `0x12302000`.
  - UFS: HCI `0x13520000`, vendor HCI `0x13521100`, UNIPRO `0x13510000`,
    protector `0x13530000`.
  - DECON_F `0x148B0000`; DPP G0 `0x14891000`, IDMA0 `0x14881000`, Y at
    `+0x40`; panel 1080×2340.
  - ALIVE pinctrl `0x11850000` (gpa0 `+0x020`, gpa1 `+0x040`), TOP
    `0x139B0000` (gpp1 `+0x020`, gpg3 `+0x120`).
  - Keys: Power GPA1-7, Vol+ GPA1-5, Vol− GPA1-6, active low.
  - Touch: Melfas MMS100 `0x48` on i2c_4 `0x13870000`; IRQ GPA0-0;
    SCL/SDA gpp1-1/gpp1-0; enable gpg3-1; `event_info = <8 12>`.
  - RTC: `exynos8-rtc` at `0x11A20000`; PMIC S2MPU09.

### Design choices

- Reuse `MACHINE_CONFIG=A5XELTE` with `-DA50_BUILD` rather than a new XNU
  board config; every A5XELTE guard still applies and the S8 target is
  unchanged.
- Do not hardcode the framebuffer: the loader reads DECON IDMA0's Y address,
  fills `boot_args.Video`, and patches the ADT `a50-fbcon` reg.
- Touch uses bit-banged i2c_4 (gpp1) instead of HSI2C, because the Exynos9610
  HSI2C clock-gate registers are not in the public DT.
- Battery is a static source until S2MPU09 is researched.
- No pstore/ramoops address is known; logs go to the panel only.

### Files added

- `shim/a50/`: `start.S`, `loader.ld`, `loader.c`, `ufs_probe.[ch]`,
  `smp_probe.[ch]`, `display_probe.[ch]`, `build.sh`.
- `tools/mkadt_a50.py`: A50 ADT (9520 bytes, 1080×2340).
- `tools/a50/`: `apply-a50.py`, `make-patch.py`, `make-boot.sh`,
  `a50_touch.c`.
- `xnu/patches/0129-a50.patch`: generated A50 XNU layer (14 files, 773
  patch lines), including `config/MASTER.arm64.a50`.
- `docs/a50-port.md`, `docs/a50-install.md`, this file.
- CI: `machine_config` input accepts `A50`; LSE-disabling branch covers it.

### Checks actually run

- `python tools/mkadt_a50.py ... --dump`: OK; `a50-fbcon` reg placeholder
  is `0x0, 0x9a3f80`, root `compatible` starts `samsung,a50`.
- `python tools/a50/apply-a50.py` on a fresh 0128 tree: all 14 files
  edited/added, every asserted anchor matched.
- `python tools/a50/make-patch.py`: 773 lines, 14 files.
- `patch -p1` on a fresh 0128 tree: all hunks apply; result equals the
  generator tree after newline normalization (CRLF vs LF only).
- Host `gcc -fsyntax-only` (x86-64): loader and all three probes pass with
  `-Wall -Wextra`.
- Zig 0.17.1 with `-target aarch64-freestanding -mcpu=cortex_a53`: all five
  objects compile, link with `loader.ld`; `zig objcopy` gives a 32,320-byte
  Image. ELF: `EM_AARCH64`, `_head` at 0, `_start` at 0x800, zero
  relocations, zero `R_AARCH64_ABS64`.
- Not run: canonical `aarch64-linux-gnu-gcc` build, XNU
  `MACHINE_CONFIG=A50` build, device boot.

### First things to fix on hardware

1. Build `MACHINE_CONFIG=A50`; fix compile errors from the A50-only paths
   (especially `a50_touch.c` and the battery branch).
2. Confirm DECON IDMA0 Y is the scanout buffer and that the panel is already
   scanning when S-Boot jumps to us. If not, the A50 needs the DECON trigger
   sequence the S8 loader has (`shim/dreamlte/decon*.c`).
3. Confirm gpp1-0/1 are in GPIO function after S-Boot; if not, program the
   TOP pinctrl function explicitly.
4. Find the real USERDATA partition name/LUN for `ufsroot=`.
5. Add a pstore/ramoops region before debugging early panics.
