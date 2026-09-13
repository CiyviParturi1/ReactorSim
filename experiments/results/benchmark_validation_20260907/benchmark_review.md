# Benchmark verification

## CATS benchmark

The validation runner uses Ganapol's 2024 CATS Table 6a, Thermal Reactor IV.
The case applies an instantaneous +1 dollar insertion with adiabatic Doppler
feedback. The runner and figures contain no other CATS case.

The fixture applies the published six-group kinetics data, prompt lifetime,
and Doppler coefficient. It maps the feedback law to the fuel-feedback path
with `alpha_f × K_heat = −B`. An adiabatic fuel node and the rod-worth
function impose the published step. At each 0.1 ms step, `pk::step()` updates
neutron density, precursors, fuel temperature, coolant state, decay groups,
and reactivity. The benchmark excludes coolant removal, poison feedback, and
decay heat, so the fixture sets those contributions to zero or a negligible
value.

The output records 1,000,000 solver states from 0 to 100 s. The figure plots
that trajectory and overlays eleven published neutron-density values. The
maximum relative difference at those checkpoints is 0.00703%.

The source is B. D. Ganapol, *A Precision Benchmark Suite for Nuclear Reactor
Point Kinetics Equations via Converged Accelerated Taylor Series (CATS)*,
2024, Table 6a and Appendix A, Thermal Reactor IV. [Read the paper](https://arxiv.org/pdf/2406.11822).

## Checks

| Test | Evidence | What it establishes |
| --- | --- | --- |
| CATS Table 6a adiabatic Doppler feedback | Full 0.1 ms trajectory and 11 external checkpoints from 1 to 100 s. Maximum error 0.00703% | The feedback-limited power response with matched benchmark parameters |
| Analytic iodine-xenon check | Three prescribed-power cases; largest xenon error 0.437 ppm | Accuracy of the 0.1 s batched poison update |
| Fixed-seed PC/HLS parity | 10,000 command frames pass | Native shared core and HLS C++ interface consistency |
| Native physics regressions | Equilibrium, double-RK4 comparison, decay heat, rod worth, precision and fault guards pass | Errors in the solver, state limits, or reset behavior |

## Scope

The CATS test covers the adiabatic fuel-feedback case when its local parameters
match the published benchmark. It does not cover the default plant
coefficients, physical rod motion, xenon feedback, coolant heat removal,
spatial effects, or a plant transient.

The prior CATS negative-step fixtures and their derived graphs were removed.
They are not part of the current benchmark claim.

## Run the check

```powershell
.\experiments\run_validation_figures.ps1
```

The generated figures are in `figures/feedback_benchmark/`.
Production model sources remain unchanged.
