# UE5.7 MLDeformerSample — 文档导航

> **UE 版本**：5.7 · **本工作区**：`MLDeformerSample/UE57/`（独立 git 仓库）  
> **配套 UE5.5 文档**：`../../docs/README.md`（理论/源码/数据管线层）  

---

## 本工作区的定位

| 目的 | 说明 |
|------|------|
| 兼容性验证 | 确认 UE5.5 → UE5.7 渲染结果保持一致（跨版本 GT 对比）|
| API 迁移文档 | 记录 UE5.5 → UE5.7 MLDeformer API 变化，指导代码适配 |
| 独立管线适配 | 基于 UE5.5 管线，适配 UE5.7 编辑器路径、新特性、hub 目录结构 |

---

## 核心变更：`static_reference_frames_dir`

传统管线中，`gt_reference_capture` 阶段需要用 UE 编辑器渲染 Reference 项目的帧。  
在 UE5.7 工作区，由于 Reference 项目是 UE5.5 格式（不能用 5.7 编辑器打开），我们引入了 **bypass**：

```json
"ue": {
  "ground_truth": {
    "capture": {
      "static_reference_frames_dir": "D:/.../.../gt/reference/frames"
    }
  }
}
```

当此键存在时，`ue_capture_mainseq.py` 直接复制现有 UE5.5 帧到 run_dir，跳过 UE 编辑器启动。  
`gt_source_capture` 仍然用 **UE5.7** 编辑器渲染，确保对比的是真实的跨版本差异。

---

## 对比阈值策略

| 指标 | UE5.5 内部对比（严格）| UE5.7 跨版本对比（放宽）|
|------|---------------------|----------------------|
| SSIM_mean | ≥ 0.995 | ≥ **0.85** |
| SSIM_p05 | ≥ 0.985 | ≥ 0.80 |
| PSNR_mean | ≥ 35.0 dB | ≥ **25.0 dB** |
| PSNR_min | ≥ 30.0 dB | ≥ 20.0 dB |
| EdgeIoU_mean | ≥ 0.97 | ≥ **0.75** |

放宽原因：不同渲染版本之间存在平台差异（着色器重新编译、细微的渲染路径变化），这是正常的。

---

## 目录索引

完整目录树见 [INDEX.md](INDEX.md)。

### 理论层（沿用 UE5.5 文档）

- [../../docs/01_theory/](../../docs/01_theory/) — LBS/DQS/NMM/NNM 理论
- [../../docs/02_code_map/](../../docs/02_code_map/) — UE5.5 源码映射（可类比参考，5.7 变更见 07_ue57_compat）

### UE5.7 专项文档

| 文件 | 说明 |
|------|------|
| [07_ue57_compat/README_UE57_Breaking_Changes_CN.md](07_ue57_compat/README_UE57_Breaking_Changes_CN.md) | UE5.5 → UE5.7 MLDeformer API 变更详细分析，含结论速查表 |
| [07_ue57_compat/README_UE57_Migration_Checklist_CN.md](07_ue57_compat/README_UE57_Migration_Checklist_CN.md) | 迁移验收 Checklist，含 A-F 六个阶段状态追踪 |

---

## 快速运行

```powershell
# 从 UE57 hub 根目录（D:\UE\Unreal Projects\MLDeformerSample\UE57\）:
.\pipeline\hou2ue\run_all.ps1 -Stage full -Profile smoke `
    -Config "pipeline/hou2ue/config/pipeline.full_exec.yaml"
```

详细说明见 [../README.md](../README.md)。
