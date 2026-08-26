#ifndef POINT_KINETICS_CORE_H
#define POINT_KINETICS_CORE_H

/* Shared reactor physics used by the PC simulator and the FPGA HLS IP.
 *
 * What this model tracks each step:
 *   n          neutron power (normalized, 1.0 = full power)
 *   C[6]       delayed-neutron precursor groups
 *   Tf, Tc     fuel and coolant temperatures (C)
 *   I_Xe, Xe   iodine / xenon (normalized to full-power equilibrium)
 *   decay_heat residual heat after fission drops
 *   rods       position 0 = fully inserted, 1 = fully withdrawn
 *   source_q   external neutron source, zero until commanded
 *
 * How time advances:
 *   step()    one physics substep (kinetics + heat + rods)
 *   advance() many substeps, then one batched poison update
 */

#include <cmath>

#include "point_kinetics_config.h"

namespace pk {

static const int PRECURSOR_GROUPS = 6;
static const int DECAY_GROUPS = 3;
static const int PLANT_MODES = 3;
static const int MAX_SUBSTEPS = PK_MAX_SUBSTEPS;

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

inline float clamp(float value, float low, float high) {
    return value < low ? low : (value > high ? high : value);
}

inline int clamp(int value, int low, int high) {
    return value < low ? low : (value > high ? high : value);
}

inline bool finite(float value) {
    return std::isfinite(value);
}

// Accurate 1 - exp(-x) for small x (avoids float cancellation).
inline float stable_one_minus_exp_negative(float exponent) {
    if (!finite(exponent) || exponent < 0.0f) {
        return 0.0f;
    }
    if (exponent < 1.0e-3f) {
        const float x2 = exponent * exponent;
        return exponent - 0.5f * x2 + (x2 * exponent) / 6.0f;
    }
    return 1.0f - expf(-exponent);
}

// Kahan sum: keeps long runs of tiny float adds from drifting.
inline void compensated_add(float increment, float& value, float& compensation) {
    const float adjusted = increment - compensation;
    const float next = value + adjusted;
    compensation = (next - value) - adjusted;
    value = next;
}

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------

struct TimePolicy {
    static float base_h() { return PK_BASE_H; }  // 1e-4 s realtime step
    static float max_h() { return PK_MAX_H; }    // 2e-3 s stability limit

    static float step_for_factor(float factor) {
        if (!finite(factor) || factor < 1.0f) {
            factor = 1.0f;
        }
        return clamp(base_h() * factor, base_h(), max_h());
    }
};

// ---------------------------------------------------------------------------
// Fixed physics parameters (same for all plant modes)
// ---------------------------------------------------------------------------

struct ReactorParams {
    float Lambda;                         // prompt neutron generation time
    float beta_total;                     // total delayed-neutron fraction
    float lam_i[PRECURSOR_GROUPS];        // precursor decay constants
    float beta_i[PRECURSOR_GROUPS];       // precursor yields

    float gamma;                          // fuel <-> coolant coupling
    float K_heat;                         // power -> temperature gain
    float Tm_const;                       // cold coolant reference (C)

    float gamma_I;                        // iodine fission yield
    float gamma_Xe;                       // xenon fission yield
    float lambda_I;                       // iodine decay
    float lambda_Xe;                      // xenon decay
    float kXe_burnout;                    // xenon burnout rate
    float kFission;                       // fission-rate scale

    float decay_fraction[DECAY_GROUPS];   // share of power in each group
    float decay_lambda[DECAY_GROUPS];     // decay-group rates

    ReactorParams()
        : Lambda(0.00002f), beta_total(PK_BETA_TOTAL),
          // Two-node thermal model at N=1:
          //   Tc ≈ 265 + 10/0.357 ≈ 293 C
          //   Tf ≈ 293 + 10/0.04  ≈ 543 C
          gamma(PK_FUEL_COUPLING), K_heat(PK_K_HEAT), Tm_const(PK_TM_CONST), gamma_I(0.061f), gamma_Xe(0.003f), lambda_I(2.87e-5f), lambda_Xe(2.09e-5f), kXe_burnout(5.0e-5f), kFission(1.0e4f) {
        const float lam[PRECURSOR_GROUPS] = {
            0.0127f, 0.0317f, 0.155f, 0.311f, 1.4f, 3.87f
        };
        const float beta[PRECURSOR_GROUPS] = {
            0.000266f, 0.001491f, 0.001316f, 0.002849f, 0.000896f, 0.000182f
        };
        // Three groups sum to 0.066 → 6.6% decay heat at full power.
        const float fractions[DECAY_GROUPS] = {
            PK_DECAY_FRACTION_0, PK_DECAY_FRACTION_1, PK_DECAY_FRACTION_2
        };
        const float lambdas[DECAY_GROUPS] = {
            PK_DECAY_LAMBDA_0, PK_DECAY_LAMBDA_1, PK_DECAY_LAMBDA_2
        };

        for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
            lam_i[i] = lam[i];
            beta_i[i] = beta[i];
        }
        for (int i = 0; i < DECAY_GROUPS; ++i) {
            decay_fraction[i] = fractions[i];
            decay_lambda[i] = lambdas[i];
        }
    }

    float total_decay_fraction() const {
        float sum = 0.0f;
        for (int i = 0; i < DECAY_GROUPS; ++i) {
            sum += decay_fraction[i];
        }
        return sum;
    }
};

// ---------------------------------------------------------------------------
// Plant mode: feedback signs and rod worth (educational presets)
// ---------------------------------------------------------------------------

struct PlantConfig {
    float alpha_f;          // fuel temperature feedback (1/C)
    float alpha_c;          // coolant temperature feedback (1/C)
    float gamma_c_init;     // coolant removal used only at reset
    float gamma_c_active;   // coolant removal during the run
    float rho_rod_min;      // reactivity at rod_position = 0
    float rho_rod_max;      // reactivity at rod_position = 1
    float kXe_worth;        // xenon reactivity scale
};

inline PlantConfig plant_config(int mode) {
    PlantConfig cfg;
    const int selected = clamp(mode, 0, PLANT_MODES - 1);

    if (selected == 0) {
        // Mode 0: PWR-SMR-like, negative feedback, passive-safe baseline.
        cfg.alpha_f = PK_MODE0_ALPHA_F;
        cfg.alpha_c = PK_MODE0_ALPHA_C;
        cfg.gamma_c_init = PK_GAMMA_C_INITIAL;
        cfg.gamma_c_active = PK_MODE0_GAMMA_C;
        cfg.rho_rod_min = PK_MODE0_RHO_ROD_MIN;
        cfg.rho_rod_max = PK_MODE0_RHO_ROD_MAX;
    } else if (selected == 1) {
        // Mode 1: RBMK-like contrast (positive coolant feedback). Not a real plant.
        cfg.alpha_f = PK_MODE1_ALPHA_F;
        cfg.alpha_c = PK_MODE1_ALPHA_C;
        cfg.gamma_c_init = PK_GAMMA_C_INITIAL;
        cfg.gamma_c_active = PK_MODE1_GAMMA_C;
        cfg.rho_rod_min = PK_MODE1_RHO_ROD_MIN;
        cfg.rho_rod_max = PK_MODE1_RHO_ROD_MAX;
    } else {
        // Mode 2: loss-of-cooling demo (weak heat removal).
        cfg.alpha_f = PK_MODE2_ALPHA_F;
        cfg.alpha_c = PK_MODE2_ALPHA_C;
        cfg.gamma_c_init = PK_GAMMA_C_INITIAL;
        cfg.gamma_c_active = PK_MODE2_GAMMA_C;
        cfg.rho_rod_min = PK_MODE2_RHO_ROD_MIN;
        cfg.rho_rod_max = PK_MODE2_RHO_ROD_MAX;
    }

    cfg.kXe_worth = PK_XENON_WORTH;
    return cfg;
}

// ---------------------------------------------------------------------------
// Live reactor state
// ---------------------------------------------------------------------------

struct ReactorState {
    float t;
    float t_compensation;
    float n;
    float C[PRECURSOR_GROUPS];
    float C_compensation[PRECURSOR_GROUPS];
    float I_Xe;
    float Xe;
    float I_compensation;
    float Xe_compensation;

    float Tf;
    float Tc;
    float Tf_compensation;
    float Tc_compensation;
    float Tf_ref;             // temperatures at last reset (feedback zero point)
    float Tc_ref;

    float decay_group[DECAY_GROUPS];
    float decay_compensation[DECAY_GROUPS];
    float decay_heat;
    float rod_position;       // 0 = in, 1 = out
    float rod_target;
    float rod_motion_residual;
    float source_q;           // external neutron source (operator command)
    int plant_mode;
    bool scram_active;
    bool numerical_fault;
};

// ---------------------------------------------------------------------------
// Reactivity pieces (rho). Dollars = rho / beta_total.
// ---------------------------------------------------------------------------

// Integral rod worth shape: differential worth is zero at both travel ends
// and peaks mid-bank, so rho(x) = min + span * (x - sin(2*pi*x)/(2*pi)).
inline float rod_worth_fraction(float position) {
    const float x = clamp(position, 0.0f, 1.0f);
    return x - sinf(6.2831853f * x) / 6.2831853f;
}

inline float rod_rho(float position, const PlantConfig& cfg) {
    return cfg.rho_rod_min + rod_worth_fraction(position) * (cfg.rho_rod_max - cfg.rho_rod_min);
}

inline float rod_rho(const ReactorState& state, const PlantConfig& cfg) {
    return rod_rho(state.rod_position, cfg);
}

inline float fuel_rho(const ReactorState& state, const PlantConfig& cfg) {
    return cfg.alpha_f * (state.Tf - state.Tf_ref);
}

inline float coolant_rho(const ReactorState& state, const PlantConfig& cfg) {
    return cfg.alpha_c * (state.Tc - state.Tc_ref);
}

inline float xenon_rho(const ReactorState& state, const PlantConfig& cfg) {
    return cfg.kXe_worth * (state.Xe - 1.0f);
}

inline float total_rho(const ReactorState& state, const PlantConfig& cfg) {
    float rho = rod_rho(state, cfg) + fuel_rho(state, cfg) + coolant_rho(state, cfg) + xenon_rho(state, cfg);
    if (state.scram_active) {
        rho += PK_SCRAM_EXTRA_RHO;
    }
    return rho;
}

// Rod position whose worth equals the target reactivity (bisection; the
// S-curve is strictly increasing, and out-of-range targets clamp to 0/1).
inline float rod_position_for_rho(float target, const PlantConfig& cfg) {
    float lo = 0.0f;
    float hi = 1.0f;
    for (int i = 0; i < 32; ++i) {
        const float mid = 0.5f * (lo + hi);
        if (rod_rho(mid, cfg) < target) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return 0.5f * (lo + hi);
}

// Rod position that would make total rho ≈ 0 at the current temperatures/xenon.
inline float critical_rod_position(const ReactorState& state, const PlantConfig& cfg) {
    const float needed = -fuel_rho(state, cfg) - coolant_rho(state, cfg) - xenon_rho(state, cfg);
    return rod_position_for_rho(needed, cfg);
}

inline float iodine_ref(const ReactorParams& params) {
    return (params.gamma_I * params.kFission) / params.lambda_I;
}

inline float xenon_ref(const ReactorParams& params, float I_ref) {
    return (params.gamma_Xe * params.kFission + params.lambda_I * I_ref) / (params.lambda_Xe + params.kXe_burnout);
}

// ---------------------------------------------------------------------------
// Iodine / xenon: one update per output frame (uses average power)
// ---------------------------------------------------------------------------

inline bool update_poison_batched(float N_avg, float poison_dt, const ReactorParams& params, float& I_norm, float& Xe_norm, float& I_compensation, float& Xe_compensation) {
    bool fault = !finite(N_avg) || !finite(poison_dt) || poison_dt < 0.0f;
    const float I_ref = iodine_ref(params);
    const float Xe_ref = xenon_ref(params, I_ref);

    // Iodine equilibrium (normalized) tracks average power.
    const float I_factor = stable_one_minus_exp_negative(params.lambda_I * poison_dt);
    compensated_add((N_avg - I_norm) * I_factor, I_norm, I_compensation);

    // Xenon: production from fission + iodine decay, loss from decay + burnout.
    const float Xe_source = params.gamma_Xe * params.kFission * N_avg + params.lambda_I * I_ref * I_norm;
    const float Xe_sink = params.lambda_Xe + params.kXe_burnout * N_avg;
    const float Xe_eq_norm = (Xe_source / Xe_sink) / Xe_ref;
    const float Xe_factor = stable_one_minus_exp_negative(Xe_sink * poison_dt);
    compensated_add((Xe_eq_norm - Xe_norm) * Xe_factor, Xe_norm, Xe_compensation);

    if (!finite(I_norm) || I_norm < 0.0f) {
        fault = true;
        I_norm = 0.0f;
        I_compensation = 0.0f;
    }
    if (!finite(Xe_norm) || Xe_norm < 0.0f) {
        fault = true;
        Xe_norm = 0.0f;
        Xe_compensation = 0.0f;
    }
    return fault;
}

// ---------------------------------------------------------------------------
// Reset / SCRAM / rod commands
// ---------------------------------------------------------------------------

inline void reset(ReactorState& state, const ReactorParams& params, float power_fraction, int plant_mode) {
    if (!finite(power_fraction)) {
        power_fraction = 1.0f;
    }
    power_fraction = clamp(power_fraction, 0.0f, 1.5f);
    state.plant_mode = clamp(plant_mode, 0, PLANT_MODES - 1);
    const PlantConfig cfg = plant_config(state.plant_mode);

    state.t = 0.0f;
    state.t_compensation = 0.0f;
    state.n = power_fraction;

    // Precursors at equilibrium for this power.
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        state.C[i] = (params.beta_i[i] * state.n) / (params.lam_i[i] * params.Lambda);
        state.C_compensation[i] = 0.0f;
    }

    // Steady temperatures for this power (using init coolant removal).
    state.Tc = params.Tm_const + (params.K_heat * state.n) / cfg.gamma_c_init;
    state.Tc_ref = state.Tc;
    state.Tf = state.Tc + (params.K_heat * state.n) / params.gamma;
    state.Tf_ref = state.Tf;
    state.Tf_compensation = 0.0f;
    state.Tc_compensation = 0.0f;

    // Poisons at equilibrium for this power.
    const float I_ref = iodine_ref(params);
    const float Xe_ref = xenon_ref(params, I_ref);
    const float Xe_source = params.gamma_Xe * params.kFission * power_fraction + params.lambda_I * I_ref * power_fraction;
    const float Xe_sink = params.lambda_Xe + params.kXe_burnout * power_fraction;
    state.I_Xe = power_fraction;
    state.Xe = (Xe_source / Xe_sink) / Xe_ref;
    state.I_compensation = 0.0f;
    state.Xe_compensation = 0.0f;

    // Critical rods: cancel xenon so rho starts at ~0 (temps are at ref).
    const float rho_xe = xenon_rho(state, cfg);
    state.rod_position = rod_position_for_rho(-rho_xe, cfg);
    state.rod_target = state.rod_position;
    state.rod_motion_residual = 0.0f;
    state.source_q = 0.0f;

    state.decay_heat = 0.0f;
    for (int i = 0; i < DECAY_GROUPS; ++i) {
        state.decay_group[i] = params.decay_fraction[i] * state.n;
        state.decay_compensation[i] = 0.0f;
        state.decay_heat += state.decay_group[i];
    }

    state.scram_active = false;
    state.numerical_fault = false;
}

inline void scram(ReactorState& state) {
    state.rod_position = 0.0f;
    state.rod_target = 0.0f;
    state.rod_motion_residual = 0.0f;
    state.scram_active = true;
}

inline void latch_numerical_fault(ReactorState& state) {
    state.numerical_fault = true;
    scram(state);
}

inline void reset_scram_trip(ReactorState& state) {
    // Numerical trips stay latched until a full reset.
    if (state.numerical_fault) {
        return;
    }
    state.scram_active = false;
}

inline void set_rod_target(ReactorState& state, float target) {
    if (state.scram_active) {
        return;
    }
    if (finite(target)) {
        state.rod_target = clamp(target, 0.0f, 1.0f);
    }
}

// ---------------------------------------------------------------------------
// One physics substep
// ---------------------------------------------------------------------------

inline void move_rods(ReactorState& state, float h) {
    // Full travel (0→1) takes 100 simulated seconds at rod_speed = 0.01.
    const float rod_speed = 0.01f;
    const float rod_delta = state.rod_target - state.rod_position;
    if (rod_delta == 0.0f) {
        state.rod_motion_residual = 0.0f;
        return;
    }

    const float direction = rod_delta > 0.0f ? 1.0f : -1.0f;
    const float magnitude = rod_delta > 0.0f ? rod_delta : -rod_delta;
    state.rod_motion_residual += rod_speed * h;

    // Accumulate tiny moves so float steps still reach the target.
    if (state.rod_motion_residual >= 1.0e-7f || state.rod_motion_residual >= magnitude) {
        const float move = state.rod_motion_residual < magnitude
                               ? state.rod_motion_residual
                               : magnitude;
        state.rod_position = clamp(state.rod_position + direction * move, 0.0f, 1.0f);
        state.rod_motion_residual -= move;
    }
}

inline void step(ReactorState& state, const ReactorParams& params, float h) {
    if (!finite(h) || h <= 0.0f) {
        h = TimePolicy::base_h();
    }
    h = clamp(h, TimePolicy::base_h(), TimePolicy::max_h());
    const PlantConfig cfg = plant_config(state.plant_mode);

    move_rods(state, h);

    float rho = total_rho(state, cfg);
    float sum_lam_C = 0.0f;
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        sum_lam_C += params.lam_i[i] * state.C[i];
    }

    // Semi-implicit (backward Euler) neutron update.
    // denom ≈ 0 means the step is unstable → trip and recompute under SCRAM.
    const float n_old = state.n;
    float n_denom = 1.0f - h * (rho - params.beta_total) / params.Lambda;
    if (!finite(n_denom) || n_denom <= 1.0e-6f) {
        latch_numerical_fault(state);
        rho = total_rho(state, cfg);
        n_denom = 1.0f - h * (rho - params.beta_total) / params.Lambda;
        if (!finite(n_denom) || n_denom <= 1.0e-6f) {
            n_denom = 1.0f;
        }
    }

    float dCdt[PRECURSOR_GROUPS];
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        dCdt[i] = (params.beta_i[i] / params.Lambda) * n_old - params.lam_i[i] * state.C[i];
    }

    // Decay heat keeps evolving after SCRAM (fission can be ~0).
    float next_decay_heat = 0.0f;
    for (int i = 0; i < DECAY_GROUPS; ++i) {
        const float derivative = params.decay_lambda[i] * (params.decay_fraction[i] * n_old - state.decay_group[i]);
        compensated_add(h * derivative, state.decay_group[i], state.decay_compensation[i]);
        if (state.decay_group[i] < 0.0f) {
            state.decay_group[i] = 0.0f;
        }
        next_decay_heat += state.decay_group[i];
    }
    state.decay_heat = next_decay_heat;

    // Thermal power = prompt fission share + decay heat.
    const float prompt_fraction = 1.0f - params.total_decay_fraction();
    const float thermal_power = prompt_fraction * n_old + state.decay_heat;
    const float dTfdt = params.K_heat * thermal_power - params.gamma * (state.Tf - state.Tc);
    const float dTcdt = params.gamma * (state.Tf - state.Tc) - cfg.gamma_c_active * (state.Tc - params.Tm_const);

    state.n = (n_old + h * (sum_lam_C + state.source_q)) / n_denom;
    compensated_add(h * dTfdt, state.Tf, state.Tf_compensation);
    compensated_add(h * dTcdt, state.Tc, state.Tc_compensation);
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        compensated_add(h * dCdt[i], state.C[i], state.C_compensation[i]);
    }

    bool state_fault = false;
    if (!finite(state.n) || state.n < 0.0f || state.n > 1.0e12f) {
        state.n = 0.0f;
        state_fault = true;
    }
    if (!finite(state.Tf)) {
        state.Tf = finite(state.Tf_ref) ? state.Tf_ref : params.Tm_const;
        state.Tf_compensation = 0.0f;
        state_fault = true;
    }
    if (!finite(state.Tc)) {
        state.Tc = finite(state.Tc_ref) ? state.Tc_ref : params.Tm_const;
        state.Tc_compensation = 0.0f;
        state_fault = true;
    }
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        if (!finite(state.C[i]) || state.C[i] < 0.0f) {
            state.C[i] = 0.0f;
            state.C_compensation[i] = 0.0f;
            state_fault = true;
        }
    }
    for (int i = 0; i < DECAY_GROUPS; ++i) {
        if (!finite(state.decay_group[i]) || state.decay_group[i] < 0.0f) {
            state.decay_group[i] = 0.0f;
            state.decay_compensation[i] = 0.0f;
            state_fault = true;
        }
    }
    if (!finite(state.decay_heat) || state.decay_heat < 0.0f) {
        state.decay_heat = 0.0f;
        state_fault = true;
    }
    compensated_add(h, state.t, state.t_compensation);
    if (!finite(state.t)) {
        state.t = 0.0f;
        state.t_compensation = 0.0f;
        state_fault = true;
    }
    if (state_fault) {
        latch_numerical_fault(state);
    }
}

inline int bounded_substeps(int requested) {
    return clamp(requested, 1, MAX_SUBSTEPS);
}

// Many substeps, then one poison update using average power.
inline void advance(ReactorState& state, const ReactorParams& params, float h, int requested_substeps) {
    if (!finite(h) || h <= 0.0f) {
        h = TimePolicy::base_h();
    }
    h = clamp(h, TimePolicy::base_h(), TimePolicy::max_h());
    const int count = bounded_substeps(requested_substeps);

    float n_sum = 0.0f;
    float n_sum_compensation = 0.0f;
    // Fixed trip count helps HLS; early break keeps PC cost proportional.
    for (int i = 0; i < MAX_SUBSTEPS; ++i) {
        if (i >= count) {
            break;
        }
        step(state, params, h);
        compensated_add(state.n, n_sum, n_sum_compensation);
    }

    const float poison_dt = h * (float)count;
    const float N_avg = n_sum / (float)count;
    if (update_poison_batched(N_avg, poison_dt, params, state.I_Xe, state.Xe, state.I_compensation, state.Xe_compensation)) {
        latch_numerical_fault(state);
    }
}

} // namespace pk

#endif
