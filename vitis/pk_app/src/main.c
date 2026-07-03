#include "xparameters.h"
#include "xil_printf.h"
#include "xgpio.h"
#include "xil_io.h"
#include "xuartps_hw.h"
#include "xiltimer.h"
#include "xtimer_config.h"
#include "sleep.h"

#define GPIO_BASEADDR   XPAR_AXI_GPIO_0_BASEADDR
#define GPIO_CHANNEL    1
#define UART_BASEADDR   XPAR_UART1_BASEADDR

#define SW_WITHDRAW     0x01u
#define SW_INSERT       0x02u
#define SW_SCRAM        0x80u

#define PK_BASEADDR     XPAR_POINT_KINETICS_STEP_0_BASEADDR

#define PK_AP_CTRL      0x000u
#define PK_H            0x010u
#define PK_SUBSTEPS     0x018u
#define PK_TC_FACTOR    0x020u
#define PK_RESET        0x028u
#define PK_RESET_POWER  0x030u
#define PK_WITHDRAW     0x038u
#define PK_INSERT       0x040u
#define PK_SCRAM        0x048u

#define PK_T_OUT        0x050u
#define PK_N_OUT        0x060u
#define PK_TF_OUT       0x070u
#define PK_TC_OUT       0x080u
#define PK_I_XE_OUT     0x090u
#define PK_XE_OUT       0x0a0u
#define PK_RHO_OUT      0x0b0u
#define PK_DOLLARS_OUT  0x0c0u
#define PK_RHO_XE_OUT   0x0d0u
#define PK_ROD_POS_OUT  0x0e0u
#define PK_ROD_TGT_OUT  0x0f0u
#define PK_TC_FACT_OUT  0x100u
#define PK_ENGINE_OUT   0x110u

#define PK_SET_ROD_TGT  0x180u
#define PK_ROD_TGT_CMD  0x188u
#define PK_PLANT_MODE   0x190u
#define PK_PLANT_UPD    0x198u
#define PK_TARGET_H_OUT 0x1a0u
#define PK_DECAY_OUT    0x1b0u
#define PK_PLANT_OUT    0x1c0u

#define MODE_REALTIME_H     0.00001f
#define MODE_TRAINING_H     0.0001f
#define MODE_XENON_H        0.002f
#define WALL_OUTPUT_INTERVAL 0.01f
#define MAX_SUBSTEPS        100000

typedef struct {
    float h;
    float tc_factor;
    float reset_power;
    int substeps;
    int reset;
    int withdraw_pulse;
    int insert_pulse;
    int scram_pulse;
    int set_rod_target;
    float rod_target;
    int plant_mode;
    int plant_update;
} AppState;

static u32 float_to_u32(float value)
{
    union {
        float f;
        u32 u;
    } cvt;
    cvt.f = value;
    return cvt.u;
}

static float u32_to_float(u32 value)
{
    union {
        float f;
        u32 u;
    } cvt;
    cvt.u = value;
    return cvt.f;
}

static float clamp_float(float value, float low, float high)
{
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

static int finite_float(float value)
{
    return (value == value) && (value <= 3.4028234e38f) &&
           (value >= -3.4028234e38f);
}

static void pk_write_float(u32 offset, float value)
{
    Xil_Out32(PK_BASEADDR + offset, float_to_u32(value));
}

static void pk_write_int(u32 offset, int value)
{
    Xil_Out32(PK_BASEADDR + offset, (u32)value);
}

static float pk_read_float(u32 offset)
{
    return u32_to_float(Xil_In32(PK_BASEADDR + offset));
}

static void pk_start_and_wait(void)
{
    Xil_Out32(PK_BASEADDR + PK_AP_CTRL, 0x01u);
    while ((Xil_In32(PK_BASEADDR + PK_AP_CTRL) & 0x02u) == 0u) {
    }
}

static int is_space(char ch)
{
    return (ch == ' ') || (ch == '\t');
}

static int parse_float_arg(const char *text, float *out)
{
    float value = 0.0f;
    float frac_scale = 0.1f;
    int sign = 1;
    int seen_digit = 0;
    int exp_sign = 1;
    int exponent = 0;

    while (is_space(*text)) {
        text++;
    }

    if (*text == '-') {
        sign = -1;
        text++;
    } else if (*text == '+') {
        text++;
    }

    while ((*text >= '0') && (*text <= '9')) {
        value = value * 10.0f + (float)(*text - '0');
        text++;
        seen_digit = 1;
    }

    if (*text == '.') {
        text++;
        while ((*text >= '0') && (*text <= '9')) {
            value += (float)(*text - '0') * frac_scale;
            frac_scale *= 0.1f;
            text++;
            seen_digit = 1;
        }
    }

    if (!seen_digit) {
        return 0;
    }

    if ((*text == 'e') || (*text == 'E')) {
        text++;
        if (*text == '-') {
            exp_sign = -1;
            text++;
        } else if (*text == '+') {
            text++;
        }
        while ((*text >= '0') && (*text <= '9')) {
            exponent = exponent * 10 + (*text - '0');
            text++;
        }
    }

    value *= (float)sign;
    while (exponent > 0) {
        value = (exp_sign > 0) ? (value * 10.0f) : (value * 0.1f);
        exponent--;
    }

    *out = value;
    return 1;
}

static void print_fixed(float value, int digits)
{
    int i;
    int scale = 1;

    if (value < 0.0f) {
        xil_printf("-");
        value = -value;
    }

    for (i = 0; i < digits; i++) {
        scale *= 10;
    }

    int whole = (int)value;
    int frac = (int)((value - (float)whole) * (float)scale + 0.5f);

    if (frac >= scale) {
        whole++;
        frac -= scale;
    }

    xil_printf("%d", whole);
    if (digits > 0) {
        xil_printf(".");
        for (i = scale / 10; i > 1; i /= 10) {
            if (frac < i) {
                xil_printf("0");
            }
        }
        xil_printf("%d", frac);
    }
}

static void print_csv_value(float value)
{
    print_fixed(value, 6);
}

static void print_precise_csv_value(float value)
{
    print_fixed(value, 9);
}

static void print_data_row(float t,
                           float n,
                           float Tf,
                           float rho,
                           float dollars,
                           float Tc,
                           float I_Xe,
                           float Xe,
                           float rho_Xe,
                           float tc_factor,
                           float rod_position,
                           float rod_target,
                           float engine_order,
                           float target_h,
                           float step_real_time,
                           float decay_heat,
                           float plant_mode)
{
    print_csv_value(t); xil_printf(",");
    print_csv_value(n); xil_printf(",");
    print_csv_value(Tf); xil_printf(",");
    print_csv_value(rho); xil_printf(",");
    print_csv_value(dollars); xil_printf(",");
    print_csv_value(Tc); xil_printf(",");
    print_csv_value(I_Xe); xil_printf(",");
    print_csv_value(Xe); xil_printf(",");
    print_csv_value(rho_Xe); xil_printf(",");
    print_csv_value(tc_factor); xil_printf(",");
    print_csv_value(rod_position); xil_printf(",");
    print_csv_value(rod_target); xil_printf(",");
    print_csv_value(engine_order); xil_printf(",");
    print_precise_csv_value(target_h); xil_printf(",");
    print_precise_csv_value(step_real_time); xil_printf(",");
    print_csv_value(decay_heat); xil_printf(",");
    print_csv_value(plant_mode); xil_printf("\r\n");
}

static int steps_per_output(float h, float tc_factor)
{
    int steps = (int)(((WALL_OUTPUT_INTERVAL * tc_factor) / h) + 0.5f);
    if (steps < 1) {
        return 1;
    }
    if (steps > MAX_SUBSTEPS) {
        return MAX_SUBSTEPS;
    }
    return steps;
}

static void set_time_factor(AppState *state, float factor, float mode_h)
{
    if (!finite_float(factor) || factor < 1.0f) {
        factor = 1.0f;
    }

    if (mode_h <= 0.0f) {
        mode_h = MODE_REALTIME_H * factor;
    }
    if (mode_h > MODE_XENON_H) {
        mode_h = MODE_XENON_H;
    }

    state->h = mode_h;
    state->substeps = steps_per_output(state->h, factor);
    state->tc_factor =
        ((float)state->substeps * state->h) / WALL_OUTPUT_INTERVAL;
}

static void apply_command(const char *cmd, AppState *state)
{
    float value = 0.0f;
    char ch = cmd[0];

    if (ch == '+') {
        state->withdraw_pulse = 1;
    } else if (ch == '-') {
        state->insert_pulse = 1;
    } else if ((ch == 'R') || (ch == 'r')) {
        state->scram_pulse = 1;
    } else if ((ch == 'W') || (ch == 'w')) {
        if (parse_float_arg(cmd + 1, &value) && finite_float(value)) {
            state->rod_target = clamp_float(value, 0.0f, 1.0f);
            state->set_rod_target = 1;
        }
    } else if ((ch == 'P') || (ch == 'p')) {
        if (parse_float_arg(cmd + 1, &value) && finite_float(value) &&
            (value >= 0.0f)) {
            state->reset_power = clamp_float(value, 0.0f, 1.5f);
            state->reset = 1;
        }
    } else if ((ch == 'C') || (ch == 'c')) {
        char digit = cmd[1];
        if ((digit >= '0') && (digit <= '2')) {
            state->plant_mode = digit - '0';
            state->reset_power = 1.0f;
            state->plant_update = 1;
        }
    } else if ((ch == 'M') || (ch == 'm')) {
        switch (cmd[1]) {
            case '0':
                set_time_factor(state, 1.0f, MODE_REALTIME_H);
                break;
            case '1':
                set_time_factor(state, 10.0f, MODE_TRAINING_H);
                break;
            case '2':
                set_time_factor(state, 1000.0f, MODE_XENON_H);
                break;
            default:
                return;
        }
    } else if ((ch == 'T') || (ch == 't')) {
        if (parse_float_arg(cmd + 1, &value) && finite_float(value) &&
            (value >= 1.0f)) {
            set_time_factor(state, value, 0.0f);
        }
    }
}

static void poll_uart_commands(AppState *state)
{
    static char cmd[32];
    static int cmd_len = 0;

    while (XUartPs_IsReceiveData(UART_BASEADDR)) {
        char ch = (char)XUartPs_ReadReg(UART_BASEADDR, XUARTPS_FIFO_OFFSET);

        if ((ch == '\r') || (ch == '\n')) {
            if (cmd_len > 0) {
                cmd[cmd_len] = '\0';
                apply_command(cmd, state);
                cmd_len = 0;
            }
        } else if (cmd_len < ((int)sizeof(cmd) - 1)) {
            cmd[cmd_len++] = ch;
        } else {
            cmd_len = 0;
        }
    }
}

static float elapsed_seconds(XTime start, XTime end)
{
    return (float)(end - start) / (float)COUNTS_PER_SECOND;
}

int main()
{
    Xil_Out32(0xF8000008, 0xDF0D);
    Xil_Out32(0xF8000900, 0x0000000F);
    Xil_Out32(0xF8000240, 0x00000000);
    Xil_Out32(0xF8000004, 0x767B);

    XGpio gpio;
    XGpio_Initialize(&gpio, GPIO_BASEADDR);
    XGpio_SetDataDirection(&gpio, GPIO_CHANNEL, 0xFF);

    AppState state;
    state.reset_power = 1.0f;
    state.reset = 1;
    state.withdraw_pulse = 0;
    state.insert_pulse = 0;
    state.scram_pulse = 0;
    state.set_rod_target = 0;
    state.rod_target = 0.0f;
    state.plant_mode = 0;
    state.plant_update = 0;
    set_time_factor(&state, 1.0f, MODE_REALTIME_H);

    u32 prev_sw = XGpio_DiscreteRead(&gpio, GPIO_CHANNEL);

    xil_printf("\r\nDATA_START\r\n");

    while (1) {
        XTime start_time;
        XTime end_time;
        XTime frame_end_time;

        poll_uart_commands(&state);

        u32 sw = XGpio_DiscreteRead(&gpio, GPIO_CHANNEL);
        u32 sw_rise = sw & ~prev_sw;
        prev_sw = sw;

        float withdraw = (((sw_rise & SW_WITHDRAW) != 0u) || state.withdraw_pulse) ? 1.0f : 0.0f;
        float insert = (((sw_rise & SW_INSERT) != 0u) || state.insert_pulse) ? 1.0f : 0.0f;
        float scram = (((sw_rise & SW_SCRAM) != 0u) || state.scram_pulse) ? 1.0f : 0.0f;

        pk_write_float(PK_H, state.h);
        pk_write_int(PK_SUBSTEPS, state.substeps);
        pk_write_float(PK_TC_FACTOR, state.tc_factor);
        pk_write_float(PK_RESET, state.reset ? 1.0f : 0.0f);
        pk_write_float(PK_RESET_POWER, state.reset_power);
        pk_write_float(PK_WITHDRAW, withdraw);
        pk_write_float(PK_INSERT, insert);
        pk_write_float(PK_SCRAM, scram);
        pk_write_float(PK_SET_ROD_TGT, state.set_rod_target ? 1.0f : 0.0f);
        pk_write_float(PK_ROD_TGT_CMD, state.rod_target);
        pk_write_int(PK_PLANT_MODE, state.plant_mode);
        pk_write_float(PK_PLANT_UPD, state.plant_update ? 1.0f : 0.0f);

        XTime_GetTime(&start_time);
        pk_start_and_wait();
        XTime_GetTime(&end_time);

        float t = pk_read_float(PK_T_OUT);
        float n = pk_read_float(PK_N_OUT);
        float Tf = pk_read_float(PK_TF_OUT);
        float Tc = pk_read_float(PK_TC_OUT);
        float I_Xe = pk_read_float(PK_I_XE_OUT);
        float Xe = pk_read_float(PK_XE_OUT);
        float rho = pk_read_float(PK_RHO_OUT);
        float dollars = pk_read_float(PK_DOLLARS_OUT);
        float rho_Xe = pk_read_float(PK_RHO_XE_OUT);
        float rod_position = pk_read_float(PK_ROD_POS_OUT);
        float rod_target = pk_read_float(PK_ROD_TGT_OUT);
        float tc_factor_out = pk_read_float(PK_TC_FACT_OUT);
        float engine_order = pk_read_float(PK_ENGINE_OUT);
        float target_h = pk_read_float(PK_TARGET_H_OUT);
        float decay_heat = pk_read_float(PK_DECAY_OUT);
        float plant_mode = pk_read_float(PK_PLANT_OUT);
        float step_real_time = elapsed_seconds(start_time, end_time) / (float)state.substeps;

        print_data_row(t, n, Tf, rho, dollars, Tc, I_Xe, Xe,
                       rho_Xe, tc_factor_out, rod_position, rod_target,
                       engine_order, target_h, step_real_time,
                       decay_heat, plant_mode);

        state.reset = 0;
        state.withdraw_pulse = 0;
        state.insert_pulse = 0;
        state.scram_pulse = 0;
        state.set_rod_target = 0;
        state.plant_update = 0;

        XTime_GetTime(&frame_end_time);
        float frame_elapsed = elapsed_seconds(start_time, frame_end_time);
        if (frame_elapsed < WALL_OUTPUT_INTERVAL) {
            usleep((unsigned int)((WALL_OUTPUT_INTERVAL - frame_elapsed) * 1000000.0f));
        }
    }

    return 0;
}
