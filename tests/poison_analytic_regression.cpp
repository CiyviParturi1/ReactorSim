#include "../common/point_kinetics_core.h"

#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

constexpr float FRAME_SECONDS = 0.1f;
constexpr double IODINE_RELATIVE_TOLERANCE = 2.0e-5;
constexpr double XENON_RELATIVE_TOLERANCE = 2.0e-4;

struct ExactPoison {
    double iodine;
    double xenon;
};

int failures = 0;
std::ostream* csv_output = nullptr;

bool near(double actual, double expected, double relative_tolerance) {
    return std::fabs(actual - expected) <= 2.0e-7
        + relative_tolerance * std::max(std::fabs(actual), std::fabs(expected));
}

ExactPoison exact_constant_power(double power, double elapsed, const pk::ReactorParams& params,
                                 double initial_iodine, double initial_xenon) {
    const double lambda_i = params.lambda_I;
    const double xenon_sink = params.lambda_Xe + params.kXe_burnout * power;
    const double iodine_reference = pk::iodine_ref(params);
    const double xenon_reference = pk::xenon_ref(params, iodine_reference);
    const double direct_xenon_source = params.gamma_Xe * params.kFission * power / xenon_reference;
    const double iodine_xenon_source = lambda_i * iodine_reference / xenon_reference;
    const double exp_i = std::exp(-lambda_i * elapsed);
    const double exp_x = std::exp(-xenon_sink * elapsed);
    const double iodine = power + (initial_iodine - power) * exp_i;
    const double constant_source = direct_xenon_source + iodine_xenon_source * power;
    const double iodine_transient = iodine_xenon_source * (initial_iodine - power)
        * (exp_i - exp_x) / (xenon_sink - lambda_i);
    const double xenon = initial_xenon * exp_x
        + constant_source * (1.0 - exp_x) / xenon_sink + iodine_transient;
    return {iodine, xenon};
}

template <std::size_t Count>
void run_case(const char* name, float power, const std::array<double, Count>& edits) {
    const pk::ReactorParams params;
    float iodine = 1.0f;
    float xenon = 1.0f;
    float iodine_compensation = 0.0f;
    float xenon_compensation = 0.0f;
    int completed_frames = 0;

    for (double edit : edits) {
        const int requested_frames = static_cast<int>(std::lround(edit / FRAME_SECONDS));
        while (completed_frames < requested_frames) {
            if (pk::update_poison_batched(power, FRAME_SECONDS, params, iodine, xenon,
                                          iodine_compensation, xenon_compensation)) {
                std::cerr << "FAIL: " << name << " reported a poison update fault\n";
                ++failures;
                return;
            }
            ++completed_frames;
        }

        const ExactPoison reference = exact_constant_power(power, edit, params, 1.0, 1.0);
        const double iodine_error = std::fabs(iodine - reference.iodine)
            / std::max(std::fabs(reference.iodine), 1.0e-12);
        const double xenon_error = std::fabs(xenon - reference.xenon)
            / std::max(std::fabs(reference.xenon), 1.0e-12);
        std::cout << std::setprecision(12) << name << " t=" << edit
                  << " I_error=" << iodine_error << " Xe_error=" << xenon_error << '\n';
        if (csv_output != nullptr) {
            *csv_output << name << ',' << power << ',' << edit << ',' << reference.iodine << ','
                        << iodine << ',' << reference.xenon << ',' << xenon << ',' << iodine_error
                        << ',' << xenon_error << '\n';
        }
        if (!near(iodine, reference.iodine, IODINE_RELATIVE_TOLERANCE)) {
            std::cerr << "FAIL: " << name << " iodine differs from the analytic solution at t=" << edit << " s\n";
            ++failures;
        }
        if (!near(xenon, reference.xenon, XENON_RELATIVE_TOLERANCE)) {
            std::cerr << "FAIL: " << name << " xenon differs from the analytic solution at t=" << edit << " s\n";
            ++failures;
        }
    }
}

} // namespace

int main(int argc, char* argv[]) {
    std::ofstream csv_file;
    if (argc == 3 && std::string(argv[1]) == "--csv") {
        csv_file.open(argv[2]);
        if (!csv_file) {
            std::cerr << "FAIL: cannot open poison CSV output\n";
            return 1;
        }
        csv_file << "scenario,power,time_s,reference_iodine,simulator_iodine,reference_xenon,simulator_xenon,iodine_relative_error,xenon_relative_error\n";
        csv_file << std::setprecision(12);
        csv_output = &csv_file;
    } else if (argc != 1) {
        std::cerr << "Usage: poison_analytic_regression [--csv output.csv]\n";
        return 2;
    }
    run_case("power reduction to 20%", 0.2f, std::array<double, 4>{{0.1, 1.0, 100.0, 7200.0}});
    run_case("power increase to 150%", 1.5f, std::array<double, 4>{{0.1, 1.0, 100.0, 3600.0}});
    run_case("SCRAM to zero power", 0.0f, std::array<double, 4>{{0.1, 1.0, 100.0, 7200.0}});

    if (failures != 0) {
        std::cerr << "FAILED: " << failures << " analytic poison checks\n";
        return 1;
    }
    std::cout << "PASS: batched iodine-xenon update tracks the analytic constant-power solution\n";
    return 0;
}
