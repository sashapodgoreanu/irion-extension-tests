param(
    [Parameter(Mandatory = $true)]
    [string]$BatteryName,
    [string]$CapabilitiesJson = '[]'
)

$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-24.04'

python -m pip install --disable-pip-version-check -r requirements/qa.txt
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to install shared QA Python dependencies on Windows'
}

function Invoke-WslBash {
    param([Parameter(Mandatory = $true)][string]$Command)
    wsl -d $distro -u root -- bash -lc $Command
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed with exit code ${LASTEXITCODE}: $Command"
    }
}

function Convert-GitWorkingTreeToLf {
    param([Parameter(Mandatory = $true)][string]$RepositoryPath)

    if (-not (Test-Path (Join-Path $RepositoryPath '.git'))) {
        return
    }

    & git -C $RepositoryPath config core.autocrlf false
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to disable core.autocrlf for $RepositoryPath"
    }
    & git -C $RepositoryPath config core.eol lf
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to select LF line endings for $RepositoryPath"
    }

    $converted = 0
    $entries = @(& git -C $RepositoryPath ls-files --eol)
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Git line endings for $RepositoryPath"
    }

    foreach ($entry in $entries) {
        if ($entry -notmatch '(^|\s)w/crlf(\s|$)') {
            continue
        }
        $tabIndex = $entry.IndexOf("`t")
        if ($tabIndex -lt 0) {
            continue
        }
        $relativePath = $entry.Substring($tabIndex + 1)
        $filePath = Join-Path $RepositoryPath $relativePath
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            continue
        }

        $bytes = [System.IO.File]::ReadAllBytes($filePath)
        $stream = [System.IO.MemoryStream]::new($bytes.Length)
        try {
            $changed = $false
            for ($index = 0; $index -lt $bytes.Length; $index++) {
                if (
                    $bytes[$index] -eq 13 -and
                    ($index + 1) -lt $bytes.Length -and
                    $bytes[$index + 1] -eq 10
                ) {
                    $stream.WriteByte(10)
                    $index++
                    $changed = $true
                }
                else {
                    $stream.WriteByte($bytes[$index])
                }
            }
            if ($changed) {
                [System.IO.File]::WriteAllBytes($filePath, $stream.ToArray())
                $converted++
            }
        }
        finally {
            $stream.Dispose()
        }
    }

    Write-Host "Normalized $converted CRLF tracked files to LF in $RepositoryPath"
}

$installed = @(wsl --list --quiet) -replace "`0", '' | ForEach-Object { $_.Trim() }
if ($installed -notcontains $distro) {
    wsl --install -d $distro --no-launch --web-download
    if ($LASTEXITCODE -ne 0) {
        throw "wsl --install failed with exit code $LASTEXITCODE"
    }
}

$workspace = $env:GITHUB_WORKSPACE
if ($workspace -notmatch '^[A-Za-z]:\\') {
    throw "Unexpected Windows workspace path: $workspace"
}
$drive = $workspace.Substring(0, 1).ToLowerInvariant()
$tail = $workspace.Substring(2).Replace('\', '/')
$workspaceLinux = "/mnt/$drive$tail"

# actions/checkout runs through Git for Windows before WSL is prepared. Its
# default checkout policy may materialize upstream shell scripts as CRLF, which
# makes otherwise valid Bash entrypoints fail inside WSL (for example env_minio,
# run_squid.sh and integration_test.sh). Normalize only tracked files Git reports
# as w/crlf, then repeat for recursively checked-out submodules.
$upstreamPath = Join-Path $workspace "upstream\$BatteryName"
if (Test-Path $upstreamPath) {
    Convert-GitWorkingTreeToLf -RepositoryPath $upstreamPath
    $submodulePaths = @(& git -C $upstreamPath submodule foreach --recursive --quiet 'pwd -W')
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to enumerate submodules for $BatteryName"
    }
    foreach ($submodulePath in $submodulePaths) {
        $normalizedSubmodulePath = $submodulePath.Trim()
        if ($normalizedSubmodulePath) {
            Convert-GitWorkingTreeToLf -RepositoryPath $normalizedSubmodulePath
        }
    }
}

$capabilities = @()
if ($CapabilitiesJson) {
    $parsed = ConvertFrom-Json -InputObject $CapabilitiesJson
    if ($null -ne $parsed) {
        $capabilities = @($parsed)
    }
}

$packages = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
@(
    'python3', 'python3-venv', 'python3-pip', 'curl', 'ca-certificates',
    'git', 'sudo', 'rsync', 'jq', 'wget'
) | ForEach-Object { [void]$packages.Add($_) }

$needsDocker = (
    $capabilities -contains 'docker' -or
    $capabilities -contains 'docker-compose' -or
    $BatteryName -in @('delta', 'iceberg')
)
if ($needsDocker) {
    [void]$packages.Add('docker.io')
    [void]$packages.Add('docker-compose-v2')
}
if ($capabilities -contains 'squid') {
    [void]$packages.Add('squid')
}
if ($capabilities -contains 'postgres-client' -or $BatteryName -eq 'ducklake') {
    [void]$packages.Add('postgresql-client')
}
if ($BatteryName -in @('delta', 'iceberg')) {
    [void]$packages.Add('make')
    [void]$packages.Add('openjdk-21-jdk-headless')
    [void]$packages.Add('build-essential')
}
if ($BatteryName -eq 'delta') {
    [void]$packages.Add('cargo')
    [void]$packages.Add('pkg-config')
    [void]$packages.Add('libssl-dev')
    [void]$packages.Add('unzip')
    [void]$packages.Add('zip')
}
if ($BatteryName -eq 'unity_catalog') {
    [void]$packages.Add('openjdk-21-jdk-headless')
}

$packageList = ($packages | Sort-Object) -join ' '
Invoke-WslBash "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq $packageList"
Invoke-WslBash "git config --global --add safe.directory '*'"

if ($needsDocker) {
    Invoke-WslBash "systemctl enable --now docker; docker info --format 'OSType={{.OSType}} Architecture={{.Architecture}}'; docker compose version"
}

if ($capabilities -contains 'azurite') {
    Invoke-WslBash "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -; apt-get install -y -qq nodejs; npm install --global azurite; node --version; azurite --version"
    Invoke-WslBash "if ! command -v az >/dev/null 2>&1; then curl -sL https://aka.ms/InstallAzureCLIDeb | bash; fi; az --version >/dev/null"
}

wsl -d $distro -u root -- test -d $workspaceLinux
if ($LASTEXITCODE -ne 0) {
    throw "WSL workspace is not visible at $workspaceLinux"
}
wsl -d $distro -u root -- bash -n "$workspaceLinux/scripts/service-manager.sh"
if ($LASTEXITCODE -ne 0) {
    throw 'Shared service-manager.sh is not valid Bash on the Windows checkout'
}

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
foreach ($alias in @(
    'duckdb-minio.com',
    'test-bucket.duckdb-minio.com',
    'test-bucket-2.duckdb-minio.com',
    'test-bucket-public.duckdb-minio.com'
)) {
    if (-not (Select-String -Path $hostsPath -SimpleMatch $alias -Quiet)) {
        Add-Content -Path $hostsPath -Value "127.0.0.1 $alias"
    }
}
Clear-DnsClientCache

if ($env:GITHUB_OUTPUT) {
    "workspace_linux=$workspaceLinux" | Out-File $env:GITHUB_OUTPUT -Append -Encoding utf8
}
Write-Host "WSL service host ready for $BatteryName at $workspaceLinux"
