#ifndef POINT_KINETICS_CSV_H
#define POINT_KINETICS_CSV_H

/* The ARM application and its host test share this fixed-point CSV formatter.
 * Define PK_CSV_PRINTF before including this header (xil_printf on ARM, printf
 * in the host regression). The formatter emits invalid or out-of-range values
 * as parseable NaN/Inf tokens instead of converting them to integers.
 */

#include "point_kinetics_c.h"

#ifndef PK_CSV_PRINTF
#define PK_CSV_PRINTF xil_printf
#endif

#define PK_CSV_MAX_PRINTABLE 2147483000.0f

static inline void pk_c_csv_print_fixed(float value, int digits)
{
    int i;
    int scale = 1;

    if (digits < 0) {
        digits = 0;
    }
    if (digits > 9) {
        digits = 9;
    }

    if (value != value) {
        PK_CSV_PRINTF("nan");
        return;
    }
    if (!pk_c_finite(value)) {
        PK_CSV_PRINTF(value < 0.0f ? "-inf" : "inf");
        return;
    }
    if (value > PK_CSV_MAX_PRINTABLE) {
        PK_CSV_PRINTF("inf");
        return;
    }
    if (value < -PK_CSV_MAX_PRINTABLE) {
        PK_CSV_PRINTF("-inf");
        return;
    }

    if (value < 0.0f) {
        PK_CSV_PRINTF("-");
        value = -value;
    }

    for (i = 0; i < digits; ++i) {
        scale *= 10;
    }

    {
        int whole = (int)value;
        int frac = (int)((value - (float)whole) * (float)scale + 0.5f);

        if (frac >= scale) {
            whole++;
            frac -= scale;
        }

        PK_CSV_PRINTF("%d", whole);
        if (digits > 0) {
            PK_CSV_PRINTF(".");
            for (i = scale / 10; i > 1; i /= 10) {
                if (frac < i) {
                    PK_CSV_PRINTF("0");
                }
            }
            PK_CSV_PRINTF("%d", frac);
        }
    }
}

#endif
