param(
    [Parameter(Mandatory = $true)]
    [string]$DuckDBVersion,

    [Parameter(Mandatory = $true)]
    [string]$CiToolsVersion,

    [int]$BuildJobs = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DuckDBRoot = Join-Path $RepoRoot 'duckdb'
$CiToolsRoot = Join-Path $RepoRoot 'extension-ci-tools'
$BuildRoot = Join-Path $RepoRoot 'build/windows/release'
$ArtifactRoot = Join-Path $RepoRoot 'build/artifact-windows'
$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

# Respect the exact commits checked out by actions/checkout (gitlinks).
# CI tools are pinned by SHA because no v2.0.0 tag exists upstream.
$DuckDBTagRef = "refs/tags/$DuckDBVersion^{commit}"
$DuckDBTagCommit = (& git -C $DuckDBRoot rev-parse --verify $DuckDBTagRef).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "DuckDB release tag $DuckDBVersion could not be resolved locally"
}
$DuckDBHead = (& git -C $DuckDBRoot rev-parse HEAD).Trim()
$CiToolsHead = (& git -C $CiToolsRoot rev-parse HEAD).Trim()
if ($DuckDBHead -ne $DuckDBTagCommit) {
    throw "DuckDB submodule $DuckDBHead does not match release $DuckDBVersion ($DuckDBTagCommit)"
}
if ($CiToolsHead -ne $CiToolsVersion) {
    throw "extension-ci-tools submodule $CiToolsHead does not match configured SHA $CiToolsVersion"
}
Write-Host "Using pinned DuckDB $DuckDBHead and extension-ci-tools $CiToolsHead"

# Match DuckDB's upstream Windows CI preparation before configuring MSVC.
Push-Location $DuckDBRoot
try {
    Invoke-Checked -Command python -Arguments @('scripts/windows_ci.py')
}
finally {
    Pop-Location
}

if (Test-Path $BuildRoot) {
    Remove-Item -Recurse -Force $BuildRoot
}
New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null

$DuckDBSource = (Resolve-Path $DuckDBRoot).Path.Replace('\', '/')
$BuildPath = (Resolve-Path $BuildRoot).Path.Replace('\', '/')
$ExtensionConfig = (Resolve-Path (Join-Path $RepoRoot 'extension_config.cmake')).Path.Replace('\', '/')

$ConfigureArguments = @(
    '-S', $DuckDBSource,
    '-B', $BuildPath,
    '-DCMAKE_BUILD_TYPE=Release',
    '-DCMAKE_GENERATOR_PLATFORM=x64',
    '-DENABLE_EXTENSION_AUTOLOADING=1',
    '-DENABLE_EXTENSION_AUTOINSTALL=1',
    '-DDISABLE_UNITY=1',
    '-DBUILD_UNITTESTS=TRUE',
    '-DENABLE_UNITTEST_CPP_TESTS=FALSE',
    "-DDUCKDB_EXTENSION_CONFIGS=$ExtensionConfig"
)
Invoke-Checked -Command cmake -Arguments $ConfigureArguments
Invoke-Checked -Command cmake -Arguments @('--build', $BuildPath, '--config', 'Release', '--parallel', "$BuildJobs")

$DuckDBExe = Join-Path $BuildRoot 'Release/duckdb.exe'
$UnitTestExe = Join-Path $BuildRoot 'test/Release/unittest.exe'
if (-not (Test-Path $DuckDBExe)) {
    throw "DuckDB executable was not produced: $DuckDBExe"
}
if (-not (Test-Path $UnitTestExe)) {
    throw "DuckDB unittest executable was not produced: $UnitTestExe"
}

$QaExtension = Get-ChildItem -Path $BuildRoot -Recurse -File -Filter 'qa_test*.duckdb_extension' |
    Select-Object -First 1
if ($null -eq $QaExtension) {
    throw 'qa_test extension output was not produced'
}

if (Test-Path $ArtifactRoot) {
    Remove-Item -Recurse -Force $ArtifactRoot
}
$BinDir = Join-Path $ArtifactRoot 'bin'
$ExtensionDir = Join-Path $ArtifactRoot 'extensions'
$LogDir = Join-Path $ArtifactRoot 'logs'
New-Item -ItemType Directory -Force -Path $BinDir, $ExtensionDir, $LogDir | Out-Null
Copy-Item $DuckDBExe (Join-Path $BinDir 'duckdb.exe')
Copy-Item $UnitTestExe (Join-Path $BinDir 'unittest.exe')
Copy-Item $QaExtension.FullName (Join-Path $ExtensionDir $QaExtension.Name)

Invoke-Checked -Command (Join-Path $BinDir 'duckdb.exe') -Arguments @('--version')
Invoke-Checked -Command (Join-Path $BinDir 'unittest.exe') -Arguments @('--help')

$Stopwatch.Stop()
$DuckDBCommit = (& git -C $DuckDBRoot rev-parse HEAD).Trim()
$CiToolsCommit = (& git -C $CiToolsRoot rev-parse HEAD).Trim()
@(
    "duckdb_version=$DuckDBVersion"
    "duckdb_commit=$DuckDBCommit"
    "ci_tools_version=$CiToolsVersion"
    "ci_tools_commit=$CiToolsCommit"
    'operating_system=windows'
    'architecture=x86_64'
    'github_runner=windows-latest'
    'compiler=msvc'
    'cmake_configuration=Release'
    'compiled_extension=qa_test'
    "build_elapsed_seconds=$([math]::Round($Stopwatch.Elapsed.TotalSeconds, 1))"
) | Set-Content -Path (Join-Path $LogDir 'build-info.txt') -Encoding utf8
