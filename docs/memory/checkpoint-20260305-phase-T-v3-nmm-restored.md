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

## NN Costume Model Status

| Asset | Size (pipeline project) | Size (Refference) | Trained? | Status |
|-------|------------------------|-------------------|----------|--------|
| `MLD_NN_lowerCostume.uasset` | 258 MB (2026-03-02) | 453 MB (2026-02-01) | ✅ March 2 | OK — ssim improved vs Refference weights |
| `MLD_NN_upperCostume.uasset` | 568 MB (2026-03-02) | 832 MB (2026-02-01) | ✅ March 2 | OK — ssim improved vs Refference weights |
| `MLD_NMMl_flesh_upperBody.uasset` | 306 MB (restored) | 306 MB (2026-02-01) | ❌ (training reverted) | Pre-training state; needs proper retraining |

NN costume training (March 2) produced SMALLER models (lookup table pruned) but
**improved** ssim: T bypass (Refference NN, original NMM) = 0.8832 vs T v3
(trained NN, original NMM) = 0.9142. Costume models do NOT need restoration.

`NearestNeighborModel.ubnne` = 240 KB (2026-03-02, written alongside NN training).

## Per-Window SSIM (T v3, 100-frame windows)

| Frames | ssim_mean | Note |
|--------|-----------|------|
| 0–99 | 0.9784 | |
| 100–199 | 0.9503 | |
| 200–299 | 0.9485 | |
| 300–399 | 0.9462 | |
| 400–499 | 0.8342 | |
| **500–599** | **0.8206** | ⚠ below threshold — NMM pre-training imprecision on extreme poses |
| **600–699** | **0.8083** | ⚠ below threshold — diff_mean≈9px, NOT near-black (≠ T v2 corruption) |
| 700–799 | 0.8505 | |
| 800–1559 | 0.90–0.98 | all good |

Frames 500–699 show **mild** rendering differences (src_mean 57–89, ref_mean 70–93,
diff_mean 5–20 px) — not the catastrophic near-black collapse of T v2 (src_mean≈16).
Root cause: NMM pre-training weights predict inaccurate deformation for this
animation segment. Will resolve after proper NMM retraining.

## Phase History

| Phase     | Run                   | ssim_mean | Result  |
|-----------|----------------------|-----------|---------|
| S (LBS)   | 20260226_195846_smoke | 0.9994    | PASS    |
| T bypass  | 20260226_200951_smoke | 0.8832    | PASS    |
| T v2 (↓)  | 20260305_130217_smoke | 0.5904    | FAIL    |
| T v3 (✅) | 20260305_141106_smoke | 0.9142    | PASS    |

## TODO
- **Primary**: Investigate why NMM training (March 3) produced harmful 2GB model.
  Hypotheses: geometry cache quality / GC normals broken; training anim range
  mismatch; outputs.bin vertex deltas (1.28 GB) too large; UE5.7 NMM training
  API change writing unbounded offsets.
- Re-train NMM flesh model with corrected settings.
- Target after proper training: ssim_mean ≥ 0.92, F500–699 ssim ≥ 0.88.
