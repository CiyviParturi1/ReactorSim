"""Rebuild the Vitis platform and ARM application from the current XSA."""

from pathlib import Path

import vitis


repo_root = Path(__file__).resolve().parent.parent
workspace = repo_root / "vitis"
xsa = repo_root / "build" / "hardware" / "pk.xsa"

if not xsa.is_file():
    raise FileNotFoundError(
        f"Missing {xsa}; run scripts/build_vivado_bitstream.tcl first."
    )

client = vitis.create_client()
try:
    client.set_workspace(path=str(workspace))

    platform = client.get_component(name="pk_platform")
    if platform is None:
        raise RuntimeError("Vitis component 'pk_platform' was not found.")
    platform.update_hw(hw_design=str(xsa))
    platform.build()

    application = client.get_component(name="pk_app")
    if application is None:
        raise RuntimeError("Vitis component 'pk_app' was not found.")
    application.build()
finally:
    vitis.dispose()
