import json
import time
from pathlib import Path

import unreal


def _set_prop_safe(obj, name, value):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception:
        return False


def _get_prop_safe(obj, name, default=None):
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def _param_lookup(params, key, required=False, default=""):
    if key in params:
        return params[key]
    lower_key = key.lower()
    for item_key, item_value in params.items():
        if str(item_key).lower() == lower_key:
            return item_value
    if required:
        raise RuntimeError(f"Missing command line argument: -{key}=<value>")
    return default


def _load_asset_checked(asset_path):
    asset = unreal.load_asset(asset_path)
    if asset is None:
        raise RuntimeError(f"Failed to load UE asset: {asset_path}")
    return asset


def _resolve_sequence_playback_range(level_sequence):
    try:
        start = int(unreal.MovieSceneSequenceExtensions.get_playback_start(level_sequence))
        end = int(unreal.MovieSceneSequenceExtensions.get_playback_end(level_sequence))
        if end < start:
            end = start
        return start, end
    except Exception:
        return 0, 119


def _set_frame_prop(output_settings, prop_name, frame_value):
    if _set_prop_safe(output_settings, prop_name, int(frame_value)):
        return
    try:
        _set_prop_safe(output_settings, prop_name, unreal.FrameNumber(int(frame_value)))
    except Exception:
        pass


def _iter_tracks_from_binding(binding):
    try:
        tracks = list(binding.get_tracks())
        if tracks:
            return tracks
    except Exception:
        pass
    tracks = _get_prop_safe(binding, "tracks", [])
    return list(tracks) if tracks else []


def _iter_sections_from_track(track):
    try:
        sections = list(track.get_sections())
        if sections:
            return sections
    except Exception:
        pass
    sections = _get_prop_safe(track, "sections", [])
    return list(sections) if sections else []


def _swap_sequence_animation(level_sequence, anim_sequence):
    replaced_sections = 0
    originals = []
    bindings = []
    try:
        bindings = list(level_sequence.get_bindings())
    except Exception:
        movie_scene = None
        try:
            movie_scene = level_sequence.get_movie_scene()
        except Exception:
            movie_scene = _get_prop_safe(level_sequence, "movie_scene", None)
        if movie_scene is not None:
            try:
                bindings = list(movie_scene.get_bindings())
            except Exception:
                bindings = list(_get_prop_safe(movie_scene, "bindings", []))

    for binding in bindings:
        for track in _iter_tracks_from_binding(binding):
            class_name = ""
            try:
                class_name = str(track.get_class().get_name()).lower()
            except Exception:
                class_name = str(type(track)).lower()
            if "skeletalanimationtrack" not in class_name:
                continue

            for section in _iter_sections_from_track(track):
                params = _get_prop_safe(section, "params", None)
                if params is None:
                    continue
                original_anim = _get_prop_safe(params, "animation", None)
                if not _set_prop_safe(params, "animation", anim_sequence):
                    continue
                _set_prop_safe(section, "params", params)
                replaced_sections += 1
                originals.append((section, original_anim))

    if replaced_sections <= 0:
        raise RuntimeError("No MovieSceneSkeletalAnimationSection found in target LevelSequence")
    return replaced_sections, originals


def _restore_sequence_animation(originals):
    restored = 0
    for item in originals or []:
        try:
            section, original_anim = item
        except Exception:
            continue
        params = _get_prop_safe(section, "params", None)
        if params is None:
            continue
        if not _set_prop_safe(params, "animation", original_anim):
            continue
        _set_prop_safe(section, "params", params)
        restored += 1
    return restored


def _collect_frames(output_dir):
    root = Path(output_dir)
    if not root.exists():
        return []
    return sorted([str(p.resolve()) for p in root.rglob("*.png") if p.is_file()])


@unreal.uclass()
class Hou2UeDemoRuntimeExecutor(unreal.MoviePipelinePythonHostExecutor):
    active_movie_pipeline = unreal.uproperty(unreal.MoviePipeline)
    started_epoch_ts = unreal.uproperty(float)
    started_monotonic_ts = unreal.uproperty(float)
    last_progress_log_ts = unreal.uproperty(float)
    demo_report_json = unreal.uproperty(str)
    demo_output_dir = unreal.uproperty(str)
    demo_sequence = unreal.uproperty(str)
    demo_anim = unreal.uproperty(str)
    demo_map = unreal.uproperty(str)
    replaced_sections = unreal.uproperty(int)
    frame_start = unreal.uproperty(int)
    frame_end = unreal.uproperty(int)
    output_res_x = unreal.uproperty(int)
    output_res_y = unreal.uproperty(int)
    warmup_frames = unreal.uproperty(int)
    restored_sections = unreal.uproperty(int)

    def _post_init(self):
        self.active_movie_pipeline = None
        self.started_epoch_ts = 0.0
        self.started_monotonic_ts = 0.0
        self.last_progress_log_ts = 0.0
        self.demo_report_json = ""
        self.demo_output_dir = ""
        self.demo_sequence = ""
        self.demo_anim = ""
        self.demo_map = ""
        self.replaced_sections = 0
        self.frame_start = 0
        self.frame_end = 119
        self.output_res_x = 1280
        self.output_res_y = 720
        self.warmup_frames = 0
        self.restored_sections = 0
        self._animation_originals = []

    def _restore_swapped_animation_sections(self):
        restored = _restore_sequence_animation(getattr(self, "_animation_originals", []))
        self.restored_sections = int(restored)
        self._animation_originals = []
        return restored

    def _write_report(self, status, success, message, output_data):
        if not self.demo_report_json:
            return

        now_ts = time.time()
        if self.started_epoch_ts > 0.0 and now_ts < self.started_epoch_ts:
            now_ts = self.started_epoch_ts

        duration = 0.0
        if self.started_monotonic_ts > 0.0:
            duration = max(0.0, time.monotonic() - self.started_monotonic_ts)
        ended_epoch = now_ts
        if self.started_epoch_ts > 0.0:
            ended_epoch = max(ended_epoch, self.started_epoch_ts + duration)

        payload = {
            "stage": "infer_demo_job",
            "status": status,
            "success": bool(success),
            "message": str(message),
            "started_epoch_sec": self.started_epoch_ts,
            "ended_epoch_sec": ended_epoch,
            "duration_sec": round(duration, 3),
            "inputs": {
                "sequence": self.demo_sequence,
                "animation": self.demo_anim,
                "map": self.demo_map,
                "frame_start": int(self.frame_start),
                "frame_end": int(self.frame_end),
                "output_resolution": [int(self.output_res_x), int(self.output_res_y)],
                "warmup_frames": int(self.warmup_frames),
            },
            "outputs": output_data or {},
            "errors": [] if success else [{"message": str(message)}],
        }

        report_path = Path(self.demo_report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    @unreal.ufunction(override=True)
    def execute_delayed(self, in_pipeline_queue):
        del in_pipeline_queue

        self.started_epoch_ts = time.time()
        self.started_monotonic_ts = time.monotonic()
        self.last_progress_log_ts = self.started_epoch_ts

        try:
            (_, _, cmd_params) = unreal.SystemLibrary.parse_command_line(unreal.SystemLibrary.get_command_line())
            self.demo_sequence = str(_param_lookup(cmd_params, "DemoSequence", required=True))
            self.demo_anim = str(_param_lookup(cmd_params, "DemoAnim", required=False, default=""))
            self.demo_output_dir = str(_param_lookup(cmd_params, "DemoOutputDir", required=True))
            self.demo_report_json = str(_param_lookup(cmd_params, "DemoReportJson", required=True))
            self.demo_map = str(_param_lookup(cmd_params, "DemoMap", required=False, default=""))
            self.output_res_x = int(_param_lookup(cmd_params, "DemoResX", required=False, default="1280"))
            self.output_res_y = int(_param_lookup(cmd_params, "DemoResY", required=False, default="720"))
            frame_start_raw = str(_param_lookup(cmd_params, "DemoStartFrame", required=False, default="")).strip()
            frame_end_raw = str(_param_lookup(cmd_params, "DemoEndFrame", required=False, default="")).strip()
            zero_pad = int(_param_lookup(cmd_params, "DemoZeroPad", required=False, default="4"))
            self.warmup_frames = int(_param_lookup(cmd_params, "DemoWarmupFrames", required=False, default="0"))

            output_dir = Path(self.demo_output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            sequence_asset = _load_asset_checked(self.demo_sequence)
            auto_start, auto_end = _resolve_sequence_playback_range(sequence_asset)
            self.frame_start = int(frame_start_raw) if frame_start_raw else int(auto_start)
            self.frame_end = int(frame_end_raw) if frame_end_raw else int(auto_end)
            if self.frame_end < self.frame_start:
                raise RuntimeError("DemoEndFrame must be >= DemoStartFrame")

            self.replaced_sections = 0
            self.restored_sections = 0
            self._animation_originals = []
            if self.demo_anim:
                anim_asset = _load_asset_checked(self.demo_anim)
                replaced, originals = _swap_sequence_animation(sequence_asset, anim_asset)
                self.replaced_sections = int(replaced)
                self._animation_originals = originals

            self.pipeline_queue = unreal.new_object(unreal.MoviePipelineQueue, outer=self)
            job = self.pipeline_queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
            job.sequence = unreal.SoftObjectPath(self.demo_sequence)
            if self.demo_map:
                _set_prop_safe(job, "map", unreal.SoftObjectPath(self.demo_map))

            config = job.get_configuration()
            output_settings = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
            output_settings.output_resolution = unreal.IntPoint(int(self.output_res_x), int(self.output_res_y))
            output_settings.file_name_format = "{sequence_name}.{frame_number}"
            output_settings.output_directory = unreal.DirectoryPath(str(output_dir))
            _set_prop_safe(output_settings, "use_custom_playback_range", True)
            _set_frame_prop(output_settings, "custom_start_frame", self.frame_start)
            _set_frame_prop(output_settings, "custom_end_frame", self.frame_end)
            _set_prop_safe(output_settings, "zero_pad_frame_numbers", zero_pad)

            if self.warmup_frames > 0:
                aa = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
                _set_prop_safe(aa, "engine_warm_up_count", int(self.warmup_frames))
                _set_prop_safe(aa, "render_warm_up_count", int(self.warmup_frames))

            config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
            config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
            config.initialize_transient_settings()

            self.active_movie_pipeline = unreal.new_object(
                self.target_pipeline_class,
                outer=self.get_last_loaded_world(),
                base_type=unreal.MoviePipeline,
            )
            self.active_movie_pipeline.on_movie_pipeline_work_finished_delegate.add_function_unique(
                self,
                "on_movie_pipeline_finished",
            )
            self.active_movie_pipeline.initialize(job)
            unreal.log(
                f"[hou2ue] Demo capture started: sequence={self.demo_sequence}, anim={self.demo_anim}, output={self.demo_output_dir}"
            )
        except Exception as exc:
            self._restore_swapped_animation_sections()
            unreal.log_error(f"[hou2ue] Demo capture execute_delayed failed: {exc}")
            self._write_report(
                status="failed",
                success=False,
                message=str(exc),
                output_data={},
            )
            self.on_executor_errored()

    @unreal.ufunction(override=True)
    def on_begin_frame(self):
        super(Hou2UeDemoRuntimeExecutor, self).on_begin_frame()

        if not self.active_movie_pipeline:
            return
        now = time.time()
        if (now - self.last_progress_log_ts) < 5.0:
            return
        self.last_progress_log_ts = now
        try:
            progress = unreal.MoviePipelineLibrary.get_completion_percentage(self.active_movie_pipeline)
            unreal.log(f"[hou2ue] Demo capture progress={progress:.3f}")
        except Exception:
            pass

    @unreal.ufunction(override=True)
    def on_map_load(self, in_world):
        del in_world
        pass

    @unreal.ufunction(override=True)
    def is_rendering(self):
        return self.active_movie_pipeline is not None

    @unreal.ufunction(ret=None, params=[unreal.MoviePipelineOutputData])
    def on_movie_pipeline_finished(self, results):
        success = bool(getattr(results, "success", False))
        self._restore_swapped_animation_sections()
        frames = _collect_frames(self.demo_output_dir)
        first_frame = frames[0] if frames else ""
        last_frame = frames[-1] if frames else ""
        message = "Render finished successfully" if success else "Render finished with failure"
        self._write_report(
            status="success" if success else "failed",
            success=success,
            message=message,
            output_data={
                "frame_count": len(frames),
                "first_frame": first_frame,
                "last_frame": last_frame,
                "output_dir": str(Path(self.demo_output_dir).resolve()),
                "replaced_animation_sections": int(self.replaced_sections),
                "restored_animation_sections": int(self.restored_sections),
            },
        )

        self.active_movie_pipeline = None
        if success:
            self.on_executor_finished_impl()
        else:
            self.on_executor_errored()
