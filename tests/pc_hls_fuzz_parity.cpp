#include "../hls/point_kinetics_hls/point_kinetics.h"

#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>

namespace {

constexpr int COMMAND_COUNT = 10000;

struct Outputs {
    float t, n, tf, tc, iodine, xenon, rho, dollars, rho_xe;
    float rod_position, rod_target, factor, order, target_h, decay, plant;
    float precursors[pk::PRECURSOR_GROUPS];
    float scram_active, source_q;
};

struct Command {
    float h;
    int substeps;
    float reset, reset_power, withdraw, insert, scram;
    float set_target, target;
    int plant;
    float plant_update, clear_scram, set_source, source;
};

struct Random {
    std::uint32_t state = 0x5EED1234u;

    std::uint32_t next() {
        state = state * 1664525u + 1013904223u;
        return state;
    }

    bool chance(std::uint32_t numerator, std::uint32_t denominator) {
        return next() % denominator < numerator;
    }

    float unit() {
        return static_cast<float>((next() >> 8) * (1.0 / 16777215.0));
    }
};

bool near(float actual, float expected) {
    return std::fabs(actual - expected) <= 2.0e-5f * (1.0f + std::fabs(actual) + std::fabs(expected));
}

void call_top(const Command& command, Outputs& out) {
    point_kinetics_step(command.h, command.substeps, 1.0f, command.reset, command.reset_power,
                        command.withdraw, command.insert, command.scram,
                        &out.t, &out.n, &out.tf, &out.tc, &out.iodine, &out.xenon,
                        &out.rho, &out.dollars, &out.rho_xe, &out.rod_position, &out.rod_target,
                        &out.factor, &out.order, out.precursors, command.set_target, command.target,
                        command.plant, command.plant_update, &out.target_h, &out.decay, &out.plant,
                        command.clear_scram, &out.scram_active, command.set_source, command.source,
                        &out.source_q);
}

void apply_to_core(pk::ReactorState& state, const pk::ReactorParams& params, bool& initialized,
                   const Command& command) {
    const bool plant_update = command.plant_update > 0.5f;
    if (!initialized || command.reset > 0.5f || plant_update) {
        const int mode = plant_update ? pk::clamp(command.plant, 0, pk::PLANT_MODES - 1)
                                      : (initialized ? state.plant_mode : 0);
        pk::reset(state, params, command.reset_power, mode);
        initialized = true;
    }
    if (command.set_target > 0.5f) {
        pk::set_rod_target(state, command.target);
    } else if (command.withdraw > 0.5f && command.insert <= 0.5f) {
        pk::set_rod_target(state, state.rod_target + 0.01f);
    } else if (command.insert > 0.5f && command.withdraw <= 0.5f) {
        pk::set_rod_target(state, state.rod_target - 0.01f);
    }
    if (command.scram > 0.5f) {
        pk::scram(state);
    }
    if (command.clear_scram > 0.5f) {
        pk::reset_scram_trip(state);
    }
    if (command.set_source > 0.5f) {
        state.source_q = pk::clamp(command.source, 0.0f, PK_SOURCE_Q_MAX);
    }
    pk::advance(state, params, command.h, command.substeps);
}

bool finite_and_bounded(const pk::ReactorState& state) {
    if (!pk::finite(state.t) || !pk::finite(state.n) || !pk::finite(state.Tf) || !pk::finite(state.Tc)
        || !pk::finite(state.I_Xe) || !pk::finite(state.Xe) || state.n < 0.0f
        || state.rod_position < 0.0f || state.rod_position > 1.0f
        || state.rod_target < 0.0f || state.rod_target > 1.0f) {
        return false;
    }
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
        if (!pk::finite(state.C[i]) || state.C[i] < 0.0f) {
            return false;
        }
    }
    return true;
}

bool matches(const pk::ReactorState& state, const pk::ReactorParams& params, const Outputs& out,
             int frame, const Command& command) {
    const pk::PlantConfig cfg = pk::plant_config(state.plant_mode);
    const float expected[] = {
        state.t, state.n, state.Tf, state.Tc, state.I_Xe, state.Xe,
        pk::total_rho(state, cfg), pk::total_rho(state, cfg) / params.beta_total,
        pk::xenon_rho(state, cfg), state.rod_position, state.rod_target,
        command.h, state.decay_heat, static_cast<float>(state.plant_mode),
        state.scram_active ? 1.0f : 0.0f, state.source_q,
    };
    const float actual[] = {
        out.t, out.n, out.tf, out.tc, out.iodine, out.xenon, out.rho, out.dollars,
        out.rho_xe, out.rod_position, out.rod_target, out.target_h, out.decay,
        out.plant, out.scram_active, out.source_q,
    };
    const char* labels[] = {
        "t", "n", "Tf", "Tc", "iodine", "xenon", "rho", "dollars", "rho_xe",
        "rod_position", "rod_target", "target_h", "decay", "plant", "scram", "source_q",
    };
    for (int i = 0; i < 16; ++i) {
        if (!near(actual[i], expected[i])) {
            std::cerr << "FAIL frame " << frame << " field " << labels[i]
                      << " HLS=" << actual[i] << " core=" << expected[i] << '\n';
            return false;
        }
    }
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
        if (!near(out.precursors[i], state.C[i])) {
            std::cerr << "FAIL frame " << frame << " precursor " << i
                      << " HLS=" << out.precursors[i] << " core=" << state.C[i] << '\n';
            return false;
        }
    }
    if (!near(out.order, state.numerical_fault ? 0.0f : 1.0f)) {
        std::cerr << "FAIL frame " << frame << " engine order mismatch\n";
        return false;
    }
    return true;
}

Command make_command(Random& random, int frame) {
    const float h_choices[] = {PK_BASE_H, 1.0e-3f, PK_MAX_H};
    Command command = {};
    command.h = h_choices[random.next() % 3];
    command.substeps = 1 + static_cast<int>(random.next() % 8);
    command.reset = (frame == 0 || random.chance(1, 97)) ? 1.0f : 0.0f;
    command.reset_power = 1.5f * random.unit();
    command.withdraw = random.chance(1, 9) ? 1.0f : 0.0f;
    command.insert = random.chance(1, 9) ? 1.0f : 0.0f;
    command.scram = random.chance(1, 71) ? 1.0f : 0.0f;
    command.set_target = random.chance(1, 5) ? 1.0f : 0.0f;
    command.target = random.unit();
    command.plant = static_cast<int>(random.next() % pk::PLANT_MODES);
    command.plant_update = random.chance(1, 83) ? 1.0f : 0.0f;
    command.clear_scram = random.chance(1, 67) ? 1.0f : 0.0f;
    command.set_source = random.chance(1, 7) ? 1.0f : 0.0f;
    command.source = PK_SOURCE_Q_MAX * random.unit();
    return command;
}

} // namespace

int main() {
    pk::ReactorParams params;
    pk::ReactorState core = {};
    Outputs out = {};
    Random random;
    bool initialized = false;

    for (int frame = 0; frame < COMMAND_COUNT; ++frame) {
        const Command command = make_command(random, frame);
        apply_to_core(core, params, initialized, command);
        call_top(command, out);
        if (!finite_and_bounded(core)) {
            std::cerr << "FAIL frame " << frame << " core violated a state invariant\n";
            return 1;
        }
        if (!matches(core, params, out, frame, command)) {
            return 1;
        }
    }

    std::cout << std::scientific << std::setprecision(9)
              << "PASS: " << COMMAND_COUNT
              << " fixed-seed PC/HLS command frames matched with bounded finite state\n";
    return 0;
}
