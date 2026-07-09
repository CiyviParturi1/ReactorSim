# Shared ZedBoard board-store discovery for Vivado batch scripts.
# Prefer PK_BOARD_REPO; otherwise use the default Vivado 2025.2 Windows store.

proc pk_configure_board_repo {} {
  if {[info exists ::env(PK_BOARD_REPO)]} {
    set_param board.repoPaths [list [file normalize $::env(PK_BOARD_REPO)]]
    return
  }
  if {[info exists ::env(APPDATA)]} {
    set board_repo [file normalize [file join \
        $::env(APPDATA) Xilinx Vivado 2025.2 xhub board_store xilinx_board_store]]
    if {[file isdirectory $board_repo]} {
      set_param board.repoPaths [list $board_repo]
    }
  }
}

proc pk_board_repo_path {} {
  if {[info exists ::env(PK_BOARD_REPO)]} {
    return [file normalize $::env(PK_BOARD_REPO)]
  }
  if {[info exists ::env(APPDATA)]} {
    set candidate [file normalize [file join \
        $::env(APPDATA) Xilinx Vivado 2025.2 xhub board_store xilinx_board_store]]
    if {[file isdirectory $candidate]} {
      return $candidate
    }
  }
  return ""
}
