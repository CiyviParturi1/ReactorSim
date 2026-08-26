# Wire the HLS engine's interrupt pin into the Zynq PS interrupt inputs.
# Run from the repository root:
#   vivado -mode batch -source scripts/wire_hls_interrupt.tcl
#
# Enables the PS fabric-interrupt input and routes the single engine done
# signal straight to IRQ_F2P[0] (GIC ID 61). No concatenation is needed
# because only one fabric interrupt exists in this design.

set script_dir  [file normalize [file dirname [info script]]]
set repo_root   [file normalize [file join $script_dir ..]]
set project_xpr [file join $repo_root vivado pk.xpr]

source [file join $script_dir common_board_repo.tcl]
pk_configure_board_repo

open_project $project_xpr
open_bd_design [get_files -norecurse system.bd]

set ps7 [get_bd_cells -filter {VLNV =~ *processing_system7*}]
if {[get_property CONFIG.PCW_USE_FABRIC_INTERRUPT $ps7] == 0} {
    set_property -dict [list \
        CONFIG.PCW_USE_FABRIC_INTERRUPT 1 \
        CONFIG.PCW_IRQ_F2P_INTR 1 \
        CONFIG.PCW_IRQ_F2P_MODE DIRECT] $ps7
}

if {[llength [get_bd_nets -quiet -of_objects \
        [get_bd_pins point_kinetics_step_0/interrupt]]] == 0} {
    connect_bd_net [get_bd_pins point_kinetics_step_0/interrupt] \
        [get_bd_pins $ps7/IRQ_F2P]
}

validate_bd_design
save_bd_design
close_project
puts "HLS interrupt wired to processing_system7 IRQ_F2P[0]."
