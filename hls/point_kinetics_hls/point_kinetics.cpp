#include "point_kinetics.h"

void point_kinetics_step(
    float h, int substeps, float tc_factor, float reset_cmd, float reset_power,
    float withdraw_cmd, float insert_cmd, float scram_cmd,
    float *t_out, float *N_out, float *Tf_out, float *Tc_out,
    float *I_Xe_out, float *Xe_out, float *rho_out, float *dollars_out,
    float *rho_Xe_out, float *rod_position_out, float *rod_target_out,
    float *tc_factor_out, float *engine_order_out, float C_out[6],
    float set_rod_target_cmd, float rod_target_cmd, int plant_mode_cmd,
    float plant_mode_update_cmd, float *target_h_out,
    float *decay_heat_out, float *plant_mode_out,
    float clear_scram_cmd, float *scram_active_out) {
#pragma HLS INTERFACE s_axilite port=h bundle=CTRL
#pragma HLS INTERFACE s_axilite port=substeps bundle=CTRL
#pragma HLS INTERFACE s_axilite port=tc_factor bundle=CTRL
#pragma HLS INTERFACE s_axilite port=reset_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=reset_power bundle=CTRL
#pragma HLS INTERFACE s_axilite port=withdraw_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=insert_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=scram_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=t_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=N_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=Tf_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=Tc_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=I_Xe_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=Xe_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=rho_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=dollars_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=rho_Xe_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=rod_position_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=rod_target_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=tc_factor_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=engine_order_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=C_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=set_rod_target_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=rod_target_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=plant_mode_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=plant_mode_update_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=target_h_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=decay_heat_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=plant_mode_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=clear_scram_cmd bundle=CTRL
#pragma HLS INTERFACE s_axilite port=scram_active_out bundle=CTRL
#pragma HLS INTERFACE s_axilite port=return bundle=CTRL
#pragma HLS ARRAY_PARTITION variable=C_out complete dim=1
 
    static bool initialized = false;
    static ReactorParams params;
    static pk::ReactorState state;
 
    const bool plant_update = pk::finite(plant_mode_update_cmd) &&
                              plant_mode_update_cmd > 0.5f;
    if (!initialized || (pk::finite(reset_cmd) && reset_cmd > 0.5f) || plant_update) {
        const int mode = plant_update ? pk::clamp(plant_mode_cmd, 0, 2)
                                      : (initialized ? state.plant_mode : 0);
        pk::reset(state, params, reset_power, mode);
        initialized = true;
    }

    if (pk::finite(set_rod_target_cmd) && set_rod_target_cmd > 0.5f) {
        pk::set_rod_target(state, rod_target_cmd);
    } else if (pk::finite(withdraw_cmd) && withdraw_cmd > 0.5f &&
               (!pk::finite(insert_cmd) || insert_cmd <= 0.5f)) {
        pk::set_rod_target(state, state.rod_target + 0.01f);
    } else if (pk::finite(insert_cmd) && insert_cmd > 0.5f &&
               (!pk::finite(withdraw_cmd) || withdraw_cmd <= 0.5f)) {
        pk::set_rod_target(state, state.rod_target - 0.01f);
    }
    if (pk::finite(scram_cmd) && scram_cmd > 0.5f) {
        pk::scram(state);
    }
    if (pk::finite(clear_scram_cmd) && clear_scram_cmd > 0.5f) {
        pk::reset_scram_trip(state);
    }

    if (!pk::finite(h) || h <= 0.0f) {
        h = pk::TimePolicy::base_h();
    }
    h = pk::clamp(h, pk::TimePolicy::base_h(), pk::TimePolicy::max_h());
    pk::advance(state, params, h, substeps);

    const PlantConfig cfg = pk::plant_config(state.plant_mode);
    const float rho = pk::total_rho(state, cfg);
    *t_out = state.t;
    *N_out = state.n;
    *Tf_out = state.Tf;
    *Tc_out = state.Tc;
    *I_Xe_out = state.I_Xe;
    *Xe_out = state.Xe;
    *rho_out = rho;
    *dollars_out = rho / params.beta_total;
    *rho_Xe_out = pk::xenon_rho(state, cfg);
    *rod_position_out = state.rod_position;
    *rod_target_out = state.rod_target;
    *tc_factor_out =
        pk::finite(tc_factor) && tc_factor >= 1.0f ? tc_factor : 1.0f;
    *engine_order_out = state.numerical_fault ? 0.0f : 1.0f;
    *target_h_out = h;
    *decay_heat_out = state.decay_heat;
    *plant_mode_out = static_cast<float>(state.plant_mode);
    *scram_active_out = state.scram_active ? 1.0f : 0.0f;
    for (int i = 0; i < pk::PRECURSOR_GROUPS; ++i) {
#pragma HLS UNROLL
        C_out[i] = state.C[i];
    }
}
