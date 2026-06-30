#ifndef POINT_KINETICS_H
#define POINT_KINETICS_H

float euler_update(float y, float dydt, float h);
float clamp_value(float value, float low, float high);

struct ReactorParams {
    float Lambda;
    float beta_total;
    float Q;

    float lam_i[6];
    float beta_i[6];

    float gamma;
    float K_heat;
    float Tm_const;

    float Tc_ref;
    float Tf_ref;

    float gamma_I;
    float gamma_Xe;
    float lambda_I;
    float lambda_Xe;
    float kXe_burnout;
    float kFission;

    ReactorParams();
};

struct PlantConfig {
    int mode_id;
    const char *name;
    float alpha_f;
    float alpha_c;
    float gamma_c_init;
    float gamma_c_active;
    float rho_rod_min;
    float rho_rod_max;
    float kXe_worth;
};

enum class TimeMode {
    REALTIME,
    TRAINING,
    XENON,
    CUSTOM
};

struct TimeCompression {
    TimeMode mode;
    float factor;

    static constexpr float BASE_H = 0.00001f;
    static constexpr float MAX_H  = 0.002f;

    TimeCompression();
    void set_mode(TimeMode m);
    void set_custom(float f);
    float h() const;
    const char* name() const;
};

class ReactorSim {
public:
    ReactorParams p;
    TimeCompression tc;
    int engine_order;

    float t;
    float n;
    float C[6];
    float Tf;
    float Tc;
    float I_Xe;
    float Xe;
    float Xe_ref;
    float decay_heat;

    float rod_position;
    float rod_target;
    float rod_speed_limit;
    float rod_motion_residual;
    bool scram_occurred;
    float t_scram;
    float pre_scram_power;

    int plant_mode;
    PlantConfig plant_configs[3];

    ReactorSim();
    void initialize(float power_fraction);
    float get_rod_rho(const PlantConfig& cfg) const;
    float get_xe_rho(const PlantConfig& cfg) const;
    float get_total_rho(const PlantConfig& cfg) const;
    float get_total_rho() const;
    void scram();
    void step(float h);
};

#ifndef __SYNTHESIS__
void run_simulation_host(ReactorSim& sim, float wall_output_interval);
#endif

void point_kinetics_step(
    float h,
    int substeps,
    float tc_factor,
    float reset,
    float reset_power,
    float withdraw_cmd,
    float insert_cmd,
    float scram_cmd,
    float *t_out,
    float *N_out,
    float *Tf_out,
    float *Tc_out,
    float *I_Xe_out,
    float *Xe_out,
    float *rho_out,
    float *dollars_out,
    float *rho_Xe_out,
    float *rod_position_out,
    float *rod_target_out,
    float *tc_factor_out,
    float *engine_order_out,
    float C_out[6],
    float set_rod_target_cmd,
    float rod_target_cmd,
    int plant_mode_cmd,
    float plant_mode_update_cmd,
    float *target_h_out,
    float *decay_heat_out,
    float *plant_mode_out
);

#endif
