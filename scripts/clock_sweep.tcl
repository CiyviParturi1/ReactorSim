# Implement the synthesized design at one alternate clock period.
# Set PK_SWEEP_PERIOD in the invoking environment, for example 8, 7, 6 or 5.

if {![info exists ::env(PK_SWEEP_PERIOD)]} {
  error "PK_SWEEP_PERIOD is not set"
}
set period [expr {double($::env(PK_SWEEP_PERIOD))}]
set script_dir [file normalize [file dirname [info script]]]
set repo_root [file normalize [file join $script_dir ..]]
set run_dir [file join $repo_root build fpga_validation clock_sweep_${period}ns]
file mkdir $run_dir

create_project -in_memory -part xc7z020clg484-1
set_property ip_repo_paths [file join $repo_root hls point_kinetics_hls point_kinetics_hls hls impl ip] [current_project]
update_ip_catalog
add_files -quiet [file join $repo_root vivado pk.runs synth_1 system_wrapper.dcp]
add_files [file join $repo_root vivado pk.srcs sources_1 bd system system.bd]
read_xdc [file join $repo_root vivado pk.srcs constrs_1 new switches.xdc]
link_design -top system_wrapper -part xc7z020clg484-1

set clock [get_clocks clk_fpga_0]
if {[llength $clock] != 1} {
  error "Expected one clk_fpga_0 clock, found: $clock"
}
create_clock -add -name clk_fpga_sweep -period $period \
    -waveform [list 0.0 [expr {$period / 2.0}]] \
    [get_pins system_i/processing_system7_0/FCLK_CLK0]
update_timing

opt_design
place_design
phys_opt_design
route_design

report_timing_summary -file [file join $run_dir timing_summary.rpt]
report_utilization -file [file join $run_dir utilization.rpt]
set setup_path [get_timing_paths -delay_type max -from [get_clocks clk_fpga_sweep] -to [get_clocks clk_fpga_sweep] -max_paths 1]
set hold_path [get_timing_paths -delay_type min -from [get_clocks clk_fpga_sweep] -to [get_clocks clk_fpga_sweep] -max_paths 1]
set setup_slack [get_property SLACK $setup_path]
set hold_slack [get_property SLACK $hold_path]
set metrics [open [file join $run_dir metrics.txt] w]
puts $metrics "period_ns=$period"
puts $metrics "frequency_mhz=[expr {1000.0 / $period}]"
puts $metrics "wns_ns=$setup_slack"
puts $metrics "whs_ns=$hold_slack"
puts $metrics "timing_closed=[expr {$setup_slack >= 0.0 && $hold_slack >= 0.0}]"
close $metrics
write_checkpoint -force [file join $run_dir routed.dcp]
close_project
puts "Clock sweep period ${period} ns: WNS=$setup_slack ns, WHS=$hold_slack ns"
