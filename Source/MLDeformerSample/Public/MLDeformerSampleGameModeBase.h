// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "MLDeformerAsset.h"
#include "MLDeformerSampleGameModeBase.generated.h"


UENUM()
enum class EMLDeformerSampleToInspect : uint8
{
	FleshDeformer UMETA(DisplayName = "Flesh"),
	ShirtDeformer UMETA(DisplayName = "Shirt"),
	PantsDeformer UMETA(DisplayName = "Pants"),
	All UMETA(DisplayName = "All"),
};

/**
 * Game mode that provides stats for an on screen HUD
 */
UCLASS()
class MLDEFORMERSAMPLE_API AMLDeformerSampleGameModeBase : public AGameModeBase
{
	GENERATED_BODY()
public: 
	virtual void BeginPlay() override;

	/** Get the total GPU MorphTarget time, which corresponds closely to the work done on the GPU for ML */
	UFUNCTION(BlueprintCallable, Category = "Timing")
	float GetGPUMorphTargetTimeMS() const;

	/** Get the total time of all inference steps in the MLDeformerComponent tick */
	UFUNCTION(BlueprintCallable, Category = "Timing")
	float GetMLInferenceTime() const;

	/** Get the memory on the CPU of all models in the MLDeformers array */
	UFUNCTION(BlueprintCallable, Category = "Timing")
	int64 GetMLRuntimeMemoryInBytes(EMLDeformerSampleToInspect InSample) const;
	
	/** Get the memory on the GPU of all models in the MLDeformers array */
	UFUNCTION(BlueprintCallable, Category = "Timing")
	int64 GetMLGPUMemoryInBytes(EMLDeformerSampleToInspect InSample) const;

	/** Returns true in a shipping build.  Please note that changing behaviour in this manner is not best practice */
	UFUNCTION(BlueprintCallable, Category = "BuildType")
	bool IsShippingBuild() const;
	/** The ML Deformer asset  for the flesh */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ML Models")
	TObjectPtr<UMLDeformerAsset> FleshDeformer;

	/** The ML Deformer asset for the shirt. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ML Models")
	TObjectPtr<UMLDeformerAsset> ShirtDeformer;

	/** The ML Deformer asset for the pants */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "ML Models")
	TObjectPtr<UMLDeformerAsset> PantsDeformer; 
private:
	void GetMatchingDeformers(EMLDeformerSampleToInspect InSample, TArray<UMLDeformerAsset*, TInlineAllocator<3>>& OutDeformers) const;
};
