#include "xparameters.h"
#include "xil_printf.h"
#include "xgpio.h"
#include "xil_io.h"
#include "xpoint_kinetics_step_hw.h"
#include "xuartps_hw.h"
#include "xiltimer.h"
#include "xtimer_config.h"
#include "sleep.h"

#include "../../../common/point_kinetics_config.h"

#define GPIO_BASEADDR   XPAR_AXI_GPIO_0_BASEADDR
#define GPIO_CHANNEL    1
#define UART_BASEADDR   XPAR_UART1_BASEADDR

#define SW_WITHDRAW     0x01u
#define SW_INSERT       0x02u
#define SW_SCRAM        0x80u

#define PK_BASEADDR     XPAR_POINT_KINETICS_STEP_0_BASEADDR

#define PK_AP_CTRL      XPOINT_KINETICS_STEP_CTRL_ADDR_AP_CTRL
#define PK_H            XPOINT_KINETICS_STEP_CTRL_ADDR_H_DATA
#define PK_SUBSTEPS     XPOINT_KINETICS_STEP_CTRL_ADDR_SUBSTEPS_DATA
#define PK_TC_FACTOR    XPOINT_KINETICS_STEP_CTRL_ADDR_TC_FACTOR_DATA
#define PK_RESET        XPOINT_KINETICS_STEP_CTRL_ADDR_RESET_CMD_DATA
#define PK_RESET_POWER  XPOINT_KINETICS_STEP_CTRL_ADDR_RESET_POWER_DATA
#define PK_WITHDRAW     XPOINT_KINETICS_STEP_CTRL_ADDR_WITHDRAW_CMD_DATA
#define PK_INSERT       XPOINT_KINETICS_STEP_CTRL_ADDR_INSERT_CMD_DATA
#define PK_SCRAM        XPOINT_KINETICS_STEP_CTRL_ADDR_SCRAM_CMD_DATA

#define PK_T_OUT        XPOINT_KINETICS_STEP_CTRL_ADDR_T_OUT_DATA
#define PK_N_OUT        XPOINT_KINETICS_STEP_CTRL_ADDR_N_OUT_DATA
#define PK_TF_OUT       XPOINT_KINETICS_STEP_CTRL_ADDR_TF_OUT_DATA
#define PK_TC_OUT       XPOINT_KINETICS_STEP_CTRL_ADDR_TC_OUT_DATA
#define PK_I_XE_OUT     XPOINT_KINETICS_STEP_CTRL_ADDR_I_XE_OUT_DATA
#define PK_XE_OUT       XPOINT_KINETICS_STEP_CTRL_ADDR_XE_OUT_DATA
#define PK_RHO_OUT      XPOINT_KINETICS_STEP_CTRL_ADDR_RHO_OUT_DATA
#define PK_DOLLARS_OUT  XPOINT_KINETICS_STEP_CTRL_ADDR_DOLLARS_OUT_DATA
#define PK_RHO_XE_OUT   XPOINT_KINETICS_STEP_CTRL_ADDR_RHO_XE_OUT_DATA
#define PK_ROD_POS_OUT  XPOINT_KINETICS_STEP_CTRL_ADDR_ROD_POSITION_OUT_DATA
#define PK_ROD_TGT_OUT  XPOINT_KINETICS_STEP_CTRL_ADDR_ROD_TARGET_OUT_DATA
#define PK_TC_FACT_OUT  XPOINT_KINETICS_STEP_CTRL_ADDR_TC_FACTOR_OUT_DATA
#define PK_ENGINE_OUT   XPOINT_KINETICS_STEP_CTRL_ADDR_ENGINE_ORDER_OUT_DATA

#define PK_SET_ROD_TGT  XPOINT_KINETICS_STEP_CTRL_ADDR_SET_ROD_TARGET_CMD_DATA
#define PK_ROD_TGT_CMD  XPOINT_KINETICS_STEP_CTRL_ADDR_ROD_TARGET_CMD_DATA
#define PK_PLANT_MODE   XPOINT_KINETICS_STEP_CTRL_ADDR_PLANT_MODE_CMD_DATA
#define PK_PLANT_UPD    XPOINT_KINETICS_STEP_CTRL_ADDR_PLANT_MODE_UPDATE_CMD_DATA
#define PK_TARGET_H_OUT XPOINT_KINETICS_STEP_CTRL_ADDR_TARGET_H_OUT_DATA
#define PK_DECAY_OUT    XPOINT_KINETICS_STEP_CTRL_ADDR_DECAY_HEAT_OUT_DATA
#define PK_PLANT_OUT    XPOINT_KINETICS_STEP_CTRL_ADDR_PLANT_MODE_OUT_DATA
#define PK_CLEAR_SCRAM  XPOINT_KINETICS_STEP_CTRL_ADDR_CLEAR_SCRAM_CMD_DATA
#define PK_SCRAM_ACTIVE XPOINT_KINETICS_STEP_CTRL_ADDR_SCRAM_ACTIVE_OUT_DATA

#define MODE_REALTIME_H      PK_BASE_H
#define MODE_TRAINING_H     (PK_BASE_H * 10.0f)
#define MODE_XENON_H         PK_MAX_H
#define WALL_OUTPUT_INTERVAL PK_WALL_OUTPUT_INTERVAL
#define MAX_SUBSTEPS         PK_MAX_SUBSTEPS

typedef struct {
    float h;
    float tc_factor;
    float reported_factor;
    float reset_power;
    int substeps;
    int reset;
    int withdraw_pulse;
    int insert_pulse;
    int scram_pulse;
    int clear_scram_pulse;
    int set_rod_target;
    float rod_target;
    int plant_mode;
    int plant_update;
    float tf_ref;
    float tc_ref;
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

static float plant_alpha_f(int mode)
{
    if (mode == 1) return PK_MODE1_ALPHA_F;
    if (mode == 2) return PK_MODE2_ALPHA_F;
    return PK_MODE0_ALPHA_F;
}

static float plant_alpha_c(int mode)
{
    if (mode == 1) return PK_MODE1_ALPHA_C;
    if (mode == 2) return PK_MODE2_ALPHA_C;
    return PK_MODE0_ALPHA_C;
}

static float plant_rod_min(int mode)
{
    if (mode == 1) return PK_MODE1_RHO_ROD_MIN;
    if (mode == 2) return PK_MODE2_RHO_ROD_MIN;
    return PK_MODE0_RHO_ROD_MIN;
}

static float plant_rod_max(int mode)
{
    if (mode == 1) return PK_MODE1_RHO_ROD_MAX;
    if (mode == 2) return PK_MODE2_RHO_ROD_MAX;
    return PK_MODE0_RHO_ROD_MAX;
}

static void set_reference_temperatures(AppState *state)
{
    state->tc_ref = PK_TM_CONST +
        (PK_K_HEAT * state->reset_power) / PK_GAMMA_C_INITIAL;
    state->tf_ref = state->tc_ref +
        (PK_K_HEAT * state->reset_power) / PK_FUEL_COUPLING;
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
                           float plant_mode,
                           float rho_rod_dlr,
                           float rho_fuel_dlr,
                           float rho_coolant_dlr,
                           float rho_xenon_dlr,
                           float rod_critical,
                           float scram_active)
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
    print_csv_value(plant_mode); xil_printf(",");
    print_csv_value(rho_rod_dlr); xil_printf(",");
    print_csv_value(rho_fuel_dlr); xil_printf(",");
    print_csv_value(rho_coolant_dlr); xil_printf(",");
    print_csv_value(rho_xenon_dlr); xil_printf(",");
    print_csv_value(rod_critical); xil_printf(",");
    print_csv_value(scram_active); xil_printf("\r\n");
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
    if (mode_h < MODE_REALTIME_H) {
        mode_h = MODE_REALTIME_H;
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
    } else if ((ch == 'K') || (ch == 'k')) {
        state->clear_scram_pulse = 1;
    } else if ((ch == 'W') || (ch == 'w')) {
        if (parse_float_arg(cmd + 1, &value) && finite_float(value)) {
            state->rod_target = clamp_float(value, 0.0f, 1.0f);
            state->set_rod_target = 1;
        }
    } else if ((ch == 'P') || (ch == 'p')) {
        if (parse_float_arg(cmd + 1, &value) && finite_float(value) &&
            (value >= 0.0f)) {
            state->reset_power = clamp_float(value, 0.0f, 1.5f);
            set_reference_temperatures(state);
            state->reset = 1;
        }
    } else if ((ch == 'C') || (ch == 'c')) {
        char digit = cmd[1];
        if ((digit >= '0') && (digit <= '2')) {
            state->plant_mode = digit - '0';
            state->reset_power = 1.0f;
            set_reference_temperatures(state);
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
    state.clear_scram_pulse = 0;
    state.set_rod_target = 0;
    state.rod_target = 0.0f;
    state.plant_mode = 0;
    state.plant_update = 0;
    state.reported_factor = 1.0f;
    set_reference_temperatures(&state);
    set_time_factor(&state, 1.0f, MODE_REALTIME_H);

    u32 prev_sw = XGpio_DiscreteRead(&gpio, GPIO_CHANNEL);
    XTime previous_frame_start;
    int have_previous_frame = 0;
    XTime_GetTime(&previous_frame_start);

    xil_printf("\r\nDATA_START\r\n");

    while (1) {
        XTime start_time;
        XTime end_time;
        XTime frame_start_time;
        XTime frame_end_time;

        XTime_GetTime(&frame_start_time);
        {
            float measured_interval = WALL_OUTPUT_INTERVAL;
            if (have_previous_frame) {
                measured_interval =
                    elapsed_seconds(previous_frame_start, frame_start_time);
            }
            have_previous_frame = 1;
            if (measured_interval > 0.0f) {
                state.reported_factor =
                    ((float)state.substeps * state.h) / measured_interval;
            }
            previous_frame_start = frame_start_time;
        }
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
        pk_write_float(PK_CLEAR_SCRAM, state.clear_scram_pulse ? 1.0f : 0.0f);
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
        float scram_active = pk_read_float(PK_SCRAM_ACTIVE);
        float step_real_time = elapsed_seconds(start_time, end_time) / (float)state.substeps;
        int active_mode = (int)plant_mode;
        float beta = PK_BETA_TOTAL;
        float rho_rod_min = plant_rod_min(active_mode);
        float rho_rod_max = plant_rod_max(active_mode);
        float rho_rod = rho_rod_min +
            rod_position * (rho_rod_max - rho_rod_min);
        float rho_fuel = plant_alpha_f(active_mode) * (Tf - state.tf_ref);
        float rho_coolant = plant_alpha_c(active_mode) * (Tc - state.tc_ref);
        float critical_numerator =
            -rho_fuel - rho_coolant - rho_Xe - rho_rod_min;
        float rod_critical = clamp_float(
            critical_numerator / (rho_rod_max - rho_rod_min),
            0.0f, 1.0f);
        tc_factor_out = state.reported_factor;

        print_data_row(t, n, Tf, rho, dollars, Tc, I_Xe, Xe,
                       rho_Xe, tc_factor_out, rod_position, rod_target,
                       engine_order, target_h, step_real_time,
                       decay_heat, plant_mode,
                       rho_rod / beta, rho_fuel / beta,
                       rho_coolant / beta, rho_Xe / beta,
                       rod_critical, scram_active);

        state.reset = 0;
        state.withdraw_pulse = 0;
        state.insert_pulse = 0;
        state.scram_pulse = 0;
        state.clear_scram_pulse = 0;
        state.set_rod_target = 0;
        state.plant_update = 0;

        XTime_GetTime(&frame_end_time);
        float frame_elapsed =
            elapsed_seconds(frame_start_time, frame_end_time);
        if (frame_elapsed < WALL_OUTPUT_INTERVAL) {
            usleep((unsigned int)((WALL_OUTPUT_INTERVAL - frame_elapsed) * 1000000.0f));
        }
    }

    return 0;
}
