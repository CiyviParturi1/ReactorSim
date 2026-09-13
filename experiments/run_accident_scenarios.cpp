#include "../common/point_kinetics_core.h"

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;

namespace {

struct CsvWriter {
    std::ofstream out;

    explicit CsvWriter(const fs::path& path) : out(path) {
        if (!out) {
            throw std::runtime_error("cannot open " + path.string());
        }
        out << "scenario,event,sim_time_s,n,thermal_power,Tf,Tc,rho,rho_dollars,"
               "rod_position,rod_target,I_norm,Xe_norm,rho_xe,decay_heat,plant_mode,"
               "scram_active,numerical_fault\n";
        out << std::setprecision(10);
    }

    void row(const std::string& scenario, const std::string& event,
             const pk::ReactorState& state, const pk::ReactorParams& params) {
        const pk::PlantConfig cfg = pk::plant_config(state.plant_mode);
        const float rho = pk::total_rho(state, cfg);
        const float thermal = (1.0f - params.total_decay_fraction()) * state.n + state.decay_heat;
        out << scenario << ',' << event << ',' << state.t << ',' << state.n << ',' << thermal << ','
            << state.Tf << ',' << state.Tc << ',' << rho << ',' << rho / params.beta_total << ','
            << state.rod_position << ',' << state.rod_target << ',' << state.I_Xe << ',' << state.Xe << ','
            << pk::xenon_rho(state, cfg) << ',' << state.decay_heat << ',' << state.plant_mode << ','
            << (state.scram_active ? 1 : 0) << ',' << (state.numerical_fault ? 1 : 0) << '\n';
    }
};

void prepare_xenon_poisoned_low_power(pk::ReactorState& state,
                                      const pk::ReactorParams& params,
                                      int mode) {
    pk::reset(state, params, 0.0625f, mode);
    state.I_Xe = 1.0f;
    state.Xe = 1.25f;
    state.I_compensation = 0.0f;
    state.Xe_compensation = 0.0f;
    const pk::PlantConfig cfg = pk::plant_config(mode);
    state.rod_position = pk::critical_rod_position(state, cfg);
    state.rod_target = state.rod_position;
    state.rod_motion_residual = 0.0f;
}

void run_chernobyl_case(const fs::path& output, int mode, bool legacy_shutdown) {
    const std::string scenario = legacy_shutdown ? "chernobyl_rbmk_like" : "chernobyl_modern_pwr";
    CsvWriter csv(output / (scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    prepare_xenon_poisoned_low_power(state, params, mode);
    csv.row(scenario, "xenon_poisoned_low_power_initial", state, params);

    const float h = pk::TimePolicy::base_h();
    const int substeps = 1000; // 0.1 simulated seconds per row.
    const pk::PlantConfig cfg = pk::plant_config(mode);
    const float inserted_rho = 2.5e-3f;
    const float start_worth = pk::rod_rho(state.rod_position, cfg);
    const float target_delta = pk::rod_position_for_rho(start_worth + inserted_rho, cfg) - state.rod_position;

    for (int frame = 0; frame < 1200; ++frame) {
        std::string event;
        if (frame == 200) {
            pk::set_rod_target(state, state.rod_target + target_delta);
            event = "test_start_and_rod_withdrawal";
        }
        if (frame == 560) {
            event = legacy_shutdown ? "az5_command_shutdown_delayed" : "automatic_scram";
            if (!legacy_shutdown) {
                pk::scram(state);
            }
        }
        if (legacy_shutdown && frame == 620) {
            pk::scram(state);
            event = "delayed_negative_shutdown_insertion";
        }
        if (!event.empty()) {
            csv.row(scenario, event, state, params);
        }
        pk::advance(state, params, h, substeps);
        csv.row(scenario, "", state, params);
    }
}

void run_tmi_case(const fs::path& output, int mode) {
    const bool loss_case = mode == 2;
    const std::string scenario = loss_case ? "tmi_loss_of_cooling" : "tmi_modern_pwr";
    CsvWriter csv(output / (scenario + ".csv"));
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, mode);
    csv.row(scenario, "loss_of_feedwater", state, params);

    const float h = pk::TimePolicy::max_h();
    const int substeps = 500; // 1 simulated second per integration frame.
    for (int second = 0; second < 4 * 3600; ++second) {
        std::string event;
        if (second == 12) {
            pk::scram(state);
            event = "reactor_trip";
        } else if (second == 600) {
            event = loss_case ? "coolant_loss_and_pump_reduction" : "residual_heat_removal_operating";
            if (loss_case) {
                // Reduce fuel-to-coolant heat transfer to represent lost inventory
                // and forced circulation. This change applies only to this scenario.
                params.gamma = 0.010f;
            }
        } else if (second == 6300) {
            event = loss_case ? "core_uncovery_heatup_surrogate_begins"
                              : "historical_core_heatup_window_begins";
            if (loss_case) {
                // Very weak coupling represents uncovered fuel no longer cooled by
                // bulk water. The larger temperature gain represents the smaller
                // effective thermal mass. Decay heat remains the only heat source.
                params.gamma = 0.00025f;
                params.K_heat = 25.0f;
            }
        } else if (second == 8280) {
            event = loss_case ? "relief_valve_isolated_and_cooling_restored"
                              : "historical_relief_valve_isolation_time";
            if (loss_case) {
                params.gamma = PK_FUEL_COUPLING;
                params.K_heat = PK_K_HEAT;
                state.plant_mode = 0;
            }
        }
        if (!event.empty()) {
            csv.row(scenario, event, state, params);
        }
        pk::advance(state, params, h, substeps);
        csv.row(scenario, "", state, params);
    }
}

} // namespace

int main(int argc, char** argv) {
    fs::path output = fs::path("experiments") / "results" / "accident_pc";
    if (argc == 3 && std::string(argv[1]) == "--output-dir") {
        output = argv[2];
    } else if (argc != 1) {
        std::cerr << "Usage: run_accident_scenarios [--output-dir DIR]\n";
        return 2;
    }

    try {
        fs::create_directories(output);
        run_chernobyl_case(output, 1, true);
        run_chernobyl_case(output, 0, false);
        run_tmi_case(output, 2);
        run_tmi_case(output, 0);
    } catch (const std::exception& error) {
        std::cerr << "Accident campaign failed: " << error.what() << '\n';
        return 1;
    }
    std::cout << "PC accident campaign completed: " << output << '\n';
    return 0;
}
