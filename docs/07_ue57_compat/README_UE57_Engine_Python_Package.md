# UE5.7 Engine-Bundled `mldeformer/` Python Package

> **Phase 3.3 documentation** — engine-bundled Python modules for MLDeformer.

---

## Location

```
<UE_5.7>/Engine/Plugins/Animation/MLDeformer/MLDeformerFramework/Content/Python/
└── mldeformer/
    ├── morph_helpers.py
    ├── training_helpers.py
    └── tensorboard_helpers.py
```

Absolute path on this workstation:
```
D:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Animation\MLDeformer\
  MLDeformerFramework\Content\Python\mldeformer\
```

---

## Module Responsibilities

| Module | Scope | Key symbols |
|--------|-------|-------------|
| `training_helpers.py` | PyTorch training loop, CUDA device discovery, dataset utilities | `get_available_cuda_devices()`, `TensorUploadDataset` |
| `morph_helpers.py` | Post-training morph-target extraction, passes deltas into C++ via `unreal` API | `extract_morph_targets()` |
| `tensorboard_helpers.py` | TensorBoard logging helpers called from the training loop | Various `log_*` helpers |

These modules are **invoked by the engine's own training Python scripts** that
run inside the UE in-process Python interpreter during `ActiveModel->Train()`.
They are **not** called from our pipeline Python scripts (`ue_train.py`, etc.)
which communicate with the engine exclusively through the C++ bridge
(`MLDTrainAutomationLibrary`).

---

## Division of Responsibility

```
Pipeline side (ue_train.py)
    │
    │  calls via Unreal Python reflection
    ▼
MLDTrainAutomationLibrary (C++ bridge)
    │
    │  calls C++ training APIs
    ▼
UMLDeformerEditorModel::Train()
    │
    │  in-process Python subprocess
    ▼
mldeformer/training_helpers.py     ← engine-bundled, NOT our code
mldeformer/morph_helpers.py        ← engine-bundled, NOT our code
mldeformer/tensorboard_helpers.py  ← engine-bundled, NOT our code
```

Our pipeline scripts do **not** import from `mldeformer.*` and are not affected
by changes to these engine modules.

---

## Tech Debt: Possible Duplication

If the project's `Content/Python/` directory contains any `training_*.py` or
`morph_*.py` scripts, audit them against the engine-bundled equivalents:

- Duplicated logic should be removed in favour of the engine version.
- Project-side scripts should only contain project-specific pipeline glue.

> Run: `Get-ChildItem "D:\UE\Unreal Projects\UE57\MLDeformerSample\Content\Python\" -Filter "*.py"`

---

## Patched Engine Files

> ⚠️ These engine Python files have been **modified in-place** on this workstation.
> Re-check after any UE5.7 engine update (launcher repair or reinstall will overwrite).

### `morph_helpers.py` — chunked `.tolist()` fix (2026-03-01)

**Problem**: `extract_morph_targets()` called `.tolist()` on the full flattened morph
target matrix in one shot. For Emil's flesh body (~60k verts × 256 modes × 3 floats
= 46M elements), Python's `.tolist()` requires ~56 bytes per float → ~2.5 GB peak
memory, causing `MemoryError` during NMM post-training extraction.

**Symptom in `train_report.json`**:
```
MemoryError in morph_helpers.py line 45:
    deltas.extend(morph_target_matrix.T.flatten().cpu().detach().numpy().tolist())
```

**Fix applied**: replaced single `.tolist()` call with chunked iteration (500 000
elements per chunk, ~28 MB peak per chunk):
```python
_arr = morph_target_matrix.T.flatten().cpu().detach().numpy()
_CHUNK = 500_000
for _s in range(0, len(_arr), _CHUNK):
    deltas.extend(_arr[_s:_s + _CHUNK].tolist())
del _arr
```

**Affected file**:
```
D:\Program Files\Epic Games\UE_5.7\Engine\Plugins\Animation\MLDeformer\
  MLDeformerFramework\Content\Python\mldeformer\morph_helpers.py
```

---

## Notes on `FMLDeformerTrainingDataProcessorAnim` (Phase 3.2)

UE5.7 introduced `FMLDeformerTrainingDataProcessorAnim` as a struct that wraps
training animation configuration.  As of this writing it is **not Python-reflected**
in `unreal.*` (probe: `getattr(unreal, "MLDeformerTrainingDataProcessorAnim", None)`
returns `None`).

The C++ bridge bypasses this new struct by writing directly into
`UMLDeformerGeomCacheModel::GetTrainingInputAnims()` before calling `Train()`.
This approach is compatible with UE5.7 and requires no changes unless a future
engine update removes the direct GeomModel path.

To detect if this becomes an issue, `ue_train.py` now logs
`training_processor_api_present: bool` in `train_report.json` at runtime.
