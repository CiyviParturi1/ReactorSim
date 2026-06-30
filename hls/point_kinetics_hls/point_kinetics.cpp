#include "point_kinetics.h"

#include <cmath>

#ifndef __SYNTHESIS__
#include <algorithm>
#include <atomic>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>
#endif

// ============================================================================
// TIME COMPRESSION DESIGN
// ============================================================================
//
// REALTIME   factor=1       h=0.00001s
// TRAINING   factor=10      h=0.0001s
// XENON      factor=1000    h=0.002s
//
// The host/Vitis side should advance wall_output_interval * factor seconds per
// display frame. Named modes use:
//   REALTIME: h=10 us, TRAINING: h=100 us, XENON: h=2 ms.
// ============================================================================

float euler_update(float y, float dydt, float h) {
    return y + h * dydt;
}

float clamp_value(float value, float low, float high) {
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

static int clamp_plant_mode(int mode) {
    if (mode < 0) return 0;
    if (mode > 2) return 2;
    return mode;
}

ReactorParams::ReactorParams()
    : Lambda(0.00002f),
      beta_total(0.007f),
      Q(0.0f),
      lam_i{0.0127f, 0.0317f, 0.155f, 0.311f, 1.4f, 3.87f},
      beta_i{0.000266f, 0.001491f, 0.001316f, 0.002849f, 0.000896f, 0.000182f},
      gamma(0.2f),
      K_heat(50.0f),
      Tm_const(290.0f),
      Tc_ref(290.0f),
      Tf_ref(540.0f),
      gamma_I(0.061f),
      gamma_Xe(0.003f),
      lambda_I(2.87e-5f),
      lambda_Xe(2.09e-5f),
      kXe_burnout(2.0e-5f),
      kFission(1.0e4f) {
}

TimeCompression::TimeCompression()
    : mode(TimeMode::REALTIME),
      factor(1.0f) {
}

void TimeCompression::set_mode(TimeMode m) {
    mode = m;
    switch (m) {
        case TimeMode::REALTIME: factor = 1.0f;    break;
        case TimeMode::TRAINING: factor = 10.0f;   break;
        case TimeMode::XENON:    factor = 1000.0f; break;
        default: break;
    }
}

void TimeCompression::set_custom(float f) {
    mode = TimeMode::CUSTOM;
    factor = (f < 1.0f) ? 1.0f : f;
}

float TimeCompression::h() const {
    float raw_h = BASE_H * factor;
    return (raw_h < MAX_H) ? raw_h : MAX_H;
}

const char* TimeCompression::name() const {
    switch (mode) {
        case TimeMode::REALTIME: return "REALTIME(1x)";
        case TimeMode::TRAINING: return "TRAINING(10x)";
        case TimeMode::XENON:    return "XENON(1000x)";
        default:                 return "CUSTOM";
    }
}

ReactorSim::ReactorSim()
    : engine_order(1),
      t(0.0f),
      n(1.0f),
      C{0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f},
      Tf(0.0f),
      Tc(0.0f),
      I_Xe(0.0f),
      Xe(0.0f),
      Xe_ref(0.0f),
      decay_heat(0.0f),
      rod_position(0.75f),
      rod_target(0.75f),
      rod_speed_limit(0.01f),
      rod_motion_residual(0.0f),
      scram_occurred(false),
      t_scram(0.0f),
      pre_scram_power(1.0f),
      plant_mode(0),
      plant_configs{
          {0, "PWR-SMR Passive Safe",      -2.5e-5f, -1.0e-5f, 0.4f, 0.4f,  -0.105f, 0.007f, -0.025f},
          {1, "RBMK-like Demonstrator",    -0.5e-5f,  1.5e-5f, 0.4f, 0.25f, -0.120f, 0.009f, -0.025f},
          {2, "TMI-inspired Cooling Loss", -2.5e-5f, -1.0e-5f, 0.4f, 0.02f, -0.105f, 0.007f, -0.025f}
      } {
    initialize(1.0f);
}

void ReactorSim::initialize(float power_fraction) {
    if (!std::isfinite(power_fraction)) power_fraction = 1.0f;
    power_fraction = clamp_value(power_fraction, 0.0f, 1.5f);
    plant_mode = clamp_plant_mode(plant_mode);
    const PlantConfig& cfg = plant_configs[plant_mode];

    t = 0.0f;
    n = power_fraction;
    scram_occurred = false;
    t_scram = 0.0f;
    pre_scram_power = n;
    decay_heat = 0.0f;

    rod_position = -cfg.rho_rod_min / (cfg.rho_rod_max - cfg.rho_rod_min);
    rod_position = clamp_value(rod_position, 0.0f, 1.0f);
    rod_target = rod_position;
    rod_motion_residual = 0.0f;

    for (int i = 0; i < 6; ++i) {
        C[i] = (p.beta_i[i] * n) / (p.lam_i[i] * p.Lambda);
    }

    Tc = p.Tm_const + (p.K_heat * n) / cfg.gamma_c_init;
    p.Tc_ref = Tc;
    Tf = Tc + (p.K_heat * n) / p.gamma;
    p.Tf_ref = Tf;

    float fission_rate = p.kFission * n;
    I_Xe = (p.gamma_I * fission_rate) / p.lambda_I;
    float Xe_source = (p.gamma_Xe * fission_rate) + (p.lambda_I * I_Xe);
    float Xe_sink = p.lambda_Xe + p.kXe_burnout * n;
    Xe = (Xe_sink > 1.0e-12f) ? (Xe_source / Xe_sink) : 0.0f;
    Xe_ref = Xe;
}

float ReactorSim::get_rod_rho(const PlantConfig& cfg) const {
    return cfg.rho_rod_min + rod_position * (cfg.rho_rod_max - cfg.rho_rod_min);
}

float ReactorSim::get_xe_rho(const PlantConfig& cfg) const {
    return (Xe_ref > 1.0e-10f)
         ? cfg.kXe_worth * ((Xe - Xe_ref) / Xe_ref)
         : 0.0f;
}

float ReactorSim::get_total_rho(const PlantConfig& cfg) const {
    float rho_Tf = cfg.alpha_f * (Tf - p.Tf_ref);
    float rho_Tc = cfg.alpha_c * (Tc - p.Tc_ref);
    return get_rod_rho(cfg) + rho_Tf + rho_Tc + get_xe_rho(cfg);
}

float ReactorSim::get_total_rho() const {
    return get_total_rho(plant_configs[clamp_plant_mode(plant_mode)]);
}

void ReactorSim::scram() {
    pre_scram_power = n;
    rod_position = 0.0f;
    rod_target = 0.0f;
    rod_motion_residual = 0.0f;
    scram_occurred = true;
    t_scram = t;
}

void ReactorSim::step(float h) {
    const PlantConfig& cfg = plant_configs[clamp_plant_mode(plant_mode)];

    float delta = rod_target - rod_position;
    if (delta == 0.0f) {
        rod_motion_residual = 0.0f;
    } else {
        float direction = (delta > 0.0f) ? 1.0f : -1.0f;
        float abs_delta = (delta > 0.0f) ? delta : -delta;
        rod_motion_residual += rod_speed_limit * h;
        if (rod_motion_residual >= 1.0e-7f || rod_motion_residual >= abs_delta) {
            float move = (rod_motion_residual < abs_delta) ? rod_motion_residual : abs_delta;
            rod_position = clamp_value(rod_position + direction * move, 0.0f, 1.0f);
            rod_motion_residual -= move;
        }
    }

    float rho = get_total_rho(cfg);

    float sum_lam_C = 0.0f;
    for (int i = 0; i < 6; i++) {
        sum_lam_C += p.lam_i[i] * C[i];
    }

    float n_old = n;
    float n_denom = 1.0f - h * (rho - p.beta_total) / p.Lambda;
    if (n_denom < 1.0e-10f) n_denom = 1.0e-10f;

    float dCdt[6];
    for (int i = 0; i < 6; i++) {
        dCdt[i] = (p.beta_i[i] / p.Lambda) * n_old - p.lam_i[i] * C[i];
    }

    decay_heat = 0.0f;
    if (scram_occurred && t >= t_scram) {
        float dt = t - t_scram + 1.0f;
        decay_heat = 0.066f * std::pow(dt, -0.2f) * pre_scram_power;
    }
    float thermal_power = n_old + decay_heat;
    float dTfdt = p.K_heat * thermal_power - p.gamma * (Tf - Tc);
    float dTcdt = p.gamma * (Tf - Tc) - cfg.gamma_c_active * (Tc - p.Tm_const);

    float fission_rate = p.kFission * n_old;
    float dIdt = p.gamma_I * fission_rate - p.lambda_I * I_Xe;
    float dXedt = p.gamma_Xe * fission_rate
                + p.lambda_I * I_Xe
                - p.lambda_Xe * Xe
                - p.kXe_burnout * n_old * Xe;

    n = (n_old + h * (sum_lam_C + p.Q)) / n_denom;
    Tf = euler_update(Tf, dTfdt, h);
    Tc = euler_update(Tc, dTcdt, h);
    I_Xe = euler_update(I_Xe, dIdt, h);
    Xe = euler_update(Xe, dXedt, h);
    for (int i = 0; i < 6; i++) {
        C[i] = euler_update(C[i], dCdt[i], h);
    }

    if (!std::isfinite(n)) n = 0.0f;
    if (n < 0.0f) n = 0.0f;
    if (n > 1.0e12f) n = 1.0e12f;
    if (I_Xe < 0.0f) I_Xe = 0.0f;
    if (Xe < 0.0f) Xe = 0.0f;

    t += h;
}

#ifndef __SYNTHESIS__
void run_simulation_host(ReactorSim& sim, float wall_output_interval) {
    std::mutex cmd_mutex;
    std::vector<std::string> pending_cmds;
    std::atomic<bool> running{true};

    std::thread stdin_thread([&]() {
        std::string line;
        while (running && std::getline(std::cin, line)) {
            std::lock_guard<std::mutex> lock(cmd_mutex);
            pending_cmds.push_back(line);
        }
    });
    stdin_thread.detach();

    std::cout << "DATA_START" << std::endl;
    std::cout << std::fixed << std::setprecision(6);

    std::cerr << "[TIME] Mode: " << sim.tc.name()
              << "  h=" << sim.tc.h() << "s" << std::endl;

    while (true) {
        {
            std::lock_guard<std::mutex> lock(cmd_mutex);
            for (auto& cmd : pending_cmds) {
                if (cmd.empty()) continue;
                char ch = cmd[0];

                if (ch == '+') {
                    sim.rod_target = std::min(1.0f, sim.rod_target + 0.01f);
                } else if (ch == '-') {
                    sim.rod_target = std::max(0.0f, sim.rod_target - 0.01f);
                } else if (ch == 'W' || ch == 'w') {
                    std::istringstream iss(cmd.substr(1));
                    float target;
                    if (iss >> target) {
                        sim.rod_target = clamp_value(target, 0.0f, 1.0f);
                    }
                } else if (ch == 'R' || ch == 'r') {
                    sim.scram();
                } else if (ch == 'P' || ch == 'p') {
                    std::istringstream iss(cmd.substr(1));
                    float power_fraction = 1.0f;
                    if (iss >> power_fraction && power_fraction >= 0.0f) {
                        sim.initialize(power_fraction);
                        std::cerr << "[INIT] Power fraction=" << sim.n
                                  << "  Tf=" << sim.Tf
                                  << "  Tc=" << sim.Tc
                                  << std::endl;
                    }
                } else if (ch == 'C' || ch == 'c') {
                    if (cmd.size() >= 2) {
                        char digit = cmd[1];
                        if (digit >= '0' && digit <= '2') {
                            sim.plant_mode = digit - '0';
                            sim.initialize(1.0f);
                            std::cerr << "[PLANT] Switched to "
                                      << sim.plant_configs[sim.plant_mode].name
                                      << " and reinitialized (power=1.0)."
                                      << std::endl;
                        }
                    }
                } else if (ch == 'M' || ch == 'm') {
                    if (cmd.size() >= 2) {
                        char digit = cmd[1];
                        TimeMode prev_mode = sim.tc.mode;
                        if (digit == '0') sim.tc.set_mode(TimeMode::REALTIME);
                        else if (digit == '1') sim.tc.set_mode(TimeMode::TRAINING);
                        else if (digit == '2') sim.tc.set_mode(TimeMode::XENON);
                        if (sim.tc.mode != prev_mode) {
                            std::cerr << "[TIME] Switched to " << sim.tc.name()
                                      << "  h=" << sim.tc.h() << "s"
                                      << "  factor=" << sim.tc.factor << "x"
                                      << std::endl;
                        }
                    }
                } else if (ch == 'T' || ch == 't') {
                    std::istringstream iss(cmd.substr(1));
                    float custom_factor = 1.0f;
                    if (iss >> custom_factor && custom_factor >= 1.0f) {
                        sim.tc.set_custom(custom_factor);
                        std::cerr << "[TIME] Custom factor=" << sim.tc.factor
                                  << "x  h=" << sim.tc.h() << "s"
                                  << "  (clamped from BASE_H*factor="
                                  << TimeCompression::BASE_H * sim.tc.factor
                                  << ")" << std::endl;
                    }
                }
            }
            pending_cmds.clear();
        }

        float h = sim.tc.h();
        float delta_sim_time = wall_output_interval * sim.tc.factor;
        int steps = std::max(1, static_cast<int>(std::round(delta_sim_time / h)));

        auto start = std::chrono::high_resolution_clock::now();
        for (int i = 0; i < steps; i++) {
            sim.step(h);
        }
        auto end = std::chrono::high_resolution_clock::now();
        std::chrono::duration<float> elapsed = end - start;
        float step_real_time = elapsed.count() / static_cast<float>(steps);

        const PlantConfig& out_cfg = sim.plant_configs[sim.plant_mode];
        float rho = sim.get_total_rho();
        float dollars = rho / sim.p.beta_total;
        float rho_Xe = sim.get_xe_rho(out_cfg);

        std::cout << std::fixed << std::setprecision(6);
        std::cout << sim.t            << ","
                  << sim.n            << ","
                  << sim.Tf           << ","
                  << rho              << ","
                  << dollars          << ","
                  << sim.Tc           << ","
                  << sim.I_Xe         << ","
                  << sim.Xe           << ","
                  << rho_Xe           << ","
                  << sim.tc.factor    << ","
                  << sim.rod_position << ","
                  << sim.rod_target   << ","
                  << sim.engine_order << ",";
        std::cout << std::scientific << std::setprecision(9);
        std::cout << h                << ","
                  << step_real_time   << ",";
        std::cout << std::fixed << std::setprecision(6);
        std::cout << sim.decay_heat   << ","
                  << sim.plant_mode   << std::endl;

        std::this_thread::sleep_for(
            std::chrono::milliseconds(static_cast<int>(wall_output_interval * 1000)));
    }
}
#endif

static float inv_fifth_root_hls(float value) {
    float low = 1.0f;
    float high = (value > 1.0f) ? value : 1.0f;

    for (int i = 0; i < 32; i++) {
        float mid = 0.5f * (low + high);
        float mid5 = mid * mid * mid * mid * mid;

        if (mid5 > value) {
            high = mid;
        } else {
            low = mid;
        }
    }

    return 1.0f / (0.5f * (low + high));
}

static void select_plant_config(
    int plant_mode,
    float *alpha_f,
    float *alpha_c,
    float *gamma_c_init,
    float *gamma_c_active,
    float *rho_rod_min,
    float *rho_rod_max,
    float *kXe_worth
) {
    int mode = clamp_plant_mode(plant_mode);

    if (mode == 1) {
        *alpha_f = -0.5e-5f;
        *alpha_c = 1.5e-5f;
        *gamma_c_init = 0.4f;
        *gamma_c_active = 0.25f;
        *rho_rod_min = -0.120f;
        *rho_rod_max = 0.009f;
        *kXe_worth = -0.025f;
    } else if (mode == 2) {
        *alpha_f = -2.5e-5f;
        *alpha_c = -1.0e-5f;
        *gamma_c_init = 0.4f;
        *gamma_c_active = 0.02f;
        *rho_rod_min = -0.105f;
        *rho_rod_max = 0.007f;
        *kXe_worth = -0.025f;
    } else {
        *alpha_f = -2.5e-5f;
        *alpha_c = -1.0e-5f;
        *gamma_c_init = 0.4f;
        *gamma_c_active = 0.4f;
        *rho_rod_min = -0.105f;
        *rho_rod_max = 0.007f;
        *kXe_worth = -0.025f;
    }
}

void point_kinetics_step(
    float h,
    int substeps,
    float tc_factor,
    float reset,
    float reset_power,
    float withdraw_cmd,
    float insert_cmd,
    float scram_cmd,
    float *t_out,
    float *N_out,
    float *Tf_out,
    float *Tc_out,
    float *I_Xe_out,
    float *Xe_out,
    float *rho_out,
    float *dollars_out,
    float *rho_Xe_out,
    float *rod_position_out,
    float *rod_target_out,
    float *tc_factor_out,
    float *engine_order_out,
    float C_out[6],
    float set_rod_target_cmd,
    float rod_target_cmd,
    int plant_mode_cmd,
    float plant_mode_update_cmd,
    float *target_h_out,
    float *decay_heat_out,
    float *plant_mode_out
) {
    #pragma HLS INTERFACE s_axilite port=h                         bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=substeps                  bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=tc_factor                 bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=reset                     bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=reset_power               bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=withdraw_cmd              bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=insert_cmd                bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=scram_cmd                 bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=t_out                     bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=N_out                     bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=Tf_out                    bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=Tc_out                    bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=I_Xe_out                  bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=Xe_out                    bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=rho_out                   bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=dollars_out               bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=rho_Xe_out                bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=rod_position_out          bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=rod_target_out            bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=tc_factor_out             bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=engine_order_out          bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=C_out                     bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=set_rod_target_cmd        bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=rod_target_cmd            bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=plant_mode_cmd            bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=plant_mode_update_cmd     bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=target_h_out              bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=decay_heat_out            bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=plant_mode_out            bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=return                    bundle=CTRL

    #pragma HLS ARRAY_PARTITION variable=C_out complete dim=1

    const float Lambda = 0.00002f;
    const float beta_total = 0.007f;
    const float Q = 0.0f;
    const float lam_i[6] = {0.0127f, 0.0317f, 0.155f, 0.311f, 1.4f, 3.87f};
    const float beta_i[6] = {
        0.000266f, 0.001491f, 0.001316f,
        0.002849f, 0.000896f, 0.000182f
    };

    const float gamma_f = 0.2f;
    const float K_heat = 50.0f;
    const float Tm_const = 290.0f;

    const float gamma_I = 0.061f;
    const float gamma_Xe = 0.003f;
    const float lambda_I = 2.87e-5f;
    const float lambda_Xe = 2.09e-5f;
    const float kXe_burnout = 2.0e-5f;
    const float kFission = 1.0e4f;

    const float rod_speed_limit = 0.01f;
    const float engine_order = 1.0f;
    const int max_substeps = 100000;

    static bool initialized = false;
    static int plant_mode = 0;
    static float t = 0.0f;
    static float n = 1.0f;
    static float C[6];
    #pragma HLS ARRAY_PARTITION variable=C complete dim=1
    static float Tf = 0.0f;
    static float Tc = 0.0f;
    static float Tf_ref = 0.0f;
    static float Tc_ref = 0.0f;
    static float I_Xe = 0.0f;
    static float Xe = 0.0f;
    static float Xe_ref = 0.0f;
    static float rod_position = 0.75f;
    static float rod_target = 0.75f;
    static float rod_motion_residual = 0.0f;
    static bool scram_occurred = false;
    static float t_scram = 0.0f;
    static float pre_scram_power = 1.0f;
    static float decay_heat = 0.0f;

    if (plant_mode_update_cmd > 0.5f) {
        plant_mode = clamp_plant_mode(plant_mode_cmd);
    }

    float alpha_f = 0.0f;
    float alpha_c = 0.0f;
    float gamma_c_init = 0.0f;
    float gamma_c_active = 0.0f;
    float rho_rod_min = 0.0f;
    float rho_rod_max = 0.0f;
    float kXe_worth = 0.0f;
    select_plant_config(plant_mode, &alpha_f, &alpha_c, &gamma_c_init,
                        &gamma_c_active, &rho_rod_min, &rho_rod_max,
                        &kXe_worth);

    if (!initialized || reset > 0.5f || plant_mode_update_cmd > 0.5f) {
        float power_fraction = clamp_value(reset_power, 0.0f, 1.5f);

        t = 0.0f;
        n = power_fraction;
        scram_occurred = false;
        t_scram = 0.0f;
        pre_scram_power = n;
        decay_heat = 0.0f;
        rod_position = -rho_rod_min / (rho_rod_max - rho_rod_min);
        rod_position = clamp_value(rod_position, 0.0f, 1.0f);
        rod_target = rod_position;
        rod_motion_residual = 0.0f;

        for (int i = 0; i < 6; ++i) {
            #pragma HLS UNROLL
            C[i] = (beta_i[i] * n) / (lam_i[i] * Lambda);
        }

        Tc = Tm_const + (K_heat * n) / gamma_c_init;
        Tc_ref = Tc;
        Tf = Tc + (K_heat * n) / gamma_f;
        Tf_ref = Tf;

        float fission_rate = kFission * n;
        I_Xe = (gamma_I * fission_rate) / lambda_I;
        float Xe_source = (gamma_Xe * fission_rate) + (lambda_I * I_Xe);
        float Xe_sink = lambda_Xe + kXe_burnout * n;
        Xe = (Xe_sink > 1.0e-12f) ? (Xe_source / Xe_sink) : 0.0f;
        Xe_ref = Xe;
        initialized = true;
    }

    if (set_rod_target_cmd > 0.5f) {
        rod_target = clamp_value(rod_target_cmd, 0.0f, 1.0f);
    } else if (withdraw_cmd > 0.5f && insert_cmd <= 0.5f) {
        rod_target = clamp_value(rod_target + 0.01f, 0.0f, 1.0f);
    } else if (insert_cmd > 0.5f && withdraw_cmd <= 0.5f) {
        rod_target = clamp_value(rod_target - 0.01f, 0.0f, 1.0f);
    }

    if (substeps < 1) {
        substeps = 1;
    } else if (substeps > max_substeps) {
        substeps = max_substeps;
    }

    if (h <= 0.0f) {
        h = TimeCompression::BASE_H;
    }

    float t_frame_start = t;
    for (int step = 0; step < substeps; step++) {
        #pragma HLS LOOP_TRIPCOUNT min=1 max=100000
        float t_step = t_frame_start + h * static_cast<float>(step);

        if (scram_cmd > 0.5f) {
            if (!scram_occurred) {
                pre_scram_power = n;
                t_scram = t_step;
            }
            rod_position = 0.0f;
            rod_target = 0.0f;
            rod_motion_residual = 0.0f;
            scram_occurred = true;
        }

        float rod_delta = rod_target - rod_position;
        if (rod_delta == 0.0f) {
            rod_motion_residual = 0.0f;
        } else {
            float direction = (rod_delta > 0.0f) ? 1.0f : -1.0f;
            float abs_delta = (rod_delta > 0.0f) ? rod_delta : -rod_delta;
            rod_motion_residual += rod_speed_limit * h;
            if (rod_motion_residual >= 1.0e-7f || rod_motion_residual >= abs_delta) {
                float move = (rod_motion_residual < abs_delta) ? rod_motion_residual : abs_delta;
                rod_position = clamp_value(rod_position + direction * move, 0.0f, 1.0f);
                rod_motion_residual -= move;
            }
        }

        float rho_rod = rho_rod_min + rod_position * (rho_rod_max - rho_rod_min);
        float rho_Tf = alpha_f * (Tf - Tf_ref);
        float rho_Tc = alpha_c * (Tc - Tc_ref);
        float rho_Xe = (Xe_ref > 1.0e-10f)
                     ? kXe_worth * ((Xe - Xe_ref) / Xe_ref)
                     : 0.0f;
        float rho = rho_rod + rho_Tf + rho_Tc + rho_Xe;

        float sum_lam_C = 0.0f;
        for (int i = 0; i < 6; i++) {
            #pragma HLS UNROLL
            sum_lam_C += lam_i[i] * C[i];
        }

        float n_old = n;
        float n_denom = 1.0f - h * (rho - beta_total) / Lambda;
        if (n_denom < 1.0e-10f) {
            n_denom = 1.0e-10f;
        }

        float dCdt[6];
        #pragma HLS ARRAY_PARTITION variable=dCdt complete dim=1
        for (int i = 0; i < 6; i++) {
            #pragma HLS UNROLL
            dCdt[i] = (beta_i[i] / Lambda) * n_old - lam_i[i] * C[i];
        }

        decay_heat = 0.0f;
        if (scram_occurred && t_step >= t_scram) {
            float dt = t_step - t_scram + 1.0f;
            decay_heat = 0.066f * inv_fifth_root_hls(dt) * pre_scram_power;
        }
        float thermal_power = n_old + decay_heat;
        float dTfdt = K_heat * thermal_power - gamma_f * (Tf - Tc);
        float dTcdt = gamma_f * (Tf - Tc) - gamma_c_active * (Tc - Tm_const);

        float fission_rate = kFission * n_old;
        float dIdt = gamma_I * fission_rate - lambda_I * I_Xe;
        float dXedt = gamma_Xe * fission_rate
                    + lambda_I * I_Xe
                    - lambda_Xe * Xe
                    - kXe_burnout * n_old * Xe;

        n = (n_old + h * (sum_lam_C + Q)) / n_denom;
        Tf = euler_update(Tf, dTfdt, h);
        Tc = euler_update(Tc, dTcdt, h);
        I_Xe = euler_update(I_Xe, dIdt, h);
        Xe = euler_update(Xe, dXedt, h);
        for (int i = 0; i < 6; i++) {
            #pragma HLS UNROLL
            C[i] = euler_update(C[i], dCdt[i], h);
        }

        if (n < 0.0f) n = 0.0f;
        if (n > 1.0e12f) n = 1.0e12f;
        if (I_Xe < 0.0f) I_Xe = 0.0f;
        if (Xe < 0.0f) Xe = 0.0f;

    }

    t = t_frame_start + h * static_cast<float>(substeps);

    float rho_rod = rho_rod_min + rod_position * (rho_rod_max - rho_rod_min);
    float rho_Tf = alpha_f * (Tf - Tf_ref);
    float rho_Tc = alpha_c * (Tc - Tc_ref);
    float rho_Xe = (Xe_ref > 1.0e-10f)
                 ? kXe_worth * ((Xe - Xe_ref) / Xe_ref)
                 : 0.0f;
    float rho = rho_rod + rho_Tf + rho_Tc + rho_Xe;

    *t_out = t;
    *N_out = n;
    *Tf_out = Tf;
    *Tc_out = Tc;
    *I_Xe_out = I_Xe;
    *Xe_out = Xe;
    *rho_out = rho;
    *dollars_out = rho / beta_total;
    *rho_Xe_out = rho_Xe;
    *rod_position_out = rod_position;
    *rod_target_out = rod_target;
    *tc_factor_out = tc_factor;
    *engine_order_out = engine_order;
    *target_h_out = h;
    *decay_heat_out = decay_heat;
    *plant_mode_out = static_cast<float>(plant_mode);
    for (int i = 0; i < 6; i++) {
        #pragma HLS UNROLL
        C_out[i] = C[i];
    }
}

#ifdef POINT_KINETICS_STANDALONE_MAIN
int main() {
    ReactorSim sim;

    std::cerr << "=== 11-Equation Reactor Simulator + Time Compression ===" << std::endl;
    std::cerr << "Equilibrium Iodine : " << sim.I_Xe << std::endl;
    std::cerr << "Equilibrium Xenon  : " << sim.Xe   << std::endl;
    std::cerr << std::endl;
    std::cerr << "TIME COMPRESSION COMMANDS:" << std::endl;
    std::cerr << "  M0          -> REALTIME  (1x)    h=0.00001s" << std::endl;
    std::cerr << "  M1          -> TRAINING  (10x)   h=0.0001s" << std::endl;
    std::cerr << "  M2          -> XENON     (1000x) h=0.002s" << std::endl;
    std::cerr << "  T <factor>  -> CUSTOM    e.g. 'T 100'" << std::endl;
    std::cerr << "  P <power>   -> FULL RESET at power fraction, e.g. 'P 0.75'" << std::endl;
    std::cerr << "PLANT CONFIG:  C0 = PWR-SMR,  C1 = RBMK-like,  C2 = TMI-loss" << std::endl;
    std::cerr << "ROD COMMANDS:  + withdraw target,  - insert target,  W <0..1> target,  R = SCRAM" << std::endl;
    std::cerr << "MODEL NOTES: temperatures are lumped model values; rod worth is linear; rod full travel is 100 simulated seconds." << std::endl;
    std::cerr << std::endl;

    run_simulation_host(sim, 0.01f);
    return 0;
}
#endif
