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

function Invoke-NativeStandardBattery {
    $artifactDir = Join-Path $workspace 'build\artifact-windows'
    $configFile = Join-Path $workspace "build\config\$BatteryName.json"
    $runtimeConfig = Join-Path $workspace "build\windows\native-config\$BatteryName"
    $nativeRuntime = Join-Path $workspace 'build\windows\native-runtime'
    $runner = Join-Path $workspace 'scripts\run-standard-tests.py'
    $preparer = Join-Path $workspace 'scripts\prepare-test-battery.py'

    Remove-Item -LiteralPath $runtimeConfig -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $runtimeConfig,$nativeRuntime | Out-Null

    Write-QaLog INFO "native preparation config=$configFile runtime_config=$runtimeConfig"
    & python $preparer $configFile $runtimeConfig
    if ($LASTEXITCODE -ne 0) {
        throw "prepare-test-battery.py failed with exit code $LASTEXITCODE"
    }

    $previousArtifact = $env:ARTIFACT_DIR
    $previousRuntimeConfig = $env:BATTERY_RUNTIME_CONFIG_DIR
    $previousRunnerTemp = $env:RUNNER_TEMP
    $previousVersion = $env:DUCKDB_VERSION
    try {
        $env:ARTIFACT_DIR = $artifactDir
        $env:BATTERY_RUNTIME_CONFIG_DIR = $runtimeConfig
        $env:RUNNER_TEMP = $nativeRuntime
        $env:DUCKDB_VERSION = $DuckDBVersion
        $env:RESULT_STARTED_AT_MS = $StartedAtMs

        $duckdb = Join-Path $artifactDir 'bin\duckdb.exe'
        $unittest = Join-Path $artifactDir 'bin\unittest.exe'
        Write-QaLog INFO "native execution duckdb=$duckdb unittest=$unittest source=$SourceRoot"
        if (-not (Test-Path -LiteralPath $duckdb -PathType Leaf)) {
            throw "Native DuckDB executable is missing: $duckdb"
        }
        if (-not (Test-Path -LiteralPath $unittest -PathType Leaf)) {
            throw "Native unittest executable is missing: $unittest"
        }

        & python $runner $BatteryName $SourceRoot
        $exitCode = $LASTEXITCODE
        Write-QaLog INFO "native standard runner exit_code=$exitCode"
        if ($exitCode -ne 0) {
            throw "Native Windows standard battery $BatteryName failed with exit code $exitCode"
        }
    }
    finally {
        $env:ARTIFACT_DIR = $previousArtifact
        $env:BATTERY_RUNTIME_CONFIG_DIR = $previousRuntimeConfig
        $env:RUNNER_TEMP = $previousRunnerTemp
        $env:DUCKDB_VERSION = $previousVersion
    }
}

Write-QaLog INFO "Windows battery entry source=$SourceRoot duckdb_version=$DuckDBVersion"

# Migration is deliberately incremental. These batteries have no WSL-hosted
# infrastructure or profile-scoped services, so they are the first proof that
# DuckDB/unittest can execute entirely on the Windows host. Additional batteries
# move to this path as their infrastructure preparation is detached from Bash.
$nativeStandardBatteries = @('irion', 'bigquery')
if ($nativeStandardBatteries -contains $BatteryName) {
    Write-QaLog INFO 'execution_mode=native-windows-standard wsl_used_for_tests=false'
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
$arguments.Add($sourceLinux)

Write-QaLog INFO 'starting legacy WSL battery path'
& wsl @arguments
$exitCode = $LASTEXITCODE
Write-QaLog INFO "legacy WSL battery exit_code=$exitCode"
if ($exitCode -ne 0) {
    throw "Shared QA battery $BatteryName failed with exit code $exitCode"
}
