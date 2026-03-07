# Checkpoint: Phase U — 视觉确认 + NMM 重训计划 (2026-03-05)

## 视觉确认

人眼逐帧对比 1349 帧（子集）：

| 帧来源 | Run | 内容 | 崩坏情况 |
|--------|-----|------|---------|
| source/frames | `20260226_200951_smoke` | MLD-active（306MB Epic NMM 激活） | 崩坏帧明显多 |
| reference/frames | `20260305_141106_smoke` | LBS-only（`MLDeformer.ForceWeight 0`） | 崩坏帧极少（仍有少量） |

**结论：崩坏主要来自 NMM 本身，而非 LBS 基础或渲染器差异。方向确认正确：重训 NMM = 减少崩坏。**

---

## 当前资产状态（截至 2026-03-05）

| 资产 | 大小 | 状态 | 备注 |
|------|------|------|------|
| `MLD_NMMl_flesh_upperBody.uasset` | **306 MB** | ⚠️ 仍是 Epic Refference 原版 | 管线两次训练均失败（见下） |
| `MLD_NN_lowerCostume.uasset` | 258 MB | ✅ 已训练（3/2） | 有效 |
| `MLD_NN_upperCostume.uasset` | 568 MB | ✅ 已训练（3/2） | 有效 |

### NMM flesh 训练失败历史

| 尝试 | 数据 | 结果 | 根因 |
|------|------|------|------|
| T v2 (3/3) | `GC_upperBodyFlesh_smoke` (1.65 GB) | ssim=0.5904 ❌ | GC 顶点偏移 p50=90.7 cm（应 < 30cm），Houdini 导出单位换算错误 |
| T v4 (3/5) | `GC_upperBodyFlesh_hero64` (117 MB) | ssim=0.637 ❌ | 几何质量正常(p50=4cm)，但 hero64 pose 覆盖不足，NMM OOD 推理失败 |

### 现有可用 GC 资产

| GC 资产 | 大小 | 日期 | 顶点偏移状态 |
|---------|------|------|-------------|
| `GC_upperBodyFlesh_5kGreedyROM` | 8.46 GB | 2026-02-02 (PDG原始) | ✅ 正常（推测 Refference 306MB 基于此训练） |
| `GC_upperBodyFlesh_hero64` | 117 MB | 2026-02-02 (PDG原始) | ✅ 几何正常，但 pose 不足 |
| `GC_upperBodyFlesh_smoke` | 1.65 GB | 2026-03-01 (pipeline) | ❌ p50_max=90.7 cm，有害 |

---

## Phase U 目标

**训练数据：** `GC_upperBodyFlesh_5kGreedyROM` + `upperBodyFlesh_5kGreedyROM`（PDG 原始 Feb 2）

**质量目标（LBS-ref vs MLD-active-src，BaseColor，1560 帧）：**

| 指标 | T v4b 基准（Refference 306MB） | Phase U 目标 |
|------|-------------------------------|-------------|
| ssim_mean | 0.9142 | ≥ 0.9142 |
| psnr_mean | 30.63 dB | ≥ 30.0 dB |
| de2000_mean | 1.58 | ≤ 2.0 |

---

## 配置变更

`UE57/pipeline/hou2ue/config/pipeline.full_exec.yaml`：
- `flesh.training_input_anims[0].anim_sequence` → `/Game/Characters/Emil/Animation/MLD_train/upperBodyFlesh_5kGreedyROM`
- `flesh.training_input_anims[0].geometry_cache_template` → `/Game/Characters/Emil/GeomCache/MLD_Train/GC_upperBodyFlesh_5kGreedyROM`
- 无其他改动（`skip_train: false`，`static_source_frames_dir: ""`，`training_order: ["flesh"]` 均已正确）

---

## 执行命令

```powershell
cd "D:\UE\Unreal Projects\MLDeformerSample\UE57"
# Step 1: Training (flesh NMM only, ~60-120 min)
.\pipeline\hou2ue\run_all.ps1 -Stage train -Profile smoke `
    -Config "pipeline/hou2ue/config/pipeline.full_exec.yaml"

# Step 2: GT source capture + compare + report
.\pipeline\hou2ue\run_all.ps1 -Stage gt_source_capture,gt_compare,report -Profile smoke `
    -Config "pipeline/hou2ue/config/pipeline.full_exec.yaml"
```

---

## 关联 Checkpoint

- 调查详情：`docs/memory/phase-TI-nmm-training-investigation.md`（NMM 训练根因分析）
- T v4b 确认：`docs/memory/checkpoint-20260305-phase-T-v4b-nmm-baseline-confirmed.md`
- UE5.5 视角：`../../docs/memory/checkpoint-20260305-phase-U-visual-confirm.md`
