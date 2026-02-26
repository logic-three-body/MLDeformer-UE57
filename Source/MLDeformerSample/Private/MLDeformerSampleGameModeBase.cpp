// Copyright Epic Games, Inc. All Rights Reserved.


#include "MLDeformerSampleGameModeBase.h"
#include "Stats/StatsData.h"
#include "Kismet/GameplayStatics.h"
#include "Math/NumericLimits.h"
#include "MLDeformerModel.h"
#include "MLDeformerMorphModel.h"
#include "RHIResources.h"

static const FName GPUGroupName(TEXT("STATGROUP_GPU"));
static const FName MLDeformerGroupName(TEXT("STATGROUP_MLDeformer"));
static const FName MorphTargetStatName = TEXT("Stat_GPU_MorphTargets");
static const FName MLDeformerStatName = TEXT("STAT_MLDeformerInference");

void AMLDeformerSampleGameModeBase::BeginPlay()
{
	Super::BeginPlay();

#if STATS
	// To record stats we need to invoke console commands to start GPU and MLDeformer logging
	// Make sure to early out if the command has already been issued. 
	if (FGameThreadStatsData* StatsData = FLatestGameThreadStatsData::Get().Latest)
	{
		if (StatsData->GroupNames.Contains(GPUGroupName))
		{
			return;
		}
	}

	if (APlayerController* TargetPC = UGameplayStatics::GetPlayerController(this, 0))
	{
		TargetPC->ConsoleCommand(FString(TEXT("stat GPU -nodisplay")), /*bWriteToLog=*/false);
		TargetPC->ConsoleCommand(FString(TEXT("stat MLDeformer -nodisplay")), /*bWriteToLog=*/false);
	}
#endif
}

float AMLDeformerSampleGameModeBase::GetGPUMorphTargetTimeMS() const
{
#if STATS
	if (FGameThreadStatsData* StatsData = FLatestGameThreadStatsData::Get().Latest)
	{
		for (int32 GroupIndex = 0; GroupIndex < StatsData->ActiveStatGroups.Num(); ++GroupIndex)
		{
			const FActiveStatGroupInfo& StatGroup = StatsData->ActiveStatGroups[GroupIndex];
			if (StatsData->GroupNames[GroupIndex] == GPUGroupName)
			{
				for (const FComplexStatMessage& Counter : StatGroup.CountersAggregate)
				{
					// STATGROUP_GPU//STAT_GPU_MorphTargets//
					const FName ShortName = Counter.GetShortName();
					if (ShortName == MorphTargetStatName)
					{
						if (Counter.NameAndInfo.GetField<EStatDataType>() == EStatDataType::ST_double)
						{
							float fValue = Counter.GetValue_double(EComplexStatField::IncAve);
							return fValue; 
						}
						else if (Counter.NameAndInfo.GetField<EStatDataType>() == EStatDataType::ST_int64)
						{
							const uint64 AvgTotalTime = Counter.GetValue_int64(EComplexStatField::IncAve);
							return FPlatformTime::ToMilliseconds(AvgTotalTime);
						}
					}
				}
			}
		}
	}
#endif
	return 0.0f; 
}

float AMLDeformerSampleGameModeBase::GetMLInferenceTime() const
{
#if STATS
	if (FGameThreadStatsData* StatsData = FLatestGameThreadStatsData::Get().Latest)
	{
		if (const FComplexStatMessage* StatMessage = StatsData->GetStatData(MLDeformerStatName))
		{
			return FPlatformTime::ToMilliseconds(StatMessage->GetValue_Duration(EComplexStatField::IncAve));
		}
	}
#endif 
	return 0.0f;
}

int64 AMLDeformerSampleGameModeBase::GetMLRuntimeMemoryInBytes(EMLDeformerSampleToInspect InSample) const
{
	TArray<UMLDeformerAsset*, TInlineAllocator<3>> Deformers;
	GetMatchingDeformers(InSample, Deformers);
	int64 MemUsageInBytes = 0;
	for (const UMLDeformerAsset* MLDeformer : Deformers)
	{
		if (MLDeformer->GetModel())
		{
			MemUsageInBytes += MLDeformer->GetModel()->GetResourceSizeBytes(EResourceSizeMode::Type::Exclusive);
		}
	}
	return MemUsageInBytes;
}

int64 AMLDeformerSampleGameModeBase::GetMLGPUMemoryInBytes(EMLDeformerSampleToInspect InSample) const
{
	TArray<UMLDeformerAsset*, TInlineAllocator<3>> Deformers;
	GetMatchingDeformers(InSample, Deformers);
	int64 GPUMemUsageInBytes = 0;
	for (const UMLDeformerAsset* MLDeformer : Deformers)
	{
		if (MLDeformer->GetModel())
		{
			const UE::MLDeformer::FVertexMapBuffer& VertexMapBuffer = MLDeformer->GetModel()->GetVertexMapBuffer();
			if (VertexMapBuffer.VertexBufferRHI.IsValid())
			{
				GPUMemUsageInBytes += VertexMapBuffer.VertexBufferRHI->GetSize();
				const UMLDeformerMorphModel* MorphModel = Cast<UMLDeformerMorphModel>(MLDeformer->GetModel());
				if (MorphModel)
				{ 
					GPUMemUsageInBytes += MorphModel->GetCompressedMorphDataSizeInBytes(); 
				}
			}
		}
	}
	return GPUMemUsageInBytes;
}

bool AMLDeformerSampleGameModeBase::IsShippingBuild() const
{
#if UE_BUILD_SHIPPING
	return true; 
#endif 
	return false;
}

void AMLDeformerSampleGameModeBase::GetMatchingDeformers(EMLDeformerSampleToInspect InSample, TArray<UMLDeformerAsset*, TInlineAllocator<3>>& OutDeformers) const
{
	bool bAddAll = InSample == EMLDeformerSampleToInspect::All; 
	if (InSample == EMLDeformerSampleToInspect::FleshDeformer || bAddAll)
	{
		OutDeformers.Add(FleshDeformer);
	}
	if (InSample == EMLDeformerSampleToInspect::ShirtDeformer || bAddAll)
	{
		OutDeformers.Add(ShirtDeformer);
	}
	if (InSample == EMLDeformerSampleToInspect::PantsDeformer || bAddAll)
	{
		OutDeformers.Add(PantsDeformer);
	}
}

