param(
    [Parameter(Mandatory = $true)]
    [string]$BatteryName,
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [Parameter(Mandatory = $true)]
    [string]$DuckDBVersion,
    [Parameter(Mandatory = $true)]
    [string]$StartedAtMs
)

$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-24.04'
$workspace = [System.IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
$logDir = Join-Path $workspace "build\logs\$BatteryName"
$runnerLog = Join-Path $logDir 'windows-runner.log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-QaLog {
    param(
        [Parameter(Mandatory = $true)][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $timestamp = [DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $line = "$timestamp [$Level] [$BatteryName] $Message"
    Write-Host $line
    Add-Content -LiteralPath $runnerLog -Value $line -Encoding utf8
}

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if ($resolved -notmatch '^([A-Za-z]):\\(.*)$') {
        throw "Cannot translate Windows path to WSL: $resolved"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $tail = $Matches[2].Replace('\', '/')
    return "/mnt/$drive/$tail"
}

function Start-WslProfileServiceHost {
    param([Parameter(Mandatory = $true)][string]$ProfileName)

    $workspaceLinux = Convert-ToWslPath $workspace
    $sourceLinux = Convert-ToWslPath $SourceRoot
    $configLinux = "$workspaceLinux/build/config/$BatteryName.json"
    $serviceRoot = Join-Path $workspace "build\windows\service-host\$BatteryName"
    $runtimeLinux = "$workspaceLinux/build/windows/service-runtime/$BatteryName"
    $envFile = Join-Path $serviceRoot 'service-env.json'
    $readyFile = Join-Path $serviceRoot 'ready'
    $stopFile = Join-Path $serviceRoot 'stop'
    $stdoutLog = Join-Path $logDir 'service-host.stdout.log'
    $stderrLog = Join-Path $logDir 'service-host.stderr.log'

    Remove-Item -LiteralPath $serviceRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $serviceRoot | Out-Null
    Remove-Item -LiteralPath $stdoutLog,$stderrLog -Force -ErrorAction SilentlyContinue

    $envFileLinux = Convert-ToWslPath $envFile
    $readyFileLinux = Convert-ToWslPath $readyFile
    $stopFileLinux = Convert-ToWslPath $stopFile

    $arguments = @(
        '-d', $distro, '-u', 'root', '--', 'env',
        'QA_SERVICE_HOST_ONLY=1',
        "QA_SERVICE_PROFILE=$ProfileName",
        "QA_SERVICE_ENV_FILE=$envFileLinux",
        "QA_SERVICE_READY_FILE=$readyFileLinux",
        "QA_SERVICE_STOP_FILE=$stopFileLinux",
        "RUNNER_TEMP=$runtimeLinux",
        "RESULT_STARTED_AT_MS=$StartedAtMs",
        'bash',
        "$workspaceLinux/scripts/run-test-battery.sh",
        $configLinux,
        $sourceLinux
    )

    Write-QaLog INFO "starting WSL infrastructure host profile=$ProfileName"
    $process = Start-Process -FilePath 'wsl.exe' -ArgumentList $arguments -PassThru `
        -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

    $ready = $false
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        if (Test-Path -LiteralPath $readyFile -PathType Leaf) {
            $ready = $true
            break
        }
        if ($process.HasExited) {
            $stderr = if (Test-Path $stderrLog) { (Get-Content -LiteralPath $stderrLog -Raw) } else { '' }
            throw "WSL infrastructure host exited before ready with code $($process.ExitCode): $stderr"
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "WSL infrastructure host did not become ready for profile $ProfileName"
    }
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "WSL infrastructure host did not export environment: $envFile"
    }

    $previousEnvironment = @{}
    $serviceEnvironment = Get-Content -LiteralPath $envFile -Raw | ConvertFrom-Json
    foreach ($property in $serviceEnvironment.PSObject.Properties) {
        $name = $property.Name
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, [string]$property.Value, 'Process')
        Write-QaLog INFO "imported infrastructure variable $name"
    }

    $markers = @{
        QA_EXTERNAL_PROFILE_SERVICES = $ProfileName
        QA_WSL_DISTRO = $distro
        QA_WSL_DUCKLAKE_RESET_HELPER = "$workspaceLinux/scripts/reset-ducklake-postgres.sh"
    }
    foreach ($entry in $markers.GetEnumerator()) {
        $previousEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
        [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, 'Process')
    }

    Write-QaLog INFO "WSL infrastructure host ready profile=$ProfileName pid=$($process.Id)"
    return [PSCustomObject]@{
        Process = $process
        StopFile = $stopFile
        PreviousEnvironment = $previousEnvironment
        ProfileName = $ProfileName
        StdoutLog = $stdoutLog
        StderrLog = $stderrLog
    }
}

function Stop-WslProfileServiceHost {
    param([Parameter(Mandatory = $true)]$HostState)

    Write-QaLog INFO "stopping WSL infrastructure host profile=$($HostState.ProfileName)"
    New-Item -ItemType File -Force -Path $HostState.StopFile | Out-Null
    if (-not $HostState.Process.WaitForExit(60000)) {
        Write-QaLog ERROR "WSL infrastructure host did not stop within timeout pid=$($HostState.Process.Id)"
        Stop-Process -Id $HostState.Process.Id -Force -ErrorAction SilentlyContinue
    }
    else {
        Write-QaLog INFO "WSL infrastructure host exit_code=$($HostState.Process.ExitCode)"
    }

    foreach ($entry in $HostState.PreviousEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
}

function Invoke-NativeStandardBattery {
    $artifactDir = Join-Path $workspace 'build\artifact-windows'
    $configFile = Join-Path $workspace "build\config\$BatteryName.json"
    $runtimeConfig = Join-Path $workspace "build\windows\native-config\$BatteryName"
    $nativeRuntime = Join-Path $workspace 'build\windows\native-runtime'
    $runner = Join-Path $workspace 'scripts\run-standard-tests.py'
    $preparer = Join-Path $workspace 'scripts\prepare-test-battery.py'
    $sourceAdapter = Join-Path $workspace 'scripts\prepare-windows-test-source.py'

    Remove-Item -LiteralPath $runtimeConfig -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $runtimeConfig,$nativeRuntime | Out-Null

    Write-QaLog INFO "native preparation config=$configFile runtime_config=$runtimeConfig"
    & python $preparer $configFile $runtimeConfig
    if ($LASTEXITCODE -ne 0) {
        throw "prepare-test-battery.py failed with exit code $LASTEXITCODE"
    }

    Write-QaLog INFO 'applying native Windows source adaptations'
    & python $sourceAdapter $BatteryName $SourceRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to prepare native Windows source adaptations for $BatteryName"
    }

    $previousArtifact = $env:ARTIFACT_DIR
    $previousRuntimeConfig = $env:BATTERY_RUNTIME_CONFIG_DIR
    $previousRunnerTemp = $env:RUNNER_TEMP
    $previousVersion = $env:DUCKDB_VERSION
    $serviceHost = $null
    try {
        $env:ARTIFACT_DIR = $artifactDir
        $env:BATTERY_RUNTIME_CONFIG_DIR = $runtimeConfig
        $env:RUNNER_TEMP = $nativeRuntime
        $env:DUCKDB_VERSION = $DuckDBVersion
        $env:RESULT_STARTED_AT_MS = $StartedAtMs

        if ($BatteryName -eq 'ducklake') {
            $serviceHost = Start-WslProfileServiceHost -ProfileName 'postgres'
        }

        $duckdb = Join-Path $artifactDir 'bin\duckdb.exe'
        $unittest = Join-Path $artifactDir 'bin\unittest.exe'
        Write-QaLog INFO "native execution duckdb=$duckdb unittest=$unittest source=$SourceRoot"
        if (-not (Test-Path -LiteralPath $duckdb -PathType Leaf)) {
            throw "Native DuckDB executable is missing: $duckdb"
        }
        if (-not (Test-Path -LiteralPath $unittest -PathType Leaf)) {
            throw "Native unittest executable is missing: $unittest"
        }
        if ($null -ne $serviceHost -and $serviceHost.Process.HasExited) {
            throw "WSL infrastructure host exited before native test execution with code $($serviceHost.Process.ExitCode)"
        }

        & python $runner $BatteryName $SourceRoot
        $exitCode = $LASTEXITCODE
        Write-QaLog INFO "native standard runner exit_code=$exitCode"
        if ($exitCode -ne 0) {
            throw "Native Windows standard battery $BatteryName failed with exit code $exitCode"
        }
    }
    finally {
        if ($null -ne $serviceHost) {
            Stop-WslProfileServiceHost -HostState $serviceHost
        }
        $env:ARTIFACT_DIR = $previousArtifact
        $env:BATTERY_RUNTIME_CONFIG_DIR = $previousRuntimeConfig
        $env:RUNNER_TEMP = $previousRunnerTemp
        $env:DUCKDB_VERSION = $previousVersion
    }
}

Write-QaLog INFO "Windows battery entry source=$SourceRoot duckdb_version=$DuckDBVersion"

# Migration is deliberately incremental. DuckLake joins the native path with
# PostgreSQL hosted in WSL as infrastructure only; DuckDB and unittest never run
# through the WSL proxy for this battery.
$nativeStandardBatteries = @('irion', 'bigquery', 'ducklake')
if ($nativeStandardBatteries -contains $BatteryName) {
    if ($BatteryName -eq 'ducklake') {
        Write-QaLog INFO 'execution_mode=native-windows-standard wsl_role=infrastructure-only'
    }
    else {
        Write-QaLog INFO 'execution_mode=native-windows-standard wsl_used_for_tests=false'
    }
    Invoke-NativeStandardBattery
    Write-QaLog INFO 'battery completed successfully'
    exit 0
}

Write-QaLog INFO 'execution_mode=legacy-wsl-orchestration migration_pending=true'

$workspaceLinux = Convert-ToWslPath $env:GITHUB_WORKSPACE
$sourceLinux = Convert-ToWslPath $SourceRoot
$configLinux = "$workspaceLinux/build/config/$BatteryName.json"
$proxyArtifactLinux = "$workspaceLinux/build/windows/wsl-artifact"
$runtimeLinux = "$workspaceLinux/build/windows/runtime/$BatteryName"
$duckdbExeLinux = Convert-ToWslPath (Join-Path $env:GITHUB_WORKSPACE 'build/artifact-windows/bin/duckdb.exe')
$unittestExeLinux = Convert-ToWslPath (Join-Path $env:GITHUB_WORKSPACE 'build/artifact-windows/bin/unittest.exe')

# Fixture generators such as Iceberg persist absolute /mnt/<drive>/... paths in
# metadata. Native Windows interprets a leading slash as the root of the current
# drive, so mirror the WSL mount namespace with a junction on that drive.
$workspaceRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($env:GITHUB_WORKSPACE))
$workspaceDrive = $workspaceRoot.Substring(0, 1).ToLowerInvariant()
$systemRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($env:SystemRoot))
$aliasRoots = @($workspaceRoot, $systemRoot) | Select-Object -Unique
foreach ($aliasRoot in $aliasRoots) {
    $wslAliasParent = Join-Path $aliasRoot 'mnt'
    $wslDriveAlias = Join-Path $wslAliasParent $workspaceDrive
    if (-not (Test-Path -LiteralPath $wslDriveAlias)) {
        New-Item -ItemType Directory -Path $wslAliasParent -Force | Out-Null
        New-Item -ItemType Junction -Path $wslDriveAlias -Target $workspaceRoot | Out-Null
    }
}
Write-QaLog INFO "WSL path alias /mnt/$workspaceDrive -> $workspaceRoot"

$normalizeCommand = @"
find '$sourceLinux' -type f \( -name '*.sh' -o -name '*.bash' -o -name 'env_*' \) -print0 | xargs -0 -r sed -i 's/\r$//'
"@
Write-QaLog INFO 'normalizing WSL shell fixtures'
wsl -d $distro -u root -- bash -lc $normalizeCommand
if ($LASTEXITCODE -ne 0) {
    throw "Unable to normalize upstream shell fixtures for $BatteryName"
}

Write-QaLog INFO 'preparing temporary WSL proxies for batteries not yet migrated'
wsl -d $distro -u root -- bash -lc "mkdir -p '$proxyArtifactLinux/bin' '$runtimeLinux'; cp '$workspaceLinux/scripts/windows-duckdb-proxy.sh' '$proxyArtifactLinux/bin/duckdb'; cp '$workspaceLinux/scripts/windows-unittest-proxy.sh' '$proxyArtifactLinux/bin/unittest'; chmod +x '$proxyArtifactLinux/bin/duckdb' '$proxyArtifactLinux/bin/unittest' '$workspaceLinux/scripts/'*.sh '$workspaceLinux/scripts/'*.py"
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to prepare WSL proxy artifact'
}

if ($BatteryName -eq 'delta') {
    Write-QaLog INFO 'ensuring Delta zstd fixture dependency'
    wsl -d $distro -u root -- bash -lc "command -v zstd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq zstd)"
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to install zstd for the Delta Windows fixture host'
    }
}

Write-QaLog INFO 'applying Windows source adaptations for legacy path'
wsl -d $distro -u root -- python3 "$workspaceLinux/scripts/prepare-windows-test-source.py" $BatteryName $sourceLinux
if ($LASTEXITCODE -ne 0) {
    throw "Unable to prepare native Windows source adaptations for $BatteryName"
}

# Delta fixtures include paths that exceed the legacy Windows MAX_PATH limit
# when rooted under the full GitHub Actions checkout. Keep fixture generation in
# the same NTFS checkout, but expose that checkout through a short drive-root
# junction for the WSL battery and native unittest.exe process.
$batterySourceLinux = $sourceLinux
$deltaSourceAlias = $null
if ($BatteryName -eq 'delta') {
    $sourceDriveRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($SourceRoot))
    $deltaSourceAlias = Join-Path $sourceDriveRoot 'qa-delta-src'
    if (Test-Path -LiteralPath $deltaSourceAlias) {
        $existingAlias = Get-Item -LiteralPath $deltaSourceAlias -Force
        if (($existingAlias.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
            throw "Refusing to replace non-junction Delta short path: $deltaSourceAlias"
        }
        Remove-Item -LiteralPath $deltaSourceAlias -Force
    }
    New-Item -ItemType Junction -Path $deltaSourceAlias -Target ([System.IO.Path]::GetFullPath($SourceRoot)) | Out-Null
    $batterySourceLinux = Convert-ToWslPath $deltaSourceAlias
    Write-QaLog INFO "Delta short source alias windows=$deltaSourceAlias linux=$batterySourceLinux target=$SourceRoot"
}

$environment = [System.Collections.Generic.List[string]]::new()
$environment.Add("ARTIFACT_DIR=$proxyArtifactLinux")
$environment.Add("RUNNER_TEMP=$runtimeLinux")
$environment.Add("RESULT_STARTED_AT_MS=$StartedAtMs")
$environment.Add("DUCKDB_VERSION=$DuckDBVersion")
$environment.Add('QA_NATIVE_WINDOWS=1')
$environment.Add("QA_WSL_RUNTIME_HELPER=$workspaceLinux/scripts/windows-wsl-runtime.sh")
$environment.Add("QA_WSL_RUNTIME_PY=$workspaceLinux/scripts/windows-wsl-runtime.py")
$environment.Add("QA_WINDOWS_DUCKDB_EXE=$duckdbExeLinux")
$environment.Add("QA_WINDOWS_UNITTEST_EXE=$unittestExeLinux")
$environment.Add("GITHUB_RUN_ID=$env:GITHUB_RUN_ID")
$environment.Add("GITHUB_RUN_ATTEMPT=$env:GITHUB_RUN_ATTEMPT")

if ($BatteryName -in @('postgres_scanner', 'mssql')) {
    $environment.Add('QA_DUCKDB_TRANSLATE_STDIN=1')
}

foreach ($name in @('BQ_TEST_PROJECT', 'BQ_TEST_DATASET', 'BQ_TEST_EXPORT_URI')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($null -ne $value -and $value -ne '') {
        $environment.Add("$name=$value")
    }
}

if ($env:GOOGLE_APPLICATION_CREDENTIALS) {
    $credentialLinux = Convert-ToWslPath $env:GOOGLE_APPLICATION_CREDENTIALS
    $environment.Add("GOOGLE_APPLICATION_CREDENTIALS=$credentialLinux")
}

$arguments = [System.Collections.Generic.List[string]]::new()
@('-d', $distro, '-u', 'root', '--', 'env') | ForEach-Object { $arguments.Add($_) }
$environment | ForEach-Object { $arguments.Add($_) }
$arguments.Add('bash')
$arguments.Add("$workspaceLinux/scripts/run-test-battery.sh")
$arguments.Add($configLinux)
$arguments.Add($batterySourceLinux)

Write-QaLog INFO "starting legacy WSL battery path source=$batterySourceLinux"
try {
    & wsl @arguments
    $exitCode = $LASTEXITCODE
}
finally {
    if ($null -ne $deltaSourceAlias -and (Test-Path -LiteralPath $deltaSourceAlias)) {
        try {
            $aliasItem = Get-Item -LiteralPath $deltaSourceAlias -Force
            if (($aliasItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
                Write-QaLog ERROR "Delta short source path is no longer a junction; leaving it untouched: $deltaSourceAlias"
            }
            else {
                Remove-Item -LiteralPath $deltaSourceAlias -Force
                Write-QaLog INFO "removed Delta short source alias $deltaSourceAlias"
            }
        }
        catch {
            Write-QaLog ERROR "unable to remove Delta short source alias $deltaSourceAlias`: $($_.Exception.Message)"
        }
    }
}
Write-QaLog INFO "legacy WSL battery exit_code=$exitCode"
if ($exitCode -ne 0) {
    throw "Shared QA battery $BatteryName failed with exit code $exitCode"
}
