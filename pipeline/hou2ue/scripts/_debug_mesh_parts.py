import unreal


def _dir_filtered(obj, keys):
    out = []
    for n in dir(obj):
        lower = n.lower()
        if any(k in lower for k in keys):
            out.append(n)
    return sorted(out)


def list_skel_parts(path: str) -> None:
    sm = unreal.load_asset(path)
    if sm is None:
        unreal.log_warning(f"SKEL missing: {path}")
        return

    unreal.log(f"SKEL {path} class={type(sm)}")
    unreal.log(
        "SKEL api hints: "
        + ",".join(_dir_filtered(sm, ["mesh", "lod", "source", "import", "section", "material", "part"]))
    )

    # UE Python API for source geometry parts differs per build; try likely properties and keep best-effort logs.
    for prop in ("asset_import_data", "skeleton", "materials"):
        try:
            value = sm.get_editor_property(prop)
            unreal.log(f"SKEL prop {path} {prop}={value}")
        except Exception as exc:
            unreal.log_warning(f"SKEL prop read failed: {path} {prop} :: {exc}")


def list_gc_tracks(path: str) -> None:
    gc = unreal.load_asset(path)
    if gc is None:
        unreal.log_warning(f"GC missing: {path}")
        return

    unreal.log(f"GC {path} class={type(gc)}")
    unreal.log("GC api hints: " + ",".join(_dir_filtered(gc, ["track", "sample", "mesh", "material"])))

    track_names = []

    # Method-based API (if exposed).
    try:
        if hasattr(gc, "get_num_tracks") and hasattr(gc, "get_track_name"):
            for i in range(int(gc.get_num_tracks())):
                track_names.append(str(gc.get_track_name(i)))
    except Exception as exc:
        unreal.log_warning(f"GC method track read failed: {path} :: {exc}")

    # Property-based API (common in UE Python wrappers).
    try:
        tracks = gc.get_editor_property("tracks")
        unreal.log(f"GC {path} tracks_prop_count={len(tracks)}")
        for t in tracks:
            name = None
            for track_prop in ("track_name", "name"):
                try:
                    value = t.get_editor_property(track_prop)
                    if value is not None:
                        name = str(value)
                        break
                except Exception:
                    pass
            if name is None:
                try:
                    name = str(t.get_name())
                except Exception:
                    name = str(t)
            track_names.append(name)
    except Exception as exc:
        unreal.log_warning(f"GC property track read failed: {path} :: {exc}")

    try:
        materials = gc.get_editor_property("materials")
        unreal.log(f"GC {path} materials_count={len(materials)}")
    except Exception as exc:
        unreal.log_warning(f"GC materials read failed: {path} :: {exc}")

    unreal.log(f"GC {path} tracks={track_names}")


if __name__ == "__main__":
    list_skel_parts("/Game/Characters/Emil/Models/Body/skm_Emil")
    list_skel_parts("/Game/Characters/Emil/Models/Costume/SKM_Emil_UpperCostume")
    list_skel_parts("/Game/Characters/Emil/Models/Costume/SKM_Emil_lowerCostume")

    list_gc_tracks("/Game/Characters/Emil/GeomCache/MLD_Train/GC_upperBodyFlesh_smoke")
    list_gc_tracks("/Game/Characters/Emil/GeomCache/MLD_Train/GC_NN_upperCostume_smoke")
    list_gc_tracks("/Game/Characters/Emil/GeomCache/MLD_Train/GC_NN_lowerCostume_smoke")
