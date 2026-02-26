import unreal

try:
    import Hou2UeDemoRuntimeExecutor  # noqa: F401

    unreal.log("[hou2ue] Loaded Python runtime executor: Hou2UeDemoRuntimeExecutor")
except Exception as exc:
    unreal.log_error(f"[hou2ue] Failed to load Hou2UeDemoRuntimeExecutor: {exc}")
