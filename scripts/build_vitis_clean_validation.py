"""Create a clean validation platform and build the ARM application with Vitis."""

from pathlib import Path

import vitis


root = Path(__file__).resolve().parents[1]
workspace = root / "vitis"
xsa = root / "build" / "hardware" / "pk.xsa"
platform_name = "pk_platform_clean"
application_name = "pk_app_clean"
domain = "standalone_ps7_cortexa9_0"

client = vitis.create_client()
try:
    client.set_workspace(path=str(workspace))
    try:
        platform = client.get_component(name=platform_name)
    except Exception:
        platform = None
    if platform is None:
        print(f"Creating {platform_name}")
        platform = client.create_platform_component(
            name=platform_name,
            hw_design=str(xsa),
            os="standalone",
            cpu="ps7_cortexa9_0",
            domain_name=domain,
            generate_dtb=False,
            compiler="gcc",
        )
    platform = client.get_component(name=platform_name)
    print(f"Building {platform_name}")
    platform.build()

    platform_xpfm = workspace / platform_name / "export" / platform_name / f"{platform_name}.xpfm"
    try:
        application = client.get_component(name=application_name)
    except Exception:
        application = None
    if application is None:
        print(f"Creating {application_name}")
        application = client.create_app_component(
            name=application_name,
            platform=str(platform_xpfm),
            domain=domain,
            template="empty_application",
        )
        application.import_files(
            from_loc=str(root / "vitis" / "pk_app" / "src"),
            files=["main.c"],
            dest_dir_in_cmp="src",
        )
    application = client.get_component(name=application_name)
    print(f"Building {application_name}")
    application.build()
finally:
    vitis.dispose()
