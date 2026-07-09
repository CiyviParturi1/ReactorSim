#ifndef POINT_KINETICS_C_H
#define POINT_KINETICS_C_H

/* * Plain-C helpers for the ARM app (no C++).
 * Same plant numbers and rod formulas as point_kinetics_core.h.
 */

#include "point_kinetics_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float alpha_f;
    float alpha_c;
    float rho_rod_min;
    float rho_rod_max;
    float kXe_worth;
} PkPlantCoeffs;

static inline float pk_c_clamp(float value, float low, float high)
{
    if (value < low) {
        return low;
    }
    if (value > high) {
        return high;
    }
    return value;
}

/* True if value is a normal float (not NaN / Inf). */
static inline int pk_c_finite(float value)
{
    return (value == value) && (value <= 3.4028234e38f) && (value >= -3.4028234e38f);
}

static inline PkPlantCoeffs pk_c_plant_coeffs(int mode)
{
    PkPlantCoeffs cfg;

    if (mode < 0) {
        mode = 0;
    }
    if (mode > 2) {
        mode = 2;
    }

    if (mode == 1) {
        cfg.alpha_f = PK_MODE1_ALPHA_F;
        cfg.alpha_c = PK_MODE1_ALPHA_C;
        cfg.rho_rod_min = PK_MODE1_RHO_ROD_MIN;
        cfg.rho_rod_max = PK_MODE1_RHO_ROD_MAX;
    } else if (mode == 2) {
        cfg.alpha_f = PK_MODE2_ALPHA_F;
        cfg.alpha_c = PK_MODE2_ALPHA_C;
        cfg.rho_rod_min = PK_MODE2_RHO_ROD_MIN;
        cfg.rho_rod_max = PK_MODE2_RHO_ROD_MAX;
    } else {
        cfg.alpha_f = PK_MODE0_ALPHA_F;
        cfg.alpha_c = PK_MODE0_ALPHA_C;
        cfg.rho_rod_min = PK_MODE0_RHO_ROD_MIN;
        cfg.rho_rod_max = PK_MODE0_RHO_ROD_MAX;
    }

    cfg.kXe_worth = PK_XENON_WORTH;
    return cfg;
}

/* Steady Tf/Tc at reset for the given power (matches pk::reset). */
static inline void pk_c_reference_temperatures(float power_fraction, float *tf_ref, float *tc_ref)
{
    float power = power_fraction;
    if (!pk_c_finite(power)) {
        power = 1.0f;
    }
    power = pk_c_clamp(power, 0.0f, 1.5f);

    *tc_ref = PK_TM_CONST + (PK_K_HEAT * power) / PK_GAMMA_C_INITIAL;
    *tf_ref = *tc_ref + (PK_K_HEAT * power) / PK_FUEL_COUPLING;
}

static inline float pk_c_rod_rho(float rod_position, const PkPlantCoeffs *cfg)
{
    return cfg->rho_rod_min + rod_position * (cfg->rho_rod_max - cfg->rho_rod_min);
}

/* Rod position that would cancel fuel + coolant + xenon reactivity. */
static inline float pk_c_critical_rod_position(float Tf, float Tc, float tf_ref, float tc_ref,
                                               float rho_Xe, const PkPlantCoeffs *cfg)
{
    const float rho_fuel = cfg->alpha_f * (Tf - tf_ref);
    const float rho_cool = cfg->alpha_c * (Tc - tc_ref);
    const float needed = -rho_fuel - rho_cool - rho_Xe;
    return pk_c_clamp((needed - cfg->rho_rod_min) / (cfg->rho_rod_max - cfg->rho_rod_min), 0.0f, 1.0f);
}

#ifdef __cplusplus
}
#endif

#endif
