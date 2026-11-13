#if defined(A50_BUILD)
/*
 * Galaxy A50 touch: Melfas MMS100 (Samsung DT "melfas,mms_ts") at 0x48 on
 * i2c_4 (0x13870000). The A50 wires it to gpp1-0/1 (SDA/SCL, TOP pinctrl
 * 0x139B0000 bank 0x020) and enables its 3.0 V rail with gpg3-1 (TOP bank
 * 0x120). Its interrupt is gpa0-0 (ALIVE pinctrl 0x11850000, bank 0x020).
 *
 * This driver does not touch the HSI2C controller: the A50's I2C4 clock
 * gate is not documented in the public DT and an unclocked HSI2C access is
 * a synchronous abort. It bit-bangs I2C on the same two pins as open-drain
 * GPIOs instead (input+pull-up = released, output-low = driven), which only
 * needs the pinctrl block S-Boot already leaves on.
 *
 * Protocol (Samsung melfas_mss100 MIP 4.0, A50 DT event_info = <8 12>):
 *   write R0,R1 then repeated-start read N bytes.
 *   event packet info  0x02/0x10: size = b & 0x7f, category = b >> 7
 *   event packet data  0x02/0x11
 *   12-byte screen packet: [0] id, [1] bit0 action, [2..4] x/y,
 *   [5..6] z, [7] size, [8..9] pressure, [10..11] major/minor.
 * The A50 panel reports 0..4095 on both axes (Samsung DT max_x_y).
 */
#define A50_TOP_PA		0x139b0000u
#define A50_ALIVE_PA		0x11850000u
#define A50_GPP1		0x020u	/* CON, DAT, PUD */
#define A50_GPG3		0x120u
#define A50_GPA0		0x020u
#define A50_TS_ADDR		0x48u
#define A50_EVENT_SIZE		12u
#define A50_FINGERS		5

static vm_offset_t a50_top, a50_alive;
static int a50_touch_sleep;
static bool a50_touch_down[A50_FINGERS];
static uint16_t a50_touch_x[A50_FINGERS], a50_touch_y[A50_FINGERS];

static void
a50_pin_con(uint32_t bank, unsigned pin, uint32_t nibble)
{
	uint32_t v = a5touch_read(a50_top, bank);
	v = (v & ~(0xfu << (4 * pin))) | ((nibble & 0xf) << (4 * pin));
	a5touch_write(a50_top, bank, v);
}

static void
a50_pin_pud(uint32_t bank, unsigned pin, uint32_t pud)
{
	uint32_t v = a5touch_read(a50_top, bank + 8);
	v = (v & ~(3u << (2 * pin))) | ((pud & 3u) << (2 * pin));
	a5touch_write(a50_top, bank + 8, v);
}

static void
a50_sda_release(void)
{
	a50_pin_con(A50_GPP1, 0, 0);	/* input */
	a50_pin_pud(A50_GPP1, 0, 3);	/* pull-up */
}

static void
a50_sda_low(void)
{
	a50_pin_pud(A50_GPP1, 0, 0);
	a50_pin_con(A50_GPP1, 0, 1);	/* output */
	a5touch_write(a50_top, A50_GPP1 + 4,
	    a5touch_read(a50_top, A50_GPP1 + 4) & ~1u);
}

static void
a50_scl_release(void)
{
	a50_pin_con(A50_GPP1, 1, 0);
	a50_pin_pud(A50_GPP1, 1, 3);
}

static void
a50_scl_low(void)
{
	a50_pin_pud(A50_GPP1, 1, 0);
	a50_pin_con(A50_GPP1, 1, 1);
	a5touch_write(a50_top, A50_GPP1 + 4,
	    a5touch_read(a50_top, A50_GPP1 + 4) & ~2u);
}

static int
a50_sda_read(void)
{
	a50_sda_release();
	return (int)((a5touch_read(a50_top, A50_GPP1 + 4) >> 0) & 1u);
}

static void
a50_i2c_delay(void)
{
	IODelay(4);
}

static void
a50_i2c_start(void)
{
	a50_sda_release();
	a50_scl_release();
	a50_i2c_delay();
	a50_sda_low();
	a50_i2c_delay();
	a50_scl_low();
	a50_i2c_delay();
}

static void
a50_i2c_stop(void)
{
	a50_sda_low();
	a50_i2c_delay();
	a50_scl_release();
	a50_i2c_delay();
	a50_sda_release();
	a50_i2c_delay();
}

/* Returns 1 when the slave acknowledged. */
static int
a50_i2c_write_byte(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {
		if (b & (1u << i)) {
			a50_sda_release();
		} else {
			a50_sda_low();
		}
		a50_i2c_delay();
		a50_scl_release();
		a50_i2c_delay();
		a50_scl_low();
		a50_i2c_delay();
	}
	a50_sda_release();
	a50_i2c_delay();
	a50_scl_release();
	a50_i2c_delay();
	int ack = !a50_sda_read();
	a50_scl_low();
	a50_i2c_delay();
	return ack;
}

static uint8_t
a50_i2c_read_byte(int ack)
{
	uint8_t b = 0;
	a50_sda_release();
	for (int i = 7; i >= 0; i--) {
		a50_i2c_delay();
		a50_scl_release();
		a50_i2c_delay();
		b = (uint8_t)((b << 1) | (a50_sda_read() & 1));
		a50_scl_low();
		a50_i2c_delay();
	}
	if (ack) {
		a50_sda_low();
	} else {
		a50_sda_release();
	}
	a50_i2c_delay();
	a50_scl_release();
	a50_i2c_delay();
	a50_scl_low();
	a50_i2c_delay();
	return b;
}

/* MIP read: 2-byte register address, repeated start, N bytes. */
static bool
a50_mip_read(uint8_t r0, uint8_t r1, uint8_t *buf, unsigned len)
{
	a50_i2c_start();
	if (!a50_i2c_write_byte((uint8_t)(A50_TS_ADDR << 1)) ||
	    !a50_i2c_write_byte(r0) || !a50_i2c_write_byte(r1)) {
		a50_i2c_stop();
		return false;
	}
	a50_i2c_start();
	if (!a50_i2c_write_byte((uint8_t)((A50_TS_ADDR << 1) | 1))) {
		a50_i2c_stop();
		return false;
	}
	for (unsigned i = 0; i < len; i++) {
		buf[i] = a50_i2c_read_byte(i + 1 < len);
	}
	a50_i2c_stop();
	return true;
}

static void
a50_touch_wait(unsigned ms)
{
	uint64_t deadline;
	clock_interval_to_deadline(ms, NSEC_PER_MSEC, &deadline);
	(void)assert_wait_deadline(&a50_touch_sleep, THREAD_UNINT, deadline);
	thread_block(THREAD_CONTINUE_NULL);
}

static void
a50_touch_report(const uint8_t *p)
{
	int id = (p[0] & 0x0fu) - 1;
	int action = p[1] & 1u;
	unsigned x = ((unsigned)(p[2] & 0x0fu) << 8) | p[3];
	unsigned y = (((unsigned)p[2] >> 4) << 8) | p[4];
	if (id < 0 || id >= A50_FINGERS) {
		return;
	}
	/* SweetHIDTouch's digitizer grid is 1080x1920. */
	x = x * 1080u / 4096u;
	y = y * 1920u / 4096u;
	if (action) {
		if (!a50_touch_down[id]) {
			printf("A50 TOUCH: down id=%d x=%u y=%u\n", id, x, y);
		}
		a50_touch_down[id] = true;
		a50_touch_x[id] = (uint16_t)x;
		a50_touch_y[id] = (uint16_t)y;
		sweet_hid_touch(id, 1, (int)x, (int)y);
	} else if (a50_touch_down[id]) {
		a50_touch_down[id] = false;
		sweet_hid_touch(id, 0, a50_touch_x[id], a50_touch_y[id]);
	}
}

static void
a50_touch_thread(void *arg, wait_result_t result)
{
	uint8_t info = 0, buf[200];
	unsigned failures = 0;
	(void)arg;
	(void)result;
	printf("A50 TOUCH: worker started\n");
	a50_touch_wait(30);	/* tsp_ldo_en settling */
	/* The controller answers 0xA0 once its boot firmware is ready. */
	for (unsigned i = 0; i < 200; i++) {
		if (a50_mip_read(0x06, 0x00, &info, 1) && info == 0xa0) {
			break;
		}
		a50_touch_wait(10);
	}
	if (info == 0xa0) {
		char name[17] = {0};
		if (a50_mip_read(0x01, 0x00, (uint8_t *)name, 16)) {
			printf("A50 TOUCH: MMS100 '%s'\n", name);
		}
	} else {
		printf("A50 TOUCH: controller not ready (status %#x)\n", info);
	}
	for (;;) {
		/* gpa0-0 is active low while events are queued. */
		if ((a5touch_read(a50_alive, A50_GPA0 + 4) & 1u)) {
			a50_touch_wait(8);
			continue;
		}
		if (!a50_mip_read(0x02, 0x10, &info, 1)) {
			if (++failures <= 8 || !(failures & 255)) {
				printf("A50 TOUCH: packet info read failed (%u)\n", failures);
			}
			a50_touch_wait(20);
			continue;
		}
		unsigned size = info & 0x7fu;
		if (!size || size > sizeof(buf)) {
			a50_touch_wait(4);
			continue;
		}
		if (!a50_mip_read(0x02, 0x11, buf, size)) {
			if (++failures <= 8 || !(failures & 255)) {
				printf("A50 TOUCH: packet read failed (%u)\n", failures);
			}
			a50_touch_wait(20);
			continue;
		}
		if (!(info & 0x80)) {	/* touch category */
			for (unsigned i = 0; i + A50_EVENT_SIZE <= size; i += A50_EVENT_SIZE) {
				a50_touch_report(buf + i);
			}
		}
		failures = 0;
	}
}

static void
a50_touch_start(void)
{
	thread_t thread;
	int enabled = 1;
	(void)PE_parse_boot_argn("a50touch", &enabled, sizeof(enabled));
	if (!enabled) {
		printf("A50 TOUCH: disabled\n");
		return;
	}
	a50_top = ml_io_map(A50_TOP_PA, 0x1000);
	a50_alive = ml_io_map(A50_ALIVE_PA, 0x1000);
	if (!a50_top || !a50_alive) {
		printf("A50 TOUCH: MMIO mapping failed\n");
		return;
	}
	/* tsp_ldo_en: gpg3-1, active high, powers the 3.0 V touch rail. */
	a50_pin_pud(A50_GPG3, 1, 0);
	a50_pin_con(A50_GPG3, 1, 1);
	a5touch_write(a50_top, A50_GPG3 + 4,
	    a5touch_read(a50_top, A50_GPG3 + 4) | 2u);
	a50_sda_release();
	a50_scl_release();
	if (kernel_thread_start(a50_touch_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	} else {
		printf("A50 TOUCH: thread start failed\n");
	}
}
#endif /* A50_BUILD */
