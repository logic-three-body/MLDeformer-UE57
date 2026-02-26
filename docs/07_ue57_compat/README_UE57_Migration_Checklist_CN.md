# UE5.7 MLDeformerSample 迁移 Checklist

> 将 UE5.5 MLDeformerSample 工程迁移到 UE5.7 的完整验收清单。  
> 每项完成后打 ✅，若有问题描述在「备注」列。

---

## 阶段 A：工程基础迁移

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| A1 | UE 工程 `.uproject` 中 `EngineAssociation` 已改为 `"5.7"` | ✅ | `UE57\MLDeformerSample\MLDeformerSample.uproject` |
| A2 | `MLDeformerSampleEditorTools` 模块已复制到 UE5.7 工程 `Source/` | ✅ | Public + Private + Build.cs |
| A3 | UE5.7 工程 `.uproject` 已注册 `MLDeformerSampleEditorTools` 模块 | ✅ | Editor / PostEngineInit |
| A4 | `Content/Python/init_unreal.py` 已复制到 UE5.7 工程 | ✅ | `UE57\MLDeformerSample\Content\Python\` |
| A5 | `Content/Python/Hou2UeDemoRuntimeExecutor.py` 已复制 | ✅ | |
| A6 | UE5.7 工程能在 Unreal Editor 5.7 中成功打开（无致命错误） | ⬜ | 待验证 |
| A7 | `MLDeformerSampleEditorTools` 模块在 UE5.7 中编译通过（无错误） | ⬜ | 预期零改动 |

---

## 阶段 B：资产兼容性

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| B1 | 三个变形器资产已在 UE5.7 工程中存在（NMM flesh + NNM upper/lower costume）| ⬜ | 检查 `Content/Characters/Emil/Deformers/` |
| B2 | 骨骼网格 `skm_Emil` 及相关 FBX 资产正常加载（无网格错误）| ⬜ | |
| B3 | DeformerGraph 资产（`DG_LBS_Morph_RecomputeNormals` 等）在 UE5.7 中存在且兼容 | ⬜ | 注意 Optimus 着色器是否需要重新编译 |
| B4 | GeomCache 资产（训练数据）已导入或可访问 | ⬜ | 或确认 `skip_train=true` 不需要 GeomCache |
| B5 | `Main_Sequence` LevelSequence 在 UE5.7 中可正常播放 | ⬜ | Demo 帧渲染的前提 |
| B6 | `/Game/Main` 地图在 UE5.7 中可正常打开（无缺失引用致命错误）| ⬜ | |

---

## 阶段 C：API 兼容性验证

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| C1 | `FMLDeformerScopedEditor` 头文件路径有效 | ✅ | `MLDeformerEditorModule.h` — 同路径 |
| C2 | `FMLDeformerEditorToolkit::Train(bool)` 签名不变 | ✅ | 已验证 |
| C3 | `FMLDeformerEditorToolkit::SwitchModelType(...)` 签名不变 | ✅ | 已验证 |
| C4 | `FMLDeformerEditorModel` 所有 virtual overrides 签名不变 | ✅ | 已验证 |
| C5 | `EMLDeformerSkinningMode` 新枚举（UE5.7 新增，可选扩展）已记录 | ✅ | 见 Breaking Changes 文档 §2.4 |
| C6 | `FMLDeformerModelOnPostEditProperty` 被 Deprecated 已记录（不调用，无影响）| ✅ | |
| C7 | `.Build.cs` 模块依赖在 UE5.7 中全部有效 | ✅ | 见 Breaking Changes 文档 §4 |

---

## 阶段 D：Pipeline 基础设施

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| D1 | UE57 hub 已初始化为独立 git 仓库 | ✅ | `UE57/.git/` |
| D2 | `UE57/` 已加入源工程 `.gitignore` | ✅ | |
| D3 | `pipeline.yaml`（UE5.7 版）已创建，指向正确 Editor 路径 | ✅ | UE_5.7 editor exe |
| D4 | `pipeline.full_exec.yaml`（UE5.7 版）已创建 | ✅ | |
| D5 | `static_reference_frames_dir` 配置路径指向实际存在的帧目录 | ✅ | 1560 PNG，来自 `20260226_170226_smoke` |
| D6 | `reference_baseline.enabled = false` 已设置 | ✅ | |
| D7 | 跨版本 GT 对比阈值已放宽（SSIM≥0.85，PSNR≥25，EdgeIoU≥0.75）| ✅ | |
| D8 | `run_all.ps1` — train 阶段 `reference_baseline.enabled=false` 分支正确跳过复制 | ✅ | |
| D9 | `ue_capture_mainseq.py` — `static_reference_frames_dir` bypass 已实现 | ✅ | |

---

## 阶段 E：GT 对比管线执行

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| E1 | `baseline_sync` 阶段正常跳过（report: success, skipped: true）| ⬜ | |
| E2 | `ue_setup` 合成报告成功写入 | ⬜ | |
| E3 | `train` 合成报告成功写入（reference_baseline disabled 分支）| ⬜ | |
| E4 | `infer` 阶段 UE5.7 编辑器正常运行 | ⬜ | |
| E5 | `gt_reference_capture` — static bypass 复制 1560 帧成功 | ⬜ | |
| E6 | `gt_source_capture` — UE5.7 编辑器渲染源帧（1560 帧）成功 | ⬜ | |
| E7 | `gt_compare` 对比完成，生成 SSIM/PSNR/EdgeIoU 报告 | ⬜ | |
| E8 | 所有指标 ≥ 放宽阈值（SSIM≥0.85 等）→ **PASS** | ⬜ | 目标：确认 UE5.7 渲染与 UE5.5 基准一致 |

---

## 阶段 F：已知问题跟踪

> 执行管线时遇到问题请填入下表，并在解决后打 ✅。

| # | 问题描述 | 影响阶段 | 状态 | 解决方案 |
|---|---------|---------|------|---------|
| — | — | — | — | — |

---

## 参考资料

- [API 变更详细分析](README_UE57_Breaking_Changes_CN.md)
- [源工程 docs/02_code_map](../../docs/02_code_map/) （UE5.5 源码映射，可类比参考）
- UE5.7 MLDeformer 插件：`D:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Animation\MLDeformer\`
- 已验证 UE5.5 运行：`pipeline/hou2ue/workspace/runs/20260226_170226_smoke/` (SSIM=0.9969 ALL PASS)
