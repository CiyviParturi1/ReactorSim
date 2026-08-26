#include "../hls/point_kinetics_hls/point_kinetics.h"

#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

const char* plant_name(int mode) {
    if (mode == 1) {
        return "RBMK-like Demonstrator";
    }
    if (mode == 2) {
        return "TMI-inspired Cooling Loss";
    }
    return "PWR-SMR Passive Safe";
}

void run_simulation_host(ReactorSim& sim, float wall_output_interval) {
    std::mutex command_mutex;
    std::vector<std::string> pending_commands;
    std::thread input_thread([&]() {
        std::string line;
        while (std::getline(std::cin, line)) {
            std::lock_guard<std::mutex> lock(command_mutex);
            pending_commands.push_back(line);
        }
    });
    input_thread.detach();

    std::cout << "DATA_START\n";
    std::cerr << "[TIME] Mode: " << sim.tc.name() << "  h=" << sim.tc.h() << "s\n";

    typedef std::chrono::steady_clock Clock;
    const Clock::duration frame_period = std::chrono::duration_cast<Clock::duration>( std::chrono::duration<double>(wall_output_interval));
    Clock::time_point next_deadline = Clock::now() + frame_period;
    Clock::time_point previous_frame_start = Clock::now();
    bool have_previous_frame = false;

    while (true) {
        const Clock::time_point frame_start = Clock::now();
        double measured_wall_interval = wall_output_interval;
        if (have_previous_frame) {
            measured_wall_interval = std::chrono::duration<double>( frame_start - previous_frame_start).count();
        }
        have_previous_frame = true;
        previous_frame_start = frame_start;
        if (measured_wall_interval <= 0.0) {
            measured_wall_interval = wall_output_interval;
        }
        {
            std::lock_guard<std::mutex> lock(command_mutex);
            for (std::size_t index = 0; index < pending_commands.size(); ++index) {
                const std::string& command = pending_commands[index];
                if (command.empty()) {
                    continue;
                }

                const char code = command[0];
                if (code == '+') {
                    pk::set_rod_target(sim, sim.rod_target + 0.01f);
                } else if (code == '-') {
                    pk::set_rod_target(sim, sim.rod_target - 0.01f);
                } else if (code == 'W' || code == 'w') {
                    std::istringstream stream(command.substr(1));
                    float target = 0.0f;
                    if (stream >> target) {
                        pk::set_rod_target(sim, target);
                    }
                } else if (code == 'R' || code == 'r') {
                    sim.scram();
                } else if (code == 'K' || code == 'k') {
                    sim.reset_scram_trip();
                } else if (code == 'P' || code == 'p') {
                    std::istringstream stream(command.substr(1));
                    float power = 1.0f;
                    if (stream >> power && pk::finite(power) && power >= 0.0f) {
                        sim.initialize(power);
                        std::cerr << "[INIT] Power fraction=" << sim.n << "  Tf=" << sim.Tf << "  Tc=" << sim.Tc << '\n';
                    }
                } else if (code == 'C' || code == 'c') {
                    if (command.size() >= 2 && command[1] >= '0' && command[1] <= '2') {
                        sim.plant_mode = command[1] - '0';
                        sim.initialize(1.0f);
                        std::cerr << "[PLANT] Switched to " << plant_name(sim.plant_mode) << " and reinitialized (power=1.0).\n";
                    }
                } else if (code == 'M' || code == 'm') {
                    if (command.size() >= 2) {
                        if (command[1] == '0') {
                            sim.tc.set_mode(TimeMode::REALTIME);
                        } else if (command[1] == '1') {
                            sim.tc.set_mode(TimeMode::TRAINING);
                        } else if (command[1] == '2') {
                            sim.tc.set_mode(TimeMode::XENON);
                        }
                        std::cerr << "[TIME] Switched to " << sim.tc.name() << "  h=" << sim.tc.h() << "s  requested=" << sim.tc.factor << "x\n";
                    }
                } else if (code == 'T' || code == 't') {
                    std::istringstream stream(command.substr(1));
                    float factor = 1.0f;
                    if (stream >> factor && pk::finite(factor) && factor >= 1.0f) {
                        sim.tc.set_custom(factor);
                        std::cerr << "[TIME] Custom requested=" << sim.tc.factor << "x  h=" << sim.tc.h() << "s\n";
                    }
                } else if (code == 'S' || code == 's') {
                    std::istringstream stream(command.substr(1));
                    float source = 0.0f;
                    if (stream >> source && pk::finite(source)) {
                        sim.source_q = pk::clamp(source, 0.0f, PK_SOURCE_Q_MAX);
                        std::cerr << "[SOURCE] External neutron source set to " << sim.source_q << '\n';
                    }
                }
            }
            pending_commands.clear();
        }

        const float h = sim.tc.h();
        const double requested_advance = static_cast<double>(wall_output_interval) * sim.tc.factor;
        const double requested_step_count = requested_advance / h;
        int steps = pk::MAX_SUBSTEPS;
        if (std::isfinite(requested_step_count) && requested_step_count < pk::MAX_SUBSTEPS) {
            const long long rounded = std::llround(requested_step_count);
            steps = rounded < 1 ? 1 : static_cast<int>(rounded);
        }
        const float achieved_factor = static_cast<float>( (steps * h) / measured_wall_interval);

        const Clock::time_point compute_start = Clock::now();
        pk::advance(static_cast<pk::ReactorState&>(sim), sim.p, h, steps);
        const std::chrono::duration<double> compute_elapsed = Clock::now() - compute_start;
        const double step_real_time = compute_elapsed.count() / steps;

        const PlantConfig config = pk::plant_config(sim.plant_mode);
        const float rho = sim.get_total_rho(config);
        const float beta = sim.p.beta_total;
        const float rho_rod_dlr = pk::rod_rho(sim, config) / beta;
        const float rho_fuel_dlr = pk::fuel_rho(sim, config) / beta;
        const float rho_coolant_dlr = pk::coolant_rho(sim, config) / beta;
        const float rho_xenon_dlr = pk::xenon_rho(sim, config) / beta;
        const float rod_critical = pk::critical_rod_position(sim, config);

        std::cout << std::fixed << std::setprecision(6) << sim.t << ',' << sim.n << ',' << sim.Tf << ',' << rho << ',' << rho / beta << ',' << sim.Tc << ',' << sim.I_Xe << ',' << sim.Xe << ','
                  << sim.get_xe_rho(config) << ',' << achieved_factor << ',' << sim.rod_position << ',' << sim.rod_target << ',' << (sim.numerical_fault ? 0 : sim.engine_order) << ','
                  << std::scientific << std::setprecision(9) << h << ',' << step_real_time << ',' << std::fixed << std::setprecision(6) << sim.decay_heat << ',' << sim.plant_mode << ','
                  << rho_rod_dlr << ',' << rho_fuel_dlr << ',' << rho_coolant_dlr << ',' << rho_xenon_dlr << ',' << rod_critical << ',' << static_cast<float>(sim.scram_active) << std::endl;

        const Clock::time_point now = Clock::now();
        if (now < next_deadline) {
            std::this_thread::sleep_until(next_deadline);
            next_deadline += frame_period;
        } else {
            // Do not add a full extra frame after computation. Re-anchor if the
            // solver cannot keep up, so reported achieved compression remains honest.
            next_deadline = now + frame_period;
            std::cerr << "[TIME] Frame deadline missed; achieved physics factor=" << achieved_factor << "x\n";
        }
    }
}

} // namespace

int main() {
    ReactorSim sim;
    std::cerr << "=== Point-Kinetics Reactor Simulator + Time Compression ===\n" << "Equilibrium Iodine : " << sim.I_Xe << '\n' << "Equilibrium Xenon  : " << sim.Xe << "\n\n"
              << "TIME: M0=REALTIME(1x), M1=TRAINING(10x), " "M2=XENON(1000x), T <factor>=CUSTOM\n" << "RESET: P <power>; PLANT: C0=PWR-SMR, " "C1=RBMK-like, C2=TMI-loss\n"
              << "RODS: +/- adjust target, W <0..1> sets target, R=SCRAM\n" << "SOURCE: S <0..0.01> sets the external neutron source\n" << "Canonical timestep: base=1e-4s, maximum=0.002s; " "output is paced at 10 Hz.\n"
              << "MODEL: grouped decay heat contributes 6.6% at equilibrium; " "prompt thermal " "power contributes 93.4%.\n\n";
    run_simulation_host(sim, PK_WALL_OUTPUT_INTERVAL);
    return 0;
}
