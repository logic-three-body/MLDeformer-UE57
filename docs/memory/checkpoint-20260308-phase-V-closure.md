# Checkpoint: Phase V Closure — NMM Global 128 Morphs PASS

**Date:** 2026-03-08
**Status:** ✅ CLOSURE ACHIEVED

---

## Summary

Phase V objective completed. NMM switched from Local mode to Global mode with 128 morph targets.
All three primary closure criteria exceeded.

---

## Training

| Parameter | Value |
|---|---|
| Mode | `global` |
| `global_num_morph_targets` | 128 |
| `num_iterations` | 25000 |
| `training_data_source` | `upperBodyFlesh_5kGreedyROM` |
| Final loss | ~0.011 |
| Training time | ~16 min (956 s) |
| NMM asset size | 207.1 MB |
| Completed at | 2026-03-08T00:32:16 local |

---

## gt_compare Results (1560 frames)

| Metric | Value | Threshold | Status |
|---|---|---|---|
| `ssim_mean` | **0.8999** | ≥ 0.83 | ✅ PASS |
| `ssim_p05` | **0.8122** | ≥ 0.70 | ✅ PASS |
| `psnr_mean` | **29.15** | ≥ 22.0 | ✅ PASS |
| `psnr_min` | **21.81** | ≥ 14.0 | ✅ PASS |
| `edge_iou_mean` | **0.9200** | ≥ 0.82 | ✅ PASS |
| `ms_ssim_mean` | **0.8659** | ≥ 0.80 | ✅ PASS |
| `ms_ssim_p05` | **0.7179** | ≥ 0.65 | ✅ PASS |
| `de2000_mean` | **2.156** | ≤ 8.0 | ✅ PASS |
| `de2000_p95` | **4.755** | ≤ 15.0 | ✅ PASS |
| `body_roi_ssim_mean` | 0.8576 | *(info)* | — |
| `body_roi_psnr_mean` | 27.90 | *(info)* | — |

gt_compare completed at: 2026-03-08T01:06:23 local (ended_at: 2026-03-07T17:06:23Z)

---

## Root Cause (Phase V2 fix)

- **Before (Local mode, 1680 MB):** ssim_mean = 0.6599 at 50k iters — FAIL
- **After (Global mode, 207 MB):** ssim_mean = 0.8999 at 25k iters — PASS
- Local mode over-parameterized the mesh: 1680 MB vs Epic Reference 306 MB
- Global mode with 128 morphs matches Epic Reference architecture intent

---

## gt_source_capture Notes

UE crashed 3 times during capture (exit code -1 / 4294967295) at ~18%, ~43%, ~62.7% of 1560 frames.
Resume logic in the pipeline accumulated all captured frames across restarts.
All 1560 PNG source frames captured successfully at 2026-03-08T00:43:34 local.

---

## Files Changed (Phase V)

- `pipeline/hou2ue/config/pipeline.full_exec.yaml` — `mode: global`, `global_num_morph_targets: 128`
- `Content/Characters/Emil/Deformers/MLD_NMMl_flesh_upperBody.uasset` — 207.1 MB (new weights)
- `docs/memory/checkpoint-20260308-phase-V2-global-mode-root-cause.md` — root cause analysis
- `docs/memory/checkpoint-20260308-phase-V-closure.md` — this file

---

## Next Steps

Phase V is closed. Pipeline is proven end-to-end with global NMM mode.
Possible follow-ups:
- Increase `global_num_morph_targets` to 256 (V3 experiment) to see if ssim improves further
- Profile inference latency on target hardware
- Package pipeline docs for handoff
