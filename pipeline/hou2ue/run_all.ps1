param(
    [ValidateSet("baseline_sync", "preflight", "houdini", "convert", "ue_import", "ue_setup", "train", "infer", "gt_reference_capture", "gt_source_capture", "gt_compare", "report", "full")]
    [string]$Stage = "full",

    [ValidateSet("smoke", "full")]
    [string]$Profile = "smoke",

    [string]$Config = "pipeline/hou2ue/config/pipeline.yaml",

    [string]$OutRoot = "pipeline/hou2ue/workspace",

    [string]$RunDir = "",

    [int]$NoActivityMinutes = 30,

    [int]$RepeatedErrorThreshold = 6,

    [int]$HoudiniMaxMinutes = 120
)

$ErrorActionPreference = "Stop"

function Resolve-AbsolutePath([string]$PathValue, [string]$BaseDir) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BaseDir $PathValue))
}

function Assert-CommandOrPath([string]$ExeOrCmd, [string]$DisplayName) {
    if ([string]::IsNullOrWhiteSpace($ExeOrCmd)) {
        throw "$DisplayName is not configured."
    }

    if (Test-Path $ExeOrCmd) {
        return
    }

    $cmd = Get-Command $ExeOrCmd -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "$DisplayName not found: $ExeOrCmd"
    }
}

function Get-StageTimeoutMinutes([string]$StageName) {
    switch ($StageName) {
        "reference_setup_dump" { return 180 }
        "baseline_sync" { return 360 }
        "preflight" { return 30 }
        "houdini" { return $HoudiniMaxMinutes }
        "convert" { return 90 }
        "ue_import" { return 90 }
        "ue_setup" { return 60 }
        "train" { return 240 }
        "infer" { return 240 }
        "gt_reference_capture" { return 240 }
        "gt_source_capture" { return 720 }
        "gt_compare" { return 60 }
        "report" { return 30 }
        default { return 120 }
    }
}

function Get-LogTail([string]$Path, [int]$TailLines = 40) {
    if (-not (Test-Path $Path)) {
        return ""
    }
    try {
        return (Get-Content -LiteralPath $Path -Tail $TailLines -ErrorAction SilentlyContinue) -join "`n"
    }
    catch {
        return ""
    }
}

function Convert-ToQuotedArgs([string[]]$InputArgs) {
    $encoded = @()
    foreach ($arg in $InputArgs) {
        if ($null -eq $arg) {
            $encoded += '""'
            continue
        }

        $value = [string]$arg
        if ($value -eq "") {
            $encoded += '""'
            continue
        }

        if ($value -match '[\s"]') {
            $escaped = $value.Replace('"', '\"')
            $encoded += '"' + $escaped + '"'
        }
        else {
            $encoded += $value
        }
    }

    return $encoded
}

function Get-RepeatedErrorLine([string]$Path, [int]$Threshold) {
    if (-not (Test-Path $Path)) {
        return $null
    }

    try {
        $lines = Get-Content -LiteralPath $Path -Tail 400 -ErrorAction SilentlyContinue |
            ForEach-Object { $_.Trim() } |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_) -and
                $_ -match "(?i)(error|exception|traceback|fatal|failed|assert)"
            }

        if (-not $lines -or $lines.Count -eq 0) {
            return $null
        }

        $top = $lines | Group-Object | Sort-Object Count -Descending | Select-Object -First 1
        if ($null -ne $top -and [int]$top.Count -ge $Threshold) {
            return [string]$top.Name
        }
    }
    catch {
        return $null
    }

    return $null
}

function Get-ProcessIdMapByName([string[]]$Names) {
    $map = @{}
    if ($null -eq $Names -or $Names.Count -eq 0) {
        return $map
    }

    $procs = Get-Process -Name $Names -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $map[[string]$p.Id] = $true
    }
    return $map
}

function Stop-NewProcessesByName([string[]]$Names, [hashtable]$BaselineIdMap) {
    if ($null -eq $Names -or $Names.Count -eq 0) {
        return
    }
    if ($null -eq $BaselineIdMap) {
        $BaselineIdMap = @{}
    }

    $procs = Get-Process -Name $Names -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $key = [string]$p.Id
        if (-not $BaselineIdMap.ContainsKey($key)) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

function Invoke-GuardedProcess(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$StageName,
    [string]$Label,
    [switch]$UseRawArgumentList
) {
    $timeoutMinutes = Get-StageTimeoutMinutes $StageName
    $reportsDir = Join-Path $ResolvedRunDir "reports"
    New-Item -ItemType Directory -Path $reportsDir -Force | Out-Null

    $safeLabel = ($Label -replace "[^a-zA-Z0-9_-]", "_")
    $stdoutPath = Join-Path $reportsDir ("guard_{0}.stdout.log" -f $safeLabel)
    $stderrPath = Join-Path $reportsDir ("guard_{0}.stderr.log" -f $safeLabel)
    Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue

    $cleanupNames = @()
    if ($StageName -in @("preflight", "houdini", "convert")) {
        $cleanupNames = @("hython", "hbatch")
    }
    $baselineIds = Get-ProcessIdMapByName -Names $cleanupNames

    if ($UseRawArgumentList) {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    }
    else {
        $quotedArgs = Convert-ToQuotedArgs -InputArgs $ArgumentList
        # -NoNewWindow keeps the child attached to the current console so console
        # applications (e.g. Anaconda python.exe) can initialise their console
        # handles without hanging on Windows.
        $proc = Start-Process -FilePath $FilePath -ArgumentList $quotedArgs -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    }
    if ($null -eq $proc) {
        throw "Failed to start process: $FilePath $($ArgumentList -join ' ')"
    }

    $startAt = Get-Date
    $lastActivityAt = $startAt
    $lastCpu = [double]$proc.CPU
    $lastStdLen = 0L
    $lastErrLen = 0L

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 10
        $proc.Refresh()

        $cpuNow = [double]$proc.CPU
        if ($cpuNow -gt ($lastCpu + 0.01)) {
            $lastActivityAt = Get-Date
            $lastCpu = $cpuNow
        }

        $stdLen = if (Test-Path $stdoutPath) { (Get-Item -LiteralPath $stdoutPath).Length } else { 0L }
        $errLen = if (Test-Path $stderrPath) { (Get-Item -LiteralPath $stderrPath).Length } else { 0L }
        if ($stdLen -ne $lastStdLen -or $errLen -ne $lastErrLen) {
            $lastActivityAt = Get-Date
            $lastStdLen = $stdLen
            $lastErrLen = $errLen
        }

        $repeatLine = Get-RepeatedErrorLine -Path $stderrPath -Threshold $RepeatedErrorThreshold
        if (-not [string]::IsNullOrWhiteSpace($repeatLine)) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
            Stop-NewProcessesByName -Names $cleanupNames -BaselineIdMap $baselineIds
            throw "Repeated error detected in stage '$StageName': $repeatLine"
        }

        $elapsedMinutes = ((Get-Date) - $startAt).TotalMinutes
        if ($elapsedMinutes -gt $timeoutMinutes) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
            Stop-NewProcessesByName -Names $cleanupNames -BaselineIdMap $baselineIds
            $errTail = Get-LogTail -Path $stderrPath -TailLines 60
            throw "Stage '$StageName' timeout (${timeoutMinutes}m). stderr tail:`n$errTail"
        }

        $idleMinutes = ((Get-Date) - $lastActivityAt).TotalMinutes
        if ($idleMinutes -gt $NoActivityMinutes) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
            Stop-NewProcessesByName -Names $cleanupNames -BaselineIdMap $baselineIds
            $stdTail = Get-LogTail -Path $stdoutPath -TailLines 40
            $errTail = Get-LogTail -Path $stderrPath -TailLines 40
            throw "No activity detected for ${NoActivityMinutes}m in stage '$StageName'. stdout tail:`n$stdTail`n----`nstderr tail:`n$errTail"
        }
    }

    $exitCode = $proc.ExitCode
    if ($exitCode -ne 0) {
        Stop-NewProcessesByName -Names $cleanupNames -BaselineIdMap $baselineIds
    }
    return @{
        exit_code = $exitCode
        stdout_path = $stdoutPath
        stderr_path = $stderrPath
        stdout_tail = Get-LogTail -Path $stdoutPath -TailLines 40
        stderr_tail = Get-LogTail -Path $stderrPath -TailLines 40
    }
}

function Invoke-PythonScript(
    [string]$Interpreter,
    [string]$ScriptPath,
    [string[]]$ExtraArgs = @(),
    [string]$StageName = ""
) {
    $argsList = @(
        $ScriptPath,
        "--config", $ResolvedConfigPath,
        "--profile", $Profile,
        "--run-dir", $ResolvedRunDir
    ) + $ExtraArgs

    if ([string]::IsNullOrWhiteSpace($StageName)) {
        $StageName = [System.IO.Path]::GetFileNameWithoutExtension($ScriptPath)
    }
    $label = [System.IO.Path]::GetFileNameWithoutExtension($ScriptPath)
    $result = Invoke-GuardedProcess -FilePath $Interpreter -ArgumentList $argsList -StageName $StageName -Label $label
    if ([int]$result.exit_code -ne 0) {
        throw "Script failed: $ScriptPath (exit code $($result.exit_code))`nstderr tail:`n$($result.stderr_tail)"
    }
    $scriptFile = [System.IO.Path]::GetFileName($ScriptPath)
    $reportStage = switch ($scriptFile) {
        "dump_reference_setup.py" { "reference_setup_dump" }
        "sync_reference_baseline.py" { "baseline_sync" }
        "parse_hip.py" { "preflight" }
        "houdini_cook.py" { "houdini" }
        "houdini_export_abc.py" { "convert" }
        "ue_capture_mainseq.py" { $StageName }
        "compare_groundtruth.py" { "gt_compare" }
        "build_report.py" { "report" }
        default { "" }
    }

    if (-not [string]::IsNullOrWhiteSpace($reportStage)) {
        $reportPath = Join-Path (Join-Path $ResolvedRunDir "reports") ("{0}_report.json" -f $reportStage)
        if (Test-Path $reportPath) {
            try {
                $reportObj = (Get-Content -Raw $reportPath) | ConvertFrom-Json
                if ($null -eq $reportObj -or [string]$reportObj.status -ne "success") {
                    throw "Stage report indicates failure: $reportPath"
                }
                return
            }
            catch {
                throw "Failed to validate stage report for ${scriptFile}: $($_.Exception.Message)"
            }
        }
    }

    if ([string]$result.stderr_tail -match "(?i)(can't open file|traceback|fatal|exception)") {
        throw "Detected fatal stderr while running ${scriptFile}:`n$($result.stderr_tail)"
    }
}

function Invoke-UnrealPythonScript(
    [string]$ScriptPath,
    [hashtable]$EnvOverrides = @{},
    [string[]]$ExtraUEArgs = @()
) {
    $oldConfig = $env:HOU2UE_CONFIG
    $oldProfile = $env:HOU2UE_PROFILE
    $oldRunDir = $env:HOU2UE_RUN_DIR
    $oldOutRoot = $env:HOU2UE_OUT_ROOT
    $overrideBackup = @{}

    try {
        $env:HOU2UE_CONFIG = $ResolvedConfigPath
        $env:HOU2UE_PROFILE = $Profile
        $env:HOU2UE_RUN_DIR = $ResolvedRunDir
        $env:HOU2UE_OUT_ROOT = $ResolvedOutRoot

        foreach ($key in $EnvOverrides.Keys) {
            $overrideBackup[$key] = [System.Environment]::GetEnvironmentVariable($key, "Process")
            $value = [string]$EnvOverrides[$key]
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
        }

        $scriptArgPath = $ScriptPath -replace "\\", "/"
        $executeArg = "-ExecutePythonScript=`"$scriptArgPath`""
        $argList = @(
            "`"$ResolvedUProjectPath`"",
            $executeArg,
            "-unattended",
            "-nop4",
            "-nosplash",
            "-NoSound",
            "-stdout",
            "-FullStdOutLogOutput"
        ) + $ExtraUEArgs

        $scriptFile = [System.IO.Path]::GetFileName($ScriptPath)
        $reportStage = switch ($scriptFile) {
            "ue_import.py" { "ue_import" }
            "ue_setup_assets.py" { "ue_setup" }
            "ue_train.py" { "train" }
            "ue_infer.py" { "infer" }
            default { "ue_stage" }
        }
        $reportPath = if (-not [string]::IsNullOrWhiteSpace($reportStage)) {
            Join-Path (Join-Path $ResolvedRunDir "reports") ("{0}_report.json" -f $reportStage)
        } else {
            ""
        }
        $reportMtimeBefore = $null
        if (-not [string]::IsNullOrWhiteSpace($reportPath) -and (Test-Path $reportPath)) {
            $reportMtimeBefore = (Get-Item -LiteralPath $reportPath).LastWriteTimeUtc
        }

        $proc = Start-Process -FilePath $ResolvedUEEditorExe -ArgumentList $argList -Wait -PassThru
        $reportFresh = $false
        if (-not [string]::IsNullOrWhiteSpace($reportPath) -and (Test-Path $reportPath)) {
            $reportMtimeAfter = (Get-Item -LiteralPath $reportPath).LastWriteTimeUtc
            if ($null -eq $reportMtimeBefore) {
                $reportFresh = $true
            }
            elseif ($reportMtimeAfter -gt $reportMtimeBefore) {
                $reportFresh = $true
            }
        }
        if ($null -eq $proc -or $proc.ExitCode -ne 0) {
            $code = if ($null -eq $proc) { -1 } else { [int]$proc.ExitCode }
            if (-not [string]::IsNullOrWhiteSpace($reportStage)) {
                if (Test-Path $reportPath) {
                    try {
                        $reportObj = (Get-Content -Raw $reportPath) | ConvertFrom-Json
                        if ($null -ne $reportObj -and [string]$reportObj.status -eq "success" -and $reportFresh) {
                            Write-Warning "UnrealEditor returned exit code $code for $scriptFile, but report status is success. Continuing."
                            return
                        }
                    }
                    catch {
                        # Keep throwing below if report cannot be parsed.
                    }
                }
            }

            throw "Unreal Python stage failed: $ScriptPath (exit code $code)"
        }

        if (-not [string]::IsNullOrWhiteSpace($reportStage)) {
            if (-not (Test-Path $reportPath)) {
                throw "Missing stage report after Unreal Python stage: $reportPath"
            }
            if (-not $reportFresh) {
                throw "Stage report is stale or unchanged after Unreal Python stage: $reportPath"
            }

            try {
                $reportObj = (Get-Content -Raw $reportPath) | ConvertFrom-Json
                if ($null -eq $reportObj -or [string]$reportObj.status -ne "success") {
                    throw "Stage report indicates failure: $reportPath"
                }
            }
            catch {
                throw "Failed to validate Unreal stage report for ${scriptFile}: $($_.Exception.Message)"
            }
        }
    }
    finally {
        $env:HOU2UE_CONFIG = $oldConfig
        $env:HOU2UE_PROFILE = $oldProfile
        $env:HOU2UE_RUN_DIR = $oldRunDir
        $env:HOU2UE_OUT_ROOT = $oldOutRoot
        foreach ($key in $overrideBackup.Keys) {
            [System.Environment]::SetEnvironmentVariable($key, $overrideBackup[$key], "Process")
        }
    }
}

$ScriptRoot = $PSScriptRoot
$ProjectRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
$ResolvedConfigPath = Resolve-AbsolutePath $Config $ProjectRoot
$ResolvedOutRoot = Resolve-AbsolutePath $OutRoot $ProjectRoot

if (-not (Test-Path $ResolvedConfigPath)) {
    throw "Config not found: $ResolvedConfigPath"
}

New-Item -ItemType Directory -Path $ResolvedOutRoot -Force | Out-Null

$configText = Get-Content -Raw $ResolvedConfigPath
try {
    $ConfigObj = $configText | ConvertFrom-Json
}
catch {
    throw "Config must be JSON-compatible YAML. Failed to parse with ConvertFrom-Json: $ResolvedConfigPath"
}

$ResolvedPythonExe = [string]$ConfigObj.paths.python_exe
$ResolvedHythonExe = [string]$ConfigObj.paths.houdini.hython_exe
$ResolvedUEEditorExe = [string]$ConfigObj.paths.ue_editor_exe
$ResolvedUProjectPath = Resolve-AbsolutePath ([string]$ConfigObj.paths.uproject) $ProjectRoot
$ResolvedHipPath = Resolve-AbsolutePath ([string]$ConfigObj.paths.hip_file) $ProjectRoot

if (-not (Test-Path $ResolvedUProjectPath)) {
    throw "uproject not found: $ResolvedUProjectPath"
}
if (-not (Test-Path $ResolvedHipPath)) {
    throw "HIP file not found: $ResolvedHipPath"
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LatestProfileDir = Join-Path (Join-Path $ResolvedOutRoot "latest") $Profile

if (-not [string]::IsNullOrWhiteSpace($RunDir)) {
    $ResolvedRunDir = Resolve-AbsolutePath $RunDir $ProjectRoot
}
elseif ($Stage -in @("baseline_sync", "preflight", "houdini", "full")) {
    $ResolvedRunDir = Join-Path (Join-Path $ResolvedOutRoot "runs") ("{0}_{1}" -f $timestamp, $Profile)
}
elseif (Test-Path $LatestProfileDir) {
    $ResolvedRunDir = [System.IO.Path]::GetFullPath($LatestProfileDir)
}
else {
    throw "No existing run directory for stage '$Stage'. Run preflight/houdini/full first, or pass -RunDir explicitly."
}

New-Item -ItemType Directory -Path $ResolvedRunDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ResolvedRunDir "reports") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ResolvedRunDir "manifests") -Force | Out-Null

Copy-Item -LiteralPath $ResolvedConfigPath -Destination (Join-Path $ResolvedRunDir "pipeline_config.input.yaml") -Force

$RunInfo = @{
    stage = $Stage
    profile = $Profile
    config = $ResolvedConfigPath
    out_root = $ResolvedOutRoot
    run_dir = $ResolvedRunDir
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json -Depth 10
$RunInfo | Set-Content -Encoding UTF8 (Join-Path $ResolvedRunDir "run_info.json")

$ScriptsDir = Join-Path $ScriptRoot "scripts"
$parseHipScript = Join-Path $ScriptsDir "parse_hip.py"
$houdiniCookScript = Join-Path $ScriptsDir "houdini_cook.py"
$houdiniExportScript = Join-Path $ScriptsDir "houdini_export_abc.py"
$ueImportScript = Join-Path $ScriptsDir "ue_import.py"
$ueSetupScript = Join-Path $ScriptsDir "ue_setup_assets.py"
$ueTrainScript = Join-Path $ScriptsDir "ue_train.py"
$ueInferScript = Join-Path $ScriptsDir "ue_infer.py"
$baselineSyncScript = Join-Path $ScriptsDir "sync_reference_baseline.py"
$dumpReferenceSetupScript = Join-Path $ScriptsDir "dump_reference_setup.py"
$ueCaptureMainSeqScript = Join-Path $ScriptsDir "ue_capture_mainseq.py"
$gtCompareScript = Join-Path $ScriptsDir "compare_groundtruth.py"
$buildReportScript = Join-Path $ScriptsDir "build_report.py"

function Assert-Preflight {
    Assert-CommandOrPath $ResolvedHythonExe "Houdini hython"
    if (-not (Test-Path $ResolvedHipPath)) {
        throw "HIP file not found: $ResolvedHipPath"
    }
}

function Assert-HoudiniForConvert {
    Assert-CommandOrPath $ResolvedHythonExe "Houdini hython"
}

function Assert-UE {
    Assert-CommandOrPath $ResolvedUEEditorExe "UnrealEditor"
}

function Assert-Python {
    Assert-CommandOrPath $ResolvedPythonExe "Python"
}

function Run-Stage([string]$StageName) {
    switch ($StageName) {
        "baseline_sync" {
            Assert-Python
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $baselineSyncScript -StageName "baseline_sync"
        }
        "preflight" {
            Assert-Preflight
            Invoke-PythonScript -Interpreter $ResolvedHythonExe -ScriptPath $parseHipScript -StageName "preflight"
        }
        "houdini" {
            Assert-Preflight
            Invoke-PythonScript -Interpreter $ResolvedHythonExe -ScriptPath $houdiniCookScript -StageName "houdini"
        }
        "convert" {
            Assert-Python
            Assert-HoudiniForConvert
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $houdiniExportScript -StageName "convert"
        }
        "ue_import" {
            Assert-UE
            Invoke-UnrealPythonScript -ScriptPath $ueImportScript
        }
        "ue_setup" {
            Assert-Python
            Assert-UE
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $dumpReferenceSetupScript -StageName "reference_setup_dump"

            $skipTrain = $false
            if ($null -ne $ConfigObj.ue -and $null -ne $ConfigObj.ue.training -and $null -ne $ConfigObj.ue.training.skip_train) {
                $skipTrain = [bool]$ConfigObj.ue.training.skip_train
            }

            if ($skipTrain) {
                Write-Host "[hou2ue] skip_train=true: Skipping ue_setup to preserve reference deformer weights."
                $setupReport = @{
                    stage = "ue_setup"
                    profile = $Profile
                    status = "success"
                    started_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    ended_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    inputs = @{ config = $ResolvedConfigPath; profile = $Profile; run_dir = $ResolvedRunDir }
                    outputs = @{
                        skipped = $true
                        reason = "skip_train enabled - preserving reference deformer weights from baseline_sync"
                    }
                    errors = @()
                } | ConvertTo-Json -Depth 10
                $setupReport | Set-Content -Encoding UTF8 (Join-Path (Join-Path $ResolvedRunDir "reports") "ue_setup_report.json")
            }
            else {
                Invoke-UnrealPythonScript -ScriptPath $ueSetupScript -ExtraUEArgs @("-nullrhi")
            }
        }
        "train" {
            $skipTrain = $false
            if ($null -ne $ConfigObj.ue -and $null -ne $ConfigObj.ue.training -and $null -ne $ConfigObj.ue.training.skip_train) {
                $skipTrain = [bool]$ConfigObj.ue.training.skip_train
            }

            if ($skipTrain) {
                # UE57 compat: when reference_baseline.enabled=false, the UE project carries its
                # own native deformer weights — no reference copy is needed or possible.
                $baselineEnabled = $true
                if ($null -ne $ConfigObj.reference_baseline -and $null -ne $ConfigObj.reference_baseline.enabled) {
                    $baselineEnabled = [bool]$ConfigObj.reference_baseline.enabled
                }

                $copyResults = @()
                $refRoot = ""
                if ($baselineEnabled) {
                    Write-Host "[hou2ue] skip_train=true: Re-syncing reference deformer uassets instead of retraining."
                    $refUProject = [string]$ConfigObj.reference_baseline.reference_uproject
                    $refRootPath = Resolve-AbsolutePath (Split-Path $refUProject -Parent) $ProjectRoot
                    $refRoot = $refRootPath

                    # Resolve destination: prefer paths.ue_project_root when set (UE57 hub layout
                    # where $ProjectRoot is the hub dir, not the UE project dir).
                    $ueProjectRoot = $ProjectRoot
                    if ($null -ne $ConfigObj.paths -and -not [string]::IsNullOrWhiteSpace([string]$ConfigObj.paths.ue_project_root)) {
                        $ueProjectRoot = Resolve-AbsolutePath ([string]$ConfigObj.paths.ue_project_root) $ProjectRoot
                    }

                    $deformerFiles = @(
                        "Content/Characters/Emil/Deformers/MLD_NMMl_flesh_upperBody.uasset",
                        "Content/Characters/Emil/Deformers/MLD_NN_upperCostume.uasset",
                        "Content/Characters/Emil/Deformers/MLD_NN_lowerCostume.uasset"
                    )
                    foreach ($rel in $deformerFiles) {
                        $src = Join-Path $refRootPath $rel
                        $dst = Join-Path $ueProjectRoot $rel
                        if (Test-Path $src) {
                            Copy-Item -LiteralPath $src -Destination $dst -Force
                            $srcHash = (Get-FileHash -Path $src -Algorithm SHA256).Hash
                            $dstHash = (Get-FileHash -Path $dst -Algorithm SHA256).Hash
                            $copyResults += @{
                                file = $rel
                                copied = $true
                                sha256_match = ($srcHash -eq $dstHash)
                                sha256 = $srcHash
                            }
                            Write-Host "  Copied: $rel (SHA256=$srcHash match=$($srcHash -eq $dstHash))"
                        }
                        else {
                            $copyResults += @{ file = $rel; copied = $false; error = "Source not found: $src" }
                            Write-Warning "  Missing reference deformer: $src"
                        }
                    }
                }
                else {
                    Write-Host "[hou2ue] skip_train=true + reference_baseline.enabled=false: UE project uses native deformer weights; skipping reference copy."
                }

                $trainReport = @{
                    stage = "train"
                    profile = $Profile
                    status = "success"
                    started_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    ended_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    inputs = @{ config = $ResolvedConfigPath; profile = $Profile; run_dir = $ResolvedRunDir }
                    outputs = @{
                        skipped = $true
                        reason = if ($baselineEnabled) { "skip_train enabled - using reference deformer weights directly" } else { "skip_train enabled - reference_baseline disabled; UE project uses native weights" }
                        reference_root = $refRoot
                        deformer_copies = $copyResults
                    }
                    errors = @()
                } | ConvertTo-Json -Depth 10
                $trainReport | Set-Content -Encoding UTF8 (Join-Path (Join-Path $ResolvedRunDir "reports") "train_report.json")
                Write-Host "[hou2ue] skip_train: Synthetic train_report.json written."
            }
            else {
                Assert-UE
                $detCfg = $null
                if ($null -ne $ConfigObj -and $null -ne $ConfigObj.ue -and $null -ne $ConfigObj.ue.training) {
                    $detCfg = $ConfigObj.ue.training.determinism
                }

                $seed = 3407
                $enabled = $false
                $torchDeterministic = $true
                $cudnnDeterministic = $true
                $cudnnBenchmark = $false

                if ($null -ne $detCfg) {
                    if ($null -ne $detCfg.seed) { $seed = [int]$detCfg.seed }
                    if ($null -ne $detCfg.enabled) { $enabled = [bool]$detCfg.enabled }
                    if ($null -ne $detCfg.torch_deterministic) { $torchDeterministic = [bool]$detCfg.torch_deterministic }
                    if ($null -ne $detCfg.cudnn_deterministic) { $cudnnDeterministic = [bool]$detCfg.cudnn_deterministic }
                    if ($null -ne $detCfg.cudnn_benchmark) { $cudnnBenchmark = [bool]$detCfg.cudnn_benchmark }
                }

                $envOverrides = @{
                    "HOU2UE_TRAIN_DETERMINISM_ENABLED" = $(if ($enabled) { "1" } else { "0" })
                    "HOU2UE_TRAIN_SEED" = [string]$seed
                    "HOU2UE_TORCH_DETERMINISTIC" = $(if ($torchDeterministic) { "1" } else { "0" })
                    "HOU2UE_CUDNN_DETERMINISTIC" = $(if ($cudnnDeterministic) { "1" } else { "0" })
                    "HOU2UE_CUDNN_BENCHMARK" = $(if ($cudnnBenchmark) { "1" } else { "0" })
                }
                Invoke-UnrealPythonScript -ScriptPath $ueTrainScript -EnvOverrides $envOverrides -ExtraUEArgs @("-nullrhi")
            }
        }
        "infer" {
            Assert-UE
            Invoke-UnrealPythonScript -ScriptPath $ueInferScript
        }
        "gt_reference_capture" {
            Assert-UE
            Assert-Python
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $ueCaptureMainSeqScript -StageName "gt_reference_capture" -ExtraArgs @("--capture-kind", "reference")
        }
        "gt_source_capture" {
            Assert-UE
            Assert-Python
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $ueCaptureMainSeqScript -StageName "gt_source_capture" -ExtraArgs @("--capture-kind", "source")
        }
        "gt_compare" {
            Assert-Python
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $gtCompareScript -StageName "gt_compare"
        }
        "report" {
            Assert-Python
            Invoke-PythonScript -Interpreter $ResolvedPythonExe -ScriptPath $buildReportScript -StageName "report" -ExtraArgs @("--out-root", $ResolvedOutRoot)
        }
        default {
            throw "Unknown stage: $StageName"
        }
    }
}

if ($Stage -eq "full") {
    # Determine if skip_train is enabled to decide stage ordering
    $fullSkipTrain = $false
    if ($null -ne $ConfigObj.ue -and $null -ne $ConfigObj.ue.training -and $null -ne $ConfigObj.ue.training.skip_train) {
        $fullSkipTrain = [bool]$ConfigObj.ue.training.skip_train
    }

    if ($fullSkipTrain) {
        # skip_train shortcut: stages 2-5 (preflight/houdini/convert/ue_import) produce GeomCache
        # that is never consumed when training is skipped. Jump straight to inference path.
        $ordered = @("baseline_sync", "ue_setup", "train", "infer", "gt_reference_capture", "gt_source_capture", "gt_compare", "report")
        Write-Host "[hou2ue] skip_train shortcut: skipping preflight/houdini/convert/ue_import (GeomCache unused)"
    }
    else {
        $ordered = @("baseline_sync", "preflight", "houdini", "convert", "ue_import", "ue_setup", "train", "infer", "gt_reference_capture", "gt_source_capture", "gt_compare", "report")
    }

    foreach ($s in $ordered) {
        Write-Host "[hou2ue] Running stage: $s"
        Run-Stage $s
    }
}
else {
    Write-Host "[hou2ue] Running stage: $Stage"
    Run-Stage $Stage
}

Write-Host "[hou2ue] Done. RunDir=$ResolvedRunDir"







