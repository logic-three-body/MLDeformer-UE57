# Checkpoint: Phase T v4b — NMM Baseline Confirmed (2026-03-05)

## 摘要

完成 NMM 训练调查并确认稳定基线：

- **T v4（hero64 训练测试）**：ssim=0.637 ❌ — 训练数据几何质量正常但 pose 覆盖不足
- **T v4b（Refference 还原确认）**：ssim=0.9142 ✅ — 与 T v3 完全一致，基线稳定

---

## 执行时间线（2026-03-05，续 T v3）

| 时间（本地）| 事件 |
|------------|------|
| 15:53 | 启动 hero64 GC 训练（`run_all.ps1 -Stage train`，profile=smoke）|
| 16:21 | 训练完成：`MLD_NMMl_flesh_upperBody.uasset` = 357 MB，25,000 iter，loss→0.021 |
| 16:32 | gt_source_capture（hero64-trained NMM），1560 帧，exit=0 |
| 17:02 | gt_compare T v4：ssim=0.637 **FAIL** |
| 17:10 | 还原 Refference NMM（306 MB），backup → `.hero64_backup_20260305` |
| 17:14 | gt_source_capture（Refference NMM），1560 帧，exit=0 |
| 17:39 | gt_compare T v4b：ssim=0.9142 **PASS** ✅ |

---

## T v4 hero64 训练详情

### 配置变更（`pipeline.full_exec.yaml`）
```yaml
# 改为 hero64 GC + 动画（防止 smoke GC 极端顶点偏移）
deformer_assets.flesh.training_input_anims:
  anim_sequence: /Game/Characters/Emil/Animation/MLD_train/upperBodyFlesh_hero64
  geometry_cache_template: /Game/Characters/Emil/GeomCache/MLD_Train/GC_upperBodyFlesh_hero64
```

### 训练质量（outputs.bin 分析，5065帧×111769顶点）
| 指标 | hero64 训练 | smoke 训练（T v2，有害）|
|------|------------|----------------------|
| p50_max vertex offset | **4.0 cm** ✅ | 90.7 cm ⚠️ |
| p90_max | 7.9 cm | 119.7 cm |
| max | 65.2 cm | 148.7 cm |
| 帧数 > 80 cm | 0/5065 ✅ | 675/1001 (67%) |

### T v4 推理结果（全失败）
```
ssim_mean=0.637,  psnr_mean=17.87,  de2000_mean=8.66  → FAILED
Per-window range: 0.4982 – 0.8026 (all windows degraded)
```

**失败根因**：hero64 动画（5065帧）的 pose 分布≠ Main_Sequence 的 pose 分布，
NMM 推理在 OOD（out-of-distribution）姿态下产生错误形变。

---

## T v4b 结果（Refference 306 MB 还原）

| 指标 | 实测值 | 阈值 | 状态 |
|------|--------|------|------|
| ssim_mean | **0.9142** | ≥ 0.83 | ✅ |
| ssim_p05 | 0.7864 | ≥ 0.70 | ✅ |
| psnr_mean | **30.63 dB** | ≥ 22.0 | ✅ |
| edge_iou_mean | 0.9036 | ≥ 0.82 | ✅ |
| ms_ssim_mean | 0.8936 | ≥ 0.80 | ✅ |
| de2000_mean | **1.58** | ≤ 8.0 | ✅ |

Per-window（T v4b，与 T v3 完全一致）：
```
F0-99:    0.9784  F100-199: 0.9503  F200-299: 0.9485
F300-399: 0.9462  F400-499: 0.8342  F500-599: 0.8206
F600-699: 0.8083  F700-799: 0.8505  F800-899: 0.8986
F900-999: 0.9269  F1000-1099:0.8941 F1100-1199:0.9459
F1200-1299:0.9799 F1300-1399:0.9569 F1400-1499:0.9456
F1500-1559:0.9610
```

---

## 当前资产状态

| 资产 | 路径 | 大小 | 状态 |
|------|------|------|------|
| `MLD_NMMl_flesh_upperBody.uasset` | `UE57/.../Deformers/` | **306 MB** | ✅ Refference 原版（当前有效）|
| `.uasset.2gb_backup_20260303` | 同目录 | 1985 MB | 🗄️ March 3 失败训练备份 |
| `.uasset.hero64_backup_20260305` | 同目录 | 374 MB | 🗄️ 本地 hero64 训练（无效）|
| `MLD_NN_lowerCostume.uasset` | `UE57/.../Deformers/` | 258 MB | ✅ 有效（March 2 训练）|
| `MLD_NN_upperCostume.uasset` | `UE57/.../Deformers/` | 568 MB | ✅ 有效（March 2 训练）|

---

## 调查结论（NMM 训练调查完结）

1. **T v2 训练失败根因（已确认）**：`GC_upperBodyFlesh_smoke`（1.65 GB，3/1）顶点偏移
   p50=90.7 cm（正常应 < 30 cm），来自 Houdini smoke 管线导出错误
2. **hero64 GC 几何质量正常**：p50=4.0 cm，0/5065 帧超过 80 cm 阈值
3. **hero64 训练推理失败**：pose 覆盖问题——训练分布≠推理分布
4. **Epic Refference NMM 是当前最佳模型**：Epic 训练数据可能使用完整 pose coverage
5. **局部训练可行路径**：需要修复 `GC_upperBodyFlesh_smoke` Houdini 导出，
   然后用 `upperBody_7000` + 修复后的 smoke GC 重新训练

---

## 后续工作

| ID | 优先级 | 工作 |
|----|--------|------|
| TI-4 | 🔲 中 | 修复 Houdini smoke GC 导出（单位/坐标系根因）|
| TI-5 | 🔲 低 | 使用修复 smoke GC + upperBody_7000 重新训练 NMM |
| TI-6 | 🔲 低 | 调查 `num_iterations:2000` 未生效于 UE5.7 NMM |

**当前稳定基线**：T v3/T v4b ssim=**0.9142**（Refference NMM 306 MB，已提交到 UE57 repo）
