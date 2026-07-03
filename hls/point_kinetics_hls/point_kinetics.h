#ifndef POINT_KINETICS_H
#define POINT_KINETICS_H

#include "../../common/point_kinetics_core.h"

using ReactorParams = pk::ReactorParams;
using PlantConfig = pk::PlantConfig;

enum class TimeMode {
    REALTIME,
    TRAINING,
    XENON,
    CUSTOM
};

struct TimeCompression {
    TimeMode mode;
    float factor;
    static constexpr float BASE_H = 1.0e-5f;
    static constexpr float MAX_H = 2.0e-3f;
    TimeCompression() : mode(TimeMode::REALTIME), factor(1.0f) {}

    void set_mode(TimeMode value) {
        mode = value;
        switch (value) {
            case TimeMode::TRAINING:
                factor = 10.0f;
                break;
            case TimeMode::XENON:
                factor = 1000.0f;
                break;
            default:
                factor = 1.0f;
                break;
        }
    }

    void set_custom(float value) {
        mode = TimeMode::CUSTOM;
        factor = pk::finite(value) && value >= 1.0f ? value : 1.0f;
    }

    float h() const {
        return pk::TimePolicy::step_for_factor(factor);
    }

    const char* name() const {
        switch (mode) {
            case TimeMode::TRAINING:
                return "TRAINING(10x)";
            case TimeMode::XENON:
                return "XENON(1000x)";
            case TimeMode::CUSTOM:
                return "CUSTOM";
            default:
                return "REALTIME(1x)";
        }
    }
};

class ReactorSim : public pk::ReactorState {
public:
    ReactorParams p;
    TimeCompression tc;
    int engine_order;

    ReactorSim() : engine_order(1) {
        plant_mode = 0;
        initialize(1.0f);
    }
    void initialize(float power) {
        pk::reset(*this, p, power, plant_mode);
    }

    float get_rod_rho(const PlantConfig& cfg) const {
        return pk::rod_rho(*this, cfg);
    }

    float get_xe_rho(const PlantConfig& cfg) const {
        return pk::xenon_rho(*this, cfg);
    }

    float get_total_rho(const PlantConfig& cfg) const {
        return pk::total_rho(*this, cfg);
    }

    float get_total_rho() const {
        return pk::total_rho(*this, pk::plant_config(plant_mode));
    }

    void scram() {
        pk::scram(*this);
    }

    void step(float h) {
        pk::step(*this, p, h);
    }
};

void point_kinetics_step(
    float h, int substeps, float tc_factor, float reset, float reset_power,
    float withdraw_cmd, float insert_cmd, float scram_cmd,
    float *t_out, float *N_out, float *Tf_out, float *Tc_out,
    float *I_Xe_out, float *Xe_out, float *rho_out, float *dollars_out,
    float *rho_Xe_out, float *rod_position_out, float *rod_target_out,
    float *tc_factor_out, float *engine_order_out, float C_out[6],
    float set_rod_target_cmd, float rod_target_cmd, int plant_mode_cmd,
    float plant_mode_update_cmd, float *target_h_out,
    float *decay_heat_out, float *plant_mode_out);

#endif
