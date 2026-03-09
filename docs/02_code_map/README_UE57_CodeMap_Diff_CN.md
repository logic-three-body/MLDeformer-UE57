# UE5.7 Code Map Diff — MLDeformer API Changes

> **Phase 5.2 doc** — Delta between UE5.5 and UE5.7 for symbols relevant to this project.
> Reference: [UE5.5 Code Map](../../docs/02_code_map/README_UE5_CodeMap_Mainline_CN.md)

---

## 1. New Enum: `EMLDeformerSkinningMode`

**File**: `MLDeformerFramework/Public/MLDeformerModel.h`

```cpp
UENUM()
enum class EMLDeformerSkinningMode : int8
{
    Linear,          // Default — fastest; use if character uses LBS
    DualQuaternion   // Better quality for rotating joints; use if character uses DQS
};
```

**Used by**: `UNeuralMorphModel::SkinningMode` (default = `Linear`).

**Pipeline config key** (Phase 2.2): `model_overrides.skinning_mode: "linear" | "dual_quaternion"`

**Phase 1 audit result**: Default is `Linear` — matches UE5.5 implicit behaviour.
The frames 400–599 quality gap (SSIM≈0.76) is **not** caused by a skinning mode
change; it is a cross-version weight mismatch from using UE5.5 pre-trained `.nmn`
weights on UE5.7. Fix: Phase 3 native UE5.7 training.

---

## 2. `FMLDeformerMaskInfo` — Replaced `FNeuralMorphMaskInfo`

**File**: `MLDeformerFramework/Public/MLDeformerMasking.h`

```cpp
UENUM()
enum class EMLDeformerMaskingMode : uint8
{
    Generated,        // Generated from skinning weights
    VertexAttribute   // Read from a named vertex attribute
};

USTRUCT()
struct FMLDeformerMaskInfo
{
    EMLDeformerMaskingMode MaskMode = EMLDeformerMaskingMode::Generated; // NEW
    FName VertexAttributeName;                                            // NEW
};
```

**What changed**:

| Symbol | UE5.5 | UE5.7 |
|--------|-------|-------|
| `FNeuralMorphMaskInfo` | `NeuralMorphTypes.h` | **Moved** to `MLDeformerMasking.h` as `FMLDeformerMaskInfo` |
| `MaskMode` | Not present | New `EMLDeformerMaskingMode` enum field |
| `VertexAttributeName` | Not present | New `FName` field |

**Properties renamed on `UNeuralMorphModel`**:

| UE5.5 UPROPERTY | UE5.7 UPROPERTY | Type change |
|-----------------|-----------------|-------------|
| `BoneMaskInfos` | `BoneMaskInfoMap` | `TMap<FName, FNeuralMorphMaskInfo>` → `TMap<FName, FMLDeformerMaskInfo>` |
| `BoneGroupMaskInfos` | `BoneGroupMaskInfoMap` | Same direction |

**Python compatibility shim**: `_normalize_model_overrides_for_ue57()` in
`ue_setup_assets.py` renames dict keys before JSON serialisation.

---

## 3. `UNearestNeighborModelSection` — UObject Refactor

**File**: `NearestNeighborModel/Public/NearestNeighborModel.h`

In UE5.4 the old `FClothPartData` struct was deprecated.  In UE5.7 the UObject
class `UNearestNeighborModelSection` is the authoritative API.

**New properties in UE5.7** (not yet surfaced in pipeline config):

| Property | Type | Description |
|----------|------|-------------|
| `WeightMapCreationMethod` | `ENearestNeighborModelSectionWeightMapCreationMethod` | How vertex weights are created (ManualVertexMap / WeightMap / VertexAttribute) |
| `BoneNames` | `TArray<FName>` | Bones driving this section's weight map |
| `AttributeName` | `FName` | Vertex attribute name when method = VertexAttribute |

**Existing properties (unchanged in UE5.7)**:

| Property | Status |
|----------|--------|
| `NeighborPoses` | ✅ Unchanged |
| `NeighborMeshes` | ✅ Unchanged |
| `ExcludedFrames` | ✅ Unchanged |
| `NumBasis` (set via `SetNumBasis()`) | ✅ Unchanged |

---

## 4. `GetNumMorphTargets` — LOD Parameter Required

**File**: `MLDeformerFramework/Public/MLDeformerMorphModel.h`

```cpp
// UE5.5 (still compiles, but deprecated since 5.4):
UE_DEPRECATED(5.4, "Please use the GetNumMorphTargets(LOD) instead")
int32 GetNumMorphTargets() const { return GetNumMorphTargets(0); }

// UE5.7 authoritative form:
UE_API int32 GetNumMorphTargets(int32 LOD) const;
```

**Impact on this project**: The C++ bridge (`MLDTrainAutomationLibrary.cpp`)
does NOT call `GetNumMorphTargets()` directly. All morph count queries flow
through `ActiveModel->UpdateNetworkOutputDim()` which uses the LOD-aware form
internally. **No code change required.**

---

## 5. `SampleGroundTruthPositionsAtFrame` — New Signature

**File**: `MLDeformerFramework/Public/MLDeformerGeomCacheModel.h` (approx.)

| UE5.5 | UE5.7 |
|-------|-------|
| `SampleGroundTruthPositions(float Time)` | `SampleGroundTruthPositionsAtFrame(int32 FrameIndex)` |

**Impact**: Only hit during inference/GT sampling when `skip_train=false`.
Currently `skip_train=true`, so this code path is not exercised.  When Phase 3
(native training) is enabled, this call site will need to be updated in
`MLDTrainAutomationLibrary.cpp` if it directly calls the deprecated form.

---

## 6. Engine-Bundled Python Package

See [README_UE57_Engine_Python_Package.md](README_UE57_Engine_Python_Package.md)
for full details on:
- `mldeformer/morph_helpers.py`
- `mldeformer/training_helpers.py`
- `mldeformer/tensorboard_helpers.py`

---

## 7. `VertexDeltaModel` Plugin (Out of Scope)

A new plugin `VertexDeltaModel` was added in UE5.7. This project uses only
NMM (`NeuralMorphModel`) and NNM (`NearestNeighborModel`) — `VertexDeltaModel`
is out of scope and not installed/enabled.

---

## Summary Table

| API / Symbol | UE5.5 | UE5.7 | Pipeline Impact | Phase |
|---|---|---|---|---|
| `EMLDeformerSkinningMode` | ❌ not present | ✅ new enum | `skinning_mode` in `model_overrides`; default Linear = no breaking change | 2.2 |
| `BoneMaskInfos` | `TMap<FName, FNeuralMorphMaskInfo>` | renamed to `BoneMaskInfoMap` + `FMLDeformerMaskInfo` | Python rename shim in `_normalize_model_overrides_for_ue57()` | 2.1 |
| `BoneGroupMaskInfos` | same pattern | `BoneGroupMaskInfoMap` | same shim | 2.1 |
| `UNNMSection.WeightMapCreationMethod` | ❌ not present | ✅ new enum | Not yet configured; stays at UObject default | 2.3 |
| `GetNumMorphTargets()` | no-arg API | deprecated; LOD param needed | Not called anywhere — no change | 2.4 |
| `SampleGroundTruthPositionsAtFrame` | `SampleGroundTruthPositions(float)` | new frame-index API | Only affects `skip_train=false` path | 3.2 |
| `mldeformer/` Python package | ❌ not present | engine-bundled | Not imported by pipeline scripts | 3.3 |
| `FMLDeformerTrainingDataProcessorAnim` | ❌ not present | new wrapper struct | Not Python-reflected; bridge bypasses it | 3.2 |

---

## 8. Phase W 实战回写：这次巨大差异不是 API 兼容偶然

2026-03-09 的 Phase W 闭环给这份 code-map diff 补了一个非常重要的工程结论：

> **W-3A 受限 Local 与 W-3B NNM 的结果差距极大，并不是因为 UE5.5 → UE5.7 出现了新的 Breaking API。真正决定结果的是模型执行路径本身。**

### 8.1 这次两条路径的实测结果

| 路线 | 关键配置 | 结果 |
|------|----------|------|
| W-3A 受限 Local | `mode: local` + `local_num_morph_targets_per_bone: 1` | `ssim_mean=0.5550`，失败 |
| W-3B NNM | `model_type: NNM` + 单 section 邻域配置 | `ssim_mean=0.9960`，闭环成功 |

### 8.2 为什么这不是 compat 层问题

本文件前面已经列出的 UE5.7 变更点，主要是：

- 新枚举 `EMLDeformerSkinningMode`
- masking 结构改名
- `UNearestNeighborModelSection` 的 UObject 化
- 个别废弃 API / 新签名

这些变更都不会自然地产生“0.5550 vs 0.9960”这种量级差异。它们最多影响：

- 配置字段如何映射
- 某些桥接代码是否需要 rename shim
- 训练 / 采样路径是否要适配新签名

而这次两条路线都使用了同一条 UE5.7 pipeline、同一套训练输入、同一套 capture/compare 闭环。差异来自**模型如何表达局部姿态细节**，不是 compat API 是否调用成功。

### 8.3 真正相关的代码路径差异

对本次结果最关键的路径不是 compat shim，而是运行时/训练时模型结构差异：

- NMM 路线：以基础网络预测为主
- NNM 路线：`UNearestNeighborModelInstance::Execute` + `RunNearestNeighborModel` 两段式执行

也就是说，W-3B 的成功来自：

1. 基础网络先给出稳定预测；
2. 邻域检索分支再对相似姿态做局部细节补偿。

而 W-3A 受限 Local 失败的原因，是在 `local_num_morph_targets_per_bone=1` 这个极小容量下，局部模型根本不够表达复杂上臂/脖颈姿态。

### 8.4 对后续 UE5.7 工作的直接指导

以后在 UE5.7 上遇到类似问题时，优先按下面顺序判断：

1. 如果怀疑 compat 问题，先查本文件列出的 API rename / signature diff。
2. 如果 pipeline 能正常完成 `ue_setup -> train -> capture -> compare`，但质量差距巨大，就不要再把主因归到 API 兼容层。
3. 对于少量连续帧、局部身体区域、姿态相关误差，优先评估 NNM 路线，而不是继续堆 Global 容量或把 Local 容量压得过低。
