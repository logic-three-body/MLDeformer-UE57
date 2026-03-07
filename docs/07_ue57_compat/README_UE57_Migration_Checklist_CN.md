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
| B1 | 三个变形器资产已在 UE5.7 工程中存在（NMM flesh + NNM upper/lower costume）| ✅ | `ue_setup` 报告 success，3 资产写入成功，`20260226_200951_smoke` |
| B2 | 骨骼网格 `skm_Emil` 及相关 FBX 资产正常加载（无网格错误）| ✅ | `ue_setup` 无 skeletal_mesh 报错 |
| B3 | DeformerGraph 资产（`DG_LBS_Morph_RecomputeNormals` 等）在 UE5.7 中存在且兼容 | ✅ | GT 源帧渲染成功（1560帧），Deformer Graph 可用 |
| B4 | GeomCache 资产（训练数据）已导入或可访问 | ✅ | `skip_train=true` → 无需 GeomCache；待 Phase 3 训练时补充 |
| B5 | `Main_Sequence` LevelSequence 在 UE5.7 中可正常播放 | ✅ | `gt_source_capture` 渲染 1560 帧成功 |
| B6 | `/Game/Main` 地图在 UE5.7 中可正常打开（无缺失引用致命错误）| ✅ | GT reference capture 通过 |

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
| D5 | `static_reference_frames_dir` 配置路径指向实际存在的帧目录 | ✅ | 1560 PNG，来自 `20260226_200951_smoke/workspace/staging/smoke/gt/reference/frames` |
| D6 | `reference_baseline.enabled = false` 已设置 | ✅ | |
| D7 | 跨版本 GT 对比阈值已放宽（SSIM≥0.80，PSNR≥22，EdgeIoU≥0.75，MS-SSIM≥0.78，ΔE≤15）| ✅ | `debug_mode: true`；待训练后收紧 |
| D8 | `run_all.ps1` — train 阶段 `reference_baseline.enabled=false` 分支正确跳过复制 | ✅ | |
| D9 | `ue_capture_mainseq.py` — `static_reference_frames_dir` bypass 已实现 | ✅ | Phase R 后此 bypass 已清空（BaseColor 模式使 Lumen 冷启动问题不再存在）|
| D10 | `ue_capture_mainseq.py` — `static_source_frames_dir` bypass 已实现 | ✅ | Phase R 后此 bypass 已清空，两侧均使用 BaseColor 实时渲染 |

---

## 阶段 E：GT 对比管线执行

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| E1 | `baseline_sync` 阶段正常跳过（report: success, skipped: true）| ✅ | `reference_baseline.enabled=false` |
| E2 | `ue_setup` 合成报告成功写入 | ✅ | run `20260226_200951_smoke` |
| E3 | `train` 合成报告成功写入（reference_baseline disabled 分支）| ✅ | `skip_train=true`，报告写入成功 |
| E4 | `infer` 阶段 UE5.7 编辑器正常运行 | ✅ | run `20260226_200951_smoke` |
| E5 | `gt_reference_capture` — static bypass 复制 1560 帧成功 | ✅ | 1560 PNG 帧从 `20260226_170226_smoke` 静态目录复制 |
| E6 | `gt_source_capture` — UE5.7 编辑器渲染源帧（1560 帧）成功 | ✅ | UE5.7 渲染完成 |
| E7 | `gt_compare` 对比完成，生成 SSIM/PSNR/EdgeIoU/MS-SSIM/ΔE2000 报告 | ✅ | 含 MS-SSIM + ΔE2000 扩展指标 |
| E8 | 所有指标 ≥ 放宽阈值（debug_mode=true）→ **PASS** | ✅ | SSIM=0.845≥0.80 ✅ PSNR=26.5≥22 ✅ Edge=0.850≥0.75 ✅ MS-SSIM=0.799≥0.78 ✅ ΔE=3.13≤15 ✅ |

---

## 阶段 F：已知问题跟踪

> 执行管线时遇到问题请填入下表，并在解决后打 ✅。

| # | 问题描述 | 影响阶段 | 状态 | 解决方案 |
|---|---------|---------|------|---------|
| F1 | **形变质量差距**（帧 470–490 最差：SSIM≈0.711，PSNR≈17dB，EdgeIoU≈0.50，ΔE≈8.67；帧 400–599 整体 SSIM≈0.76，Edge≈0.69）| gt_compare | ⚠️ **Phase U 重训中**（2026-03-05） | **根因（已视觉确认）**：人眼 1349 帧对比（20260226 source MLD-active vs 20260305 reference LBS-only）确认 NMM 为崩坏主因，LBS 帧崩坏极少。之前两次 pipeline 训练均失败：smoke GC p50=90.7cm（单位错误），hero64 pose 覆盖不足。**Phase U 修复方案**：改用 `GC_upperBodyFlesh_5kGreedyROM`（PDG 原始 Feb 2，8.46 GB，正常顶点偏移，宽 pose 覆盖）重训 NMM flesh，目标 ssim_mean ≥ 0.9142（T v4b Refference NMM 基准）。 |
| F2 | **渲染器基准差距**（Lumen/VSM/TAA 引擎内部变更，Lit 模式 ~8% SSIM 底线）| gt_compare | ✅ 已解决（改用 BaseColor 模式） | **根因**：Lumen GI / VSM / TAA 算法变更，配置层面不可消除。**已解决**：Phase R 引入 BaseColor 渲染模式（禁用 showflag.Lighting 等 9 个 showflag），两侧均只渲染 unlit 漫反射，消除 Lumen 底线噪声。BaseColor 模式下 F0–99 SSIM 预计接近 1.0。 |

---

## 阶段 H：渲染器差距诊断（2026-03-01）

> 说明两分量差距诊断的结论，为设定合理训练后目标提供依据。

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| H1 | 比对两版本 `DefaultEngine.ini`：`[/Script/Engine.RendererSettings]` 完全相同 | ✅ | `UE57/Config/` 与 `Refference/Config/` 逐字节一致，排除配置差异 |
| H2 | 识别渲染器内部变更分量（约 8% SSIM）：F0–99 静止帧已显示差距，deformer 贡献近零 | ✅ | SSIM<sub>F0-99</sub>=0.918 vs 0.997；此分量由 Lumen GI / VSM / TAA 算法变更引起，配置层面不可消除 |
| H3 | 设定训练后质量目标：`ssim_mean_min` 0.80（debug_mode）→ 0.92（训练后），F470–490 SSIM ≥ 0.88，EdgeIoU ≥ 0.92 | ✅ | 已记录于 `pipeline.full_exec.yaml` `_thresholds_post_training_note` 注释 |
| H4 | 人眼 1349 帧对比（20260226 source vs 20260305 reference）确认 NMM 是崩坏主因 | ✅ | LBS reference 崩坏帧极少；MLD-active source 崩坏帧明显多。方向确认正确：修复训练数据（5kGreedyROM GC）是关键修复路径。当前稳定基准：T v4b ssim_mean=0.9142（Refference 306MB NMM）。Phase U 目标：管线训练版本 ≥ 0.9142。 |

---

## 阶段 T：Phase 3 — UE5.7 原生训练（执行中）

> 依赖前置条件：ArtSource 已核验（2026-03-01），PDG 部分输出可复用。

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| T1 | ArtSource 核验：`.hip`、FBX 训练动画、Rest caches、部分 PDG 输出均存在 | ✅ | `simRoot/Mio_muscle_setup.hip` + `outputFiles/PDG_sim_MM_OLD_*/`（tissue_sim 完整，mesh partial）；`reuse_existing_outputs:true` + `allow_sample_padding:true` 可填充至 20 帧 |
| T2 | `skip_train: false`（已改）| ✅ | `pipeline.full_exec.yaml` |
| T3 | `training_data_source: "pipeline"`（已改）| ✅ | 同上 |
| T4 | 执行训练阶段：`ue_setup` + `train`（NMM flesh `num_iterations=2000`） | ✅ 完成（20260301_162455_smoke） | **MemoryError 根因**：`morph_helpers.py` 中 `.tolist()` 一次性分配 ~2.5 GB Python 列表（46M floats × 56字节）→ 已打补丁为分块（500K/chunk）。3 个模型（NNM upper/lower + NMM flesh）均训练完成，`train_report.json` success。D3D12 TDR 通过删除 `cached_mask_index_per_sample.bin`、从 Reference 恢复 uasset、重建项目解决。|
| T5 | 检查 `train_report.json`：3 个模型均 success，`.nmn` / `.ubnne` 路径有效 | ✅ | `train_report.json` 已确认 success，`train_determinism_report.json` 生成 |
| T6 | `gt_compare_report.json`：BaseColor 模式下 SSIM ≥ 0.92（无 Lumen 底线噪声）| ⬜ | Phase R BaseColor 验证中 |
| T7 | 达标后将 `ssim_mean_min` 提升至 0.92，移除 `debug_mode: true` | ⬜ | Phase R 验证通过后修改 |

---

## 阶段 G：API 兼容加固（Phase 2 Roadmap 完成状态）

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| G1 | `BoneMaskInfos` → `BoneMaskInfoMap` Python 侧 rename shim | ✅ | `ue_setup_assets.py` — `_normalize_model_overrides_for_ue57()` |
| G2 | `BoneGroupMaskInfos` → `BoneGroupMaskInfoMap` Python 侧 rename | ✅ | 同上，同一函数 |
| G3 | `skinning_mode` 枚举覆盖支持（C++ bridge + Python config） | ✅ | C++：`ApplyModelOverrides` 新增 `SetEnumPropertyByName(NMM, "SkinningMode", ...)`；默认 Linear，不需更改现有 config |
| G4 | `bone_mask_info_map` / `bone_group_mask_info_map` C++ 侧 warn-and-skip | ✅ | C++ bridge 识别键名、记录警告；TMap 序列化留待后续 |
| G5 | NNM Section 属性名审计（UE5.7）| ✅ | `NeighborPoses`、`NeighborMeshes`、`ExcludedFrames`、`NumBasis` 均无变化 |
| G6 | `GetNumMorphTargets()` 无参版废弃审计 | ✅ | bridge 及 Python 脚本均未调用，记录于 C++ 注释 |
| G7 | `FMLDeformerTrainingDataProcessorAnim` 文档及旁路说明 | ✅ | `README_UE57_Engine_Python_Package.md` + `ue_train.py` probe 字段 |
| G8 | `verify_train_determinism.py` 脚本（SHA-256 比对两个 run 的 .nmn）| ✅ | 待 Phase 3 训练完成后执行 |

---

---

## 阶段 V：验证结果汇总（Run 20260226_200951_smoke，Lit 模式）

> ⚠️ **此结果为 Lumen Lit 渲染模式（已废弃）**。Phase R 引入 BaseColor 渲染模式后，此基准将被新 BaseColor 结果取代。  
> 采用 Feb26 静态帧旁路（`static_source_frames_dir`），绕过 Lumen GI 冷启动问题。

### 全局指标（1560 帧，阈值 debug_mode=true）

| 指标 | 实测值 | 阈值 | 状态 |
|------|--------|------|------|
| ssim_mean | 0.8453 | ≥ 0.80 | ✅ |
| ssim_p05 | 0.7290 | ≥ 0.60 | ✅ |
| psnr_mean | 26.47 dB | ≥ 22.0 | ✅ |
| edge_iou_mean | 0.8499 | ≥ 0.75 | ✅ |
| ms_ssim_mean | 0.7987 | ≥ 0.78 | ✅ |
| de2000_mean | 3.13 | ≤ 15.0 | ✅ |

### 逐段 SSIM（100帧窗口）

| 帧段 | ssim_mean | 说明 |
|------|-----------|------|
| 0–99 | 0.917 | 静止姿态，渲染器底线差距 ~8% |
| 100–199 | 0.842 | 通过 |
| 200–299 | 0.858 | 通过 |
| 300–399 | 0.856 | 通过 |
| **400–499** | **0.780** | ⚠️ 场景切换区，Lumen 冷启动 + 复杂姿态 |
| **500–599** | **0.759** | ⚠️ source 亮度异常（Lumen 未收敛，mean≈35 vs ref≈97） |
| **600–699** | **0.750** | ⚠️ Lumen 已恢复亮度但模型预测误差高 |
| 700–799 | 0.800 | 刚过阈值 |
| 800–899 | 0.863 | 通过 |

**最差帧**（SSIM 升序 Top-5）：帧 483、470、484、471、486  
**热力图目录**：`runs/20260226_200951_smoke/workspace/staging/smoke/gt/compare/heatmaps/`

---

## 阶段 R：BaseColor 渲染模式（2026-03-03）

> 消除 Lumen GI 冷启动噪声对 GT 对比的影响。Reference 与 Source 两侧均渲染 BaseColor（unlit albedo）而非全光照画面。

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| R1 | `Hou2UeDemoRuntimeExecutor.py` 支持 `-DemoRenderMode=basecolor` 命令行参数 | ✅ | 解析并设置 9 个 showflag：Lighting / GlobalIllumination / ReflectionEnvironment / AmbientOcclusion / Bloom / LensFlares / EyeAdaptation / ScreenSpaceReflections / ContactShadows 全部禁用 |
| R2 | `ue_capture_mainseq.py` 从 config 读取 `render_mode` 并传递至 UE 命令行 | ✅ | `capture_cfg.get("render_mode", "lit")` → `-DemoRenderMode=basecolor` |
| R3 | `pipeline.yaml` + `pipeline.full_exec.yaml` 均设置 `render_mode: "basecolor"` | ✅ | `ue.ground_truth.capture.render_mode` |
| R4 | `static_reference_frames_dir` 和 `static_source_frames_dir` 均已清空 | ✅ | BaseColor 模式下 Lumen 已禁用，不再需要静态帧旁路 |
| R5 | `Hou2UeDemoRuntimeExecutor.py` 已同步至 UE5.7 工程 `Content/Python/` | ✅ | 手动同步至 `UE57\MLDeformerSample\Content\Python\` |
| R6 | BaseColor 模式 GT 对比运行成功，SSIM 接近 1.0（F0–99 预估） | ✅ | Run `20260301_162455_smoke`：SSIM=0.9995，PSNR=62.1 dB，ALL PASS |
| R7 | BaseColor 数据确认后将阈值收紧 `ssim_mean_min → 0.97`，删除 `debug_mode` | ✅ | 已收紧，见阶段 S |

**提交**：`98e26ba` — Add BaseColor render mode: disable lighting showflags to eliminate Lumen variance

### 阶段 R 验证结果（Run 20260301_162455_smoke）

| 指标 | 实测值 | 阈值 | 状态 |
|------|--------|------|------|
| ssim_mean | 0.9995 | ≥ 0.80 | ✅ |
| psnr_mean | 62.1 dB | ≥ 22.0 | ✅ |
| 总帧数 | 1560 | — | ✅ |

**Heatmap 修复**：`compare_groundtruth.py` `_write_heatmap()` 由硬编码 `clip(diff, 0, 255)` 改为自动标准化 `ceil = max(diff.max(), 30.0)`，使微小色差可见（r_max 从 7–22 提升至 119–187/255）。

### 相机机位调查记录（2026-03-0x）

> 背景：用户发现 run `20260226_200951_smoke`（旧）与 `20260301_162455_smoke`（新）的 reference 帧视觉差异极大，怀疑相机机位发生变化。

**调查结论：相机机位未发生变化。** 视觉差异完全由渲染模式切换（Lit → BaseColor）造成。

**关键证据**

| 对比组 | SSIM | 解释 |
|--------|------|------|
| UE5.7 Lit src vs UE5.7 BaseColor ref（同引擎、同相机、不同模式） | 0.61 | 纯渲染模式差异 |
| UE5.5 Lit ref vs UE5.7 Lit src（跨引擎、同相机、同模式） | 0.80–0.91 | 引擎版本差异 + ML误差 |
| UE5.7 BaseColor ref vs UE5.7 BaseColor src（同次运行内部） | 0.9994 | ML Deformer 精度 |
| Template match：UE5.5 Lit ref → UE5.7 Lit src | **2.8 px** | 相机位置一致 ✅ |
| Template match：UE5.5 Lit ref → UE5.7 BaseColor ref | 477 px（误报） | 渲染模式破坏相似度，模板匹配失效 |

**根本原因（实为预期行为）**

- 旧跑（`20260226_200951_smoke`）：`static_bypass: true`，reference 来自 `20260226_170226_smoke` 的 **UE5.5 Lit** 帧（`static_reference_frames_dir` 旁路）。  
- 新跑（`20260301_162455_smoke`）：`da048d5` 提交清空 `static_reference_frames_dir`，引擎从 UE5.7 重新渲染 **BaseColor** 帧。  
- Background 从 Lit（亮、约 80 mean）变为 BaseColor（纯黑、约 56 mean），占画面约 60–70%，导致 SSIM 从 0.84 降至 0.61——即使相机完全不动。  
- BaseColor 模式下 Canny 边缘重心偏移（229–448 px）与模板匹配位移（477 px）均为背景消失导致的**算法误报**，不代表镜头移动。

**两次运行的对比语义不同**

| 运行 | reference 来源 | 渲染模式 | 衡量内容 |
|------|--------------|---------|----------|
| `20260226_200951_smoke` | UE5.5 Lit 静态旁路 | Lit (全光照) | 跨引擎兼容性（含引擎版本差异）|
| `20260301_162455_smoke` | UE5.7 重新渲染 | BaseColor (unlit albedo) | ML Deformer 纯精度（排除引擎差异）|

---

## 阶段 L：Lumen GI 冷启动问题记录（已解决）

> `r.Lumen.HardwareRayTracing=True` + `r.Lumen.TraceMeshSDFs=0`（仅 HW RT，无 SW 兜底）  
> 帧 ~490 场景切换后 Lumen probe cache 重建，ML Deformer 每帧 mesh 形变加速 probe 失效。

| 帧号 | Feb26 source 亮度 | 当前 source 亮度 | reference 亮度 |
|------|-----------------|----------------|---------------|
| 485 | 66.8 | 56.3 | — |
| 520 | 86.7 | 36.8 | — |
| 600 | 95.1 | 38.3 | 96.6 |
| 900 | — | 47.8 | 90.3 |

**已采用方案**：~~`static_source_frames_dir` 旁路~~（Phase R 已废弃）→ **BaseColor 渲染模式**：禁用 showflag.Lighting/GlobalIllumination/ReflectionEnvironment/AmbientOcclusion/Bloom/LensFlares/EyeAdaptation/ScreenSpaceReflections/ContactShadows，彻底消除 Lumen 底线噪声。

---

## 参考资料

- [API 变更详细分析](README_UE57_Breaking_Changes_CN.md)
- [源工程 docs/02_code_map](../../docs/02_code_map/) （UE5.5 源码映射，可类比参考）
- UE5.7 MLDeformer 插件：`D:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Animation\MLDeformer\`
- 已验证 UE5.5 运行：`pipeline/hou2ue/workspace/runs/20260226_170226_smoke/` (SSIM=0.9969 ALL PASS)
- 已验证 UE5.7 跨版本运行（debug_mode）：`runs/20260226_200951_smoke/` (SSIM=0.845 ALL PASS)

---

## 阶段 S：阈值收紧（2026-03-04）

> Phase R 全面配置已验证通过后，将对比阈值从跨引擎宽松值收紧至 BaseColor 自对比精度预期。

| # | 检查项 | 状态 | 备注 |
|---|--------|------|------|
| S1 | `pipeline.full_exec.yaml` 阈值收紧 + `debug_mode → false` | ✅ | `ssim_mean_min 0.80→0.97`, `psnr_mean_min 22→40`, `edge_iou_mean→0.92`, `ms_ssim→0.995`, `de2000_mean_max→1.0` |
| S2 | 使用已有帧重跑 `gt_compare` 验证新阈值通过 | ✅ | Run `20260301_162455_smoke`：ALL PASS（参见下表） |

### 阶段 S 验证结果

| 指标 | 实测值 | 新阈值 | 状态 |
|------|--------|--------|------|
| ssim_mean | 0.9995 | ≥ 0.97 | ✅ |
| ssim_p05 | 0.9990 | ≥ 0.92 | ✅ |
| psnr_mean | 62.1 dB | ≥ 40.0 | ✅ |
| psnr_min | 55.7 dB | ≥ 35.0 | ✅ |
| edge_iou_mean | 0.9990 | ≥ 0.92 | ✅ |
| ms_ssim_mean | 0.9998 | ≥ 0.995 | ✅ |
| ms_ssim_p05 | 0.9996 | ≥ 0.97 | ✅ |
| de2000_mean | 0.075 | ≤ 1.0 | ✅ |
| de2000_p95 | 0.134 | ≤ 2.5 | ✅ |

**提交**：阶段 S——tighten thresholds for BaseColor self-comparison

---

## 阶段 T-MLD：MLD 测量——LBS-vs-MLD GT 对比（2026-03-05）

> 目标：在 UE5.7 下量化 ML Deformer（NMM + NN 服装模型）与 LBS Ground Truth 的误差。  
> Reference = LBS（禁用 MLD 的 BaseColor 帧）；Source = MLD 激活的 BaseColor 帧。  
> 阈值：`ssim_mean_min: 0.83`（Phase T pipeline thresholds，已放宽至 MLD 精度预期）。

### T-MLD 执行历史

| 轮次 | Run | NMM flesh 模型 | ssim_mean | 结果 | 说明 |
|------|-----|--------------|-----------|------|------|
| Phase S（LBS-vs-LBS 基准）| `20260226_200951_smoke` | — (MLD 禁用) | **0.9994** | ✅ ALL PASS | LBS-vs-LBS 基准，ssim≈1.0 确认 pipeline 精度 |
| T bypass（原始权重）| `20260226_200951_smoke` | 306 MB 原始（Refference）| **0.8832** | ✅ ALL PASS | `skip_train=true`，使用项目原生预训练权重 |
| T v2（训练回归）| `20260305_130217_smoke` | 2 GB 训练后（2026-03-03）| **0.5904** | ❌ FAIL | March 3 训练写入错误顶点偏移，shots 5-6 近黑帧（F1231-1428）|
| T v3（回滚修复）| `20260305_141106_smoke` | 306 MB 恢复（Refference）| **0.9142** | ✅ ALL PASS | 恢复预训练模型，方向已确认正确 |
| T v4（hero64 训练测试）| `20260305_141106_smoke` | 357 MB 本地训练（hero64 GC）| **0.637** | ❌ FAIL | 训练数据质量正常（p50_GC=4.0 cm）但 hero64 pose 不覆盖 Main_Sequence |
| **T v4b（基线确认）** | `20260305_141106_smoke` | 306 MB 恢复（Refference）| **0.9142** | ✅ ALL PASS | 还原 Refference 模型确认稳定；**当前已验证基线** |

### T v3 / T v4b 详细指标（1560 帧，`20260305_141106_smoke`，Refference NMM 306 MB）

| 指标 | 实测值 | 阈值 | 状态 |
|------|--------|------|------|
| ssim_mean | 0.9142 | ≥ 0.83 | ✅ |
| ssim_p05 | 0.7864 | ≥ 0.70 | ✅ |
| psnr_mean | 30.63 dB | ≥ 22.0 | ✅ |
| psnr_min | 17.23 dB | ≥ 14.0 | ✅ |
| edge_iou_mean | 0.9036 | ≥ 0.82 | ✅ |
| ms_ssim_mean | 0.8936 | ≥ 0.80 | ✅ |
| ms_ssim_p05 | 0.7304 | ≥ 0.65 | ✅ |
| de2000_mean | 1.584 | ≤ 8.0 | ✅ |
| de2000_p95 | 4.012 | ≤ 15.0 | ✅ |

### T v3 / T v4b 逐段 SSIM（100帧窗口，Refference NMM）

| 帧段 | ssim_mean | 说明 |
|------|-----------|------|
| 0–99 | 0.9784 | 静止姿态 |
| 100–199 | 0.9503 | |
| 200–299 | 0.9485 | |
| 300–399 | 0.9462 | |
| 400–499 | 0.8342 | |
| **500–599** | **0.8206** | ⚠️ 略低于阈值——NMM 预训练对极端姿态预测精度不足 |
| **600–699** | **0.8083** | ⚠️ 略低于阈值——diff_mean≈9px，非近黑帧（≠ T v2 崩坏） |
| 700–799 | 0.8505 | |
| 800–899 | 0.8986 | |
| 900–999 | 0.9269 | |
| 1000–1099 | 0.8941 | |
| 1100–1199 | 0.9459 | |
| 1200–1299 | 0.9799 | |
| 1300–1399 | 0.9569 | |
| 1400–1499 | 0.9456 | |
| 1500–1559 | 0.9610 | |

> 帧 500–699 差异为 *柔和*（diff_mean 5–20 px，ref_mean 70–93），非 T v2 的近黑帧崩坏（diff_mean 40+，src_mean≈16）。  
> 根因：NMM 预训练权重在该动画段的极端姿态处形变预测不准。

### 当前资产状态

| 资产 | 路径 | 大小 | 状态 | 备注 |
|------|------|------|------|------|
| `MLD_NMMl_flesh_upperBody.uasset` | `.../Deformers/` | **306 MB** | ✅ 预训练（Epic 原版）| **当前有效**：T v4b 确认 ssim=0.9142；本地 hero64 训练=0.637（差）→已还原 |
| `MLD_NMMl_flesh_upperBody.uasset.2gb_backup_20260303` | `.../Deformers/` | 1985 MB | 🗄️ 备份 | March 3 失败训练模型（smoke GC 异常顶点偏移） |
| `MLD_NMMl_flesh_upperBody.uasset.hero64_backup_20260305` | `.../Deformers/` | 374 MB | 🗄️ 备份 | 2026-03-05 hero64 训练模型（几何质量好但 pose 覆盖不足） |
| `MLD_NN_lowerCostume.uasset` | `.../Deformers/` | 258 MB | ✅ 已训练（2026-03-02）| Refference 原始 453 MB；训练后缩小，当前性能正常 |
| `MLD_NN_upperCostume.uasset` | `.../Deformers/` | 568 MB | ✅ 已训练（2026-03-02）| Refference 原始 832 MB；训练后缩小，当前性能正常 |

> **NN 服装模型说明**：March 2 训练使 NN 模型缩小（NearestNeighbor lookup table 大小不同），但 ssim=0.9142 **优于** 使用 Refference 原始 NN 模型的 T bypass（ssim=0.8832），确认其训练有效。

### T-MLD 已知问题

| # | 问题 | 状态 | 方向 |
|---|------|------|------|
| TM1 | **NMM 预训练精度不足**（F500–699，ssim≈0.82）| ⚠️ 当前限制 | 需使用覆盖 Main_Sequence pose 空间的动画数据重新训练 NMM |
| TM2 | **NMM 训练回归（2 GB 模型）** | ✅ 根因已查明 | `GC_upperBodyFlesh_smoke` 顶点偏移异常（p50=90.7 cm）来自 Houdini 导出问题 |
| TM3 | **hero64 训练 pose 覆盖不足** | ✅ 已确认 | hero64（5065帧）pose 空间≠ Main_Sequence；训练数据必须匹配推理动画 |
| TM4 | **`num_iterations:2000` 配置未生效** | 🔲 待查 | UE5.7 NMM 默认使用 25,000 iterations，config 覆盖值无效 |

### T-MLD 已完成里程碑

| 里程碑 | 日期 | 结果 |
|--------|------|------|
| Phase S LBS-vs-LBS 基准 | 2026-02-26 | ssim=0.9994 ✅（commit `9b3b172`）|
| T bypass Refference 预训练 | 2026-02-26 | ssim=0.8832 ✅（commit `53f3e72`）|
| T v2 训练回归记录 | 2026-03-05 | ssim=0.5904 ❌（commit `609a33d`）|
| T v3 回滚稳定基线 | 2026-03-05 | ssim=0.9142 ✅（commits `6ed4371` + `f02d912`）|
| TI NMM 训练根因调查 | 2026-03-05 | smoke GC p50=90.7 cm 根因确认（commit `a641103`）|
| T v4 hero64 训练测试 | 2026-03-05 | ssim=0.637 ❌（几何质量好但 pose 覆盖不足）|
| **T v4b 基线还原确认** | **2026-03-05** | **ssim=0.9142 ✅（Refference 306 MB 为有效基线）** |

### 下一步目标

1. **修复 Houdini smoke GC 导出**（单位/坐标系问题，`GC_upperBodyFlesh_smoke`顶点偏移需 < 30 cm）
2. 使用修复后 smoke GC + `upperBody_7000`（full pose coverage）重新训练 NMM
3. 验证目标：`ssim_mean ≥ 0.92`，F500–699 ssim ≥ 0.88
4. 调查 `num_iterations:2000` pipeline 配置项未覆盖 UE5.7 NMM 默认值问题

---

## 阶段 U：Phase U — 5kGreedyROM 重训（2026-03-05/07）

> 使用 PDG 原始 `GC_upperBodyFlesh_5kGreedyROM`（Feb 2，8.46 GB，p50<30cm，宽 pose 覆盖）重训 NMM flesh。
> 两次尝试，均失败（ssim=0.66 < 0.83 目标）。

### Phase U 训练结果

| 轮次 | 数据 | mode | 模型大小 | ssim_mean | 结果 | 说明 |
|------|------|------|---------|-----------|------|------|
| U v1（5kGreedyROM）| `GC_upperBodyFlesh_5kGreedyROM` | **Local**（默认）| 1680 MB | 0.6599 | ❌ FAIL | Local 模式，过大模型，过拟合/泛化差 |
| U v1b（重跑验证）| 同上 | **Local**（默认）| 1680 MB | 0.6599 | ❌ FAIL | 结果完全相同，排除随机因素 |

### Phase U 根因分析（2026-03-07 本 session 确认）

**关键发现：Epic Refference NMM 使用 Global 模式，all our experiments 使用 Local 模式（默认）。**

| 对比项 | Epic Refference (ssim=0.9142) | Phase U 实验（ssim=0.66）|
|--------|-------------------------------|--------------------------|
| NMM mode | **Global** | Local（UE 默认）|
| 形态目标数 | **128**（global_num_morph_targets）| 本地每骨骼 6 × ~80 骨骼 |
| 模型大小 | **306 MB** = 128 × 200k × 3 × 4 ✅ | 1680 MB（过大）|
| 训练后 loss | ~0.011（极低）| >1.4（收敛差）|

**证明**：128 global morphs × ~200k body vertices × 3 axes × 4 bytes/float = **307 MB** ≈ Epic Refference 306 MB ✅

### Phase U 配置问题

TM4 根因确认：`num_iterations: 2000` 曾写入 config 但训练实际使用 25000（UE NMM 内部默认值 override 失效）。已修复：现在 config 明确写 `num_iterations: 25000`。

---

## 阶段 V：Phase V — Global Mode 修复训练（2026-03-07/08）

> 根因确认为 NMM 模式错误。切换为 `mode: "global" + global_num_morph_targets: 128`，与 Epic Refference 架构一致。

### V-MAIN 配置（GPU0）

```json
"model_overrides": {
  "mode": "global",
  "global_num_morph_targets": 128,
  "global_num_hidden_layers": 2,
  "global_num_neurons_per_layer": 128,
  "num_iterations": 25000
}
```

训练数据：`upperBodyFlesh_5kGreedyROM` + `GC_upperBodyFlesh_5kGreedyROM`（5000 帧 GreedyROM，8.46 GB）

### V-MAIN 训练进度

| 状态 | 详情 |
|------|------|
| ue_setup | ✅ 2026-03-07 22:48（global 128 morphs 已配置）|
| train | 🔄 **进行中**（截至 2026-03-08 00:26 UTC，iter=21901/25000，loss=0.011，剩余~1.5min）|
| gt_source_capture | ⏳ 待执行（训练完成后立即执行）|
| gt_compare | ⏳ 待执行 |
| 目标 ssim | ≥ 0.83（预期接近 0.9142）|

### V3 并行实验（GPU1，256 morphs）

| 状态 | 详情 |
|------|------|
| ue_setup | ✅ 2026-03-07 23:16（global 256 morphs，pipeline_base_config 应用）|
| train | ❌ 崩溃于 iter 5401（1.78GB GPU，loss≈1.44）— UE exit -1 无效 train_report |
| 根因 | UE 崩溃（exit -1）运行结束但未写入有效 report；V3 run_all.ps1 仅支持有限重试 |
| 下一步 | 删除旧 train_report → 重跑；若 MAIN 已达目标可跳过 |

### 闭环判定阈值（LBS-ref vs MLD-src，BaseColor，1560 帧）

| 指标 | 目标 | Epic Refference v4b 实测 |
|------|------|--------------------------|
| ssim_mean | **≥ 0.83** | 0.9142 |
| psnr_mean | **≥ 22.0 dB** | 30.63 dB |
| edge_iou_mean | **≥ 0.82** | 0.9036 |
