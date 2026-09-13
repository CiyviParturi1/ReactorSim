// Map the published CATS Table 6a adiabatic Doppler case onto the test fixture's
// fuel-temperature feedback path. The fixture does not change production code.
#include "../common/point_kinetics_core.h"

#include <array>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

constexpr float H = 1.0e-4f;
constexpr float B = 2.5e-6f;  // CATS Table 6a: rho / (MW s)
constexpr float TRIV_BETA_TOTAL = 0.00645f;  // Sum of the six published beta_i values.
constexpr double MAX_CHECKPOINT_RELATIVE_ERROR = 0.015;

struct Checkpoint {
    int time_s;
    double reference_n;
};

constexpr std::array<Checkpoint, 11> CHECKPOINTS{{
    {1, 805.2781254488}, {10, 131.9458587776}, {20, 51.67559913980},
    {30, 28.16547812308}, {40, 18.14181257533}, {50, 12.77696143166},
    {60, 9.473241952811}, {70, 7.243300206432}, {80, 5.645428375455},
    {90, 4.456183708438}, {100, 3.549601214084},
}};

pk::ReactorParams cats_triv_parameters() {
    pk::ReactorParams params;
    params.Lambda = 5.0e-5f;
    params.beta_total = TRIV_BETA_TOTAL;
    const float beta[pk::PRECURSOR_GROUPS] = {0.00021f, 0.00141f, 0.00127f,
                                               0.00255f, 0.00074f, 0.00027f};
    const float lambda[pk::PRECURSOR_GROUPS] = {0.0124f, 0.0305f, 0.111f,
                                                 0.301f, 1.14f, 3.00f};
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
        params.beta_i[i] = beta[i];
        params.lam_i[i] = lambda[i];
    }

    // CATS uses rho = rho_0 - B * integral(N dt). Mode 0 has the production
    // fuel coefficient alpha_f = -2.5e-5 / C, so K_heat = B / -alpha_f = 0.1.
    // Negligible fuel-to-coolant conductance makes the test fuel node
    // adiabatic. Calling step() directly and setting the decay fractions to
    // zero removes decay heat and poison feedback from this fixture.
    params.K_heat = 0.1f;
    params.gamma = 1.0e-9f;
    for (int i = 0; i < pk::DECAY_GROUPS; ++i) {
        params.decay_fraction[i] = 0.0f;
    }
    return params;
}

void set_adiabatic_initial_state(pk::ReactorState& state, const pk::ReactorParams& params) {
    pk::reset(state, params, 1.0f, 0);
    // reset() constructs a steady-state plant temperature. The benchmark is
    // instead adiabatic and starts from its feedback reference temperature.
    state.Tf = params.Tm_const;
    state.Tc = params.Tm_const;
    state.Tf_ref = params.Tm_const;
    state.Tc_ref = params.Tm_const;
    state.I_Xe = 1.0f;
    state.Xe = 1.0f;
}

float imposed_step_rho(const pk::ReactorState& state, const pk::PlantConfig& cfg) {
    // The rod is a test-only actuator for the prescribed CATS +1$ insertion.
    // Cancel the tiny coolant term so total rho is rho_step + fuel_rho.
    const float rho_step = TRIV_BETA_TOTAL;
    const float target = rho_step - pk::coolant_rho(state, cfg) - pk::xenon_rho(state, cfg);
    return pk::rod_position_for_rho(target, cfg);
}

void write_trace_header(std::ofstream& out) {
    out << "time_s,simulator_n,fuel_temperature_C,feedback_rho,total_rho\n";
}

}  // namespace

int main(int argc, char** argv) {
    std::string checkpoint_path;
    std::string trace_path;
    for (int i = 1; i + 1 < argc; ++i) {
        if (std::string(argv[i]) == "--csv") checkpoint_path = argv[++i];
        else if (std::string(argv[i]) == "--trace") trace_path = argv[++i];
    }

    std::ofstream checkpoint_csv;
    if (!checkpoint_path.empty()) {
        checkpoint_csv.open(checkpoint_path);
        checkpoint_csv << "scenario,time_s,reference_n,simulator_n,relative_error\n";
    }
    std::ofstream trace_csv;
    if (!trace_path.empty()) {
        trace_csv.open(trace_path);
        write_trace_header(trace_csv);
    }

    const pk::ReactorParams params = cats_triv_parameters();
    const pk::PlantConfig cfg = pk::plant_config(0);
    pk::ReactorState state{};
    set_adiabatic_initial_state(state, params);
    int checkpoint_index = 0;
    double worst_error = 0.0;

    constexpr int TOTAL_STEPS = 1000000;
    for (int step = 1; step <= TOTAL_STEPS; ++step) {
        const float position = imposed_step_rho(state, cfg);
        state.rod_position = position;
        state.rod_target = position;
        pk::step(state, params, H);
        if (state.numerical_fault) {
            std::cerr << "FAIL: numerical fault in CATS Doppler feedback fixture\n";
            return 1;
        }

        const int elapsed_steps = step;
        // Retain every 0.1 ms solver state. The plotting workflow draws this
        // dense trajectory and overlays only the published CATS checkpoints.
        if (!trace_path.empty()) {
            trace_csv << std::setprecision(10) << state.t << ',' << state.n << ',' << state.Tf << ','
                      << pk::fuel_rho(state, cfg) << ',' << pk::total_rho(state, cfg) << '\n';
        }
        if (checkpoint_index < static_cast<int>(CHECKPOINTS.size()) &&
            elapsed_steps == CHECKPOINTS[checkpoint_index].time_s * 10000) {
            const Checkpoint& checkpoint = CHECKPOINTS[checkpoint_index++];
            const double error = std::fabs(static_cast<double>(state.n) - checkpoint.reference_n)
                                 / checkpoint.reference_n;
            worst_error = std::max(worst_error, error);
            std::cout << "CATS Doppler t=" << checkpoint.time_s << " s ref=" << checkpoint.reference_n
                      << " sim=" << state.n << " rel_error=" << error << '\n';
            if (checkpoint_csv.is_open()) {
                checkpoint_csv << std::setprecision(12) << "CATS TRIV +1$ adiabatic Doppler," << checkpoint.time_s
                               << ',' << checkpoint.reference_n << ',' << state.n << ',' << error << '\n';
            }
        }
    }

    if (checkpoint_index != static_cast<int>(CHECKPOINTS.size()) || worst_error > MAX_CHECKPOINT_RELATIVE_ERROR) {
        std::cerr << "FAIL: CATS Doppler maximum checkpoint relative error=" << worst_error
                  << " (limit " << MAX_CHECKPOINT_RELATIVE_ERROR << ")\n";
        return 1;
    }
    std::cout << "PASS: CATS TRIV +1$ adiabatic Doppler feedback, max checkpoint error="
              << worst_error * 100.0 << "%\n";
    return 0;
}
