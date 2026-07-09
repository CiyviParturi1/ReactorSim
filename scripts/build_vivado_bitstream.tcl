# Build the refreshed FPGA design and export a hardware platform.
# Run from the repository root:
#   vivado -mode batch -source scripts/build_vivado_bitstream.tcl

set script_dir [file normalize [file dirname [info script]]]
set repo_root [file normalize [file join $script_dir ..]]
set project_xpr [file join $repo_root vivado pk.xpr]
set report_dir [file join $repo_root build hardware]
file mkdir $report_dir

source [file join $script_dir common_board_repo.tcl]
pk_configure_board_repo

open_project $project_xpr
reset_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 10
wait_on_run impl_1

set run_status [get_property STATUS [get_runs impl_1]]
if {![string match "*write_bitstream Complete*" $run_status]} {
  error "Implementation did not complete: $run_status"
}

open_run impl_1
report_timing_summary -file [file join $report_dir timing_summary.rpt]
report_utilization -file [file join $report_dir utilization.rpt]

set setup_path [get_timing_paths -delay_type max -max_paths 1]
set hold_path [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup_path] == 0 || [llength $hold_path] == 0} {
  error "Timing signoff failed: no setup or hold path was found."
}
set setup_slack [get_property SLACK $setup_path]
set hold_slack [get_property SLACK $hold_path]
if {$setup_slack < 0.0 || $hold_slack < 0.0} {
  error "Timing signoff failed: setup WNS=$setup_slack ns, hold WHS=$hold_slack ns."
}

write_hw_platform -fixed -include_bit -force \
    -file [file join $report_dir pk.xsa]
close_project

puts "Built bitstream and exported [file join $report_dir pk.xsa]"
