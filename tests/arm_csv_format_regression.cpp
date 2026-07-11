#include <cfloat>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <iostream>
#include <string>

static std::string captured;

static void test_printf(const char* format, ...) {
    char buffer[128];
    va_list arguments;
    va_start(arguments, format);
    const int length = std::vsnprintf(buffer, sizeof(buffer), format, arguments);
    va_end(arguments);
    if (length > 0) {
        captured.append(buffer, static_cast<std::size_t>(length));
    }
}

#define PK_CSV_PRINTF test_printf
#include "../common/point_kinetics_csv.h"

namespace {

int failures = 0;

void expect(const std::string& actual, const std::string& expected, const char* message) {
    if (actual != expected) {
        std::cerr << "FAIL: " << message << " actual='" << actual << "' expected='" << expected << "'\n";
        ++failures;
    }
}

void check(float value, int digits, const char* expected, const char* message) {
    captured.clear();
    pk_c_csv_print_fixed(value, digits);
    expect(captured, expected, message);
}

} // namespace

int main() {
    check(12.3456f, 6, "12.345600", "finite values must retain fixed CSV formatting");
    check(-12.3456f, 6, "-12.345600", "negative finite values must retain fixed CSV formatting");
    check(std::numeric_limits<float>::quiet_NaN(), 6, "nan", "NaN must not reach integer conversion");
    check(std::numeric_limits<float>::infinity(), 6, "inf", "positive infinity must be CSV-safe");
    check(-std::numeric_limits<float>::infinity(), 6, "-inf", "negative infinity must be CSV-safe");
    check(FLT_MAX, 6, "inf", "oversized finite values must be CSV-safe");
    check(-FLT_MAX, 6, "-inf", "oversized negative values must be CSV-safe");

    if (failures != 0) {
        std::cerr << "FAILED: " << failures << " ARM CSV formatting checks\n";
        return 1;
    }
    std::cout << "PASS: ARM CSV formatting handles finite, NaN, Inf and oversized values\n";
    return 0;
}
