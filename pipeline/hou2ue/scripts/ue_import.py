#!/usr/bin/env python3
"""UE import stage: bring FBX/ABC assets into project with idempotent update behavior."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import unreal

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from ue_common import (
    apply_template,
    finalize_report,
    get_context,
    make_report,
    require_nested,
    write_stage_report,
)


def _set_prop_safe(obj: Any, name: str, value: Any) -> None:
    try:
        obj.set_editor_property(name, value)
    except Exception:
        pass


def _split_asset(asset_path: str) -> tuple[str, str]:
    folder, name = asset_path.rsplit("/", 1)
    return folder, name


def _ensure_folder(folder: str) -> None:
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        unreal.EditorAssetLibrary.make_directory(folder)


def _asset_exists(asset_path: str) -> bool:
    return unreal.EditorAssetLibrary.does_asset_exist(asset_path)


def _build_fbx_options(import_kind: str, skeleton: Optional[unreal.Skeleton]) -> unreal.FbxImportUI:
    options = unreal.FbxImportUI()
    _set_prop_safe(options, "automated_import_should_detect_type", False)
    _set_prop_safe(options, "import_materials", False)
    _set_prop_safe(options, "import_textures", False)

    if import_kind == "skeletal_mesh":
        _set_prop_safe(options, "import_mesh", True)
        _set_prop_safe(options, "import_as_skeletal", True)
        _set_prop_safe(options, "import_animations", False)
        _set_prop_safe(options, "mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    elif import_kind == "animation":
        _set_prop_safe(options, "import_mesh", False)
        _set_prop_safe(options, "import_as_skeletal", False)
        _set_prop_safe(options, "import_animations", True)
        _set_prop_safe(options, "mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
        if skeleton is not None:
            _set_prop_safe(options, "skeleton", skeleton)
    else:
        raise RuntimeError(f"Unsupported FBX import kind: {import_kind}")

    return options


def _build_abc_options() -> Optional[unreal.AbcImportSettings]:
    try:
        options = unreal.AbcImportSettings()
        _set_prop_safe(options, "import_type", unreal.AlembicImportType.GEOMETRY_CACHE)
        # Disable UE's built-in axis conversion — the Houdini side already
        # baked Y<->Z swap + x100 scale in the VEX coord transform.  Leaving
        # the default Maya preset would double-apply the axis rotation.
        try:
            conv = options.get_editor_property("conversion_settings")
            if conv is not None:
                _set_prop_safe(conv, "preset", unreal.AbcConversionPreset.CUSTOM)
                _set_prop_safe(conv, "flip_u", False)
                _set_prop_safe(conv, "flip_v", False)
                _set_prop_safe(conv, "rotation", unreal.Vector(0.0, 0.0, 0.0))
                _set_prop_safe(conv, "scale", unreal.Vector(1.0, 1.0, 1.0))
                _set_prop_safe(options, "conversion_settings", conv)
        except Exception:
            pass
        # Keep source track/object names so MLDeformer can match against skeletal mesh geometry parts.
        try:
            gc_settings = options.get_editor_property("geometry_cache_settings")
            if gc_settings is not None:
                _set_prop_safe(gc_settings, "flatten_tracks", False)
                _set_prop_safe(gc_settings, "store_imported_vertex_numbers", True)
                _set_prop_safe(gc_settings, "b_store_imported_vertex_numbers", True)
                _set_prop_safe(options, "geometry_cache_settings", gc_settings)
        except Exception:
            pass
        return options
    except Exception:
        return None


def _run_import_task(
    source_file: Path,
    destination_asset: str,
    options: Any,
) -> Dict[str, Any]:
    folder, name = _split_asset(destination_asset)
    _ensure_folder(folder)

    existed = _asset_exists(destination_asset)

    task = unreal.AssetImportTask()
    task.filename = str(source_file)
    task.destination_path = folder
    task.destination_name = name
    task.automated = True
    task.replace_existing = True
    task.replace_existing_settings = True
    task.save = True
    if options is not None:
        task.options = options

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    imported = [str(v) for v in task.get_editor_property("imported_object_paths")]
    status = "update" if existed else "create"

    result = {
        "source": str(source_file),
        "destination": destination_asset,
        "status": status,
        "imported_object_paths": imported,
        "success": len(imported) > 0 or _asset_exists(destination_asset),
    }

    if isinstance(options, unreal.AbcImportSettings):
        abc_settings: Dict[str, Any] = {}
        try:
            gc_settings = options.get_editor_property("geometry_cache_settings")
            if gc_settings is not None:
                for key in (
                    "flatten_tracks",
                    "store_imported_vertex_numbers",
                    "b_store_imported_vertex_numbers",
                    "apply_constant_topology_optimizations",
                ):
                    try:
                        abc_settings[key] = gc_settings.get_editor_property(key)
                    except Exception:
                        pass
        except Exception:
            pass
        if abc_settings:
            result["abc_import_settings"] = abc_settings

    if not result["success"]:
        result["status"] = "failed"
        result["error"] = "No imported object paths and destination asset missing"

    return result


def _load_body_skeleton(body_mesh_asset: str) -> Optional[unreal.Skeleton]:
    skm = unreal.load_asset(body_mesh_asset)
    if skm is None:
        return None
    try:
        skeleton = skm.get_editor_property("skeleton")
        if isinstance(skeleton, unreal.Skeleton):
            return skeleton
    except Exception:
        return None
    return None


def _load_coord_manifest(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "manifests" / "coord_validation_manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_extent_xyz(value: Any) -> List[float]:
    try:
        return [float(value.x), float(value.y), float(value.z)]
    except Exception:
        pass
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except Exception:
        return [0.0, 0.0, 0.0]


def _asset_bounds_size(asset_path: str) -> List[float]:
    asset = unreal.load_asset(asset_path)
    if asset is None:
        return [0.0, 0.0, 0.0]

    # Try common APIs/properties exposed by GeometryCache in UE Python.
    for fn_name in ("get_bounds", "calculate_extended_bounds", "get_imported_bounds"):
        fn = getattr(asset, fn_name, None)
        if callable(fn):
            try:
                bounds = fn()
                extent = None
                for key in ("box_extent", "boxExtent"):
                    try:
                        extent = bounds.get_editor_property(key)
                        break
                    except Exception:
                        continue
                if extent is None:
                    extent = getattr(bounds, "box_extent", None) or getattr(bounds, "boxExtent", None)
                if extent is not None:
                    ext = _extract_extent_xyz(extent)
                    return [max(0.0, 2.0 * ext[0]), max(0.0, 2.0 * ext[1]), max(0.0, 2.0 * ext[2])]
            except Exception:
                pass

    for key in ("imported_bounds", "extended_bounds", "bounds"):
        try:
            bounds = asset.get_editor_property(key)
            extent = None
            for ext_key in ("box_extent", "boxExtent"):
                try:
                    extent = bounds.get_editor_property(ext_key)
                    break
                except Exception:
                    continue
            if extent is not None:
                ext = _extract_extent_xyz(extent)
                return [max(0.0, 2.0 * ext[0]), max(0.0, 2.0 * ext[1]), max(0.0, 2.0 * ext[2])]
        except Exception:
            continue

    return [0.0, 0.0, 0.0]


def _bbox_size_from_manifest(entry: Dict[str, Any], prefix: str) -> List[float]:
    mn = entry.get(f"bbox_{prefix}_min")
    mx = entry.get(f"bbox_{prefix}_max")
    if not isinstance(mn, list) or not isinstance(mx, list) or len(mn) != 3 or len(mx) != 3:
        return [0.0, 0.0, 0.0]
    return [abs(float(mx[i]) - float(mn[i])) for i in range(3)]


def _coord_mismatch_ratio(expected: List[float], actual: List[float]) -> float:
    ratios: List[float] = []
    for e, a in zip(expected, actual):
        e = abs(float(e))
        a = abs(float(a))
        if e <= 1e-6 and a <= 1e-6:
            ratios.append(0.0)
            continue
        denom = max(e, 1e-6)
        ratios.append(abs(a - e) / denom)
    return max(ratios) if ratios else 0.0


def main() -> int:
    ctx = get_context()
    cfg = ctx["config"]
    run_dir: Path = ctx["run_dir"]
    profile: str = ctx["profile"]

    report = make_report(
        "ue_import",
        profile,
        {
            "config": str(ctx["config_path"]),
            "profile": profile,
            "run_dir": str(run_dir),
        },
    )

    try:
        art_root = Path(require_nested(cfg, ("paths", "art_source_root")))
        if not art_root.exists():
            raise RuntimeError(f"ArtSource path does not exist: {art_root}")

        coord_manifest = _load_coord_manifest(run_dir)
        coord_entries = coord_manifest.get("entries", {}) if isinstance(coord_manifest.get("entries"), dict) else {}
        houdini_cfg = cfg.get("houdini", {}) if isinstance(cfg.get("houdini"), dict) else {}
        coord_cfg = houdini_cfg.get("coord_system", {}) if isinstance(houdini_cfg.get("coord_system"), dict) else {}
        validate_cfg = coord_cfg.get("validate", {}) if isinstance(coord_cfg.get("validate"), dict) else {}
        coord_validate_enabled = bool(validate_cfg.get("enabled", False))
        coord_tolerance = float(validate_cfg.get("tolerance", 0.15))
        coord_fail_on_mismatch = bool(validate_cfg.get("fail_on_mismatch", True))

        import_cfg = require_nested(cfg, ("ue", "imports"))
        skm_jobs = list(require_nested(import_cfg, ("skeletal_meshes",)))
        anim_jobs = list(require_nested(import_cfg, ("animations",)))
        baseline_cfg = cfg.get("reference_baseline", {}) if isinstance(cfg.get("reference_baseline"), dict) else {}
        skip_static_imports = bool(baseline_cfg.get("enabled", False))

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        coord_targets: Dict[str, str] = {}

        # 1) Skeletal meshes.
        for job in skm_jobs:
            dst = str(require_nested(job, ("destination",)))
            if skip_static_imports:
                exists = _asset_exists(dst)
                results.append(
                    {
                        "source": "",
                        "destination": dst,
                        "status": "skip_baseline",
                        "imported_object_paths": [],
                        "success": bool(exists),
                    }
                )
                if not exists:
                    errors.append({"message": f"Missing baseline-synced skeletal mesh: {dst}", "destination": dst})
                continue

            src = art_root / str(require_nested(job, ("source_rel",)))
            if not src.exists():
                errors.append({"message": f"Missing source file: {src}", "destination": dst})
                continue
            options = _build_fbx_options("skeletal_mesh", skeleton=None)
            result = _run_import_task(src, dst, options)
            results.append(result)
            if not result["success"]:
                errors.append({"message": result.get("error", "Import failed"), "destination": dst})

        # 2) Load skeleton from body mesh for animation import.
        body_mesh_asset = "/Game/Characters/Emil/Models/Body/skm_Emil"
        body_skeleton = _load_body_skeleton(body_mesh_asset)

        # 3) Animations.
        for job in anim_jobs:
            dst = str(require_nested(job, ("destination",)))
            if skip_static_imports:
                exists = _asset_exists(dst)
                results.append(
                    {
                        "source": "",
                        "destination": dst,
                        "status": "skip_baseline",
                        "imported_object_paths": [],
                        "success": bool(exists),
                    }
                )
                if not exists:
                    errors.append({"message": f"Missing baseline-synced animation: {dst}", "destination": dst})
                continue

            src = art_root / str(require_nested(job, ("source_rel",)))
            if not src.exists():
                errors.append({"message": f"Missing source file: {src}", "destination": dst})
                continue
            options = _build_fbx_options("animation", skeleton=body_skeleton)
            result = _run_import_task(src, dst, options)
            results.append(result)
            if not result["success"]:
                errors.append({"message": result.get("error", "Import failed"), "destination": dst})

        # 4) Dynamic flesh geometry cache from convert stage output.
        dynamic_cfg = require_nested(cfg, ("ue", "dynamic_assets"))
        gc_dst_template = str(require_nested(dynamic_cfg, ("flesh_geom_cache_destination_template",)))
        gc_dst = apply_template(gc_dst_template, profile)

        gc_src = run_dir / "workspace" / "staging" / profile / "houdini_exports" / f"GC_upperBodyFlesh_{profile}.abc"
        if not gc_src.exists():
            errors.append({
                "message": "Missing Houdini export Alembic for UE import",
                "source": str(gc_src),
                "destination": gc_dst,
            })
        else:
            result = _run_import_task(gc_src, gc_dst, _build_abc_options())
            results.append(result)
            if not result["success"]:
                errors.append({"message": result.get("error", "GeomCache import failed"), "destination": gc_dst})
            else:
                coord_targets["flesh"] = gc_dst

        # 5) Optional NNM geometry caches (upper/lower costume), exported during convert stage.
        for key in (
            "nnm_upper_geom_cache_destination_template",
            "nnm_lower_geom_cache_destination_template",
        ):
            template = str(dynamic_cfg.get(key, "") or "").strip()
            if not template:
                continue

            dst_asset = apply_template(template, profile)
            asset_name = dst_asset.rsplit("/", 1)[-1]
            src_abc = run_dir / "workspace" / "staging" / profile / "houdini_exports" / f"{asset_name}.abc"
            if not src_abc.exists():
                errors.append(
                    {
                        "message": "Missing NNM Alembic export for UE import",
                        "source": str(src_abc),
                        "destination": dst_asset,
                    }
                )
                continue

            result = _run_import_task(src_abc, dst_asset, _build_abc_options())
            results.append(result)
            if not result["success"]:
                errors.append({"message": result.get("error", "GeomCache import failed"), "destination": dst_asset})
            else:
                entry_name = "nnm_upper" if "upper" in key.lower() else "nnm_lower"
                coord_targets[entry_name] = dst_asset

        coord_rows: List[Dict[str, Any]] = []
        coord_errors: List[Dict[str, Any]] = []
        if coord_validate_enabled:
            for entry_name, asset_path in coord_targets.items():
                manifest_entry = coord_entries.get(entry_name, {})
                if not isinstance(manifest_entry, dict) or not manifest_entry:
                    coord_errors.append(
                        {
                            "message": "coord validation entry missing in manifest",
                            "entry": entry_name,
                            "asset_path": asset_path,
                        }
                    )
                    continue

                expected_size = _bbox_size_from_manifest(manifest_entry, "output")
                actual_size = _asset_bounds_size(asset_path)
                bounds_available = any(abs(v) > 1e-6 for v in actual_size)
                if not bounds_available:
                    unreal.log_warning(
                        f"[coord_validation] Bounds unavailable for '{entry_name}' "
                        f"({asset_path}). Strict bbox check SKIPPED — "
                        f"double-transform errors cannot be detected. "
                        f"Expected bbox size: {expected_size}"
                    )
                    row = {
                        "entry": entry_name,
                        "asset_path": asset_path,
                        "expected_bbox_size": expected_size,
                        "actual_bbox_size": actual_size,
                        "mismatch_ratio": 0.0,
                        "tolerance": coord_tolerance,
                        "passed": True,
                        "bounds_available": False,
                        "message": "WARNING: bounds unavailable from UE API; skipped strict bbox check — potential double-transform undetectable",
                    }
                    coord_rows.append(row)
                    continue

                mismatch_ratio = _coord_mismatch_ratio(expected_size, actual_size)
                passed = mismatch_ratio <= coord_tolerance
                row = {
                    "entry": entry_name,
                    "asset_path": asset_path,
                    "expected_bbox_size": expected_size,
                    "actual_bbox_size": actual_size,
                    "mismatch_ratio": mismatch_ratio,
                    "tolerance": coord_tolerance,
                    "passed": passed,
                    "bounds_available": True,
                }
                coord_rows.append(row)
                if not passed:
                    coord_errors.append(
                        {
                            "message": "coord validation mismatch",
                            "entry": entry_name,
                            "asset_path": asset_path,
                            "expected_bbox_size": expected_size,
                            "actual_bbox_size": actual_size,
                            "mismatch_ratio": mismatch_ratio,
                            "tolerance": coord_tolerance,
                        }
                    )

        coord_status = "success"
        if coord_validate_enabled and coord_fail_on_mismatch and coord_errors:
            coord_status = "failed"
            errors.extend(coord_errors)

        coord_report = make_report(
            "coord_validation",
            profile,
            {
                "run_dir": str(run_dir),
                "coord_manifest_path": str((run_dir / "manifests" / "coord_validation_manifest.json").resolve()),
                "enabled": coord_validate_enabled,
                "tolerance": coord_tolerance,
                "fail_on_mismatch": coord_fail_on_mismatch,
            },
        )
        finalize_report(
            coord_report,
            status=coord_status,
            outputs={
                "entries_checked": coord_rows,
                "manifest_entries": sorted(coord_entries.keys()),
                "target_entries": sorted(coord_targets.keys()),
            },
            errors=coord_errors,
        )
        coord_report_path = write_stage_report(run_dir, "coord_validation", coord_report)

        status = "success" if not errors else "failed"
        finalize_report(
            report,
            status=status,
            outputs={
                "asset_results": results,
                "imported_count": len([r for r in results if r.get("success")]),
                "failed_count": len(errors),
                "body_skeleton_loaded": body_skeleton is not None,
                "skip_static_imports": skip_static_imports,
                "coord_validation_enabled": coord_validate_enabled,
                "coord_validation_status": coord_status,
                "coord_validation_report": str(coord_report_path.resolve()),
            },
            errors=errors,
        )

        write_stage_report(run_dir, "ue_import", report)
        return 0 if status == "success" else 1

    except Exception as exc:
        finalize_report(
            report,
            status="failed",
            outputs={},
            errors=[{"message": str(exc), "traceback": traceback.format_exc()}],
        )
        write_stage_report(run_dir, "ue_import", report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
