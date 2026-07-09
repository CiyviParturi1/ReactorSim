# Export the current Vivado project as a portable reconstruction script.
#
# Run from the repository root with:
#   vivado -mode batch -source scripts/export_vivado_project.tcl

set script_dir  [file normalize [file dirname [info script]]]
set repo_root   [file normalize [file join $script_dir ..]]
set project_xpr [file join $repo_root vivado pk.xpr]
set output_tcl  [file join $script_dir recreate_vivado_project.tcl]

if {![file exists $project_xpr]} {
    error "Vivado project not found: $project_xpr"
}

open_project $project_xpr
write_project_tcl -force -use_bd_files \
    -paths_relative_to $repo_root \
    $output_tcl
close_project

# write_project_tcl also records a few pieces of local/generated project state.
# Remove those so a clone needs only source-controlled inputs.
set input [open $output_tcl r]
set data [read $input]
close $input

regsub -line {^set origin_dir ".*"$} $data \
    {set origin_dir [file normalize [file join [file dirname [info script]] ..]]} data
set board_setup {# Locate the ZedBoard definition without embedding a username.
source [file join [file dirname [info script]] common_board_repo.tcl]
set board_repo [pk_board_repo_path]
if {$board_repo ne ""} {
  set_property -name "board_part_repo_paths" -value $board_repo -objects $obj
}
}
regsub -line {^set_property -name "board_part_repo_paths".*\n} $data $board_setup data

regsub {(?s)#call make_wrapper.*?\n\n\n# Set 'sources_1' fileset file properties} $data \
    {# Refresh the imported block design against the packaged HLS IP before
# generating its wrapper. A changed HLS implementation keeps VLNV 1.0 but
# increments the catalog revision, which otherwise leaves the BD locked.
open_bd_design [get_files -norecurse system.bd]
set hls_ip [get_ips -quiet system_point_kinetics_step_0_0]
if {$hls_ip ne ""} {
  upgrade_ip $hls_ip
}
validate_bd_design
save_bd_design

# Create the HDL wrapper from the block design.
set wrapper_path [make_wrapper -fileset sources_1 -files [get_files -norecurse system.bd] -top]
add_files -norecurse -fileset sources_1 $wrapper_path

# Set 'sources_1' fileset file properties} data

regsub {(?s)# Set 'utils_1' fileset object.*?# Set 'utils_1' fileset properties\nset obj \[get_filesets utils_1\]\n} $data \
    {# Do not restore generated incremental checkpoints in utils_1.
} data

regsub -all -line {^.*system_wrapper\.dcp.*\n} $data {} data
regsub -line {^set_property -name "incremental_checkpoint".*\n} $data {} data

# The generated required-path check unnecessarily nests file normalization for
# the HLS repository. It is disabled upstream, so remove that redundant block.
regsub {(?s)\n  set paths \[list \\\n.*?\n  \]\n  foreach ipath \$paths \{.*?\n  \}\n} $data "\n" data
set data [string map [list [file normalize $repo_root] {$origin_dir}] $data]

set output [open $output_tcl w]
puts -nonewline $output $data
close $output

puts "Wrote portable project script: $output_tcl"
