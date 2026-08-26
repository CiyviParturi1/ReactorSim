#include "../common/point_kinetics_core.h"

#include <array>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr double OUTPUT_FRAME_S = 0.1;

struct CsvWriter {
    std::ofstream out;

    explicit CsvWriter(const fs::path& path) : out(path) {
        if (!out) {
            throw std::runtime_error("cannot open " + path.string());
        }
        out << "scenario,event,sim_time_s,n,thermal_power,Tf,Tc,rho,rho_dollars,"
               "rod_position,rod_target,I_norm,Xe_norm,rho_xe,critical_rod_position,"
               "decay_heat,plant_mode,scram_active,h,substeps,requested_factor\n";
        out << std::setprecision(10);
    }

    void row(const std::string& scenario, const std::string& event,
             const pk::ReactorState& state, const pk::ReactorParams& params,
             float h, int substeps, double requested_factor) {
        const pk::PlantConfig cfg = pk::plant_config(state.plant_mode);
        const float rho = pk::total_rho(state, cfg);
        const float thermal_power = (1.0f - params.total_decay_fraction()) * state.n + state.decay_heat;
        out << scenario << ',' << event << ',' << state.t << ',' << state.n << ',' << thermal_power << ','
            << state.Tf << ',' << state.Tc << ',' << rho << ',' << rho / params.beta_total << ','
            << state.rod_position << ',' << state.rod_target << ',' << state.I_Xe << ',' << state.Xe << ','
            << pk::xenon_rho(state, cfg) << ',' << pk::critical_rod_position(state, cfg) << ','
            << state.decay_heat << ',' << state.plant_mode << ',' << (state.scram_active ? 1 : 0) << ','
            << h << ',' << substeps << ',' << requested_factor << '\n';
    }
};

fs::path output_file(const fs::path& root, const std::string& name) {
    return root / name;
}

int frame_count(double duration_s, double frame_s = OUTPUT_FRAME_S) {
    return static_cast<int>(std::llround(duration_s / frame_s));
}

std::string power_label(float power) {
    std::ostringstream text;
    text << std::fixed << std::setprecision(2) << power;
    std::string value = text.str();
    for (char& character : value) {
        if (character == '.') {
            character = '_';
        }
    }
    return value;
}

void advance_frame(pk::ReactorState& state, const pk::ReactorParams& params,
                   float h, int substeps) {
    pk::advance(state, params, h, substeps);
}

void run_steady_state(const fs::path& root, float power) {
    const std::string scenario = "steady_power_" + power_label(power);
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, power, 0);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    const float h = 1.0e-3f;
    const int substeps = 100;
    for (int frame = 0; frame < frame_count(300.0); ++frame) {
        advance_frame(state, params, h, substeps);
        csv.row(scenario, "", state, params, h, substeps, 10.0);
    }
}

void run_rod_transient(const fs::path& root, float delta, const std::string& label) {
    const std::string scenario = "rod_" + label;
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    const float initial_target = state.rod_target;
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    const float h = 1.0e-3f;
    const int substeps = 100;
    const int frames = frame_count(180.0);
    for (int frame = 0; frame < frames; ++frame) {
        const double before = frame * OUTPUT_FRAME_S;
        std::string event;
        if (std::fabs(before - 20.0) < 1.0e-9) {
            pk::set_rod_target(state, initial_target + delta);
            event = delta > 0.0f ? "withdraw_0.05" : "insert_0.05";
        } else if (std::fabs(before - 80.0) < 1.0e-9) {
            pk::set_rod_target(state, initial_target);
            event = "return_target";
        }
        advance_frame(state, params, h, substeps);
        csv.row(scenario, event, state, params, h, substeps, 10.0);
    }
}

void run_scram_fast(const fs::path& root) {
    const std::string scenario = "scram_fast";
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    const float h = PK_BASE_H;
    const int substeps = 1000;
    for (int frame = 0; frame < frame_count(70.0); ++frame) {
        const double before = frame * OUTPUT_FRAME_S;
        std::string event;
        if (std::fabs(before - 10.0) < 1.0e-9) {
            pk::scram(state);
            event = "scram";
        }
        advance_frame(state, params, h, substeps);
        csv.row(scenario, event, state, params, h, substeps, 1.0);
    }
}

void run_scram_long(const fs::path& root) {
    const std::string scenario = "scram_long";
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    // Establish a short full-power operating interval before SCRAM.
    for (int frame = 0; frame < frame_count(10.0); ++frame) {
        advance_frame(state, params, PK_BASE_H, 1000);
    }
    csv.row(scenario, "pre_scram", state, params, PK_BASE_H, 1000, 1.0);
    pk::scram(state);
    csv.row(scenario, "scram", state, params, 0.0f, 0, 0.0);

    const float h = PK_MAX_H;
    const int substeps = 50; // 0.1 simulated seconds per output row.
    for (int frame = 0; frame < frame_count(7200.0); ++frame) {
        advance_frame(state, params, h, substeps);
        csv.row(scenario, "", state, params, h, substeps, 1.0);
    }
}

void run_xenon_transient(const fs::path& root) {
    const std::string scenario = "xenon_36h";
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    for (int frame = 0; frame < frame_count(10.0); ++frame) {
        advance_frame(state, params, 1.0e-3f, 100);
    }
    pk::scram(state);
    csv.row(scenario, "scram", state, params, 0.0f, 0, 0.0);

    // XENON policy: h=0.002 s, 50,000 substeps, 100 simulated seconds/output row.
    const float h = PK_MAX_H;
    const int substeps = 50000;
    const int frames = frame_count(36.0 * 3600.0, 100.0);
    for (int frame = 0; frame < frames; ++frame) {
        advance_frame(state, params, h, substeps);
        csv.row(scenario, "xenon_batch", state, params, h, substeps, 1000.0);
    }
}

void run_preset_comparison(const fs::path& root) {
    const float delta_rho = 5.0e-4f;
    for (int mode = 0; mode < pk::PLANT_MODES; ++mode) {
        const std::string scenario = "preset_" + std::to_string(mode);
        CsvWriter csv(output_file(root, scenario + ".csv"));
        pk::ReactorParams params;
        pk::ReactorState state;
        pk::reset(state, params, 1.0f, mode);
        const float initial_target = state.rod_target;
        const pk::PlantConfig cfg = pk::plant_config(mode);
        const float target_delta = pk::rod_position_for_rho( pk::rod_rho(initial_target, cfg) + delta_rho, cfg) - initial_target;
        csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

        const float h = 1.0e-3f;
        const int substeps = 100;
        for (int frame = 0; frame < frame_count(180.0); ++frame) {
            const double before = frame * OUTPUT_FRAME_S;
            std::string event;
            if (std::fabs(before - 20.0) < 1.0e-9) {
                pk::set_rod_target(state, initial_target + target_delta);
                event = "same_drho_withdraw";
            } else if (std::fabs(before - 80.0) < 1.0e-9) {
                pk::set_rod_target(state, initial_target);
                event = "return_target";
            }
            advance_frame(state, params, h, substeps);
            csv.row(scenario, event, state, params, h, substeps, 10.0);
        }
    }
}

struct DoubleState {
    static constexpr int SIZE = 1 + pk::PRECURSOR_GROUPS + 2 + pk::DECAY_GROUPS;
    std::array<double, SIZE> value{};
};

DoubleState derivative(const DoubleState& state, const pk::ReactorParams& params,
                       const pk::PlantConfig& cfg, double tf_ref, double tc_ref,
                       double rod_position) {
    DoubleState result{};
    const int n_index = 0;
    const int c_index = 1;
    const int tf_index = c_index + pk::PRECURSOR_GROUPS;
    const int tc_index = tf_index + 1;
    const int decay_index = tc_index + 1;

    const double n = state.value[n_index];
    const double tf = state.value[tf_index];
    const double tc = state.value[tc_index];
    const double two_pi = 6.283185307179586;
    const double worth = rod_position - std::sin(two_pi * rod_position) / two_pi;
    const double rho_rod = cfg.rho_rod_min + worth * (cfg.rho_rod_max - cfg.rho_rod_min);
    const double rho = rho_rod + cfg.alpha_f * (tf - tf_ref) + cfg.alpha_c * (tc - tc_ref);

    double delayed_source = 0.0;
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
        delayed_source += params.lam_i[i] * state.value[c_index + i];
        result.value[c_index + i] = (params.beta_i[i] / params.Lambda) * n
                                   - params.lam_i[i] * state.value[c_index + i];
    }
    result.value[n_index] = ((rho - params.beta_total) / params.Lambda) * n
                          + delayed_source;

    double decay_heat = 0.0;
    for (int i = 0; i < pk::DECAY_GROUPS; ++i) {
        const double group = state.value[decay_index + i];
        result.value[decay_index + i] = params.decay_lambda[i] * (params.decay_fraction[i] * n - group);
        decay_heat += group;
    }
    const double thermal_power = (1.0 - params.total_decay_fraction()) * n + decay_heat;
    result.value[tf_index] = params.K_heat * thermal_power - params.gamma * (tf - tc);
    result.value[tc_index] = params.gamma * (tf - tc) - cfg.gamma_c_active * (tc - params.Tm_const);
    return result;
}

void rk4_step(DoubleState& state, const pk::ReactorParams& params,
              const pk::PlantConfig& cfg, double tf_ref, double tc_ref,
              double rod_position, double h) {
    const DoubleState k1 = derivative(state, params, cfg, tf_ref, tc_ref, rod_position);
    DoubleState temporary = state;
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        temporary.value[i] = state.value[i] + 0.5 * h * k1.value[i];
    }
    const DoubleState k2 = derivative(temporary, params, cfg, tf_ref, tc_ref, rod_position);
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        temporary.value[i] = state.value[i] + 0.5 * h * k2.value[i];
    }
    const DoubleState k3 = derivative(temporary, params, cfg, tf_ref, tc_ref, rod_position);
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        temporary.value[i] = state.value[i] + h * k3.value[i];
    }
    const DoubleState k4 = derivative(temporary, params, cfg, tf_ref, tc_ref, rod_position);
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        state.value[i] += (h / 6.0) * (k1.value[i] + 2.0 * k2.value[i]
                                     + 2.0 * k3.value[i] + k4.value[i]);
    }
}

DoubleState to_double_state(const pk::ReactorState& source) {
    DoubleState result{};
    int index = 0;
    result.value[index++] = source.n;
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
        result.value[index++] = source.C[i];
    }
    result.value[index++] = source.Tf;
    result.value[index++] = source.Tc;
    for (int i = 0; i < pk::DECAY_GROUPS; ++i) {
        result.value[index++] = source.decay_group[i];
    }
    return result;
}

void run_timestep_convergence(const fs::path& root) {
    std::ofstream out(output_file(root, "rk4_convergence.csv"));
    if (!out) {
        throw std::runtime_error("cannot open rk4_convergence.csv");
    }
    out << "h_s,sim_time_s,ref_n,test_n,error_n,ref_Tf,test_Tf,error_Tf,ref_Tc,test_Tc,error_Tc\n";
    out << std::setprecision(12);

    pk::ReactorParams params;
    pk::ReactorState initial;
    pk::reset(initial, params, 1.0f, 0);
    initial.rod_position = 0.80f;
    initial.rod_target = 0.80f;
    const pk::PlantConfig cfg = pk::plant_config(0);
    const DoubleState initial_reference = to_double_state(initial);
    const double reference_h = 1.0e-5;
    const int samples = 1000;
    const int reference_steps_per_sample = 1000;

    for (const float test_h : {1.0e-4f, 5.0e-4f, 1.0e-3f, 2.0e-3f}) {
        DoubleState reference = initial_reference;
        pk::ReactorState test = initial;
        const int test_steps_per_sample = static_cast<int>(std::llround(0.01 / test_h));
        for (int sample = 1; sample <= samples; ++sample) {
            for (int i = 0; i < reference_steps_per_sample; ++i) {
                rk4_step(reference, params, cfg, initial.Tf_ref, initial.Tc_ref, 0.80, reference_h);
            }
            for (int i = 0; i < test_steps_per_sample; ++i) {
                pk::step(test, params, test_h);
            }
            const int tf_index = 1 + pk::PRECURSOR_GROUPS;
            const int tc_index = tf_index + 1;
            const double ref_n = reference.value[0];
            const double ref_tf = reference.value[tf_index];
            const double ref_tc = reference.value[tc_index];
            out << test_h << ',' << sample * 0.01 << ',' << ref_n << ',' << test.n << ','
                << (static_cast<double>(test.n) - ref_n) << ',' << ref_tf << ',' << test.Tf << ','
                << (static_cast<double>(test.Tf) - ref_tf) << ',' << ref_tc << ',' << test.Tc << ','
                << (static_cast<double>(test.Tc) - ref_tc) << '\n';
        }
    }
}

struct PerformanceMode {
    const char* name;
    float h;
    int substeps;
    double requested_factor;
};

void run_performance(const fs::path& root) {
    std::ofstream out(output_file(root, "performance_frames.csv"));
    if (!out) {
        throw std::runtime_error("cannot open performance_frames.csv");
    }
    out << "mode,frame,simulated_frame_s,wall_compute_s,kernel_throughput_factor,missed_100ms_deadline,n\n";
    out << std::setprecision(12);

    const PerformanceMode modes[] = {
        {"REALTIME", PK_BASE_H, 1000, 1.0},
        {"TRAINING", 1.0e-3f, 1000, 10.0},
        {"XENON", PK_MAX_H, 50000, 1000.0}
    };

    pk::ReactorParams params;
    volatile float anti_opt = 0.0f;
    for (const PerformanceMode& mode : modes) {
        pk::ReactorState state;
        pk::reset(state, params, 1.0f, 0);
        for (int i = 0; i < 10; ++i) {
            advance_frame(state, params, mode.h, mode.substeps);
        }
        const double simulated_frame_s = static_cast<double>(mode.h) * mode.substeps;
        for (int frame = 0; frame < 1000; ++frame) {
            const auto start = std::chrono::steady_clock::now();
            advance_frame(state, params, mode.h, mode.substeps);
            const std::chrono::duration<double> elapsed = std::chrono::steady_clock::now() - start;
            const double wall_s = elapsed.count();
            out << mode.name << ',' << frame << ',' << simulated_frame_s << ',' << wall_s << ','
                << (simulated_frame_s / wall_s) << ',' << (wall_s > OUTPUT_FRAME_S ? 1 : 0) << ','
                << state.n << '\n';
        }
        anti_opt += state.n;
    }
    std::cerr << "Performance anti-optimization value: " << anti_opt << '\n';
}

void run_fpga_parity_rod(const fs::path& root, float delta, const std::string& label) {
    const std::string scenario = "rod_" + label;
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    const float initial_target = state.rod_target;
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    const float h = pk::TimePolicy::base_h();
    const int substeps = 1000;
    for (int frame = 0; frame < frame_count(180.0); ++frame) {
        const double before = frame * OUTPUT_FRAME_S;
        std::string event;
        if (std::fabs(before - 20.0) < 1.0e-9) {
            pk::set_rod_target(state, initial_target + delta);
            event = delta > 0.0f ? "withdraw_0.05" : "insert_0.05";
        } else if (std::fabs(before - 80.0) < 1.0e-9) {
            pk::set_rod_target(state, initial_target);
            event = "return_target";
        }
        advance_frame(state, params, h, substeps);
        csv.row(scenario, event, state, params, h, substeps, 1.0);
    }
}

void run_fpga_parity_preset(const fs::path& root, int mode) {
    const std::string scenario = "preset_" + std::to_string(mode);
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, mode);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);
    const float h = pk::TimePolicy::base_h();
    const int substeps = 1000;
    for (int frame = 0; frame < frame_count(5.0); ++frame) {
        advance_frame(state, params, h, substeps);
        csv.row(scenario, "", state, params, h, substeps, 1.0);
    }
}

void run_fpga_parity_xenon(const fs::path& root) {
    const std::string scenario = "xenon_36h";
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);
    for (int frame = 0; frame < frame_count(10.0); ++frame) {
        advance_frame(state, params, pk::TimePolicy::base_h(), 1000);
    }
    pk::scram(state);
    csv.row(scenario, "scram", state, params, 0.0f, 0, 0.0);
    const float h = pk::TimePolicy::max_h();
    const int substeps = 50000;
    for (int frame = 0; frame < frame_count(36.0 * 3600.0, 100.0); ++frame) {
        advance_frame(state, params, h, substeps);
        csv.row(scenario, "xenon_batch", state, params, h, substeps, 1000.0);
    }
}

void run_fpga_hardware_xenon_reference(const fs::path& root) {
    const std::string scenario = "xenon_hardware_capture";
    CsvWriter csv(output_file(root, scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    csv.row(scenario, "reset", state, params, 0.0f, 0, 0.0);

    // Match the recorded physical command timeline: SCRAM arrived at 1.6 s;
    // M2 was selected after ten 0.1 s realtime frames, at 2.6 s.
    for (int frame = 0; frame < 16; ++frame) {
        advance_frame(state, params, pk::TimePolicy::base_h(), 1000);
        csv.row(scenario, "", state, params, pk::TimePolicy::base_h(), 1000, 1.0);
    }
    pk::scram(state);
    for (int frame = 0; frame < 10; ++frame) {
        advance_frame(state, params, pk::TimePolicy::base_h(), 1000);
        csv.row(scenario, frame == 0 ? "scram" : "", state, params, pk::TimePolicy::base_h(), 1000, 1.0);
    }
    const float h = pk::TimePolicy::max_h();
    const int substeps = 50000;
    for (int frame = 0; frame < 1297; ++frame) {
        advance_frame(state, params, h, substeps);
        csv.row(scenario, "xenon_batch", state, params, h, substeps, 1000.0);
    }
}

void run_fpga_parity_references(const fs::path& root) {
    fs::create_directories(root);
    run_fpga_parity_rod(root, 0.05f, "withdrawal");
    run_fpga_parity_rod(root, -0.05f, "insertion");
    for (int mode = 0; mode < 3; ++mode) {
        run_fpga_parity_preset(root, mode);
    }
    run_fpga_parity_xenon(root);
    run_fpga_hardware_xenon_reference(root);
}

void run_campaign(const fs::path& root) {
    fs::create_directories(root);
    for (const float power : {0.10f, 0.50f, 1.00f, 1.50f}) {
        std::cerr << "[campaign] steady power " << power << '\n';
        run_steady_state(root, power);
    }
    std::cerr << "[campaign] rod transients\n";
    run_rod_transient(root, 0.05f, "withdrawal");
    run_rod_transient(root, -0.05f, "insertion");
    std::cerr << "[campaign] SCRAM scenarios\n";
    run_scram_fast(root);
    run_scram_long(root);
    std::cerr << "[campaign] 36-hour xenon scenario\n";
    run_xenon_transient(root);
    std::cerr << "[campaign] three-preset comparison\n";
    run_preset_comparison(root);
    std::cerr << "[campaign] RK4 timestep convergence\n";
    run_timestep_convergence(root);
    std::cerr << "[campaign] PC physics-kernel performance\n";
    run_performance(root);
}

} // namespace

int main(int argc, char** argv) {
    fs::path output = fs::path("experiments") / "results" / "latest";
    bool fpga_parity = false;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--output-dir" && i + 1 < argc) {
            output = argv[++i];
        } else if (argument == "--fpga-parity") {
            fpga_parity = true;
        } else if (argument == "--help") {
            std::cout << "Usage: run_pc_campaign [--output-dir DIR] [--fpga-parity]\n";
            return 0;
        } else {
            std::cerr << "Unknown argument: " << argument << '\n';
            return 2;
        }
    }

    try {
        if (fpga_parity) {
            run_fpga_parity_references(output);
        } else {
            run_campaign(output);
        }
    } catch (const std::exception& error) {
        std::cerr << "Campaign failed: " << error.what() << '\n';
        return 1;
    }
    std::cout << "PC campaign completed: " << output << '\n';
    return 0;
}
