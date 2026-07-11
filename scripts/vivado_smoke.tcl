# Minimal batch smoke test used to distinguish Vivado startup problems from
# design/IP failures. It does not open or modify a project.
puts "VIVADO_VERSION=[version -short]"
puts "VIVADO_SMOKE=PASS"
exit
