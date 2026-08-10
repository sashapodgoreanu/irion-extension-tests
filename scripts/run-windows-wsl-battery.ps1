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
Write-Host "Native Windows WSL path aliases ready: /mnt/$workspaceDrive -> $workspaceRoot"

# actions/checkout runs on the Windows host, so remote repositories that do not
# declare LF explicitly can arrive with CRLF shell fixtures. The shared battery
# orchestration runs those fixtures in WSL. Normalize only shell-like files in
# the checked-out test source; SQLLogicTest/data/binary inputs remain untouched.
$normalizeCommand = @"
find '$sourceLinux' -type f \( -name '*.sh' -o -name '*.bash' -o -name 'env_*' \) -print0 | xargs -0 -r sed -i 's/\r$//'
"@
wsl -d $distro -u root -- bash -lc $normalizeCommand
if ($LASTEXITCODE -ne 0) {
    throw "Unable to normalize upstream shell fixtures for $BatteryName"
}

wsl -d $distro -u root -- bash -lc "mkdir -p '$proxyArtifactLinux/bin' '$runtimeLinux'; cp '$workspaceLinux/scripts/windows-duckdb-proxy.sh' '$proxyArtifactLinux/bin/duckdb'; cp '$workspaceLinux/scripts/windows-unittest-proxy.sh' '$proxyArtifactLinux/bin/unittest'; chmod +x '$proxyArtifactLinux/bin/duckdb' '$proxyArtifactLinux/bin/unittest' '$workspaceLinux/scripts/'*.sh '$workspaceLinux/scripts/'*.py"
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to prepare WSL proxy artifact'
}

if ($BatteryName -eq 'delta') {
    # GNU tar delegates .zst decompression to the zstd executable. Without it,
    # unwrap_golden_tables.sh leaves the golden-table directories empty.
    wsl -d $distro -u root -- bash -lc "command -v zstd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq zstd)"
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to install zstd for the Delta Windows fixture host'
    }
}

# Keep platform-specific source differences explicit and drift-checked instead
# of weakening the shared Linux battery or silently skipping Windows coverage.
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

# These specialized upstream fixtures pipe SQL containing WSL-mounted paths to
# the DuckDB CLI. Let the Windows proxy translate only those stdin SQL streams;
# normal -c probes and SQLLogicTest execution keep their existing input rules.
if ($BatteryName -in @('postgres_scanner', 'mssql')) {
    $environment.Add('QA_DUCKDB_TRANSLATE_STDIN=1')
}
if ($BatteryName -eq 'postgres_scanner') {
    # postgres_execute sends this path to the Linux PostgreSQL server. Do not
    # mark it as a WSLENV path: the native process must preserve /mnt/... text.
    $environment.Add("PGSCANNER_SERVER_WORKING_DIRECTORY=$sourceLinux")
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

& wsl @arguments
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    throw "Shared QA battery $BatteryName failed with exit code $exitCode"
}
