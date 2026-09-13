# Chapter 7 physical ZedBoard results

This directory preserves the July 13, 2026 board campaign. `metadata.json`
identifies the board image and software artifacts. Each test folder keeps the
original UART stream, capture settings, malformed-line record, and validation
result. The raw UART text matters because a test run cannot recreate data from
the physical board.

Parsed telemetry and command-timeline CSV files are local derived files and
remain ignored by Git. The summary, parity reports, and figures contain the
results used in Chapter 7.
