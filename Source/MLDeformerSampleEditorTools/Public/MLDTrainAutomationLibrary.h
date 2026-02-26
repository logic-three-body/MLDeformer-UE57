#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MLDTrainTypes.h"
#include "MLDTrainAutomationLibrary.generated.h"

UCLASS()
class MLDEFORMERSAMPLEEDITORTOOLS_API UMLDTrainAutomationLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Open the ML Deformer asset editor, optionally switch model type, train, load trained network, and close editor.
	 */
	UFUNCTION(BlueprintCallable, Category = "MLDeformer|Automation")
	static FMldTrainResult TrainDeformerAsset(const FMldTrainRequest& Request);

	/**
	 * Ensure the target deformer asset has the requested model type set.
	 * Returns true if model type is already correct or switched successfully.
	 */
	UFUNCTION(BlueprintCallable, Category = "MLDeformer|Automation")
	static bool EnsureModelType(const FString& AssetPath, const FString& ModelType, bool bForceSwitch = true);

	/**
	 * Configure a deformer asset for automated training without relying on protected Python-only properties.
	 */
	UFUNCTION(BlueprintCallable, Category = "MLDeformer|Automation")
	static FMldSetupResult SetupDeformerAsset(const FMldSetupRequest& Request);

	/**
	 * Dump a deformer asset setup into JSON payloads for strict clone/repro checks.
	 */
	UFUNCTION(BlueprintCallable, Category = "MLDeformer|Automation")
	static FMldDumpResult DumpDeformerSetup(const FMldDumpRequest& Request);
};
