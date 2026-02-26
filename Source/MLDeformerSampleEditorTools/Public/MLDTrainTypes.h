#pragma once

#include "CoreMinimal.h"
#include "MLDTrainTypes.generated.h"

USTRUCT(BlueprintType)
struct MLDEFORMERSAMPLEEDITORTOOLS_API FMldTrainRequest
{
	GENERATED_BODY()

	/** Package path to deformer asset, e.g. /Game/Characters/Emil/Deformers/MLD_NMMl_flesh_upperBody */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString asset_path;

	/** NMM | NNM | NeuralMorph | NearestNeighbor */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString model_type;

	/** Keep training non-interactive when running in batch mode. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool suppress_dialogs = true;

	/** Force model type switching without UI prompts. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool force_switch = true;
};

USTRUCT(BlueprintType)
struct MLDEFORMERSAMPLEEDITORTOOLS_API FMldTrainResult
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool success = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	int32 training_result_code = -1;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	double duration_sec = 0.0;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool network_loaded = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString message;
};

USTRUCT(BlueprintType)
struct MLDEFORMERSAMPLEEDITORTOOLS_API FMldSetupRequest
{
	GENERATED_BODY()

	/** Package path to deformer asset, e.g. /Game/Characters/Emil/Deformers/MLD_NMMl_flesh_upperBody */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString asset_path;

	/** NMM | NNM | NeuralMorph | NearestNeighbor */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString model_type;

	/** Skeletal mesh asset path */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString skeletal_mesh;

	/** Deformer graph asset path */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString deformer_graph;

	/** Test animation asset path */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString test_anim_sequence;

	/**
	 * JSON array of training input anim entries:
	 * [{anim_sequence, geometry_cache, enabled, use_custom_range, start_frame, end_frame}, ...]
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString training_input_anims_json;

	/** JSON object for model overrides. Keys are loosely matched against UPROPERTY names. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString model_overrides_json;

	/**
	 * JSON array for nearest-neighbor sections:
	 * [{neighbor_poses, neighbor_meshes, mesh_index, num_pca_coeffs, excluded_frames, vertex_map_string, external_txt_file}, ...]
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString nnm_sections_json;

	/** Force model type switching without UI prompts. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool force_switch = true;
};

USTRUCT(BlueprintType)
struct MLDEFORMERSAMPLEEDITORTOOLS_API FMldSetupResult
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool success = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString message;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	TArray<FString> warnings;
};

USTRUCT(BlueprintType)
struct MLDEFORMERSAMPLEEDITORTOOLS_API FMldDumpRequest
{
	GENERATED_BODY()

	/** Package path to deformer asset, e.g. /Game/Characters/Emil/Deformers/MLD_NMMl_flesh_upperBody */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString asset_path;
};

USTRUCT(BlueprintType)
struct MLDEFORMERSAMPLEEDITORTOOLS_API FMldDumpResult
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	bool success = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString message;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString model_type;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString skeletal_mesh;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString deformer_graph;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString test_anim;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString training_input_anims_json;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString nnm_sections_json;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MLDeformer")
	FString model_overrides_json;
};
