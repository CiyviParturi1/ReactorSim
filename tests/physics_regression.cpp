#include "../common/point_kinetics_core.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>

namespace {

int failures = 0;

void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++failures;
    }
}

bool near(double actual, double expected, double absolute_tolerance,
          double relative_tolerance = 0.0) {
    return std::fabs(actual - expected) <=
           absolute_tolerance +
               relative_tolerance * std::max(std::fabs(actual),
                                             std::fabs(expected));
}

struct DoubleState {
    static constexpr int SIZE =
        1 + pk::PRECURSOR_GROUPS + 2 + pk::DECAY_GROUPS;
    std::array<double, SIZE> value;
};

DoubleState derivative(const DoubleState& state,
                       const pk::ReactorParams& params,
                       const pk::PlantConfig& cfg,
                       double tf_ref,
                       double tc_ref,
                       double rod_position) {
    DoubleState result = {};
    const int n_index = 0;
    const int c_index = 1;
    const int tf_index = c_index + pk::PRECURSOR_GROUPS;
    const int tc_index = tf_index + 1;
    const int decay_index = tc_index + 1;

    const double n = state.value[n_index];
    const double tf = state.value[tf_index];
    const double tc = state.value[tc_index];
    const double rho_rod =
        cfg.rho_rod_min +
        rod_position * (cfg.rho_rod_max - cfg.rho_rod_min);
    const double rho =
        rho_rod + cfg.alpha_f * (tf - tf_ref) +
        cfg.alpha_c * (tc - tc_ref);

    double delayed_source = 0.0;
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
        delayed_source +=
            params.lam_i[i] * state.value[c_index + i];
        result.value[c_index + i] =
            (params.beta_i[i] / params.Lambda) * n -
            params.lam_i[i] * state.value[c_index + i];
    }
    result.value[n_index] =
        ((rho - params.beta_total) / params.Lambda) * n +
        delayed_source + params.Q;

    double decay_heat = 0.0;
    for (int i = 0; i < pk::DECAY_GROUPS; ++i) {
        const double group = state.value[decay_index + i];
        result.value[decay_index + i] =
            params.decay_lambda[i] *
            (params.decay_fraction[i] * n - group);
        decay_heat += group;
    }
    const double thermal_power =
        (1.0 - params.total_decay_fraction()) * n + decay_heat;
    result.value[tf_index] =
        params.K_heat * thermal_power - params.gamma * (tf - tc);
    result.value[tc_index] =
        params.gamma * (tf - tc) -
        cfg.gamma_c_active * (tc - params.Tm_const);
    return result;
}

void rk4_step(DoubleState& state,
              const pk::ReactorParams& params,
              const pk::PlantConfig& cfg,
              double tf_ref,
              double tc_ref,
              double rod_position,
              double h) {
    const DoubleState k1 =
        derivative(state, params, cfg, tf_ref, tc_ref, rod_position);
    DoubleState temporary = state;
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        temporary.value[i] = state.value[i] + 0.5 * h * k1.value[i];
    }
    const DoubleState k2 =
        derivative(temporary, params, cfg, tf_ref, tc_ref, rod_position);
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        temporary.value[i] = state.value[i] + 0.5 * h * k2.value[i];
    }
    const DoubleState k3 =
        derivative(temporary, params, cfg, tf_ref, tc_ref, rod_position);
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        temporary.value[i] = state.value[i] + h * k3.value[i];
    }
    const DoubleState k4 =
        derivative(temporary, params, cfg, tf_ref, tc_ref, rod_position);
    for (int i = 0; i < DoubleState::SIZE; ++i) {
        state.value[i] +=
            (h / 6.0) *
            (k1.value[i] + 2.0 * k2.value[i] +
             2.0 * k3.value[i] + k4.value[i]);
    }
}

DoubleState to_double_state(const pk::ReactorState& source) {
    DoubleState result = {};
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

void test_equilibrium_resets() {
    const float powers[] = {
        0.0f, 0.01f, 0.10f, 0.25f, 0.50f, 0.75f, 1.0f, 1.5f
    };
    pk::ReactorParams params;
    for (int mode = 0; mode < pk::PLANT_MODES; ++mode) {
        const pk::PlantConfig cfg = pk::plant_config(mode);
        for (float power : powers) {
            pk::ReactorState state;
            pk::reset(state, params, power, mode);
            expect(
                std::fabs(pk::total_rho(state, cfg)) < 2.0e-7f,
                "every supported reset power must initialize critical");
            expect(
                state.rod_position >= 0.0f && state.rod_position <= 1.0f,
                "reset rod position must remain reachable");
            expect(
                near(state.rod_position,
                     pk::critical_rod_position(state, cfg),
                     2.0e-6),
                "reported critical rod must match reset rod position");
        }
    }
}

void test_long_duration_clock() {
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 0);
    state.t = 2040.0f;
    state.t_compensation = 0.0f;
    pk::advance(state, params, PK_BASE_H, PK_MAX_SUBSTEPS);
    expect(
        near(state.t, 2050.0, 2.0e-3),
        "base-step clock must advance through the former 2048 s freeze");

    state.t = 65530.0f;
    state.t_compensation = 0.0f;
    pk::advance(state, params, PK_MAX_H, 5000);
    expect(
        near(state.t, 65540.0, 1.0e-2),
        "xenon-step clock must advance through the former 65536 s freeze");
}

void test_poison_precision() {
    const float x = 2.87e-7f;
    const double expected = -std::expm1(-static_cast<double>(x));
    expect(
        near(pk::stable_one_minus_exp_negative(x), expected, 1.0e-12, 1.0e-6),
        "small poison exponent must retain float precision");

    pk::ReactorParams params;
    float iodine = 1.0f;
    float xenon = 1.0f;
    float iodine_compensation = 0.0f;
    float xenon_compensation = 0.0f;
    for (int frame = 0; frame < 100000; ++frame) {
        pk::update_poison_batched(
            0.5f, 0.01f, params, iodine, xenon,
            iodine_compensation, xenon_compensation);
    }
    const double iodine_expected =
        0.5 + 0.5 * std::exp(-params.lambda_I * 1000.0);
    expect(
        near(iodine, iodine_expected, 2.0e-6),
        "batched iodine must accumulate sub-ULP frame changes");
}

void test_decay_heat_curve() {
    pk::ReactorParams params;
    double decay_at_two_hours = 0.0;
    for (int i = 0; i < pk::DECAY_GROUPS; ++i) {
        decay_at_two_hours +=
            params.decay_fraction[i] *
            std::exp(-params.decay_lambda[i] * 7200.0);
    }
    expect(
        decay_at_two_hours > 0.01 && decay_at_two_hours < 0.02,
        "reduced decay model must retain 1-2% heat at two hours");
}

void test_positive_reactivity_guard() {
    pk::ReactorParams params;
    pk::ReactorState state;
    pk::reset(state, params, 1.0f, 1);
    state.Tc = state.Tc_ref + 2000.0f;
    pk::step(state, params, PK_MAX_H);
    expect(
        state.numerical_fault,
        "positive-reactivity solver pole must latch a numerical fault");
    expect(
        state.scram_active && state.rod_position == 0.0f,
        "positive-reactivity solver pole must force a shutdown state");
    expect(
        std::isfinite(state.n) && state.n >= 0.0f,
        "positive-reactivity guard must keep power finite");
}

void test_against_double_rk4() {
    pk::ReactorParams params;
    const pk::PlantConfig cfg = pk::plant_config(0);
    pk::ReactorState float_state;
    pk::reset(float_state, params, 1.0f, 0);
    float_state.rod_position = 0.80f;
    float_state.rod_target = 0.80f;

    DoubleState reference = to_double_state(float_state);
    const double reference_h = 1.0e-5;
    for (int i = 0; i < 1000000; ++i) {
        rk4_step(
            reference, params, cfg,
            float_state.Tf_ref, float_state.Tc_ref,
            0.80, reference_h);
    }
    for (int i = 0; i < 100000; ++i) {
        pk::step(float_state, params, PK_BASE_H);
    }

    const int tf_index = 1 + pk::PRECURSOR_GROUPS;
    const int tc_index = tf_index + 1;
    expect(
        near(float_state.n, reference.value[0], 2.0e-3, 3.0e-3),
        "float semi-implicit power must track double RK4");
    expect(
        near(float_state.Tf, reference.value[tf_index], 0.08),
        "float fuel temperature must track double RK4");
    expect(
        near(float_state.Tc, reference.value[tc_index], 0.08),
        "float coolant temperature must track double RK4");
}

} // namespace

int main() {
    expect(PK_BASE_H == 1.0e-4f, "canonical base timestep changed unexpectedly");
    expect(PK_MAX_H == 2.0e-3f, "canonical maximum timestep changed unexpectedly");
    expect(PK_MAX_SUBSTEPS == 100000, "canonical substep cap changed unexpectedly");
    test_equilibrium_resets();
    test_long_duration_clock();
    test_poison_precision();
    test_decay_heat_curve();
    test_positive_reactivity_guard();
    test_against_double_rk4();

    if (failures != 0) {
        std::cerr << "FAILED: " << failures << " physics regression checks\n";
        return 1;
    }
    std::cout << "PASS: independent physics and precision regressions\n";
    return 0;
}
