set_property PACKAGE_PIN F22 [get_ports {GPIO_0_tri_i[0]}]
set_property PACKAGE_PIN G22 [get_ports {GPIO_0_tri_i[1]}]
set_property PACKAGE_PIN H22 [get_ports {GPIO_0_tri_i[2]}]
set_property PACKAGE_PIN F21 [get_ports {GPIO_0_tri_i[3]}]
set_property PACKAGE_PIN H19 [get_ports {GPIO_0_tri_i[4]}]
set_property PACKAGE_PIN H18 [get_ports {GPIO_0_tri_i[5]}]
set_property PACKAGE_PIN H17 [get_ports {GPIO_0_tri_i[6]}]
set_property PACKAGE_PIN M15 [get_ports {GPIO_0_tri_i[7]}]

set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {GPIO_0_tri_i[7]}]

# Board switches are asynchronous human inputs sampled through AXI GPIO by
# software. They have no source-synchronous timing relationship to clk_fpga_0.
set_false_path -from [get_ports {GPIO_0_tri_i[*]}]
