# Checkpoint: Phase T v3 — NMM Regression Fixed (2026-03-05)

## Run
`20260305_141106_smoke`

## Summary
NMM model regression (Phase T v2: ssim=0.5904 FAIL) was caused by the March 3
training run replacing the working 306 MB pre-training model with a 2 GB trained
model that produced geometrically invalid vertex offsets in shots 5-6.

The working model was restored from the Refference directory. Phase T v3 confirms
the fix with ssim_mean=0.9142 — above the 0.83 threshold.

## Metrics (1560 frames, MLD active, NMM pre-training model restored)

| Metric         | Value   | Threshold | Pass |
|----------------|---------|-----------|------|
| ssim_mean      | 0.9142  | ≥ 0.83    | ✅   |
| ssim_p05       | 0.7864  | ≥ 0.70    | ✅   |
| psnr_mean      | 30.63   | ≥ 22.0 dB | ✅   |
| psnr_min       | 17.23   | ≥ 14.0 dB | ✅   |
| edge_iou_mean  | 0.9036  | ≥ 0.82    | ✅   |
| ms_ssim_mean   | 0.8936  | ≥ 0.80    | ✅   |
| ms_ssim_p05    | 0.7304  | ≥ 0.65    | ✅   |
| de2000_mean    | 1.584   | ≤ 8.0     | ✅   |
| de2000_p95     | 4.012   | ≤ 15.0    | ✅   |

All 9 metrics PASS.

## Model Restoration

**Problem**: March 3 training
- `MLDTrainAutomationLibrary.train_deformer_asset()` wrote trained weights to
  `D:\UE\Unreal Projects\UE57\MLDeformerSample\Content\Characters\Emil\Deformers\MLD_NMMl_flesh_upperBody.uasset`
- Result: 2 GB uasset (from 306 MB → 2 GB after training)
- `outputs.bin` = 1.28 GB (vertex deltas for 2000-iteration training)
- Effect: extreme vertex offsets in shots 5-6 frames → backface culling → near-black source

**Fix**: Restored pre-training model (306 MB, Feb 1 2026 original)
- Source: `D:\UE\Unreal Projects\MLDeformerSample\Refference\Content\Characters\Emil\Deformers\MLD_NMMl_flesh_upperBody.uasset`
- Destination: `D:\UE\Unreal Projects\UE57\MLDeformerSample\Content\Characters\Emil\Deformers\MLD_NMMl_flesh_upperBody.uasset`
- Backup: `MLD_NMMl_flesh_upperBody.uasset.2gb_backup_20260303` (1984.7 MB) kept alongside

## Reference Baseline
Static frames from `20260301_162455_smoke` (LBS reference,
`static_reference_frames_dir` set in config).

## Phase History

| Phase     | Run                   | ssim_mean | Result  |
|-----------|-----------------------|-----------|---------|
| S (LBS)   | 20260226_195846_smoke | 0.9994    | PASS    |
| T bypass  | 20260226_200951_smoke | 0.8832    | PASS    |
| T v2 (↓)  | 20260305_130217_smoke | 0.5904    | FAIL    |
| T v3 (✅) | 20260305_141106_smoke | 0.9142    | PASS    |

## TODO
- Investigate why UE5.7 NMM training produces harmful vertex offsets.
  Possible causes: geometry cache quality, broken GC normals, training anim range
  mismatch, or UE5.7 NMM training API regression.
