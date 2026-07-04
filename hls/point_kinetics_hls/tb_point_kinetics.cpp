#include <cmath>
#include <iostream>

#include "point_kinetics.h"

using namespace std;

static bool finite_state(const ReactorSim& sim) {
    if (!isfinite(sim.t) || !isfinite(sim.n) || !isfinite(sim.Tf) ||
        !isfinite(sim.Tc) || !isfinite(sim.I_Xe) || !isfinite(sim.Xe)) {
        return false;
    }

    for (int i = 0; i < 6; ++i) {
        if (!isfinite(sim.C[i])) return false;
    }

    return true;
}

static int expect(bool condition, const char* message) {
    if (!condition) {
        cerr << "FAIL: " << message << endl;
        return 1;
    }
    return 0;
}

static int test_hls_top() {
    int failures = 0;

    float h = 0.0001f;
    float t_out = 0.0f;
    float n_out = 0.0f;
    float tf_out = 0.0f;
    float tc_out = 0.0f;
    float iodine_out = 0.0f;
    float xenon_out = 0.0f;
    float rho_out = 0.0f;
    float dollars_out = 0.0f;
    float rho_xe_out = 0.0f;
    float rod_position_out = 0.0f;
    float rod_target_out = 0.0f;
    float tc_factor_out = 0.0f;
    float engine_order_out = 0.0f;
    float target_h_out = 0.0f;
    float decay_heat_out = 0.0f;
    float plant_mode_out = 0.0f;
    float c_out[6] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};

    float clear_scram_cmd = 0.0f;
    float scram_active_out = 0.0f;

    point_kinetics_step(h, 1, 1.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f,
                        &t_out, &n_out, &tf_out, &tc_out,
                        &iodine_out, &xenon_out, &rho_out,
                        &dollars_out, &rho_xe_out,
                        &rod_position_out, &rod_target_out,
                        &tc_factor_out, &engine_order_out, c_out,
                        0.0f, 0.0f, 0, 0.0f,
                        &target_h_out, &decay_heat_out, &plant_mode_out,
                        clear_scram_cmd, &scram_active_out);

    failures += expect(isfinite(t_out), "HLS top time output is finite");
    failures += expect(isfinite(n_out), "HLS top neutron output is finite");
    failures += expect(isfinite(tf_out), "HLS top fuel temperature output is finite");
    failures += expect(isfinite(tc_out), "HLS top coolant temperature output is finite");
    failures += expect(isfinite(iodine_out), "HLS top iodine output is finite");
    failures += expect(isfinite(xenon_out), "HLS top xenon output is finite");
    failures += expect(isfinite(rho_out), "HLS top reactivity output is finite");
    failures += expect(fabs(t_out - h) < 1.0e-6f, "HLS top advances one timestep");
    failures += expect(fabs(n_out - 1.0f) < 1.0e-5f,
                       "HLS top starts near critical power");
    failures += expect(fabs(rod_position_out - rod_target_out) < 1.0e-6f,
                       "HLS top initializes rod position at target");
    failures += expect(fabs(target_h_out - h) < 1.0e-8f,
                       "HLS top reports target timestep");
    failures += expect(fabs(decay_heat_out - 0.066f) < 1.0e-5f,
                       "HLS top initializes equilibrium grouped decay heat");
    failures += expect(plant_mode_out == 0.0f, "HLS top starts in PWR-SMR mode");

    for (int i = 0; i < 6; ++i) {
        failures += expect(isfinite(c_out[i]), "HLS top precursor output is finite");
    }

#ifdef POINT_KINETICS_LONG_TEST
    const float frame_h = PK_BASE_H;
    const int frame_substeps = PK_MAX_SUBSTEPS;
#else
    const float frame_h = 0.0001f;
    const int frame_substeps = 100;
#endif

    point_kinetics_step(frame_h, frame_substeps, 1.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f,
                        &t_out, &n_out, &tf_out, &tc_out,
                        &iodine_out, &xenon_out, &rho_out,
                        &dollars_out, &rho_xe_out,
                        &rod_position_out, &rod_target_out,
                        &tc_factor_out, &engine_order_out, c_out,
                        0.0f, 0.0f, 0, 0.0f,
                        &target_h_out, &decay_heat_out, &plant_mode_out,
                        0.0f, &scram_active_out);

#ifdef POINT_KINETICS_LONG_TEST
    float prev_t = t_out;
    for (int frame = 0; frame < 250; ++frame) {
        point_kinetics_step(frame_h, frame_substeps, 1.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f,
                            &t_out, &n_out, &tf_out, &tc_out,
                            &iodine_out, &xenon_out, &rho_out,
                            &dollars_out, &rho_xe_out,
                            &rod_position_out, &rod_target_out,
                            &tc_factor_out, &engine_order_out, c_out,
                            0.0f, 0.0f, 0, 0.0f,
                            &target_h_out, &decay_heat_out, &plant_mode_out,
                            0.0f, &scram_active_out);
        failures += expect(t_out > prev_t, "HLS top time advances beyond float substep precision limit");
        prev_t = t_out;
    }
    failures += expect(
        t_out > 2400.0f,
        "HLS top advances beyond the former 2048-second float freeze");
#else
    failures += expect(t_out > 0.009f && t_out < 0.011f,
                       "HLS top frame-step time advances in cosim-sized test");
#endif

    cout << "HLS top step" << endl;
    cout << "t=" << t_out
         << " N_out=" << n_out
         << " Tf=" << tf_out
         << " Tc=" << tc_out
         << " I_Xe=" << iodine_out
         << " Xe=" << xenon_out
         << " rod=" << rod_position_out
         << " C0_out=" << c_out[0] << endl;

    return failures;
}

int main() {
    int failures = 0;
    failures += test_hls_top();

    ReactorSim sim;
    cout << "Initial state" << endl;
    cout << "t=" << sim.t
         << " n=" << sim.n
         << " Tf=" << sim.Tf
         << " Tc=" << sim.Tc
         << " I_Xe=" << sim.I_Xe
         << " Xe=" << sim.Xe
         << " rho=" << sim.get_total_rho()
         << " rod=" << sim.rod_position
         << endl;

    failures += expect(finite_state(sim), "initial state is finite");
    failures += expect(fabs(sim.get_total_rho()) < 1.0e-6f,
                       "initial reactivity is critical");
    failures += expect(fabs((1.0f - sim.p.total_decay_fraction()) * sim.n +
                            sim.decay_heat - 1.0f) < 1.0e-6f,
                       "prompt plus decay heat is normalized at equilibrium");
    failures += expect(sim.tc.factor == 1.0f, "default time factor is 1x");
    failures += expect(fabs(sim.tc.h() - TimeCompression::BASE_H) < 1.0e-6f,
                       "default timestep is BASE_H");

    float initial_rod = sim.rod_position;
    sim.rod_target = pk::clamp(initial_rod + 0.10f, 0.0f, 1.0f);
    for (int i = 0; i < 100; ++i) {
        sim.step(sim.tc.h());
    }

    cout << "After realtime rod motion" << endl;
    cout << "t=" << sim.t
         << " n=" << sim.n
         << " rho=" << sim.get_total_rho()
         << " rod=" << sim.rod_position
         << " target=" << sim.rod_target
         << endl;

    failures += expect(finite_state(sim), "state remains finite after realtime steps");
    failures += expect(sim.t > 0.0099f && sim.t < 0.0101f, "realtime step time advances");
    failures += expect(sim.rod_position > initial_rod, "rod moves toward withdrawn target");

    sim.tc.set_mode(TimeMode::TRAINING);
    failures += expect(sim.tc.factor == 10.0f, "training mode factor is 10x");
    failures += expect(fabs(sim.tc.h() - 0.001f) < 1.0e-8f,
                       "training mode timestep is 0.001");

    float t_before_training = sim.t;
    for (int i = 0; i < 100; ++i) {
        sim.step(sim.tc.h());
    }
    failures += expect(sim.t > t_before_training, "training mode advances time");
    failures += expect(finite_state(sim), "state remains finite in training mode");

    sim.tc.set_mode(TimeMode::XENON);
    failures += expect(sim.tc.factor == 1000.0f, "xenon mode factor is 1000x");
    failures += expect(fabs(sim.tc.h() - 0.002f) < 1.0e-8f,
                       "xenon mode timestep is 0.002");

    sim.tc.set_custom(500.0f);
    failures += expect(sim.tc.mode == TimeMode::CUSTOM, "custom mode is selected");
    failures += expect(sim.tc.factor == 500.0f, "custom factor is stored");
    failures += expect(fabs(sim.tc.h() - 0.002f) < 1.0e-8f,
                       "custom factor clamps timestep");

    float decay_at_scram = sim.decay_heat;
    sim.scram();
    failures += expect(sim.rod_position == 0.0f && sim.rod_target == 0.0f,
                       "SCRAM fully inserts rods");

    for (int i = 0; i < 500; ++i) {
        sim.step(sim.tc.h());
    }

    cout << "After SCRAM" << endl;
    cout << "t=" << sim.t
         << " n=" << sim.n
         << " Tf=" << sim.Tf
         << " Tc=" << sim.Tc
         << " rho=" << sim.get_total_rho()
         << " rod=" << sim.rod_position
         << endl;

    failures += expect(finite_state(sim), "state remains finite after SCRAM");
    failures += expect(sim.n >= 0.0f, "power is non-negative after SCRAM");
    failures += expect(sim.decay_heat > 0.0f, "decay heat is tracked after SCRAM");
    failures += expect(sim.decay_heat < decay_at_scram,
                       "grouped decay heat decreases after SCRAM");

    sim.initialize(0.75f);
    cout << "After reset to 75% power" << endl;
    cout << "t=" << sim.t
         << " n=" << sim.n
         << " Tf=" << sim.Tf
         << " Tc=" << sim.Tc
         << " rho=" << sim.get_total_rho()
         << " rod=" << sim.rod_position
         << endl;

    failures += expect(finite_state(sim), "reset state is finite");
    failures += expect(fabs(sim.n - 0.75f) < 1.0e-6f, "reset applies requested power");
    failures += expect(fabs(sim.get_total_rho()) < 1.0e-6f,
                       "reset returns to critical rod configuration");

    sim.plant_mode = 1;
    sim.initialize(1.0f);
    failures += expect(sim.plant_mode == 1, "plant mode can switch to RBMK-like preset");
    failures += expect(fabs(sim.get_total_rho()) < 1.0e-6f,
                       "plant preset reset returns to critical state");

    if (failures == 0) {
        cout << "PASS: point kinetics simulator smoke test" << endl;
        return 0;
    }

    cerr << "FAILED: " << failures << " checks failed" << endl;
    return 1;
}
