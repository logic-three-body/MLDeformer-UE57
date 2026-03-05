# Phase TI：NMM Training Investigation（2026-03-05）

## 问题描述

March 3 使用 `smoke` profile 训练 NMM flesh 模型（`MLD_NMMl_flesh_upperBody`）后，
uasset 从 306 MB 膨胀至 2 GB，且在 Main_Sequence shots 5-6（frames 1231-1428）
产生近黑色帧（src_mean≈16 vs ref_mean≈77），导致 ssim=0.5904 FAIL。
已临时回滚至 Refference 306 MB 原始模型（ssim=0.9142 PASS）。

---

## 根因分析（2026-03-05 调查结论）

### outputs.bin 统计数据

训练产物 `Intermediate/NeuralMorphModel/outputs.bin` = 1.34 GB，内容：
- **1001 帧** × **111,769 顶点** × 3 floats（XYZ 偏移）
- 顶点偏移值范围：`min=-148.7 cm`, `max=140.7 cm`  
- **median 帧的 max-abs = 90.7 cm**（超过 50% 帧的最大顶点位移 > 90 cm）
- **35% 帧（349/1001）的最大顶点位移 > 100 cm**
- 无 NaN / Inf

```
Per-frame max-abs vertex offset distribution:
  p50 = 90.7 cm   (median)
  p90 = 119.7 cm
  p99 = 137.7 cm
  max = 148.7 cm  (frame 714)
```

### 根本原因判断

UE 单位为厘米（1 unit = 1 cm）。人体角色上身组织的合理形变范围约 5–30 cm（极端姿态
不超过 60 cm）。outputs.bin 的顶点偏移高达 148 cm（约 1.5 m），明显超出物理合理范围。

**根因：`GC_upperBodyFlesh_smoke.uasset`（1.65 GB，2026-03-01）包含的顶点偏移值
异常偏大，疑似 Houdini 导出时单位换算错误或 tissue sim 数据未正确归一化。**

### 对比参照

| GC 资产 | 大小 | 日期 | 来源 | 状态 |
|---------|------|------|------|------|
| `GC_upperBodyFlesh_smoke` | 1.65 GB | 2026-03-01 | Houdini pipeline smoke | ⚠️ 顶点偏移异常大 |
| `GC_upperBodyFlesh_5kGreedyROM` | 8.46 GB | 2026-02-02 | PDG 原始输出 | ✅ 疑似正确（原始训练数据）|
| `GC_upperBodyFlesh_hero64` | 117 MB | 2026-02-02 | PDG 原始输出 | ✅ 疑似正确（小型验证集）|

Refference 306 MB 模型推测在 `GC_upperBodyFlesh_5kGreedyROM` 或类似原始 GC 上完成
训练，产生合理顶点偏移（ssim=0.9142 可接受）。

### inputs.bin 验证

输入骨骼旋转值范围 [-1.0, 1.0]，符合旋转矩阵分量的预期（无异常）。问题仅在输出端。

---

## 修复方案（优先级排列）

### 方案 A（推荐）：改用已验证的 hero64 GC 进行 smoke 测试训练

**步骤**：
1. 在 `pipeline.full_exec.yaml` smoke profile 的 flesh 配置中，将
   `geometry_cache_template` 指向 `GC_upperBodyFlesh_hero64`（已知 Feb 2 数据）
2. 或改为 `reference` 训练数据源，使用 `GC_upperBodyFlesh_5kGreedyROM`
3. 运行训练，检查新 outputs.bin 的顶点偏移范围（p50 应 < 30 cm）
4. 如范围正常，运行 gt_compare 验证 ssim 目标

**优点**：不依赖修复 Houdini 管线，立即可测试  
**缺点**：hero64 仅 117 MB（帧数少），训练质量可能受限

### 方案 B：诊断 Houdini smoke GC 生成问题

**步骤**：
1. 检查 Houdini `.hip` 文件（`simRoot/Mio_muscle_setup.hip`）中 smoke profile 的 GC 导出节点
2. 对比 smoke 导出设置与 5kGreedyROM 导出设置（单位、归一化、坐标系）
3. 修复后重新导出 `GC_upperBodyFlesh_smoke`
4. 验证新 GC 的顶点偏移范围正常后重新训练

**优点**：修复根源，后续 smoke 训练可复用  
**缺点**：需要 Houdini 环境和 `.hip` 配置审查

### 方案 C（临时）：训练前过滤极端帧

**步骤**：
- 在 `ue_train.py` 中增加训练前检查：读取 `outputs.bin` 后，过滤 max-abs > 60 cm 的帧
- 重新运行训练

**优点**：不需要重新生成 GC  
**缺点**：会减少训练数据量；滤掉极端帧可能导致模型泛化差

---

## 下一步执行计划

| 步骤 | 行动 | 预期验证 |
|------|------|---------|
| TI-1 | 用 `GC_upperBodyFlesh_hero64` 配置 smoke 训练（方案 A）| outputs.bin p50 < 30 cm |
| TI-2 | 运行训练，检查 uasset 大小（应 < 1 GB，理想 300-400 MB）| uasset 大小正常 |
| TI-3 | gt_source_capture → gt_compare（新 trained run）| ssim_mean ≥ 0.92 |
| TI-4 | 若 TI-1/TI-3 成功，再检查 smoke GC 生成问题（方案 B）| 确认修复根源 |

**目标**：训练后 ssim_mean ≥ 0.92，F500–699 ssim ≥ 0.88（当前帧 500–699 为预训练弱项）

---

## 当前资产状态快照

```
D:\UE\Unreal Projects\UE57\MLDeformerSample\Content\Characters\Emil\Deformers\
  MLD_NMMl_flesh_upperBody.uasset          306 MB  (2026-02-01, RESTORED, pre-training)
  MLD_NMMl_flesh_upperBody.uasset.2gb_backup_20260303  1985 MB  (BAD trained, backup)
  MLD_NN_lowerCostume.uasset               258 MB  (2026-03-02, trained, WORKING OK)
  MLD_NN_upperCostume.uasset               568 MB  (2026-03-02, trained, WORKING OK)

D:\UE\Unreal Projects\UE57\MLDeformerSample\Content\Characters\Emil\GeomCache\MLD_Train\
  GC_upperBodyFlesh_smoke.uasset          1646 MB  (2026-03-01, SUSPECT — extreme offsets)
  GC_upperBodyFlesh_5kGreedyROM.uasset    8462 MB  (2026-02-02, OK but 8.4 GB)
  GC_upperBodyFlesh_hero64.uasset          117 MB  (2026-02-02, OK, small validation set)

D:\UE\Unreal Projects\UE57\MLDeformerSample\Intermediate\NeuralMorphModel\
  outputs.bin   1280 MB  (2026-03-03, from bad smoke training — p50=90.7 cm!)
  inputs.bin       2 MB  (2026-03-03, correct: values in [-1, 1])
```
