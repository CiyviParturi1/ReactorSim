#ifndef POINT_KINETICS_CORE_H
#define POINT_KINETICS_CORE_H

#include <cmath>

namespace pk {

static const int PRECURSOR_GROUPS = 6;
static const int DECAY_GROUPS = 3;
static const int PLANT_MODES = 3;
static const int MAX_SUBSTEPS = 1000000;

inline float clamp(float value, float low, float high) {
    return value < low ? low : (value > high ? high : value);
}

inline int clamp(int value, int low, int high) {
    return value < low ? low : (value > high ? high : value);
}

inline bool finite(float value) {
    return std::isfinite(value);
}

struct TimePolicy {
    static float base_h() {
        // 1e-4 s = 10,000 physics steps/s at real time.
        // This matches the FPGA/ARM real-time target and avoids excessive
        // STDOUT/Matplotlib frame deadline misses.
        return 1.0e-4f;
    }

    static float max_h() {
        return 2.0e-3f;
    }

    static float step_for_factor(float factor) {
        if (!finite(factor) || factor < 1.0f) {
            factor = 1.0f;
        }
        return clamp(base_h() * factor, base_h(), max_h());
    }
};

struct ReactorParams {
    // Point kinetics.
    float Lambda;
    float beta_total;
    float Q;
    float lam_i[PRECURSOR_GROUPS];
    float beta_i[PRECURSOR_GROUPS];

    // Lumped fuel and coolant temperatures.
    float gamma;
    float K_heat;
    float Tm_const;

    // Iodine-135 and xenon-135.
    float gamma_I;
    float gamma_Xe;
    float lambda_I;
    float lambda_Xe;
    float kXe_burnout;
    float kFission;

    // Reduced decay-heat model.
    float decay_fraction[DECAY_GROUPS];
    float decay_lambda[DECAY_GROUPS];

        ReactorParams()
        : Lambda(0.00002f),
          beta_total(0.007f),
          Q(0.0f),

          // NuScale-like two-node thermal model.
          // N = 1.0 corresponds to 200 MWt.
          // Tc_eq = 265 + 10 / 0.357142857 ≈ 293 C
          // Tf_eq = 293 + 10 / 0.04 ≈ 543 C
          gamma(0.04f),
          K_heat(10.0f),
          Tm_const(265.0f),

          gamma_I(0.061f),
          gamma_Xe(0.003f),
          lambda_I(2.87e-5f),
          lambda_Xe(2.09e-5f),
          kXe_burnout(5.0e-5f),
          kFission(1.0e4f) {
        const float lam[PRECURSOR_GROUPS] = {
            0.0127f, 0.0317f, 0.155f, 0.311f, 1.4f, 3.87f
        };

        const float beta[PRECURSOR_GROUPS] = {
            0.000266f, 0.001491f, 0.001316f,
            0.002849f, 0.000896f, 0.000182f
        };

        // Reduced decay heat model.
        // Sum = 0.066, so steady full-power decay heat is 6.6%.
        const float fractions[DECAY_GROUPS] = {
            0.020f, 0.025f, 0.021f
        };

        const float lambdas[DECAY_GROUPS] = {
            0.069314718f, 0.006931472f, 0.000693147f
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

struct PlantConfig {
    float alpha_f;
    float alpha_c;
    float gamma_c_init;
    float gamma_c_active;
    float rho_rod_min;
    float rho_rod_max;
    float kXe_worth;
};

inline PlantConfig plant_config(int mode) {
    PlantConfig cfg;
    const int selected_mode = clamp(mode, 0, PLANT_MODES - 1);

    if (selected_mode == 0) {
        // ------------------------------------------------------------
        // Mode 0: NuScale-like PWR-SMR / passive-safe baseline
        // ------------------------------------------------------------
        cfg.alpha_f = -2.5e-5f;
        cfg.alpha_c = -1.0e-5f;

        // Stable NuScale-like coolant operating point:
        // Tc_eq ≈ 293 C at N = 1.
        cfg.gamma_c_init = 0.357142857f;
        cfg.gamma_c_active = 0.357142857f;

        // Rod worth:
        // critical rod position = 0.00735 / (0.00735 + 0.00245) = 0.75
        cfg.rho_rod_min = -0.00735f;  // -1.05 $
        cfg.rho_rod_max =  0.00245f;  // +0.35 $

    } else if (selected_mode == 1) {
        // ------------------------------------------------------------
        // Mode 1: RBMK-like educational contrast
        // Positive coolant coefficient + weaker Doppler feedback.
        // Not a real RBMK model; only a qualitative contrast case.
        // ------------------------------------------------------------
        cfg.alpha_f = -0.5e-5f;
        cfg.alpha_c =  1.5e-5f;

        // Keep initialization near the PWR-SMR temperature scale,
        // but reduce active heat removal so temperature feedback becomes visible.
        cfg.gamma_c_init = 0.357142857f;
        cfg.gamma_c_active = 0.25f;

        // Stronger rod worth for accident/instability demonstration.
        cfg.rho_rod_min = -0.120f;
        cfg.rho_rod_max =  0.009f;

    } else {
        // ------------------------------------------------------------
        // Mode 2: TMI-loss / loss-of-cooling educational scenario
        // Negative feedback remains, but heat removal is strongly degraded.
        // ------------------------------------------------------------
        cfg.alpha_f = -2.5e-5f;
        cfg.alpha_c = -1.0e-5f;

        // Initialize from normal PWR-SMR condition,
        // then simulate degraded heat removal after scenario selection.
        cfg.gamma_c_init = 0.357142857f;
        cfg.gamma_c_active = 0.02f;

        cfg.rho_rod_min = -0.00735f;  // -1.05 $
        cfg.rho_rod_max =  0.00245f;  // +0.35 $
    }

    cfg.kXe_worth = -0.020f;
    return cfg;
}

struct ReactorState {
    // Kinetics and poison state.
    float t;
    float n;
    float C[PRECURSOR_GROUPS];
    float I_Xe;
    float Xe;

    // Thermal state and equilibrium references.
    float Tf;
    float Tc;
    float Tf_ref;
    float Tc_ref;

    // Decay heat and control rods.
    float decay_group[DECAY_GROUPS];
    float decay_heat;
    float rod_position;
    float rod_target;
    float rod_motion_residual;
    int plant_mode;
    bool scram_occurred;
    bool scram_active;
    float t_scram;
};

inline float rod_rho(const ReactorState& state, const PlantConfig& cfg) {
    return cfg.rho_rod_min +
           state.rod_position * (cfg.rho_rod_max - cfg.rho_rod_min);
}

inline float xenon_rho(const ReactorState& state, const PlantConfig& cfg) {
    return cfg.kXe_worth * (state.Xe - 1.0f);
}

inline float total_rho(const ReactorState& state, const PlantConfig& cfg) {
    const float rho_rod = rod_rho(state, cfg);
    const float rho_fuel = cfg.alpha_f * (state.Tf - state.Tf_ref);
    const float rho_cool = cfg.alpha_c * (state.Tc - state.Tc_ref);
    const float rho_xe = xenon_rho(state, cfg);

    float rho_total = rho_rod + rho_fuel + rho_cool + rho_xe;

    if (state.scram_active) {
        const float rho_scram_extra = -0.07665f;  // about -10.95$
        rho_total += rho_scram_extra;
    }

    return rho_total;
}

inline void update_poison_batched(
    float N_avg,
    float poison_dt,
    const ReactorParams& params,
    float& I_norm,
    float& Xe_norm
) {
    // Reference equilibrium at N = 1.0
    const float I_ref = (params.gamma_I * params.kFission) / params.lambda_I;
    const float Xe_ref = (params.gamma_Xe * params.kFission + params.lambda_I * I_ref)
                         / (params.lambda_Xe + params.kXe_burnout);

    // Iodine normalized update
    float I_eq = N_avg;
    float I_factor = 1.0f - expf(-params.lambda_I * poison_dt);
    I_norm += (I_eq - I_norm) * I_factor;

    // Xenon normalized update
    float Xe_source = params.gamma_Xe * params.kFission * N_avg +
                      params.lambda_I * I_ref * I_norm;
    float Xe_sink = params.lambda_Xe + params.kXe_burnout * N_avg;

    float Xe_eq_norm = (Xe_source / Xe_sink) / Xe_ref;
    float Xe_factor = 1.0f - expf(-Xe_sink * poison_dt);

    Xe_norm += (Xe_eq_norm - Xe_norm) * Xe_factor;

    if (!finite(I_norm) || I_norm < 0.0f) {
        I_norm = 0.0f;
    }
    if (!finite(Xe_norm) || Xe_norm < 0.0f) {
        Xe_norm = 0.0f;
    }
}

inline void reset(ReactorState& state, const ReactorParams& params,
                  float power_fraction, int plant_mode) {
    if (!finite(power_fraction)) {
        power_fraction = 1.0f;
    }
    power_fraction = clamp(power_fraction, 0.0f, 1.5f);
    state.plant_mode = clamp(plant_mode, 0, PLANT_MODES - 1);
    const PlantConfig cfg = plant_config(state.plant_mode);

    state.t = 0.0f;
    state.n = power_fraction;
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        state.C[i] = (params.beta_i[i] * state.n) /
                     (params.lam_i[i] * params.Lambda);
    }

    state.Tc = params.Tm_const +
               (params.K_heat * state.n) / cfg.gamma_c_init;
    state.Tc_ref = state.Tc;
    state.Tf = state.Tc + (params.K_heat * state.n) / params.gamma;
    state.Tf_ref = state.Tf;

    const float I_ref = (params.gamma_I * params.kFission) / params.lambda_I;
    const float Xe_ref = (params.gamma_Xe * params.kFission + params.lambda_I * I_ref)
                         / (params.lambda_Xe + params.kXe_burnout);

    float Xe_source = params.gamma_Xe * params.kFission * power_fraction +
                      params.lambda_I * I_ref * power_fraction;
    float Xe_sink = params.lambda_Xe + params.kXe_burnout * power_fraction;

    state.I_Xe = power_fraction;
    state.Xe = (Xe_source / Xe_sink) / Xe_ref;

    // Calculate critical rod position to balance the Xenon reactivity and stay critical on reset
    const float rho_xe = xenon_rho(state, cfg);
    state.rod_position = clamp(
        (-rho_xe - cfg.rho_rod_min) / (cfg.rho_rod_max - cfg.rho_rod_min), 0.0f, 1.0f);
    state.rod_target = state.rod_position;
    state.rod_motion_residual = 0.0f;

    state.decay_heat = 0.0f;
    for (int i = 0; i < DECAY_GROUPS; ++i) {
        state.decay_group[i] = params.decay_fraction[i] * state.n;
        state.decay_heat += state.decay_group[i];
    }
    state.scram_occurred = false;
    state.scram_active = false;
    state.t_scram = 0.0f;
}

inline void scram(ReactorState& state) {
    state.rod_position = 0.0f;
    state.rod_target = 0.0f;
    state.rod_motion_residual = 0.0f;
    state.scram_active = true;
    state.scram_occurred = true;
    state.t_scram = state.t;
}

inline void reset_scram_trip(ReactorState& state) {
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

inline void step(ReactorState& state, const ReactorParams& params, float h) {
    if (!finite(h) || h <= 0.0f) {
        h = TimePolicy::base_h();
    }
    h = clamp(h, TimePolicy::base_h(), TimePolicy::max_h());
    const PlantConfig cfg = plant_config(state.plant_mode);

    // Move the control rods toward their target.
    const float rod_speed = 0.01f;
    const float rod_delta = state.rod_target - state.rod_position;
    if (rod_delta == 0.0f) {
        state.rod_motion_residual = 0.0f;
    } else {
        const float direction = rod_delta > 0.0f ? 1.0f : -1.0f;
        const float magnitude = rod_delta > 0.0f ? rod_delta : -rod_delta;
        state.rod_motion_residual += rod_speed * h;
        if (state.rod_motion_residual >= 1.0e-7f ||
            state.rod_motion_residual >= magnitude) {
            const float move = state.rod_motion_residual < magnitude
                                   ? state.rod_motion_residual
                                   : magnitude;
            state.rod_position = clamp(
                state.rod_position + direction * move, 0.0f, 1.0f);
            state.rod_motion_residual -= move;
        }
    }

    // Calculate reactivity and delayed-neutron precursor derivatives.
    const float rho = total_rho(state, cfg);
    float sum_lam_C = 0.0f;
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        sum_lam_C += params.lam_i[i] * state.C[i];
    }

    const float n_old = state.n;
    float n_denom =
        1.0f - h * (rho - params.beta_total) / params.Lambda;
    if (n_denom < 1.0e-10f) {
        n_denom = 1.0e-10f;
    }

    float dCdt[PRECURSOR_GROUPS];
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        dCdt[i] = (params.beta_i[i] / params.Lambda) * n_old -
                  params.lam_i[i] * state.C[i];
    }

    // Evolve decay heat continuously, including before and after SCRAM.
    float next_decay_heat = 0.0f;
    for (int i = 0; i < DECAY_GROUPS; ++i) {
        const float derivative = params.decay_lambda[i] *
            (params.decay_fraction[i] * n_old - state.decay_group[i]);
        state.decay_group[i] += h * derivative;
        if (state.decay_group[i] < 0.0f) {
            state.decay_group[i] = 0.0f;
        }
        next_decay_heat += state.decay_group[i];
    }
    state.decay_heat = next_decay_heat;

    // Calculate thermal and poison derivatives.
    const float prompt_fraction = 1.0f - params.total_decay_fraction();
    const float thermal_power = prompt_fraction * n_old + state.decay_heat;
    const float dTfdt =
        params.K_heat * thermal_power - params.gamma * (state.Tf - state.Tc);
    const float dTcdt =
        params.gamma * (state.Tf - state.Tc) -
        cfg.gamma_c_active * (state.Tc - params.Tm_const);
    // Apply one semi-implicit kinetics step and explicit auxiliary updates.
    state.n = (n_old + h * (sum_lam_C + params.Q)) / n_denom;
    state.Tf += h * dTfdt;
    state.Tc += h * dTcdt;
    for (int i = 0; i < PRECURSOR_GROUPS; ++i) {
        state.C[i] += h * dCdt[i];
    }

    if (!finite(state.n) || state.n < 0.0f) {
        state.n = 0.0f;
    }
    if (state.n > 1.0e12f) {
        state.n = 1.0e12f;
    }
    state.t += h;
}

inline int bounded_substeps(int requested) {
    return clamp(requested, 1, MAX_SUBSTEPS);
}

inline void advance(ReactorState& state, const ReactorParams& params,
                    float h, int requested_substeps) {
    const int count = bounded_substeps(requested_substeps);
    float n_sum = 0.0f;
    for (int i = 0; i < MAX_SUBSTEPS; ++i) {
        if (i >= count) {
            break;
        }
        step(state, params, h);
        n_sum += state.n;
    }
    float poison_dt = h * (float)count;
    float N_avg = n_sum / (float)count;
    update_poison_batched(N_avg, poison_dt, params, state.I_Xe, state.Xe);
}

} // namespace pk

#endif
