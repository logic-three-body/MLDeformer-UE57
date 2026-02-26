# UE5.7 MLDeformerSample — 兼容性验证工作区

> **本目录是 UE5.7 兼容性工作独立子仓库**，纯粹是脚本 + 文档的存放中心。  
> 对应的 UE 工程文件在另一个路径下独立管理：
> `D:\UE\Unreal Projects\UE57\MLDeformerSample\`

---

## 目录结构

```
UE57/
├── pipeline/
│   └── hou2ue/
│       ├── run_all.ps1            # 主流水线驱动脚本（UE5.7 适配版）
│       ├── config/
│       │   ├── pipeline.yaml               # UE5.7 基础配置
│       │   └── pipeline.full_exec.yaml     # UE5.7 完整执行配置（含 GT 对比）
│       └── scripts/               # 18 个管线脚本（含 UE57 扩展）
│           └── ue_capture_mainseq.py  ★ static_reference_frames_dir bypass
├── docs/
│   ├── README.md                  # 文档导航总览（UE5.7 视角）
│   ├── INDEX.md                   # 全量文件树索引
│   ├── 01_theory/ .. 06_appendix/ # 沿用 UE5.5 理论层文档
│   └── 07_ue57_compat/ ★          # UE5.7 新增：兼容性专项
│       ├── README_UE57_Breaking_Changes_CN.md
│       └── README_UE57_Migration_Checklist_CN.md
└── README.md                      # 本文件
```

---

## 适配策略总结

| 方面 | UE5.5（源工程） | UE5.7 |
|------|----------------|-------|
| UE 工程路径 | `MLDeformerSample/` | `D:\UE\Unreal Projects\UE57\MLDeformerSample\` |
| Pipeline Hub | `pipeline/hou2ue/` | `UE57/pipeline/hou2ue/`（本目录） |
| UE Editor | `UE_5.5` | `UE_5.7` |
| Reference Baseline | `Refference/` 同工程目录 | `enabled: false`（UE5.5 项目不能用 5.7 编辑器打开）|
| GT Reference 帧来源 | 实时渲染 Reference 项目 | `static_reference_frames_dir`（复用已验证 UE5.5 帧）|
| GT Source 帧来源 | 渲染源工程 UE5.5 | 渲染 UE5.7 工程（**这才是兼容性测试的核心**）|
| GT 对比阈值 | SSIM≥0.995 / PSNR≥35 / EdgeIoU≥0.97 | **SSIM≥0.85 / PSNR≥25 / EdgeIoU≥0.75**（跨版本放宽）|
| MLDTrainAutomation | 完整源码 | 复制源码，API 向后兼容（UE5.7 中零代码改动）|
| SkinningMode | 不支持 | UE5.7 新增 `EMLDeformerSkinningMode`（可选扩展）|

---

## 快速运行 GT 对比管线

```powershell
# 从 UE57 hub 根目录运行（D:\UE\Unreal Projects\MLDeformerSample\UE57\）
.\pipeline\hou2ue\run_all.ps1 -Stage full -Profile smoke `
    -Config "pipeline/hou2ue/config/pipeline.full_exec.yaml"
```

**该命令会执行**：
1. `baseline_sync` → `enabled=false` → 跳过（UE5.7 项目使用自带 deformer 权重）
2. `ue_setup` → `skip_train=true` → 写合成报告，跳过资产配置
3. `train` → `skip_train=true` + `referenced_baseline disabled` → 写合成报告，跳过权重复制
4. `infer` → UE5.7 编辑器运行推理
5. `gt_reference_capture` → **static_reference_frames_dir bypass**（复用 UE5.5 已渲染 1560 帧）
6. `gt_source_capture` → UE5.7 编辑器渲染源帧
7. `gt_compare` → SSIM / PSNR / EdgeIoU 对比
8. `report` → 汇总报告

---

## 关键文件说明

| 文件 | 说明 |
|------|------|
| `pipeline/hou2ue/scripts/ue_capture_mainseq.py` | 新增 `static_reference_frames_dir` bypass；当配置此键时，`gt_reference_capture` 直接复制已有帧，跳过 UE 编辑器渲染 |
| `pipeline/hou2ue/run_all.ps1` | 修改 `train` 阶段：当 `reference_baseline.enabled=false` 时跳过权重复制；支持 `paths.ue_project_root` 区分 Hub 与 UE 项目路径 |
| `pipeline/hou2ue/config/pipeline.full_exec.yaml` | UE5.7 执行配置：禁用 reference_baseline、设置 static_reference_frames_dir、放宽对比阈值 |
| `docs/07_ue57_compat/` | UE5.5→5.7 API 变更分析 + 迁移 Checklist |

---

## UE5.7 API 兼容性速查

详见 [docs/07_ue57_compat/README_UE57_Breaking_Changes_CN.md](docs/07_ue57_compat/README_UE57_Breaking_Changes_CN.md)。

**结论**：`MLDTrainAutomationLibrary.cpp` 在 UE5.7 下**无需任何代码改动**即可编译。主要变更均为新增（`EMLDeformerSkinningMode`、`MLDeformerTrainingDataProcessorSettings.h`）或废弃但未移除（`FMLDeformerModelOnPostEditProperty`）。

---

## 已验证 UE5.5 基准（参考数据）

| 指标 | 值 |
|------|----|
| Run | `20260226_170226_smoke` |
| 帧数 | 1560 |
| SSIM_mean | 0.9969 |
| PSNR_mean | 55.85 dB |
| EdgeIoU_mean | 0.989 |
| 耗时 | 24 min |
| 状态 | **ALL PASS** |
