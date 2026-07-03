#include "../hls/point_kinetics_hls/point_kinetics.h"

#include <cmath>
#include <iostream>
#include <limits>

namespace {

struct Outputs {
    float t, n, tf, tc, iodine, xenon, rho, dollars, rho_xe;
    float rod_position, rod_target, factor, order, target_h, decay, plant;
    float precursors[6];
};

void call_top(float h, int substeps, float reset, float reset_power,
              float withdraw, float insert, float scram,
              float set_target, float target, int plant, float plant_update,
              Outputs& out) {
    point_kinetics_step(
        h, substeps, 1.0f, reset, reset_power, withdraw, insert, scram,
        &out.t, &out.n, &out.tf, &out.tc, &out.iodine, &out.xenon,
        &out.rho, &out.dollars, &out.rho_xe, &out.rod_position,
        &out.rod_target, &out.factor, &out.order, out.precursors,
        set_target, target, plant, plant_update, &out.target_h,
        &out.decay, &out.plant);
}

bool near(float a, float b, float tolerance = 2.0e-5f) {
    const float scale = 1.0f + std::fabs(a) + std::fabs(b);
    return std::fabs(a - b) <= tolerance * scale;
}

int compare(const pk::ReactorState& state, const Outputs& out,
            const char* scenario) {
    const PlantConfig cfg = pk::plant_config(state.plant_mode);
    int failures = 0;
#define CHECK(field, expected) \
    do { \
        if (!near(out.field, (expected))) { \
            std::cerr << "FAIL " << scenario << ": " #field << " top=" \
                      << out.field << " core=" << (expected) << '\n'; \
            ++failures; \
        } \
    } while (false)
    CHECK(t, state.t);
    CHECK(n, state.n);
    CHECK(tf, state.Tf);
    CHECK(tc, state.Tc);
    CHECK(iodine, state.I_Xe);
    CHECK(xenon, state.Xe);
    CHECK(rho, pk::total_rho(state, cfg));
    CHECK(rho_xe, pk::xenon_rho(state, cfg));
    CHECK(rod_position, state.rod_position);
    CHECK(rod_target, state.rod_target);
    CHECK(decay, state.decay_heat);
    CHECK(plant, static_cast<float>(state.plant_mode));
    for (int i = 0; i < 6; ++i) {
        if (!near(out.precursors[i], state.C[i])) {
            ++failures;
        }
    }
#undef CHECK
    return failures;
}

} // namespace

int main() {
    int failures = 0;
    const float h = 1.0e-4f;
    ReactorParams params;
    pk::ReactorState core;
    Outputs out = {};

    pk::reset(core, params, 1.0f, 0);
    pk::advance(core, params, h, 100);
    call_top(h, 100, 1.0f, 1.0f, 0, 0, 0, 0, 0, 0, 0, out);
    failures += compare(core, out, "equilibrium");
    if (!near((1.0f - params.total_decay_fraction()) * core.n +
              core.decay_heat, 1.0f)) {
        std::cerr << "FAIL equilibrium: thermal power is not normalized\n";
        ++failures;
    }

    pk::set_rod_target(core, core.rod_target + 0.05f);
    pk::advance(core, params, h, 500);
    call_top(h, 500, 0, 1, 0, 0, 0, 1, out.rod_target + 0.05f,
             0, 0, out);
    failures += compare(core, out, "rod step");

    const float decay_before_scram = core.decay_heat;
    pk::scram(core);
    if (core.decay_heat != decay_before_scram) {
        std::cerr << "FAIL SCRAM: decay heat jumped at command time\n";
        ++failures;
    }
    pk::advance(core, params, 0.002f, 5000);
    call_top(0.002f, 5000, 0, 1, 0, 0, 1, 0, 0, 0, 0, out);
    failures += compare(core, out, "SCRAM");
    if (!(core.decay_heat > 0.0f && core.decay_heat < decay_before_scram)) {
        std::cerr << "FAIL SCRAM: decay heat must be positive and decreasing\n";
        ++failures;
    }

    pk::reset(core, params, 0.75f, 0);
    pk::advance(core, params, h, 1);
    call_top(h, 1, 1, 0.75f, 0, 0, 0, 0, 0, 0, 0, out);
    failures += compare(core, out, "reset");

    for (int mode = 0; mode < 3; ++mode) {
        pk::reset(core, params, 1.0f, mode);
        pk::advance(core, params, h, 10);
        call_top(h, 10, 0, 1, 0, 0, 0, 0, 0, mode, 1, out);
        failures += compare(core, out, "plant mode");
        if (!std::isfinite(core.n) || core.n < 0.0f) {
            ++failures;
        }
    }

    // Non-finite controls must not poison state or overwrite the rod target.
    const float old_target = core.rod_target;
    call_top(std::numeric_limits<float>::quiet_NaN(), 1, 0, 1, 0, 0, 0,
             1, std::numeric_limits<float>::infinity(), 2, 0, out);
    if (!std::isfinite(out.n) || !near(out.rod_target, old_target) ||
        !near(out.target_h, pk::TimePolicy::base_h())) {
        std::cerr << "FAIL non-finite command validation\n";
        ++failures;
    }

    if (failures != 0) {
        std::cerr << "FAILED: " << failures << " parity checks\n";
        return 1;
    }
    std::cout << "PASS: PC/core and HLS top parity scenarios\n";
    return 0;
}
