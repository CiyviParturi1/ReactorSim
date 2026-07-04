#ifndef POINT_KINETICS_CONFIG_H
#define POINT_KINETICS_CONFIG_H

/*
 * C-compatible constants shared by the C++ physics/HLS core and the
 * standalone ARM application. Keep cross-target timing and plant constants
 * here so the host cannot request a timestep that the HLS core later changes.
 */

#define PK_BASE_H                  1.0e-4f
#define PK_MAX_H                   2.0e-3f
#define PK_MAX_SUBSTEPS            100000
#define PK_WALL_OUTPUT_INTERVAL    0.10f

#define PK_BETA_TOTAL              0.007f
#define PK_TM_CONST                265.0f
#define PK_K_HEAT                  10.0f
#define PK_FUEL_COUPLING           0.04f
#define PK_GAMMA_C_INITIAL         0.357142857f

#define PK_MODE0_ALPHA_F          -2.5e-5f
#define PK_MODE0_ALPHA_C          -1.0e-5f
#define PK_MODE0_GAMMA_C           0.357142857f
#define PK_MODE0_RHO_ROD_MIN      -0.020f
#define PK_MODE0_RHO_ROD_MAX       0.0066666667f

#define PK_MODE1_ALPHA_F          -0.5e-5f
#define PK_MODE1_ALPHA_C           1.5e-5f
#define PK_MODE1_GAMMA_C           0.25f
#define PK_MODE1_RHO_ROD_MIN      -0.120f
#define PK_MODE1_RHO_ROD_MAX       0.009f

#define PK_MODE2_ALPHA_F          -2.5e-5f
#define PK_MODE2_ALPHA_C          -1.0e-5f
#define PK_MODE2_GAMMA_C           0.02f
#define PK_MODE2_RHO_ROD_MIN      -0.020f
#define PK_MODE2_RHO_ROD_MAX       0.0066666667f

#define PK_XENON_WORTH            -0.020f
#define PK_SCRAM_EXTRA_RHO        -0.07665f

#define PK_DECAY_FRACTION_0        0.025f
#define PK_DECAY_FRACTION_1        0.021f
#define PK_DECAY_FRACTION_2        0.020f

/* Half-lives: 10 s, 300 s, and 15,000 s. */
#define PK_DECAY_LAMBDA_0          0.069314718f
#define PK_DECAY_LAMBDA_1          0.0023104906f
#define PK_DECAY_LAMBDA_2          0.000046209812f

#endif
