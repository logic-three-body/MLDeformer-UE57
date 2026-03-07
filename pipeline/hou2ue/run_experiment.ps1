# run_experiment.ps1
# ──────────────────────────────────────────────────────────────────────────────
# Worktree experiment runner.
# Syncs the experiment branch's config into the UE57 runtime, then chains
# train → gt_source_capture → gt_compare → report.
#
# Usage (run from ANY directory):
#   & "D:\UE\Unreal Projects\MLDeformerSample\UE57\pipeline\hou2ue\workspace\run_experiment.ps1" `
#       -Exp V-2
#
# Or specify a custom worktree path:
#   & "...\run_experiment.ps1" -Exp custom -WorktreePath "D:\UE\my_wt"
#
# Experiment registry (auto-resolved from -Exp short name):
#   V-1  master    D:\UE\Unreal Projects\MLDeformerSample   (local=1)
#   V-2  experiment/V-2   D:\UE\WT_V2                       (local=2)
#   V-3  experiment/V-3   D:\UE\WT_V3                       (local=1, neurons=12, hidden=2)
#   V-4  experiment/V-4   D:\UE\WT_V4                       (LBS sanity)
# ──────────────────────────────────────────────────────────────────────────────
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("V-1","V-2","V-3","V-4","custom")]
    [string]$Exp,

    [string]$WorktreePath = ""   # required only when -Exp custom
)

$ErrorActionPreference = "Stop"

# ── Experiment → worktree path registry ──────────────────────────────────────
$registry = @{
    "V-1" = "D:\UE\Unreal Projects\MLDeformerSample"
    "V-2" = "D:\UE\WT_V2"
    "V-3" = "D:\UE\WT_V3"
    "V-4" = "D:\UE\WT_V4"
}

if ($Exp -eq "custom") {
    if (-not $WorktreePath) { throw "-WorktreePath is required when -Exp custom" }
    $wtRoot = $WorktreePath
} else {
    $wtRoot = $registry[$Exp]
}

# ── Paths ──────────────────────────────────────────────────────────────────────
$ue57Base    = "D:\UE\Unreal Projects\MLDeformerSample\UE57\pipeline\hou2ue"
$srcConfig   = "$wtRoot\pipeline\hou2ue\config\pipeline.full_exec.yaml"
$dstConfig   = "$ue57Base\config\pipeline.full_exec.yaml"
$timestamp   = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile     = "$ue57Base\workspace\exp_${Exp}_${timestamp}.log"
$runAllScript = "$ue57Base\run_all.ps1"

# ── Validate ───────────────────────────────────────────────────────────────────
if (-not (Test-Path $srcConfig)) { throw "Config not found: $srcConfig" }
if (-not (Test-Path $runAllScript)) { throw "run_all.ps1 not found: $runAllScript" }

"" | Set-Content $logFile

function Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content $logFile $line
}

Log "=== run_experiment.ps1 ==="
Log "Experiment : $Exp"
Log "Worktree   : $wtRoot"
Log "SrcConfig  : $srcConfig"
Log "DstConfig  : $dstConfig"
Log "Log        : $logFile"
Log ""

# ── Sync config from worktree into UE57 runtime ────────────────────────────────
Log "Syncing config $Exp → UE57..."
Copy-Item $srcConfig $dstConfig -Force
Log "Config synced OK."

# Show the model_overrides being applied
$morphLine = Select-String -Path $dstConfig -Pattern "local_num_morph|global_num_morph|local_num_neurons|skip_train|disable_ml_deformer_for_source" | Select-Object -First 8
Log "--- Applied overrides preview ---"
foreach ($l in $morphLine) { Log "  L$($l.LineNumber): $($l.Line.Trim())" }
Log ""

Push-Location $ue57Base

# ── Stage: train (skip if V-4 LBS sanity) ─────────────────────────────────────
$skipTrain = ($Exp -eq "V-4")
if (-not $skipTrain) {
    Log "=== Stage: train ==="
    & ".\run_all.ps1" -Stage train -Config $dstConfig -Profile smoke 2>&1 | Tee-Object -Append $logFile
    $trainExit = $LASTEXITCODE
    Log "train exit=$trainExit"
    if ($trainExit -ne 0) { Log "ERROR: train failed. Aborting."; Pop-Location; exit 1 }
} else {
    Log "=== Skipping train (LBS sanity experiment) ==="
}

# ── Stage: gt_source_capture ──────────────────────────────────────────────────
Log "=== Stage: gt_source_capture ==="
& ".\run_all.ps1" -Stage gt_source_capture -Config $dstConfig -Profile smoke 2>&1 | Tee-Object -Append $logFile
$captureExit = $LASTEXITCODE
Log "gt_source_capture exit=$captureExit"
if ($captureExit -ne 0) { Log "ERROR: capture failed. Aborting."; Pop-Location; exit 1 }

# ── Stage: gt_compare ─────────────────────────────────────────────────────────
Log "=== Stage: gt_compare ==="
& ".\run_all.ps1" -Stage gt_compare -Config $dstConfig -Profile smoke 2>&1 | Tee-Object -Append $logFile
$compareExit = $LASTEXITCODE
Log "gt_compare exit=$compareExit"

# ── Stage: report (always attempt) ────────────────────────────────────────────
$staleReport = "$ue57Base\workspace\latest\smoke\reports\report_report.json"
if (Test-Path $staleReport) { Remove-Item $staleReport -Force; Log "Removed stale report_report.json" }

Log "=== Stage: report ==="
& ".\run_all.ps1" -Stage report -Config $dstConfig -Profile smoke 2>&1 | Tee-Object -Append $logFile

Pop-Location

# ── Summary ───────────────────────────────────────────────────────────────────
$compareRpt = "$ue57Base\workspace\latest\smoke\reports\gt_compare_report.json"
if (Test-Path $compareRpt) {
    $rpt = Get-Content $compareRpt -Raw | ConvertFrom-Json
    $ssim  = $rpt.outputs.metrics.ssim_mean
    $psnr  = $rpt.outputs.metrics.psnr_mean
    $status = $rpt.status
    Log ""
    Log "=== RESULT: $Exp ==="
    Log "  status=$status  ssim=$ssim  psnr=$psnr"
    Log "  (thresholds: ssim>=0.83, psnr>=22.0)"
    if ($status -eq "success") {
        Log "  >>> PASS <<< Pipeline closure achieved for $Exp!"
    } else {
        Log "  >>> FAIL <<< ssim/psnr below threshold."
    }
}

Log "=== run_experiment.ps1 DONE. Log: $logFile ==="
