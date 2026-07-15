# PC accident-character simulation results

These are **simplified educational surrogates**, not validated reconstructions or safety analyses. The model contains lumped point kinetics, iodine/xenon, decay heat, two temperatures and rod feedback; it does not model coolant inventory, void fraction, pressure, core coverage, spatial power, graphite displacers or material failure.

## Results

| Scenario | Main result | Modern C0 comparison | Numerical status |
|---|---:|---:|---|
| Chernobyl-style C1 | peak neutron power 2.155 (34.49x initial), 6.0 s after AZ-5 | peak 0.242 (3.88x); immediate SCRAM | finite, no fault |
| TMI-style C2 | delayed fuel peak 836.4 deg C at 2.30 h | peak fuel 543.0 deg C at startup, then cooling | finite, no fault |

## Scenario timing and interpretation

- **Chernobyl character:** test start to AZ-5 is 36.0 s and the surrogate negative shutdown insertion is delayed another 6.0 s. C1's positive coolant-temperature feedback produces a continuing rapid rise while C0's prompt SCRAM collapses power. These timings are imposed to mirror the IAEA sequence; accident magnitude is **not validated**.
- **TMI character:** reactor trip occurs at 12.0 s, within the NRC 9-12 s range. Cooling degrades at 10 min, the core-uncovery surrogate begins at 1.75 h, and cooling is restored at 2.3 h. These scheduled stages create the intended delayed heat-up and recovery shape for presentation.

## Automated checks

| Check | Result |
|---|---|
| expected trace lengths | PASS |
| time is nondecreasing | PASS |
| scenario names are consistent | PASS |
| expected events occur once | PASS |
| scheduled event times match | PASS |
| all traces finite | PASS |
| zero numerical faults | PASS |
| rbmk peak exceeds 10x initial | PASS |
| rbmk peak exceeds modern | PASS |
| modern scram collapses power within 1s | PASS |
| tmi like delayed fuel peak exceeds modern by 200C | PASS |
| tmi trip timing matches NRC window | PASS |
| tmi delayed heatup occurs in scheduled window | PASS |
| tmi cooling restoration returns below 300C | PASS |


The TMI core-uncovery stage is a transparent presentation surrogate implemented by reducing fuel-to-coolant coupling; it is not a solved coolant-inventory model. Higher-fidelity work would require coolant level, pressure and relief-flow dynamics. The Chernobyl surrogate similarly schedules its shutdown delay rather than modelling rod/displacer geometry.

## References

- IAEA, *INSAG-7: The Chernobyl Accident*: https://pub.iaea.org/MTCD/publications/PDF/Pub913e_web.pdf
- US NRC, *Backgrounder on the Three Mile Island Accident*: https://www.nrc.gov/reading-rm/doc-collections/fact-sheets/3mile-isle
- US NRC, *Bulletin 79-05A accident timeline*: https://www.nrc.gov/reading-rm/doc-collections/gen-comm/bulletins/1979/bl79005a
