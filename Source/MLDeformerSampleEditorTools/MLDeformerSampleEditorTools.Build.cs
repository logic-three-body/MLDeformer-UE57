// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class MLDeformerSampleEditorTools : ModuleRules
{
	public MLDeformerSampleEditorTools(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
				"CoreUObject",
				"Engine"
			}
		);

		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"UnrealEd",
				"AssetTools",
				"GeometryCache",
				"Json",
				"JsonUtilities",
				"MLDeformerFramework",
				"MLDeformerFrameworkEditor",
				"NeuralMorphModel",
				"NearestNeighborModel",
				"Persona",
				"SkeletalMeshDescription",
				"Slate",
				"SlateCore"
			}
		);
	}
}
