#include "MLDTrainAutomationLibrary.h"

#include "Animation/AnimSequence.h"
#include "Animation/AnimTypes.h"
#include "Animation/MeshDeformer.h"
#include "BoneContainer.h"
#include "Engine/SkeletalMesh.h"
#include "GeometryCache.h"
#include "GeometryCacheTrack.h"
#include "HAL/PlatformTime.h"
#include "MLDeformerAsset.h"
#include "MLDeformerEditorModel.h"
#include "MLDeformerEditorToolkit.h"
#include "MLDeformerGeomCacheModel.h"
#include "MLDeformerGeomCacheTrainingInputAnim.h"
#include "MLDeformerCurveReference.h"
#include "MLDeformerInputInfo.h"
#include "MLDeformerModel.h"
#include "MLDeformerTestHelpers.h"
#include "MLDeformerVizSettings.h"
#include "Misc/PackageName.h"
#include "Modules/ModuleManager.h"
#include "NearestNeighborModel.h"
#include "NeuralMorphModel.h"
#include "Rendering/SkeletalMeshModel.h"
#include "SkeletalMeshAttributes.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"
#include "MLDeformerGeomCacheHelpers.h"

DEFINE_LOG_CATEGORY_STATIC(LogMLDTrainAutomation, Log, All);

namespace
{
	FString NormalizeAssetPath(const FString& InAssetPath)
	{
		FString AssetPath = InAssetPath;
		AssetPath.TrimStartAndEndInline();
		if (AssetPath.IsEmpty())
		{
			return AssetPath;
		}

		if (AssetPath.Contains(TEXT(".")))
		{
			return AssetPath;
		}

		const FString AssetName = FPackageName::GetLongPackageAssetName(AssetPath);
		if (AssetName.IsEmpty())
		{
			return AssetPath;
		}

		return FString::Printf(TEXT("%s.%s"), *AssetPath, *AssetName);
	}

	template <typename T>
	T* LoadAssetByPath(const FString& InAssetPath)
	{
		const FString LoadPath = NormalizeAssetPath(InAssetPath);
		if (LoadPath.IsEmpty())
		{
			return nullptr;
		}
		return LoadObject<T>(nullptr, *LoadPath);
	}

	UClass* ResolveModelClass(const FString& InModelType)
	{
		FString Key = InModelType;
		Key.TrimStartAndEndInline();
		Key.ToLowerInline();

		if (Key.IsEmpty())
		{
			return nullptr;
		}

		if (Key == TEXT("nmm") || Key == TEXT("neuralmorph") || Key == TEXT("neural_morph") || Key == TEXT("neuralmorphmodel"))
		{
			return UNeuralMorphModel::StaticClass();
		}

		if (Key == TEXT("nnm") || Key == TEXT("nearestneighbor") || Key == TEXT("nearest_neighbor") || Key == TEXT("nearestneighbormodel"))
		{
			return UNearestNeighborModel::StaticClass();
		}

		return nullptr;
	}

	FString JoinStrings(const TArray<FString>& Values, const TCHAR* Separator = TEXT(","))
	{
		if (Values.IsEmpty())
		{
			return TEXT("<none>");
		}
		return FString::Join(Values, Separator);
	}

	TArray<FString> ExtractGeomTrackNames(const UGeometryCache* GeomCache)
	{
		TArray<FString> Names;
		if (!GeomCache)
		{
			return Names;
		}

		for (const TObjectPtr<UGeometryCacheTrack>& Track : GeomCache->Tracks)
		{
			if (Track)
			{
				Names.Add(Track->GetName());
			}
		}
		return Names;
	}

	TArray<FString> ExtractSourceGeometryPartNames(const USkeletalMesh* SkeletalMesh, const int32 LODIndex = 0)
	{
		TArray<FString> Names;
		if (!SkeletalMesh)
		{
			return Names;
		}

		USkeletalMesh* MutableSkeletalMesh = const_cast<USkeletalMesh*>(SkeletalMesh);
		FMeshDescription* MeshDescription = MutableSkeletalMesh ? MutableSkeletalMesh->GetMeshDescription(LODIndex) : nullptr;
		if (!MeshDescription)
		{
			return Names;
		}

		FSkeletalMeshAttributes MeshAttributes(*MeshDescription);
		if (!MeshAttributes.HasSourceGeometryParts())
		{
			return Names;
		}

		const FSkeletalMeshAttributes::FSourceGeometryPartNameConstRef PartNames = MeshAttributes.GetSourceGeometryPartNames();
		const FSkeletalMeshAttributes::FSourceGeometryPartVertexOffsetAndCountConstRef PartOffsetAndCounts =
			MeshAttributes.GetSourceGeometryPartVertexOffsetAndCounts();

		for (int32 GeoPartIndex = 0; GeoPartIndex < MeshAttributes.GetNumSourceGeometryParts(); ++GeoPartIndex)
		{
			const FSourceGeometryPartID PartID(GeoPartIndex);
			const FString PartName = PartNames[PartID].ToString();
			const TArrayView<const int32> PartInfo = PartOffsetAndCounts.Get(GeoPartIndex);
			const int32 NumVerts = (PartInfo.Num() > 1) ? PartInfo[1] : -1;
			Names.Add(FString::Printf(TEXT("%s:%d"), *PartName, NumVerts));
		}
		return Names;
	}

	bool OpenEditorForAsset(
		const FString& AssetPath,
		UMLDeformerAsset*& OutAsset,
		UE::MLDeformer::FMLDeformerEditorToolkit*& OutToolkit,
		TUniquePtr<UE::MLDeformer::FMLDeformerScopedEditor>& OutScopedEditor,
		FString& OutMessage)
	{
		OutAsset = nullptr;
		OutToolkit = nullptr;
		OutScopedEditor.Reset();

		const FString LoadPath = NormalizeAssetPath(AssetPath);
		OutAsset = LoadObject<UMLDeformerAsset>(nullptr, *LoadPath);
		if (!OutAsset)
		{
			OutMessage = FString::Printf(TEXT("Failed to load ML Deformer asset: %s"), *LoadPath);
			return false;
		}

		OutToolkit = UE::MLDeformer::FMLDeformerTestHelpers::OpenAssetEditor(OutAsset);
		if (!OutToolkit)
		{
			OutMessage = FString::Printf(TEXT("Failed to open ML Deformer editor for asset: %s"), *LoadPath);
			return false;
		}

		OutScopedEditor = MakeUnique<UE::MLDeformer::FMLDeformerScopedEditor>(OutToolkit);
		if (!OutScopedEditor.IsValid() || !OutScopedEditor->IsValid())
		{
			OutMessage = FString::Printf(TEXT("Failed to create scoped editor wrapper for asset: %s"), *LoadPath);
			return false;
		}

		OutScopedEditor->SetCloseEditor(true);
		return true;
	}

	bool EnsureModelTypeInternal(
		UE::MLDeformer::FMLDeformerEditorToolkit* Toolkit,
		const FString& ModelType,
		const bool bForceSwitch,
		FString& OutMessage)
	{
		if (!Toolkit)
		{
			OutMessage = TEXT("Editor toolkit is null.");
			return false;
		}

		UClass* DesiredModelClass = ResolveModelClass(ModelType);
		if (!DesiredModelClass)
		{
			FString Trimmed = ModelType;
			Trimmed.TrimStartAndEndInline();
			if (Trimmed.IsEmpty())
			{
				return true;
			}

			OutMessage = FString::Printf(TEXT("Unsupported model_type: '%s'"), *ModelType);
			return false;
		}

		UE::MLDeformer::FMLDeformerEditorModel* ActiveModel = Toolkit->GetActiveModel();
		if (!ActiveModel || !ActiveModel->GetModel())
		{
			OutMessage = TEXT("No active model found in ML Deformer editor.");
			return false;
		}

		UClass* CurrentClass = ActiveModel->GetModel()->GetClass();
		if (CurrentClass == DesiredModelClass)
		{
			return true;
		}

		if (!Toolkit->SwitchModelType(DesiredModelClass, bForceSwitch))
		{
			OutMessage = FString::Printf(
				TEXT("SwitchModelType failed. requested=%s current=%s"),
				*DesiredModelClass->GetName(),
				(CurrentClass ? *CurrentClass->GetName() : TEXT("None")));
			return false;
		}

		return true;
	}

	ETrainingResult TrainWithResult(
		UE::MLDeformer::FMLDeformerEditorToolkit* Toolkit,
		const bool bSuppressDialogs,
		double& OutDurationSec,
		bool& bOutNetworkLoaded,
		bool& bOutSuccess,
		FString& OutMessage)
	{
		OutDurationSec = 0.0;
		bOutNetworkLoaded = false;
		bOutSuccess = false;

		if (!Toolkit)
		{
			OutMessage = TEXT("Editor toolkit is null.");
			return ETrainingResult::Other;
		}

		UE::MLDeformer::FMLDeformerEditorModel* ActiveModel = Toolkit->GetActiveModel();
		if (!ActiveModel || !ActiveModel->GetModel())
		{
			OutMessage = TEXT("No active model to train.");
			return ETrainingResult::Other;
		}

		// Property-driven setup may not have gone through details panel callbacks.
		// Force a full input refresh so readiness checks use up-to-date frame/input caches.
		ActiveModel->TriggerInputAssetChanged(true);
		ActiveModel->UpdateIsReadyForTrainingState();
		if (!ActiveModel->IsReadyForTraining())
		{
			TArray<FString> DetailLines;
			const auto AddDetail = [&DetailLines](const TCHAR* Label, const FText& Text)
			{
				if (!Text.IsEmpty())
				{
					DetailLines.Add(FString::Printf(TEXT("%s=%s"), Label, *Text.ToString()));
				}
			};

			AddDetail(TEXT("inputs"), ActiveModel->GetInputsErrorText());
			AddDetail(TEXT("base_asset"), ActiveModel->GetBaseAssetChangedErrorText());
			AddDetail(TEXT("vertex_map"), ActiveModel->GetVertexMapChangedErrorText());
			AddDetail(TEXT("target_asset"), ActiveModel->GetTargetAssetChangedErrorText());
			AddDetail(TEXT("skeletal_mesh"), ActiveModel->GetSkeletalMeshNeedsReimportErrorText());
			DetailLines.Add(FString::Printf(
				TEXT("diag:num_inputs=%d training_frames=%d has_ground_truth=%d has_skel=%d"),
				ActiveModel->GetNumTrainingInputAnims(),
				ActiveModel->GetNumTrainingFrames(),
				ActiveModel->GetModel()->HasTrainingGroundTruth() ? 1 : 0,
				ActiveModel->GetModel()->GetSkeletalMesh() ? 1 : 0));
			for (int32 InputIndex = 0; InputIndex < ActiveModel->GetNumTrainingInputAnims(); ++InputIndex)
			{
				const FMLDeformerTrainingInputAnim* BaseInput = ActiveModel->GetTrainingInputAnim(InputIndex);
				if (!BaseInput)
				{
					DetailLines.Add(FString::Printf(TEXT("diag:input[%d]=null"), InputIndex));
					continue;
				}

				DetailLines.Add(FString::Printf(
					TEXT("diag:input[%d]:enabled=%d valid=%d"),
					InputIndex,
					BaseInput->IsEnabled() ? 1 : 0,
					BaseInput->IsValid() ? 1 : 0));

				if (const FMLDeformerGeomCacheTrainingInputAnim* GeomInput = static_cast<const FMLDeformerGeomCacheTrainingInputAnim*>(BaseInput))
				{
					const UAnimSequence* Anim = GeomInput->GetAnimSequence();
					const UGeometryCache* Geom = GeomInput->GetGeometryCache();
					DetailLines.Add(FString::Printf(
						TEXT("diag:input[%d]:anim=%s geom=%s use_range=%d start=%d end=%d frames_to_sample=%d"),
						InputIndex,
						Anim ? *Anim->GetPathName() : TEXT("<null>"),
						Geom ? *Geom->GetPathName() : TEXT("<null>"),
						GeomInput->GetUseCustomRange() ? 1 : 0,
						GeomInput->GetStartFrame(),
						GeomInput->GetEndFrame(),
						GeomInput->GetNumFramesToSample()));

					if (Geom)
					{
						const USkeletalMesh* SkeletalMesh = ActiveModel->GetModel()->GetSkeletalMesh();
						const TArray<FString> TrackNames = ExtractGeomTrackNames(Geom);
						const TArray<FString> SourcePartNames = ExtractSourceGeometryPartNames(SkeletalMesh);
						DetailLines.Add(FString::Printf(
							TEXT("diag:input[%d]:geom_tracks=%s"),
							InputIndex,
							*JoinStrings(TrackNames)));
						DetailLines.Add(FString::Printf(
							TEXT("diag:input[%d]:geom_imported_vertices=%d"),
							InputIndex,
							UE::MLDeformer::ExtractNumImportedGeomCacheVertices(const_cast<UGeometryCache*>(Geom))));
						DetailLines.Add(FString::Printf(
							TEXT("diag:input[%d]:skel_source_parts=%s"),
							InputIndex,
							*JoinStrings(SourcePartNames)));

						const FText MappingError = UE::MLDeformer::GetGeomCacheMeshMappingErrorText(
							const_cast<USkeletalMesh*>(SkeletalMesh),
							const_cast<UGeometryCache*>(Geom));
						if (!MappingError.IsEmpty())
						{
							FString MappingErrorString = MappingError.ToString();
							MappingErrorString.ReplaceInline(TEXT("|"), TEXT("/"));
							DetailLines.Add(FString::Printf(
								TEXT("diag:input[%d]:geom_mapping_error=%s"),
								InputIndex,
								*MappingErrorString));
						}
					}
				}
			}

			if (DetailLines.IsEmpty())
			{
				OutMessage = TEXT("Model is not ready for training. Check inputs (skeletal mesh / animation / geom cache / sections).");
			}
			else
			{
				OutMessage = FString::Printf(
					TEXT("Model is not ready for training. %s"),
					*FString::Join(DetailLines, TEXT(" | ")));
			}
			return ETrainingResult::FailOnData;
		}

		ActiveModel->OnPreTraining();
		ActiveModel->UpdateEditorInputInfo();

		const UMLDeformerInputInfo* EditorInputInfo = ActiveModel->GetEditorInputInfo();
		if (!EditorInputInfo || EditorInputInfo->IsEmpty())
		{
			OutMessage = TEXT("Editor input info is empty. Training aborted before launch.");
			return ETrainingResult::FailOnData;
		}

		const double StartTime = FPlatformTime::Seconds();
		const ETrainingResult TrainingResult = ActiveModel->Train();
		OutDurationSec = FPlatformTime::Seconds() - StartTime;

		bool bUsePartiallyTrained = false;
		switch (TrainingResult)
		{
		case ETrainingResult::Success:
		{
			ActiveModel->SetResamplingInputOutputsNeeded(false);
			bOutNetworkLoaded = ActiveModel->LoadTrainedNetwork();
			if (bOutNetworkLoaded)
			{
				ActiveModel->InitInputInfo(ActiveModel->GetModel()->GetInputInfo());
				bOutSuccess = true;
				OutMessage = TEXT("Training succeeded and network loaded.");
			}
			else
			{
				OutMessage = TEXT("Training succeeded but LoadTrainedNetwork failed.");
			}
		}
		break;
		case ETrainingResult::Aborted:
			OutMessage = bSuppressDialogs ? TEXT("Training aborted (dialogs suppressed).") : TEXT("Training aborted.");
			break;
		case ETrainingResult::AbortedCantUse:
			OutMessage = TEXT("Training aborted and partial network is not usable.");
			break;
		case ETrainingResult::FailOnData:
			OutMessage = TEXT("Training failed due to invalid input data.");
			break;
		case ETrainingResult::FailPythonError:
			OutMessage = TEXT("Training failed due to Python error. Check Output Log.");
			break;
		default:
			OutMessage = TEXT("Training failed with an unknown error.");
			break;
		}

		ActiveModel->OnPostTraining(TrainingResult, bUsePartiallyTrained);
		const bool bNeedsResamplingBackup = ActiveModel->GetResamplingInputOutputsNeeded();
		ActiveModel->SetResamplingInputOutputsNeeded(bNeedsResamplingBackup);
		ActiveModel->RefreshMLDeformerComponents();

		if (UMLDeformerModel* RuntimeModel = ActiveModel->GetModel())
		{
			if (UMLDeformerVizSettings* VizSettings = RuntimeModel->GetVizSettings())
			{
				ActiveModel->SetHeatMapMaterialEnabled(VizSettings->GetShowHeatMap());
			}
		}
		ActiveModel->UpdateDeformerGraph();

		return TrainingResult;
	}

	bool ParseJsonObject(const FString& JsonText, TSharedPtr<FJsonObject>& OutObject, FString& OutError)
	{
		FString Trimmed = JsonText;
		Trimmed.TrimStartAndEndInline();
		if (Trimmed.IsEmpty())
		{
			OutObject = MakeShared<FJsonObject>();
			return true;
		}

		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Trimmed);
		if (!FJsonSerializer::Deserialize(Reader, OutObject) || !OutObject.IsValid())
		{
			OutError = TEXT("Invalid JSON object.");
			return false;
		}
		return true;
	}

	bool ParseJsonArray(const FString& JsonText, TArray<TSharedPtr<FJsonValue>>& OutArray, FString& OutError)
	{
		FString Trimmed = JsonText;
		Trimmed.TrimStartAndEndInline();
		if (Trimmed.IsEmpty())
		{
			OutArray.Reset();
			return true;
		}

		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Trimmed);
		if (!FJsonSerializer::Deserialize(Reader, OutArray))
		{
			OutError = TEXT("Invalid JSON array.");
			return false;
		}
		return true;
	}

	bool JsonFieldToString(const TSharedPtr<FJsonObject>& Object, const FString& Field, FString& OutValue)
	{
		if (!Object.IsValid() || !Object->HasField(Field))
		{
			return false;
		}
		OutValue = Object->GetStringField(Field);
		return true;
	}

	bool JsonFieldToBool(const TSharedPtr<FJsonObject>& Object, const FString& Field, bool& OutValue)
	{
		if (!Object.IsValid() || !Object->HasField(Field))
		{
			return false;
		}

		const TSharedPtr<FJsonValue> Value = Object->TryGetField(Field);
		if (!Value.IsValid())
		{
			return false;
		}
		if (Value->Type == EJson::Boolean)
		{
			OutValue = Value->AsBool();
			return true;
		}
		if (Value->Type == EJson::Number)
		{
			OutValue = !FMath::IsNearlyZero(Value->AsNumber());
			return true;
		}
		return false;
	}

	bool JsonFieldToInt(const TSharedPtr<FJsonObject>& Object, const FString& Field, int32& OutValue)
	{
		if (!Object.IsValid() || !Object->HasField(Field))
		{
			return false;
		}
		const TSharedPtr<FJsonValue> Value = Object->TryGetField(Field);
		if (!Value.IsValid())
		{
			return false;
		}
		if (Value->Type == EJson::Number)
		{
			OutValue = static_cast<int32>(FMath::RoundToInt(Value->AsNumber()));
			return true;
		}
		return false;
	}

	bool JsonFieldToFloat(const TSharedPtr<FJsonObject>& Object, const FString& Field, float& OutValue)
	{
		if (!Object.IsValid() || !Object->HasField(Field))
		{
			return false;
		}
		const TSharedPtr<FJsonValue> Value = Object->TryGetField(Field);
		if (!Value.IsValid())
		{
			return false;
		}
		if (Value->Type == EJson::Number)
		{
			OutValue = static_cast<float>(Value->AsNumber());
			return true;
		}
		return false;
	}

	TArray<int32> JsonFieldToIntArray(const TSharedPtr<FJsonObject>& Object, const FString& Field)
	{
		TArray<int32> Result;
		if (!Object.IsValid() || !Object->HasTypedField<EJson::Array>(Field))
		{
			return Result;
		}

		const TArray<TSharedPtr<FJsonValue>>& JsonArray = Object->GetArrayField(Field);
		Result.Reserve(JsonArray.Num());
		for (const TSharedPtr<FJsonValue>& Value : JsonArray)
		{
			if (Value.IsValid() && Value->Type == EJson::Number)
			{
				Result.Add(static_cast<int32>(FMath::RoundToInt(Value->AsNumber())));
			}
		}
		return Result;
	}

	bool SetObjectPropertyByName(UObject* Target, const TCHAR* PropertyName, UObject* Value)
	{
		if (!Target)
		{
			return false;
		}

		FObjectPropertyBase* Property = FindFProperty<FObjectPropertyBase>(Target->GetClass(), PropertyName);
		if (!Property)
		{
			return false;
		}

		void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Target);
		Property->SetObjectPropertyValue(ValuePtr, Value);
		return true;
	}

	bool SetBoolPropertyByName(UObject* Target, const TCHAR* PropertyName, bool Value)
	{
		if (!Target)
		{
			return false;
		}
		FBoolProperty* Property = FindFProperty<FBoolProperty>(Target->GetClass(), PropertyName);
		if (!Property)
		{
			return false;
		}

		void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Target);
		Property->SetPropertyValue(ValuePtr, Value);
		return true;
	}

	bool SetIntPropertyByName(UObject* Target, const TCHAR* PropertyName, int32 Value)
	{
		if (!Target)
		{
			return false;
		}
		FNumericProperty* Property = FindFProperty<FNumericProperty>(Target->GetClass(), PropertyName);
		if (!Property || !Property->IsInteger())
		{
			return false;
		}

		void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Target);
		Property->SetIntPropertyValue(ValuePtr, static_cast<int64>(Value));
		return true;
	}

	bool SetFloatPropertyByName(UObject* Target, const TCHAR* PropertyName, float Value)
	{
		if (!Target)
		{
			return false;
		}
		FNumericProperty* Property = FindFProperty<FNumericProperty>(Target->GetClass(), PropertyName);
		if (!Property || !Property->IsFloatingPoint())
		{
			return false;
		}

		void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Target);
		Property->SetFloatingPointPropertyValue(ValuePtr, Value);
		return true;
	}

	bool SetEnumPropertyByName(UObject* Target, const TCHAR* PropertyName, const FString& EnumString)
	{
		if (!Target)
		{
			return false;
		}

		FProperty* Property = FindFProperty<FProperty>(Target->GetClass(), PropertyName);
		if (!Property)
		{
			return false;
		}

		UEnum* Enum = nullptr;
		FNumericProperty* Underlying = nullptr;
		if (FEnumProperty* EnumProperty = CastField<FEnumProperty>(Property))
		{
			Enum = EnumProperty->GetEnum();
			Underlying = EnumProperty->GetUnderlyingProperty();
		}
		else if (FByteProperty* ByteProperty = CastField<FByteProperty>(Property); ByteProperty && ByteProperty->Enum)
		{
			Enum = ByteProperty->Enum;
			Underlying = ByteProperty;
		}

		if (!Enum || !Underlying)
		{
			return false;
		}

		int64 EnumValue = Enum->GetValueByNameString(EnumString);
		if (EnumValue == INDEX_NONE)
		{
			FString Upper = EnumString;
			Upper.TrimStartAndEndInline();
			Upper.ToUpperInline();
			for (int32 Idx = 0; Idx < Enum->NumEnums(); ++Idx)
			{
				FString Name = Enum->GetNameStringByIndex(Idx);
				Name.ToUpperInline();
				if (Name == Upper)
				{
					EnumValue = Enum->GetValueByIndex(Idx);
					break;
				}
			}
		}

		if (EnumValue == INDEX_NONE)
		{
			return false;
		}

		void* ValuePtr = Property->ContainerPtrToValuePtr<void>(Target);
		Underlying->SetIntPropertyValue(ValuePtr, EnumValue);
		return true;
	}

	bool SetIntArrayPropertyByName(UObject* Target, const TCHAR* PropertyName, const TArray<int32>& Values)
	{
		if (!Target)
		{
			return false;
		}

		FArrayProperty* ArrayProperty = FindFProperty<FArrayProperty>(Target->GetClass(), PropertyName);
		if (!ArrayProperty)
		{
			return false;
		}

		FNumericProperty* InnerNumeric = CastField<FNumericProperty>(ArrayProperty->Inner);
		if (!InnerNumeric || !InnerNumeric->IsInteger())
		{
			return false;
		}

		void* ArrayPtr = ArrayProperty->ContainerPtrToValuePtr<void>(Target);
		FScriptArrayHelper ArrayHelper(ArrayProperty, ArrayPtr);
		ArrayHelper.Resize(Values.Num());
		for (int32 Index = 0; Index < Values.Num(); ++Index)
		{
			InnerNumeric->SetIntPropertyValue(ArrayHelper.GetRawPtr(Index), static_cast<int64>(Values[Index]));
		}
		return true;
	}

	TArray<FBoneReference> BuildAllBoneReferences(const USkeletalMesh* SkeletalMesh)
	{
		TArray<FBoneReference> Bones;
		if (!SkeletalMesh)
		{
			return Bones;
		}

		const FReferenceSkeleton& RefSkeleton = SkeletalMesh->GetRefSkeleton();
		Bones.Reserve(RefSkeleton.GetNum());
		for (int32 BoneIndex = 0; BoneIndex < RefSkeleton.GetNum(); ++BoneIndex)
		{
			FBoneReference BoneRef;
			BoneRef.BoneName = RefSkeleton.GetBoneName(BoneIndex);
			Bones.Add(BoneRef);
		}
		return Bones;
	}

	FString InferVertexMapString(UNearestNeighborModel* Model, int32 MeshIndex)
	{
		if (!Model || !Model->GetSkeletalMesh())
		{
			return FString();
		}

		const TArray<FInt32Range> Ranges = Model->GetMeshVertRanges(*Model->GetSkeletalMesh());
		if (Ranges.IsValidIndex(MeshIndex))
		{
			const FInt32Range& Range = Ranges[MeshIndex];
			if (Range.HasLowerBound() && Range.HasUpperBound())
			{
				const int32 Start = Range.GetLowerBoundValue();
				const int32 EndExclusive = Range.GetUpperBoundValue();
				if (EndExclusive > Start)
				{
					return FString::Printf(TEXT("%d-%d"), Start, EndExclusive - 1);
				}
			}
		}

		const int32 NumVerts = Model->GetSkeletalMesh()->GetNumImportedVertices();
		if (NumVerts > 0)
		{
			return FString::Printf(TEXT("0-%d"), NumVerts - 1);
		}
		return FString();
	}

	void ApplyModelOverrides(UMLDeformerModel* Model, const FString& ModelOverridesJson, TArray<FString>& OutWarnings)
	{
		TSharedPtr<FJsonObject> Overrides;
		FString ParseError;
		if (!ParseJsonObject(ModelOverridesJson, Overrides, ParseError))
		{
			OutWarnings.Add(FString::Printf(TEXT("model_overrides_json parse failed: %s"), *ParseError));
			return;
		}

		if (!Overrides.IsValid() || Overrides->Values.IsEmpty())
		{
			return;
		}

		auto SetIfInt = [&Overrides, &OutWarnings](UObject* Obj, const TCHAR* JsonKey, const TCHAR* PropName)
		{
			int32 Value = 0;
			if (JsonFieldToInt(Overrides, JsonKey, Value) && !SetIntPropertyByName(Obj, PropName, Value))
			{
				OutWarnings.Add(FString::Printf(TEXT("Override skipped: %s"), JsonKey));
			}
		};
		auto SetIfFloat = [&Overrides, &OutWarnings](UObject* Obj, const TCHAR* JsonKey, const TCHAR* PropName)
		{
			float Value = 0.0f;
			if (JsonFieldToFloat(Overrides, JsonKey, Value) && !SetFloatPropertyByName(Obj, PropName, Value))
			{
				OutWarnings.Add(FString::Printf(TEXT("Override skipped: %s"), JsonKey));
			}
		};
		auto SetIfBool = [&Overrides, &OutWarnings](UObject* Obj, const TCHAR* JsonKey, const TCHAR* PropName)
		{
			bool bValue = false;
			if (JsonFieldToBool(Overrides, JsonKey, bValue) && !SetBoolPropertyByName(Obj, PropName, bValue))
			{
				OutWarnings.Add(FString::Printf(TEXT("Override skipped: %s"), JsonKey));
			}
		};

		SetIfInt(Model, TEXT("num_iterations"), TEXT("NumIterations"));
		SetIfInt(Model, TEXT("batch_size"), TEXT("BatchSize"));
		SetIfFloat(Model, TEXT("learning_rate"), TEXT("LearningRate"));
		SetIfFloat(Model, TEXT("regularization_factor"), TEXT("RegularizationFactor"));
		SetIfFloat(Model, TEXT("smooth_loss_beta"), TEXT("SmoothLossBeta"));

		if (UNeuralMorphModel* NMM = Cast<UNeuralMorphModel>(Model))
		{
			FString ModeString;
			if (JsonFieldToString(Overrides, TEXT("mode"), ModeString) && !SetEnumPropertyByName(NMM, TEXT("Mode"), ModeString))
			{
				OutWarnings.Add(TEXT("Override skipped: mode"));
			}

			SetIfInt(NMM, TEXT("local_num_morph_targets_per_bone"), TEXT("LocalNumMorphTargetsPerBone"));
			SetIfInt(NMM, TEXT("global_num_morph_targets"), TEXT("GlobalNumMorphTargets"));
			SetIfInt(NMM, TEXT("local_num_hidden_layers"), TEXT("LocalNumHiddenLayers"));
			SetIfInt(NMM, TEXT("local_num_neurons_per_layer"), TEXT("LocalNumNeuronsPerLayer"));
			SetIfInt(NMM, TEXT("global_num_hidden_layers"), TEXT("GlobalNumHiddenLayers"));
			SetIfInt(NMM, TEXT("global_num_neurons_per_layer"), TEXT("GlobalNumNeuronsPerLayer"));
			SetIfBool(NMM, TEXT("b_enable_bone_masks"), TEXT("bEnableBoneMasks"));
		}

		if (UNearestNeighborModel* NNM = Cast<UNearestNeighborModel>(Model))
		{
			SetIfBool(NNM, TEXT("b_use_pca"), TEXT("bUsePCA"));
			SetIfInt(NNM, TEXT("num_basis_per_section"), TEXT("NumBasisPerSection"));
			SetIfBool(NNM, TEXT("b_use_dual_quaternion_deltas"), TEXT("bUseDualQuaternionDeltas"));
			SetIfFloat(NNM, TEXT("decay_factor"), TEXT("DecayFactor"));
			SetIfFloat(NNM, TEXT("nearest_neighbor_offset_weight"), TEXT("NearestNeighborOffsetWeight"));
			SetIfInt(NNM, TEXT("early_stop_epochs"), TEXT("EarlyStopEpochs"));
			SetIfBool(NNM, TEXT("b_use_rbf"), TEXT("bUseRBF"));
			SetIfFloat(NNM, TEXT("rbf_sigma"), TEXT("RBFSigma"));

			const TArray<int32> HiddenDims = JsonFieldToIntArray(Overrides, TEXT("hidden_layer_dims"));
			if (!HiddenDims.IsEmpty() && !SetIntArrayPropertyByName(NNM, TEXT("HiddenLayerDims"), HiddenDims))
			{
				OutWarnings.Add(TEXT("Override skipped: hidden_layer_dims"));
			}
		}
	}

	bool ApplyTrainingInputs(UMLDeformerModel* Model, const FString& TrainingInputJson, TArray<FString>& OutWarnings, FString& OutError)
	{
		UMLDeformerGeomCacheModel* GeomModel = Cast<UMLDeformerGeomCacheModel>(Model);
		if (!GeomModel)
		{
			return true;
		}

		TArray<TSharedPtr<FJsonValue>> JsonArray;
		if (!ParseJsonArray(TrainingInputJson, JsonArray, OutError))
		{
			OutError = FString::Printf(TEXT("training_input_anims_json parse failed: %s"), *OutError);
			return false;
		}

		TArray<FMLDeformerGeomCacheTrainingInputAnim> Inputs;
		Inputs.Reserve(JsonArray.Num());

		for (const TSharedPtr<FJsonValue>& ItemValue : JsonArray)
		{
			if (!ItemValue.IsValid() || ItemValue->Type != EJson::Object)
			{
				continue;
			}
			const TSharedPtr<FJsonObject> Item = ItemValue->AsObject();
			if (!Item.IsValid())
			{
				continue;
			}

			FMLDeformerGeomCacheTrainingInputAnim Input;
			FString AnimPath;
			if (JsonFieldToString(Item, TEXT("anim_sequence"), AnimPath) && !AnimPath.IsEmpty())
			{
				if (UAnimSequence* Anim = LoadAssetByPath<UAnimSequence>(AnimPath))
				{
					Input.SetAnimSequence(Anim);
				}
				else
				{
					OutWarnings.Add(FString::Printf(TEXT("Missing anim_sequence asset: %s"), *AnimPath));
				}
			}

			FString GeomPath;
			if (JsonFieldToString(Item, TEXT("geometry_cache"), GeomPath) && !GeomPath.IsEmpty())
			{
				if (UGeometryCache* Geom = LoadAssetByPath<UGeometryCache>(GeomPath))
				{
					Input.SetGeometryCache(Geom);
				}
				else
				{
					OutWarnings.Add(FString::Printf(TEXT("Missing geometry_cache asset: %s"), *GeomPath));
				}
			}

			bool bEnabled = true;
			if (JsonFieldToBool(Item, TEXT("enabled"), bEnabled))
			{
				Input.SetEnabled(bEnabled);
			}

			bool bUseCustomRange = false;
			if (JsonFieldToBool(Item, TEXT("use_custom_range"), bUseCustomRange))
			{
				Input.SetUseCustomRange(bUseCustomRange);
			}

			int32 StartFrame = 0;
			if (JsonFieldToInt(Item, TEXT("start_frame"), StartFrame))
			{
				Input.SetStartFrame(StartFrame);
			}

			int32 EndFrame = 0;
			if (JsonFieldToInt(Item, TEXT("end_frame"), EndFrame))
			{
				Input.SetEndFrame(EndFrame);
			}

			Inputs.Add(MoveTemp(Input));
		}

		GeomModel->GetTrainingInputAnims() = MoveTemp(Inputs);
		return true;
	}

	bool ApplyNnmSections(UMLDeformerModel* Model, const FString& SectionsJson, TArray<FString>& OutWarnings, FString& OutError)
	{
		UNearestNeighborModel* NNM = Cast<UNearestNeighborModel>(Model);
		if (!NNM)
		{
			return true;
		}

		TArray<TSharedPtr<FJsonValue>> JsonArray;
		if (!ParseJsonArray(SectionsJson, JsonArray, OutError))
		{
			OutError = FString::Printf(TEXT("nnm_sections_json parse failed: %s"), *OutError);
			return false;
		}

		NNM->RemoveAllSections();
		for (int32 Index = 0; Index < JsonArray.Num(); ++Index)
		{
			const TSharedPtr<FJsonValue>& ItemValue = JsonArray[Index];
			if (!ItemValue.IsValid() || ItemValue->Type != EJson::Object)
			{
				continue;
			}
			const TSharedPtr<FJsonObject> Item = ItemValue->AsObject();
			if (!Item.IsValid())
			{
				continue;
			}

			UNearestNeighborModelSection* Section = NewObject<UNearestNeighborModelSection>(NNM);
			if (!Section)
			{
				OutWarnings.Add(FString::Printf(TEXT("NNM section %d creation failed"), Index));
				continue;
			}
			Section->SetModel(NNM);

			int32 MeshIndex = 0;
			JsonFieldToInt(Item, TEXT("mesh_index"), MeshIndex);
			Section->SetMeshIndex(MeshIndex);

			int32 NumBasis = 64;
			JsonFieldToInt(Item, TEXT("num_pca_coeffs"), NumBasis);
			Section->SetNumBasis(FMath::Max(1, NumBasis));

			FString VertexMapString;
			JsonFieldToString(Item, TEXT("vertex_map_string"), VertexMapString);
			if (VertexMapString.IsEmpty())
			{
				VertexMapString = InferVertexMapString(NNM, MeshIndex);
			}
			if (!VertexMapString.IsEmpty())
			{
				Section->SetVertexMapString(VertexMapString);
			}

			FString ExternalTxtFile;
			if (JsonFieldToString(Item, TEXT("external_txt_file"), ExternalTxtFile) && !ExternalTxtFile.IsEmpty())
			{
				Section->SetExternalTxtFile(ExternalTxtFile);
			}

			FString NeighborPosesPath;
			if (JsonFieldToString(Item, TEXT("neighbor_poses"), NeighborPosesPath) && !NeighborPosesPath.IsEmpty())
			{
				UAnimSequence* NeighborAnim = LoadAssetByPath<UAnimSequence>(NeighborPosesPath);
				if (!NeighborAnim || !SetObjectPropertyByName(Section, TEXT("NeighborPoses"), NeighborAnim))
				{
					OutWarnings.Add(FString::Printf(TEXT("NNM section %d neighbor_poses failed: %s"), Index, *NeighborPosesPath));
				}
			}

			FString NeighborMeshesPath;
			if (JsonFieldToString(Item, TEXT("neighbor_meshes"), NeighborMeshesPath) && !NeighborMeshesPath.IsEmpty())
			{
				UGeometryCache* NeighborGeom = LoadAssetByPath<UGeometryCache>(NeighborMeshesPath);
				if (!NeighborGeom || !SetObjectPropertyByName(Section, TEXT("NeighborMeshes"), NeighborGeom))
				{
					OutWarnings.Add(FString::Printf(TEXT("NNM section %d neighbor_meshes failed: %s"), Index, *NeighborMeshesPath));
				}
			}

			const TArray<int32> ExcludedFrames = JsonFieldToIntArray(Item, TEXT("excluded_frames"));
			if (!ExcludedFrames.IsEmpty() && !SetIntArrayPropertyByName(Section, TEXT("ExcludedFrames"), ExcludedFrames))
			{
				OutWarnings.Add(FString::Printf(TEXT("NNM section %d excluded_frames failed"), Index));
			}

			NNM->AddSection(Section);
		}

		NNM->InvalidateTraining();
		NNM->UpdateNetworkInputDim();
		NNM->UpdateNetworkOutputDim();
		return true;
	}

	bool ConfigureFromSetupRequest(UMLDeformerModel* Model, const FMldSetupRequest& Request, FMldSetupResult& OutResult)
	{
		if (!Model)
		{
			OutResult.message = TEXT("Model is null.");
			return false;
		}
		if (Request.skeletal_mesh.TrimStartAndEnd().IsEmpty())
		{
			OutResult.message = TEXT("skeletal_mesh is empty.");
			return false;
		}

		USkeletalMesh* SkeletalMesh = LoadAssetByPath<USkeletalMesh>(Request.skeletal_mesh);
		if (!SkeletalMesh)
		{
			OutResult.message = FString::Printf(TEXT("Failed to load skeletal mesh: %s"), *Request.skeletal_mesh);
			return false;
		}

		Model->SetSkeletalMesh(SkeletalMesh);
		Model->SetBoneIncludeList(BuildAllBoneReferences(SkeletalMesh));
		if (const FSkeletalMeshModel* ImportedModel = SkeletalMesh->GetImportedModel())
		{
			if (ImportedModel->LODModels.IsValidIndex(0))
			{
				Model->SetVertexMap(ImportedModel->LODModels[0].MeshToImportVertexMap);
			}
		}
		Model->UpdateCachedNumVertices();

		if (UMLDeformerVizSettings* VizSettings = Model->GetVizSettings())
		{
			if (!Request.deformer_graph.TrimStartAndEnd().IsEmpty())
			{
				if (UMeshDeformer* Graph = LoadAssetByPath<UMeshDeformer>(Request.deformer_graph))
				{
					VizSettings->SetDeformerGraph(Graph);
				}
				else
				{
					OutResult.warnings.Add(FString::Printf(TEXT("Missing deformer_graph: %s"), *Request.deformer_graph));
				}
			}

			if (!Request.test_anim_sequence.TrimStartAndEnd().IsEmpty())
			{
				if (UAnimSequence* TestAnim = LoadAssetByPath<UAnimSequence>(Request.test_anim_sequence))
				{
					VizSettings->SetTestAnimSequence(TestAnim);
				}
				else
				{
					OutResult.warnings.Add(FString::Printf(TEXT("Missing test_anim_sequence: %s"), *Request.test_anim_sequence));
				}
			}
		}

		FString Error;
		if (!ApplyTrainingInputs(Model, Request.training_input_anims_json, OutResult.warnings, Error))
		{
			OutResult.message = Error;
			return false;
		}
		if (!ApplyNnmSections(Model, Request.nnm_sections_json, OutResult.warnings, Error))
		{
			OutResult.message = Error;
			return false;
		}

		ApplyModelOverrides(Model, Request.model_overrides_json, OutResult.warnings);
		return true;
	}

	FString ObjectPathOrEmpty(const UObject* Object)
	{
		return Object ? Object->GetPathName() : FString();
	}

	FString SerializeJsonObject(const TSharedPtr<FJsonObject>& JsonObject)
	{
		if (!JsonObject.IsValid())
		{
			return TEXT("{}");
		}

		FString Out;
		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(JsonObject.ToSharedRef(), Writer);
		return Out;
	}

	FString SerializeJsonArray(const TArray<TSharedPtr<FJsonValue>>& JsonArray)
	{
		FString Out;
		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(JsonArray, Writer);
		return Out;
	}

	bool TryGetStringPropertyByName(const UObject* Target, const TCHAR* PropertyName, FString& OutValue)
	{
		if (!Target)
		{
			return false;
		}
		const FStrProperty* Property = FindFProperty<FStrProperty>(Target->GetClass(), PropertyName);
		if (!Property)
		{
			return false;
		}
		OutValue = Property->GetPropertyValue_InContainer(Target);
		return true;
	}

	FString BuildTrainingInputsJson(const UMLDeformerGeomCacheModel* GeomModel)
	{
		TArray<TSharedPtr<FJsonValue>> OutArray;
		if (!GeomModel)
		{
			return SerializeJsonArray(OutArray);
		}

		const TArray<FMLDeformerGeomCacheTrainingInputAnim>& Inputs = GeomModel->GetTrainingInputAnims();
		OutArray.Reserve(Inputs.Num());
		for (const FMLDeformerGeomCacheTrainingInputAnim& Input : Inputs)
		{
			const TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
			Row->SetStringField(TEXT("anim_sequence"), ObjectPathOrEmpty(Input.GetAnimSequence()));
			Row->SetStringField(TEXT("geometry_cache"), ObjectPathOrEmpty(Input.GetGeometryCache()));
			Row->SetBoolField(TEXT("enabled"), Input.IsEnabled());
			Row->SetBoolField(TEXT("use_custom_range"), Input.GetUseCustomRange());
			Row->SetNumberField(TEXT("start_frame"), Input.GetStartFrame());
			Row->SetNumberField(TEXT("end_frame"), Input.GetEndFrame());
			if (!Input.GetVertexMask().IsNone())
			{
				Row->SetStringField(TEXT("vertex_mask"), Input.GetVertexMask().ToString());
			}
			OutArray.Add(MakeShared<FJsonValueObject>(Row));
		}

		return SerializeJsonArray(OutArray);
	}

	FString BuildNnmSectionsJson(const UNearestNeighborModel* NNM)
	{
		TArray<TSharedPtr<FJsonValue>> OutArray;
		if (!NNM)
		{
			return SerializeJsonArray(OutArray);
		}

		const int32 NumSections = NNM->GetNumSections();
		OutArray.Reserve(NumSections);
		for (int32 SectionIndex = 0; SectionIndex < NumSections; ++SectionIndex)
		{
			const UNearestNeighborModelSection* Section = NNM->GetSectionPtr(SectionIndex);
			if (!Section)
			{
				continue;
			}

			const TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
			Row->SetNumberField(TEXT("mesh_index"), Section->GetMeshIndex());
			Row->SetNumberField(TEXT("num_pca_coeffs"), Section->GetNumBasis());
			Row->SetStringField(TEXT("neighbor_poses"), ObjectPathOrEmpty(Section->GetNeighborPoses()));
			Row->SetStringField(TEXT("neighbor_meshes"), ObjectPathOrEmpty(Section->GetNeighborMeshes()));

			FString VertexMapString;
			if (TryGetStringPropertyByName(Section, TEXT("VertexMapString"), VertexMapString) && !VertexMapString.IsEmpty())
			{
				Row->SetStringField(TEXT("vertex_map_string"), VertexMapString);
			}

			const FString ExternalTxt = Section->GetExternalTxtFile();
			if (!ExternalTxt.IsEmpty())
			{
				Row->SetStringField(TEXT("external_txt_file"), ExternalTxt);
			}

			TArray<TSharedPtr<FJsonValue>> ExcludedFrames;
			for (const int32 Frame : Section->GetExcludedFrames())
			{
				ExcludedFrames.Add(MakeShared<FJsonValueNumber>(Frame));
			}
			Row->SetArrayField(TEXT("excluded_frames"), ExcludedFrames);
			OutArray.Add(MakeShared<FJsonValueObject>(Row));
		}

		return SerializeJsonArray(OutArray);
	}

	FString BuildModelOverridesJson(const UMLDeformerModel* Model)
	{
		const TSharedPtr<FJsonObject> Overrides = MakeShared<FJsonObject>();
		if (!Model)
		{
			return SerializeJsonObject(Overrides);
		}

		if (const UNeuralMorphModel* NMM = Cast<UNeuralMorphModel>(Model))
		{
			const UEnum* ModeEnum = StaticEnum<ENeuralMorphMode>();
			const FString ModeName = ModeEnum ? ModeEnum->GetNameStringByValue(static_cast<int64>(NMM->GetModelMode())) : TEXT("Local");
			Overrides->SetStringField(TEXT("mode"), ModeName);
			Overrides->SetNumberField(TEXT("local_num_morph_targets_per_bone"), NMM->GetLocalNumMorphsPerBone());
			Overrides->SetNumberField(TEXT("global_num_morph_targets"), NMM->GetGlobalNumMorphs());
			Overrides->SetNumberField(TEXT("num_iterations"), NMM->GetNumIterations());
			Overrides->SetNumberField(TEXT("local_num_hidden_layers"), NMM->GetLocalNumHiddenLayers());
			Overrides->SetNumberField(TEXT("local_num_neurons_per_layer"), NMM->GetLocalNumNeuronsPerLayer());
			Overrides->SetNumberField(TEXT("global_num_hidden_layers"), NMM->GetGlobalNumHiddenLayers());
			Overrides->SetNumberField(TEXT("global_num_neurons_per_layer"), NMM->GetGlobalNumNeuronsPerLayer());
			Overrides->SetNumberField(TEXT("batch_size"), NMM->GetBatchSize());
			Overrides->SetNumberField(TEXT("learning_rate"), NMM->GetLearningRate());
			Overrides->SetNumberField(TEXT("regularization_factor"), NMM->GetRegularizationFactor());
			Overrides->SetNumberField(TEXT("smooth_loss_beta"), NMM->GetSmoothLossBeta());
			Overrides->SetBoolField(TEXT("b_enable_bone_masks"), NMM->IsBoneMaskingEnabled());
			return SerializeJsonObject(Overrides);
		}

		if (const UNearestNeighborModel* NNM = Cast<UNearestNeighborModel>(Model))
		{
			Overrides->SetBoolField(TEXT("b_use_pca"), NNM->DoesUsePCA());
			Overrides->SetNumberField(TEXT("num_basis_per_section"), NNM->GetNumBasisPerSection());
			Overrides->SetBoolField(TEXT("b_use_dual_quaternion_deltas"), NNM->DoesUseDualQuaternionDeltas());
			Overrides->SetNumberField(TEXT("decay_factor"), NNM->GetDecayFactor());
			Overrides->SetNumberField(TEXT("nearest_neighbor_offset_weight"), NNM->GetNearestNeighborOffsetWeight());
			Overrides->SetNumberField(TEXT("num_iterations"), NNM->GetNumIterations());
			Overrides->SetNumberField(TEXT("batch_size"), NNM->GetBatchSize());
			Overrides->SetNumberField(TEXT("learning_rate"), NNM->GetLearningRate());
			Overrides->SetNumberField(TEXT("early_stop_epochs"), NNM->GetEarlyStopEpochs());
			Overrides->SetNumberField(TEXT("regularization_factor"), NNM->GetRegularizationFactor());
			Overrides->SetNumberField(TEXT("smooth_loss_beta"), NNM->GetSmoothLossBeta());
			Overrides->SetBoolField(TEXT("b_use_rbf"), NNM->DoesUseRBF());
			Overrides->SetNumberField(TEXT("rbf_sigma"), NNM->GetRBFSigma());

			TArray<TSharedPtr<FJsonValue>> HiddenLayerDims;
			for (const int32 Dim : NNM->GetHiddenLayerDims())
			{
				HiddenLayerDims.Add(MakeShared<FJsonValueNumber>(Dim));
			}
			Overrides->SetArrayField(TEXT("hidden_layer_dims"), HiddenLayerDims);
			return SerializeJsonObject(Overrides);
		}

		return SerializeJsonObject(Overrides);
	}

	FString ResolveModelType(const UMLDeformerModel* Model)
	{
		if (Cast<UNeuralMorphModel>(Model))
		{
			return TEXT("NMM");
		}
		if (Cast<UNearestNeighborModel>(Model))
		{
			return TEXT("NNM");
		}
		return Model ? Model->GetClass()->GetName() : TEXT("");
	}
}

FMldTrainResult UMLDTrainAutomationLibrary::TrainDeformerAsset(const FMldTrainRequest& Request)
{
	FMldTrainResult Result;

	if (Request.asset_path.TrimStartAndEnd().IsEmpty())
	{
		Result.message = TEXT("AssetPath is empty.");
		return Result;
	}

	UMLDeformerAsset* DeformerAsset = nullptr;
	UE::MLDeformer::FMLDeformerEditorToolkit* Toolkit = nullptr;
	TUniquePtr<UE::MLDeformer::FMLDeformerScopedEditor> ScopedEditor;

	FString Message;
	if (!OpenEditorForAsset(Request.asset_path, DeformerAsset, Toolkit, ScopedEditor, Message))
	{
		Result.message = Message;
		UE_LOG(LogMLDTrainAutomation, Error, TEXT("%s"), *Message);
		return Result;
	}

	if (!EnsureModelTypeInternal(Toolkit, Request.model_type, Request.force_switch, Message))
	{
		Result.message = Message;
		UE_LOG(LogMLDTrainAutomation, Error, TEXT("%s"), *Message);
		return Result;
	}

	bool bNetworkLoaded = false;
	bool bSuccess = false;
	double DurationSec = 0.0;
	const ETrainingResult TrainingResult = TrainWithResult(
		Toolkit,
		Request.suppress_dialogs,
		DurationSec,
		bNetworkLoaded,
		bSuccess,
		Message);

	Result.success = bSuccess;
	Result.training_result_code = static_cast<int32>(TrainingResult);
	Result.duration_sec = DurationSec;
	Result.network_loaded = bNetworkLoaded;
	Result.message = Message;

	if (bSuccess && DeformerAsset)
	{
		DeformerAsset->Modify();
		DeformerAsset->MarkPackageDirty();
	}

	return Result;
}

bool UMLDTrainAutomationLibrary::EnsureModelType(const FString& AssetPath, const FString& ModelType, const bool bForceSwitch)
{
	if (AssetPath.TrimStartAndEnd().IsEmpty())
	{
		UE_LOG(LogMLDTrainAutomation, Error, TEXT("EnsureModelType failed: AssetPath is empty."));
		return false;
	}

	UMLDeformerAsset* DeformerAsset = nullptr;
	UE::MLDeformer::FMLDeformerEditorToolkit* Toolkit = nullptr;
	TUniquePtr<UE::MLDeformer::FMLDeformerScopedEditor> ScopedEditor;
	FString Message;

	if (!OpenEditorForAsset(AssetPath, DeformerAsset, Toolkit, ScopedEditor, Message))
	{
		UE_LOG(LogMLDTrainAutomation, Error, TEXT("EnsureModelType failed: %s"), *Message);
		return false;
	}

	const bool bOk = EnsureModelTypeInternal(Toolkit, ModelType, bForceSwitch, Message);
	if (!bOk)
	{
		UE_LOG(LogMLDTrainAutomation, Error, TEXT("EnsureModelType failed: %s"), *Message);
		return false;
	}

	if (DeformerAsset)
	{
		DeformerAsset->Modify();
		DeformerAsset->MarkPackageDirty();
	}

	return true;
}

FMldSetupResult UMLDTrainAutomationLibrary::SetupDeformerAsset(const FMldSetupRequest& Request)
{
	FMldSetupResult Result;

	if (Request.asset_path.TrimStartAndEnd().IsEmpty())
	{
		Result.message = TEXT("asset_path is empty.");
		return Result;
	}

	UMLDeformerAsset* DeformerAsset = nullptr;
	UE::MLDeformer::FMLDeformerEditorToolkit* Toolkit = nullptr;
	TUniquePtr<UE::MLDeformer::FMLDeformerScopedEditor> ScopedEditor;
	FString Message;

	if (!OpenEditorForAsset(Request.asset_path, DeformerAsset, Toolkit, ScopedEditor, Message))
	{
		Result.message = Message;
		return Result;
	}

	if (!EnsureModelTypeInternal(Toolkit, Request.model_type, Request.force_switch, Message))
	{
		Result.message = Message;
		return Result;
	}

	UE::MLDeformer::FMLDeformerEditorModel* ActiveModel = Toolkit ? Toolkit->GetActiveModel() : nullptr;
	if (!ActiveModel || !ActiveModel->GetModel())
	{
		Result.message = TEXT("No active model found after model switch.");
		return Result;
	}

	if (!ConfigureFromSetupRequest(ActiveModel->GetModel(), Request, Result))
	{
		return Result;
	}

	ActiveModel->TriggerInputAssetChanged(true);
	ActiveModel->UpdateIsReadyForTrainingState();

	if (DeformerAsset)
	{
		DeformerAsset->Modify();
		DeformerAsset->MarkPackageDirty();
	}

	Result.success = true;
	Result.message = TEXT("Setup completed.");
	return Result;
}

FMldDumpResult UMLDTrainAutomationLibrary::DumpDeformerSetup(const FMldDumpRequest& Request)
{
	FMldDumpResult Result;

	if (Request.asset_path.TrimStartAndEnd().IsEmpty())
	{
		Result.message = TEXT("asset_path is empty.");
		return Result;
	}

	UMLDeformerAsset* DeformerAsset = nullptr;
	UE::MLDeformer::FMLDeformerEditorToolkit* Toolkit = nullptr;
	TUniquePtr<UE::MLDeformer::FMLDeformerScopedEditor> ScopedEditor;
	FString Message;

	if (!OpenEditorForAsset(Request.asset_path, DeformerAsset, Toolkit, ScopedEditor, Message))
	{
		Result.message = Message;
		return Result;
	}

	UE::MLDeformer::FMLDeformerEditorModel* ActiveModel = Toolkit ? Toolkit->GetActiveModel() : nullptr;
	UMLDeformerModel* RuntimeModel = ActiveModel ? ActiveModel->GetModel() : nullptr;
	if (!RuntimeModel)
	{
		Result.message = TEXT("No active runtime model found.");
		return Result;
	}

	Result.model_type = ResolveModelType(RuntimeModel);
	Result.skeletal_mesh = ObjectPathOrEmpty(RuntimeModel->GetSkeletalMesh());

	if (const UMLDeformerVizSettings* VizSettings = RuntimeModel->GetVizSettings())
	{
		Result.deformer_graph = ObjectPathOrEmpty(VizSettings->GetDeformerGraph());
		Result.test_anim = ObjectPathOrEmpty(VizSettings->GetTestAnimSequence());
	}

	Result.training_input_anims_json = BuildTrainingInputsJson(Cast<UMLDeformerGeomCacheModel>(RuntimeModel));
	Result.nnm_sections_json = BuildNnmSectionsJson(Cast<UNearestNeighborModel>(RuntimeModel));
	Result.model_overrides_json = BuildModelOverridesJson(RuntimeModel);
	Result.success = true;
	Result.message = TEXT("Dump completed.");
	return Result;
}

IMPLEMENT_MODULE(FDefaultModuleImpl, MLDeformerSampleEditorTools)
