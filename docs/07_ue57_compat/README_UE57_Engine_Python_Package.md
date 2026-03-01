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
