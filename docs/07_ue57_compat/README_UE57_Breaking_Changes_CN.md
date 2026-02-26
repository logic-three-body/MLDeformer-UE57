# UE5.5 → UE5.7 MLDeformer API 变更分析

> **范围**：仅覆盖 `MLDeformerSampleEditorTools` 模块所调用的 API，以及工程移植时开发者可能遇到的重要变更。  
> **引擎路径对比**：  
> - UE5.5：`D:\Program Files\Epic Games\UE_5.5\Engine\Plugins\Animation\MLDeformer\`  
> - UE5.7：`D:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Animation\MLDeformer\`

---

## 1. 结论速查

| 类别 | 数量 | 影响 |
|------|------|------|
| 需要代码改动的 Breaking Change | **0** | `MLDTrainAutomationLibrary.cpp` 在 UE5.7 无需任何修改 |
| 新增 API（可选使用） | 4 | 新枚举 + 新方法，不使用也不报错 |
| 废弃 API（Deprecated，未移除）| 1 | 源工程中未调用，无影响 |
| 导出宏风格变更 | 1 | 仅影响插件内部，调用方无感知 |

---

## 2. 详细变更列表

### 2.1 `FMLDeformerScopedEditor`（`MLDeformerEditorModule.h`）

| 比较项 | UE5.5 | UE5.7 | 影响 |
|--------|-------|-------|------|
| 类定义 | `MLDEFORMEDITOR_API class FMLDeformerScopedEditor` | 同 | ✅ 无变化 |
| 构造函数签名 | `FMLDeformerScopedEditor(UMLDeformerAsset*)` | 同 | ✅ 无变化 |
| `GetToolkit()` | 返回 `FMLDeformerEditorToolkit*` | 同 | ✅ 无变化 |

**结论**：我们的 `MLDTrainAutomationLibrary.cpp` 用 `FMLDeformerScopedEditor Editor(Asset); Editor.GetToolkit()->Train(...)` — **零改动**。

---

### 2.2 `FMLDeformerEditorToolkit`（`MLDeformerEditorToolkit.h`）

| 方法 | UE5.5 签名 | UE5.7 签名 | 影响 |
|------|-----------|-----------|------|
| `Train(bool bSuppressDialogs)` | ✓ | ✓（相同） | ✅ 无变化 |
| `SwitchModelType(TSubclassOf<UMLDeformerModel>, bool)` | ✓ | ✓（相同） | ✅ 无变化 |
| `GetTrainingStatusIcon()` | ❌ 不存在 | ✅ **新增** | 纯新增，不影响现有代码 |

---

### 2.3 `FMLDeformerEditorModel`（`MLDeformerEditorModel.h`）

所有 `virtual` override 函数在 UE5.5 → UE5.7 中**签名不变**：

- `TriggerInputAssetChanged(bool bForceReinit)` ✅
- `UpdateIsReadyForTrainingState()` ✅
- `IsReadyForTraining()` ✅
- `SetActiveModel(UMLDeformerModel*)` ✅

---

### 2.4 `UNeuralMorphModel`（`NeuralMorphModel.h`）— 新增 API ★

UE5.7 新增 **蒙皮模式枚举**（定义于 `MLDeformerModel.h`）：

```cpp
UENUM(BlueprintType)
enum class EMLDeformerSkinningMode : uint8
{
    Linear      UMETA(DisplayName = "Linear Blend Skinning"),
    DualQuaternion UMETA(DisplayName = "Dual Quaternion Skinning"),
};
```

UE5.7 `UNeuralMorphModel` 新增方法：

```cpp
// UE5.7 only
EMLDeformerSkinningMode GetSkinningMode() const;
void SetSkinningMode(EMLDeformerSkinningMode InSkinningMode);
bool SupportsGlobalModeOnly() const;  // 查询模型是否仅支持全局模式
```

**对现有代码的影响**：`MLDTrainAutomationLibrary.cpp` 不调用这些方法 → **零影响**。

**可选扩展**（低优先级）：若未来需要通过配置控制 DQS，可在 `ApplyModelOverrides` 中添加：

```cpp
#if ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 7
    if (UNeuralMorphModel* NMM = Cast<UNeuralMorphModel>(ActiveModel))
    {
        FString ModeStr;
        if (JsonFieldToString(Overrides, TEXT("skinning_mode"), ModeStr))
        {
            auto Mode = ModeStr.ToLower() == TEXT("dualquaternion")
                ? EMLDeformerSkinningMode::DualQuaternion
                : EMLDeformerSkinningMode::Linear;
            NMM->SetSkinningMode(Mode);
        }
    }
#endif
```

---

### 2.5 `MLDeformerTrainingDataProcessorSettings.h` — 新增文件

UE5.7 新增头文件 `MLDeformerTrainingDataProcessorSettings.h`，包含训练数据处理器配置类。  
当前 `MLDTrainAutomationLibrary.cpp` **不引用此头文件** → **零影响**。

---

### 2.6 `FMLDeformerModelOnPostEditProperty` — 废弃 ★

| 版本 | 状态 |
|------|------|
| UE5.5 | 正常使用 |
| UE5.7 | `UE_DEPRECATED(5.6, ...)` 标注，建议改用 `FMLDeformerReinitModelInstancesDelegate` |

**对现有代码的影响**：`MLDTrainAutomationLibrary.cpp` **未调用** 此 delegate → **零影响**。

---

### 2.7 导出宏风格变更

| 版本 | 导出风格 |
|------|---------|
| UE5.5 | `class MLDEFORMERFRAMEWORK_API UMLDeformerModel { ... }` |
| UE5.7 | `class UMLDeformerModel { ... UE_API void SomeMethod(); ... }` |

**含义**：UE5.7 改用**函数级导出**（`UE_API`），而非类级导出。  
**对调用方的影响**：**零影响** — 编译器和链接器行为对调用方完全透明。

---

## 3. 插件结构变化

### UE5.5 插件结构
```
MLDeformer/
├── MLDeformerFramework/
├── NeuralMorphModel/
├── NearestNeighborModel/
└── MLDeformerEditor/  (编辑器层)
```

### UE5.7 插件结构
```
MLDeformer/
├── MLDeformerFramework/
├── NeuralMorphModel/
├── NearestNeighborModel/
├── VertexDeltaModel/     ← UE5.7 新增子插件
└── MLDeformerEditor/
```

**新增 `VertexDeltaModel`**：是全新的网格顶点增量模型，不影响现有 NMM/NNM 工作流。

---

## 4. `MLDeformerSample.Build.cs` 模块依赖完整性检查

| 依赖模块 | UE5.5 中存在 | UE5.7 中存在 | 状态 |
|----------|-------------|-------------|------|
| `MLDeformerFramework` | ✓ | ✓ | ✅ |
| `MLDeformerEditor` | ✓ | ✓ | ✅ |
| `NeuralMorphModel` | ✓ | ✓ | ✅ |
| `NearestNeighborModel` | ✓ | ✓ | ✅ |
| `UnrealEd` | ✓ | ✓ | ✅ |
| `Engine` | ✓ | ✓ | ✅ |

**结论**：所有依赖在 UE5.7 中均存在，`.Build.cs` 无需修改。

---

## 5. UE5.7 新增关注点（非 Breaking，但建议了解）

### 5.1 Masking 系统
`MLDeformerMasking.h` — UE5.7 新增遮罩系统，允许对特定骨骼/顶点区域限制变形影响。  
本工程当前不使用遮罩，无需配置。

### 5.2 训练数据处理器配置
`MLDeformerTrainingDataProcessorSettings.h` — 集中配置数据预处理参数（归一化策略等）。  
现有训练流程通过 `model_overrides` JSON 配置，暂时无需迁移。

### 5.3 Morph Quality Level
`MLDeformerMorphModelQualityLevel.h` — LOD 级别的 Morph 权重质量控制，影响运行时性能/质量取舍。  
本工程使用固定 LOD0，暂无影响。

---

*文档生成于 UE5.7 compat workspace 初始化阶段。如发现新的兼容性问题请更新本文档并同步 `README_UE57_Migration_Checklist_CN.md`。*
