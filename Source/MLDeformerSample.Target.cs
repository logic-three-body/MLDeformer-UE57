// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;
using System.Collections.Generic;

public class MLDeformerSampleTarget : TargetRules
{
	public MLDeformerSampleTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V2;
		GlobalDefinitions.Add("FORCE_USE_STATS=1");
		GlobalDefinitions.Add("ALLOW_CONSOLE_IN_SHIPPING=1");
		bUseLoggingInShipping = true;
		bUseChecksInShipping = false;
		bOverrideBuildEnvironment = true;
		ExtraModuleNames.AddRange( new string[] { "MLDeformerSample" } );
	}
}
