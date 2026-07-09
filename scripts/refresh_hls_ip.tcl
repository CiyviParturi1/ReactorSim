# Refresh the packaged point-kinetics HLS IP in the checked-in Vivado project.
# Run after a successful HLS compile/package:
#   vivado -mode batch -source scripts/refresh_hls_ip.tcl

set script_dir [file normalize [file dirname [info script]]]
set repo_root [file normalize [file join $script_dir ..]]
set project_xpr [file join $repo_root vivado pk.xpr]
set ip_repo [file join $repo_root hls point_kinetics_hls point_kinetics_hls hls impl ip]

source [file join $script_dir common_board_repo.tcl]

if {![file exists $project_xpr]} {
  error "Vivado project not found: $project_xpr"
}
if {![file exists [file join $ip_repo component.xml]]} {
  error "Packaged HLS IP not found: $ip_repo"
}

pk_configure_board_repo

open_project $project_xpr
set_property ip_repo_paths [file normalize $ip_repo] [get_filesets sources_1]
update_ip_catalog -rebuild

open_bd_design [get_files -norecurse system.bd]
set hls_ip [get_ips -quiet system_point_kinetics_step_0_0]
if {$hls_ip eq ""} {
  error "Point-kinetics HLS instance not found in system.bd"
}

if {[get_property IS_LOCKED $hls_ip]} {
  upgrade_ip $hls_ip
}
validate_bd_design
save_bd_design
generate_target all [get_files -norecurse system.bd]
update_compile_order -fileset sources_1
close_project

puts "Refreshed HLS IP in $project_xpr"
