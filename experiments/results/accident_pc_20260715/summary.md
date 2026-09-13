# PC accident-character simulation results

These results come from simplified educational cases. They are not validated
accident reconstructions or safety analyses. The model includes lumped point
kinetics, iodine-xenon poisoning, decay heat, two temperatures, and rod
feedback. It omits coolant inventory, void fraction, pressure, core coverage,
spatial power, graphite displacers, and material failure.

## Results

| Scenario | Main result | Modern C0 comparison | Numerical status |
|---|---:|---:|---|
| Chernobyl-style C1 | peak neutron power 2.155 (34.49x initial), 6.0 s after AZ-5 | peak 0.242 (3.88x); immediate SCRAM | finite, no fault |
| TMI-style C2 | delayed fuel peak 836.4 deg C at 2.30 h | peak fuel 543.0 deg C at startup, then cooling | finite, no fault |

## Scenario timing and interpretation

- In the Chernobyl-style case, AZ-5 occurs 36.0 s after the test starts. The
  model delays negative shutdown insertion by another 6.0 s. Positive
  coolant-temperature feedback drives C1 upward while C0's prompt SCRAM cuts
  power. These times follow the IAEA sequence, but the model does not validate
  the accident magnitude.
- In the TMI-style case, the reactor trips at 12.0 s, within the NRC range of
  9 to 12 s. Cooling degrades at 10 min, the core-uncovery case begins at 1.75
  h, and cooling returns at 2.3 h. These prescribed stages produce the delayed
  heat-up and recovery shown in the figure.

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


The TMI core-uncovery case reduces fuel-to-coolant coupling. It does not solve
coolant inventory. A physical treatment would need coolant level, pressure,
and relief-flow dynamics. The Chernobyl case schedules the shutdown delay
instead of modelling rod and displacer geometry.

## References

- [IAEA, *INSAG-7: The Chernobyl Accident*](https://pub.iaea.org/MTCD/publications/PDF/Pub913e_web.pdf)
- [US NRC, *Backgrounder on the Three Mile Island Accident*](https://www.nrc.gov/reading-rm/doc-collections/fact-sheets/3mile-isle)
- [US NRC, *Bulletin 79-05A accident timeline*](https://www.nrc.gov/reading-rm/doc-collections/gen-comm/bulletins/1979/bl79005a)
