# Collect post-implementation evidence from an already completed Vivado run.

set script_dir [file normalize [file dirname [info script]]]
set repo_root [file normalize [file join $script_dir ..]]
set project_xpr [file join $repo_root vivado pk.xpr]
set report_dir [file join $repo_root build hardware]
set evidence_dir [file join $repo_root build fpga_validation]
file mkdir $report_dir
file mkdir $evidence_dir

open_project $project_xpr
open_run impl_1

report_timing_summary -file [file join $report_dir timing_summary.rpt]
report_utilization -file [file join $report_dir utilization.rpt]
report_power -file [file join $report_dir power.rpt]
report_drc -file [file join $report_dir drc.rpt]

set setup_path [get_timing_paths -delay_type max -max_paths 1]
set hold_path [get_timing_paths -delay_type min -max_paths 1]
set setup_slack [get_property SLACK $setup_path]
set hold_slack [get_property SLACK $hold_path]
set metrics [open [file join $evidence_dir vivado_metrics.txt] w]
puts $metrics "part=[get_property PART [current_design]]"
puts $metrics "run_status=[get_property STATUS [get_runs impl_1]]"
puts $metrics "setup_wns_ns=$setup_slack"
puts $metrics "hold_whs_ns=$hold_slack"
puts $metrics "clock_period_ns=10.0"
puts $metrics "clock_frequency_mhz=100.0"
puts $metrics "timing_closed=[expr {$setup_slack >= 0.0 && $hold_slack >= 0.0}]"
close $metrics

write_hw_platform -fixed -include_bit -force \
    -file [file join $report_dir pk.xsa]
close_project
puts "Collected routed reports and exported [file join $report_dir pk.xsa]"
