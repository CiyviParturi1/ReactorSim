#include <iostream>
#include <vector>
#include <cmath>
#include <iomanip>
#include <thread>
#include <chrono>
#include <string>
#include <mutex>
#include <atomic>
#include <sstream>


// COMMANDS (stdin, one per line):
//   + / -      Withdraw / insert rods by 1% target position
//   W <value>  Set rod target withdrawal directly, 0.0 to 1.0
//   R / r      SCRAM (all rods in)
//   M0         Mode: REALTIME  (1x)
//   M1         Mode: TRAINING  (10x)
//   M2         Mode: XENON     (1000x)
//   T <factor> Custom factor, e.g. "T 100" for 100x
//   P <power>  Full reset at power fraction, e.g. "P 0.75"
//   C0/C1/C2   Plant config: PWR-SMR / RBMK-like / TMI-loss
// ============================================================================

double euler_update(double y, double dydt, double h) {
    return y + h * dydt;
}

double clamp_value(double value, double low, double high) {
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

// ============================================================================
// Reactor Parameters (11-Equation Model)
// ============================================================================
struct ReactorParams {
    double Lambda     = 0.00002;
    double beta_total = 0.007;
    double Q          = 0.0;

    double lam_i[6]  = {0.0127, 0.0317, 0.155, 0.311, 1.4, 3.87};
    double beta_i[6] = {0.000266, 0.001491, 0.001316, 0.002849, 0.000896, 0.000182};

    double gamma    = 0.2;
    double K_heat   = 50.0;
    double Tm_const = 290.0;

    double Tc_ref   = 290.0;
    double Tf_ref   = 540.0;

    // Xenon / Iodine
    double gamma_I      = 0.061;
    double gamma_Xe     = 0.003;
    double lambda_I     = 2.87e-5;
    double lambda_Xe    = 2.09e-5;
    double kXe_burnout  = 2.0e-5;
    double kFission     = 1.0e4;
};

// ============================================================================
// Plant Configurations
// ============================================================================
struct PlantConfig {
    int mode_id;
    const char* name;
    double alpha_f;
    double alpha_c;
    double gamma_c_init;
    double gamma_c_active;
    double rho_rod_min;
    double rho_rod_max;
    double kXe_worth;
};

// ============================================================================
// Time Compression Mode
// ============================================================================
enum class TimeMode {
    REALTIME,   // 1x    — h = 0.0000001s
    TRAINING,   // 10x   — h = 0.000001s
    XENON,      // 1000x — h = 0.0001s (clamped by MAX_H)
    CUSTOM      // user-defined factor
};

struct TimeCompression {
    TimeMode mode   = TimeMode::REALTIME;
    double   factor = 1.0;

    // Base timestep at 1x — safe for all 11 equations at real time
    static constexpr double BASE_H = 0.0000001;

    // Maximum compressed physics step. Keep explicit Euler below the
    // prompt-neutron timescale so stiff point-kinetics equations are resolved.
    static constexpr double MAX_H  = 0.002;

    void set_mode(TimeMode m) {
        mode = m;
        switch (m) {
            case TimeMode::REALTIME: factor = 1.0;    break;
            case TimeMode::TRAINING: factor = 10.0;   break;
            case TimeMode::XENON:    factor = 1000.0; break;
            default: break; // CUSTOM: factor already set externally
        }
    }

    void set_custom(double f) {
        mode   = TimeMode::CUSTOM;
        factor = std::max(1.0, f);
    }

    // Effective physics timestep — clamped to MAX_H for numerical stability
    double h() const {
        return std::min(BASE_H * factor, MAX_H);
    }

    // Human-readable mode name
    const char* name() const {
        switch (mode) {
            case TimeMode::REALTIME: return "REALTIME(1x)";
            case TimeMode::TRAINING: return "TRAINING(10x)";
            case TimeMode::XENON:    return "XENON(1000x)";
            default:                 return "CUSTOM";
        }
    }
};

// ============================================================================
// Reactor Simulation (11 equations)
// ============================================================================
class ReactorSim {
public:
    ReactorParams   p;
    TimeCompression tc;  
    int engine_order = 1;

    double t = 0.0;
    double n = 1.0;
    double C[6];
    double Tf;
    double Tc;
    double I_Xe;
    double Xe;
    double Xe_ref = 0.0;
    double decay_heat = 0.0;

    // Continuous rod model: 0.0 = fully inserted, 1.0 = fully withdrawn.
    // Startup chooses the rod position that makes rod reactivity zero.
    double rod_position    = 0.75;
    double rod_target      = 0.75;
    double rod_speed_limit = 0.01;   // full travel in 100 simulated seconds
    bool   scram_occurred  = false;
    double t_scram         = 0.0;
    double pre_scram_power = 1.0;

    int plant_mode = 0;

    // Plant presets — fixed array for HLS portability.
    // {mode_id, name, alpha_f, alpha_c, gamma_c_init, gamma_c_active, rho_rod_min, rho_rod_max, kXe_worth}
    PlantConfig plant_configs[3] = {
        {0, "PWR-SMR Passive Safe",      -2.5e-5, -1.0e-5, 0.4, 0.4,  -0.105, 0.007, -0.025},
        {1, "RBMK-like Demonstrator",    -0.5e-5,  1.5e-5, 0.4, 0.25, -0.120, 0.009, -0.025},
        {2, "TMI-inspired Cooling Loss", -2.5e-5, -1.0e-5, 0.4, 0.02, -0.105, 0.007, -0.025}
    };

    ReactorSim() {
        initialize(1.0);
    }

    void initialize(double power_fraction) {
        if (!std::isfinite(power_fraction)) power_fraction = 1.0;
        power_fraction = clamp_value(power_fraction, 0.0, 1.5);

        t = 0.0;
        n = power_fraction;
        scram_occurred = false;
        t_scram = 0.0;
        pre_scram_power = n;
        decay_heat = 0.0;

        const auto& cfg = plant_configs[plant_mode];

        rod_position = -cfg.rho_rod_min / (cfg.rho_rod_max - cfg.rho_rod_min);
        rod_position = clamp_value(rod_position, 0.0, 1.0);
        rod_target = rod_position;

        for (int i = 0; i < 6; ++i)
            C[i] = (p.beta_i[i] * n) / (p.lam_i[i] * p.Lambda);

        Tc      = p.Tm_const + (p.K_heat * n) / cfg.gamma_c_init;
        p.Tc_ref = Tc;
        Tf      = Tc + (p.K_heat * n) / p.gamma;
        p.Tf_ref = Tf;

        double fission_rate = p.kFission * n;
        I_Xe = (p.gamma_I * fission_rate) / p.lambda_I;
        double Xe_source = (p.gamma_Xe * fission_rate) + (p.lambda_I * I_Xe);
        double Xe_sink   = p.lambda_Xe + p.kXe_burnout * n;
        Xe    = (Xe_sink > 1e-12) ? (Xe_source / Xe_sink) : 0.0;
        Xe_ref = Xe;
    }

    double get_rod_rho(const PlantConfig& cfg) const {
        return cfg.rho_rod_min + rod_position * (cfg.rho_rod_max - cfg.rho_rod_min);
    }

    double get_xe_rho(const PlantConfig& cfg) const {
        return (Xe_ref > 1e-10)
             ? cfg.kXe_worth * ((Xe - Xe_ref) / Xe_ref)
             : 0.0;
    }

    double get_total_rho(const PlantConfig& cfg) const {
        double rho_Tf = cfg.alpha_f * (Tf - p.Tf_ref);
        double rho_Tc = cfg.alpha_c * (Tc - p.Tc_ref);
        return get_rod_rho(cfg) + rho_Tf + rho_Tc + get_xe_rho(cfg);
    }

    double get_total_rho() const {
        return get_total_rho(plant_configs[plant_mode]);
    }

    void scram() {
        pre_scram_power = n;
        rod_position = 0.0;
        rod_target = 0.0;
        scram_occurred = true;
        t_scram = t;
    }

    void step(double h) {
        const auto& cfg = plant_configs[plant_mode];
        double max_change = rod_speed_limit * h;
        double delta = rod_target - rod_position;
        if (delta > max_change) delta = max_change;
        if (delta < -max_change) delta = -max_change;
        rod_position += delta;
        rod_position = clamp_value(rod_position, 0.0, 1.0);

        double rho = get_total_rho(cfg);

        // Neutron density
        double sum_lam_C = 0;
        for (int i = 0; i < 6; i++) sum_lam_C += p.lam_i[i] * C[i];
        double n_old = n;
        double n_denom = 1.0 - h * (rho - p.beta_total) / p.Lambda;
        if (n_denom < 1.0e-10) n_denom = 1.0e-10;

        // Precursors
        double dCdt[6];
        for (int i = 0; i < 6; i++)
            dCdt[i] = (p.beta_i[i]/p.Lambda)*n_old - p.lam_i[i]*C[i];

        // Thermal. After SCRAM, decay heat keeps the fuel/coolant elevated even
        // as prompt fission power falls away.
        decay_heat = 0.0;
        if (scram_occurred && t >= t_scram) {
            double dt = t - t_scram + 1.0;
            decay_heat = 0.066 * std::pow(dt, -0.2) * pre_scram_power;
        }
        double thermal_power = n_old + decay_heat;
        double dTfdt = p.K_heat*thermal_power - p.gamma  *(Tf - Tc);
        double dTcdt = p.gamma*(Tf - Tc) - cfg.gamma_c_active*(Tc - p.Tm_const);

        // Iodine
        double fission_rate = p.kFission * n_old;
        double dIdt = p.gamma_I * fission_rate - p.lambda_I * I_Xe;

        // Xenon
        double dXedt = p.gamma_Xe * fission_rate
                     + p.lambda_I * I_Xe
                     - p.lambda_Xe * Xe
                     - p.kXe_burnout * n_old * Xe;

        // Semi-implicit neutron update; all other ODEs remain explicit Euler.
        n = (n_old + h * (sum_lam_C + p.Q)) / n_denom;
        Tf   = euler_update(Tf,   dTfdt, h);
        Tc   = euler_update(Tc,   dTcdt, h);
        I_Xe = euler_update(I_Xe, dIdt,  h);
        Xe   = euler_update(Xe,   dXedt, h);
        for (int i = 0; i < 6; i++)
            C[i] = euler_update(C[i], dCdt[i], h);

        // Clamps
        if (!std::isfinite(n)) n = 0;
        if (n    < 0)    n    = 0;
        if (n    > 1e12) n    = 1e12;
        if (I_Xe < 0)    I_Xe = 0;
        if (Xe   < 0)    Xe   = 0;

        t += h;
    }
};

// ============================================================================
// HOST ADAPTER
// ============================================================================
void run_simulation_host(ReactorSim& sim, double wall_output_interval) {
    // Wall-clock output period is fixed at wall_output_interval seconds.
    // Physics steps fill each wall-clock frame.
    // Number of steps per frame = wall_output_interval / h(factor)
    // Because h is clamped, at very high factors we just take fewer, larger steps.

    std::mutex              cmd_mutex;
    std::vector<std::string> pending_cmds;
    std::atomic<bool>        running{true};

    // Stdin reader thread
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

    // Announce initial mode to stderr (instructor console)
    std::cerr << "[TIME] Mode: " << sim.tc.name()
              << "  h=" << sim.tc.h() << "s" << std::endl;

    while (true) {
        // ----------------------------------------------------------------
        // 1. PROCESS COMMANDS
        // ----------------------------------------------------------------
        {
            std::lock_guard<std::mutex> lock(cmd_mutex);
            for (auto& cmd : pending_cmds) {
                if (cmd.empty()) continue;
                char ch = cmd[0];

                if (ch == '+') {
                    // Withdraw rod target by 1% of full travel.
                    double step_size = 0.01;
                    sim.rod_target = std::min(1.0, sim.rod_target + step_size);

                } else if (ch == '-') {
                    // Insert rod target by 1% of full travel.
                    double step_size = 0.01;
                    sim.rod_target = std::max(0.0, sim.rod_target - step_size);

                } else if (ch == 'W' || ch == 'w') {
                    std::istringstream iss(cmd.substr(1));
                    double target;
                    if (iss >> target)
                        sim.rod_target = clamp_value(target, 0.0, 1.0);

                } else if (ch == 'R' || ch == 'r') {
                    // SCRAM
                    sim.scram();

                } else if (ch == 'P' || ch == 'p') {
                    std::istringstream iss(cmd.substr(1));
                    double power_fraction = 1.0;
                    if (iss >> power_fraction && power_fraction >= 0.0) {
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
                            sim.initialize(1.0);
                            std::cerr << "[PLANT] Switched to " << sim.plant_configs[sim.plant_mode].name
                                      << " and reinitialized (power=1.0)." << std::endl;
                        }
                    }

                } else if (ch == 'M' || ch == 'm') {
                    if (cmd.size() >= 2) {
                        char digit = cmd[1];
                        TimeMode prev_mode = sim.tc.mode;
                        if      (digit == '0') sim.tc.set_mode(TimeMode::REALTIME);
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
                    double custom_factor = 1.0;
                    if (iss >> custom_factor && custom_factor >= 1.0) {
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

        // ----------------------------------------------------------------
        // 2. PHYSICS STEPS FOR THIS WALL-CLOCK FRAME
        //
        // We want to advance simulation time by:
        //   delta_sim = wall_output_interval * factor
        // using steps of size h (which is clamped).
        // ----------------------------------------------------------------
        double h              = sim.tc.h();
        double delta_sim_time = wall_output_interval * sim.tc.factor;
        int    steps          = std::max(1, (int)std::round(delta_sim_time / h));

        auto start = std::chrono::high_resolution_clock::now();
        for (int i = 0; i < steps; i++) {
            sim.step(h);
        }
        auto end = std::chrono::high_resolution_clock::now();
        std::chrono::duration<double> elapsed = end - start;
        double step_real_time = elapsed.count() / steps;

        // ----------------------------------------------------------------
        // 3. OUTPUT ONE DATA ROW
        //
        // sim.t is the accumulated simulation time.
        // Column layout:
        //   [0]  sim_time       — reactor time (seconds)
        //   [1]  n              — neutron density / power (normalised)
        //   [2]  Tf             — fuel temperature (°C)
        //   [3]  rho            — total reactivity
        //   [4]  dollars        — reactivity in dollars
        //   [5]  Tc             — coolant temperature (°C)
        //   [6]  I_Xe           — Iodine-135 concentration
        //   [7]  Xe             — Xenon-135 concentration
        //   [8]  rho_Xe         — xenon reactivity contribution
        //   [9]  tc_factor      — current time compression factor
        //   [10] rod_position   — current rod withdrawal, 0..1
        //   [11] rod_target     — target rod withdrawal, 0..1
        //   [12] engine_order
        //   [13] target_h       — target timestep h (seconds)
        //   [14] step_real_time — actual execution time per step (seconds)
        //   [15] decay_heat     — decay heat component
        //   [16] plant_mode     — active plant configuration (0/1/2)
        // ----------------------------------------------------------------
        const auto& out_cfg = sim.plant_configs[sim.plant_mode];
        double rho     = sim.get_total_rho();
        double dollars = rho / sim.p.beta_total;
        double rho_Xe  = sim.get_xe_rho(out_cfg);

        // Columns [0]-[12]: fixed precision 6
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
        // Columns [13]-[14]: scientific precision 9 (sub-microsecond values)
        std::cout << std::scientific << std::setprecision(9);
        std::cout << h               << ","
                  << step_real_time   << ",";
        // Columns [15]-[16]: fixed precision 6
        std::cout << std::fixed << std::setprecision(6);
        std::cout << sim.decay_heat   << ","
                  << sim.plant_mode   << std::endl;

        // Wall-clock pacing — always sleep one real output interval
        std::this_thread::sleep_for(
            std::chrono::milliseconds((int)(wall_output_interval * 1000)));
    }
}

// ============================================================================
// MAIN
// ============================================================================
int main() {
    ReactorSim sim;

    std::cerr << "=== 11-Equation Reactor Simulator + Time Compression ===" << std::endl;
    std::cerr << "Equilibrium Iodine : " << sim.I_Xe << std::endl;
    std::cerr << "Equilibrium Xenon  : " << sim.Xe   << std::endl;
    std::cerr << std::endl;
    std::cerr << "TIME COMPRESSION COMMANDS:" << std::endl;
    std::cerr << "  M0          -> REALTIME  (1x)    h=0.0000001s" << std::endl;
    std::cerr << "  M1          -> TRAINING  (10x)   h=0.000001s"  << std::endl;
    std::cerr << "  M2          -> XENON     (1000x) h=0.0001s" << std::endl;
    std::cerr << "  T <factor>  -> CUSTOM    e.g. 'T 100'" << std::endl;
    std::cerr << "  P <power>   -> FULL RESET at power fraction, e.g. 'P 0.75'" << std::endl;
    std::cerr << "PLANT CONFIG:  C0 = PWR-SMR,  C1 = RBMK-like,  C2 = TMI-loss" << std::endl;
    std::cerr << "ROD COMMANDS:  + withdraw target,  - insert target,  W <0..1> target,  R = SCRAM" << std::endl;
    std::cerr << "MODEL NOTES: temperatures are lumped model values; rod worth is linear; rod full travel is 100 simulated seconds." << std::endl;
    std::cerr << std::endl;

    double wall_output_interval = 0.01; // 100 Hz display, always real time

    run_simulation_host(sim, wall_output_interval);
    return 0;
}
