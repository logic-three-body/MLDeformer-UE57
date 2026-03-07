# Checkpoint: Phase V2 — Global Mode 根因确认 + 训练进行中 (2026-03-08)

## 根因发现（本 session 最关键结论）

### Local vs Global 模式对比

| 项目 | Epic Refference (ssim=0.9142) | V-1 / Phase U（ssim=0.66） |
|------|-------------------------------|---------------------------|
| 模式 | **Global** | Local（默认） |
| 形态目标数 | **128**（global_num_morph_targets） | ~80 bones × 6 = 480 构造，但输出 1 NMM/bone |
| 模型大小 | **306 MB** = 128 × ~200k verts × 3 × 4 bytes ✅ | 1680 MB（过大，过拟合） |
| 训练收敛损失 | ~0.01（预期） | ~1.44（V3 在5401 iter时） |

### 根因

所有历史实验（Phase T v2/v4、Phase U V-1）使用 **Local 模式**（UE 默认），
产生 ~1680 MB 的过大模型，导致 ssim≈0.637–0.66，远低于 Epic Refference 的 0.9142。

**正确配置**（与 Epic Refference 306 MB 一致）：
```json
"model_overrides": {
  "mode": "global",
  "global_num_morph_targets": 128,
  "global_num_hidden_layers": 2,
  "global_num_neurons_per_layer": 128,
  "num_iterations": 25000
}
```

### 验证证据
- 128 × 200,000 顶点 × 3 × 4 bytes = 307 MB ≈ Epic Refference 306 MB ✅
- MAIN training iter 20701/25000，Avg loss = **0.01152**（极低，收敛中）✅
- V-1 Local 模式 iter 25000，最终 loss 仍较高 → ssim=0.659

---

## 当前实验状态（2026-03-08）

### MAIN（GPU0，global 128 morphs，5kGreedyROM）

| 状态 | 详情 |
|------|------|
| ue_setup | ✅ 2026-03-07 22:48:24 |
| train | 🔄 **进行中** — iter 20701/25000，loss=0.011，剩余 ~1.5min |
| gt_source_capture | ⏳ 待执行 |
| gt_compare | ⏳ 待执行 |
| 预期 ssim | **≥ 0.83**（目标），≈0.9142 若与 Epic 等价 |

### V3（GPU1，global 256 morphs，5kGreedyROM）

| 状态 | 详情 |
|------|------|
| ue_setup | ✅ 2026-03-07 23:16:21（pipeline_base_config，strict_clone 禁用） |
| train | ❌ 崩溃于 iter 5401（V3 UE log 停止在 15:36:43 UTC），loss≈1.44（还未收敛） |
| 根因 | UE exit -1 无法写 train_report；V3 NMM 仍为 292 MB（未更新） |
| 下一步 | 删除旧 train_report → 重试训练 |

---

## V3 训练失败修复步骤

V3 run_all.ps1 不像 MAIN 那样有健壮的 `-1 → success` 处理。V3 训练在 5401 iter 后崩溃。

```powershell
# 删除旧失败报告以强制重跑
Remove-Item "D:\UE\WT_V3\pipeline\hou2ue\workspace\runs\20260307_193656_smoke\reports\train_report.json" -Force

# 用 CUDA_VISIBLE_DEVICES=1 重跑 V3 训练
$env:CUDA_VISIBLE_DEVICES = '1'
$runAll = 'D:\UE\WT_V3\pipeline\hou2ue\run_all.ps1'
& $runAll -Stage train -Config 'D:\UE\WT_V3\pipeline\hou2ue\config\pipeline.full_exec.yaml' `
          -Profile smoke -RunDir 'D:\UE\WT_V3\pipeline\hou2ue\workspace\runs\20260307_193656_smoke'
```

---

## 已修复的 V3 依赖问题

| 问题 | 修复 |
|------|------|
| `Refference` 文件夹缺失 | junction: `D:\UE\WT_V3\Refference` → `D:\UE\Unreal Projects\MLDeformerSample\Refference` |
| `GeomCache` 8GB 资产缺失 | junction: `D:\UE\WT_V3\Content\...\GeomCache` → MAIN GC 目录 |
| NMM 资产缺失 | 从 Refference copy: `MLD_NMMl_flesh_upperBody.uasset` 292 MB |
| strict_clone 阻塞 ue_setup | V3 config: `strict_clone.enabled = false` |

---

## 闭环目标（不变）

| 指标 | 目标 |
|------|------|
| ssim_mean | ≥ 0.83 |
| psnr_mean | ≥ 22.0 dB |
| edge_iou_mean | ≥ 0.82 |

> Epic Refference v4b 实测: ssim=0.9142, psnr=30.63, edge_iou≈0.88
