<#
.SYNOPSIS
Run the full pytest suite in Linux, where the Home Assistant plugin tests run.

.DESCRIPTION
Native Windows Python has no `fcntl`, so `tests/conftest.py` skips the HA-runtime
modules (config flow, coordinator, setup/unload, device triggers, diagnostics).
This builds the image in docker/test.Dockerfile once and runs pytest inside it,
so nothing is skipped. Requires a running Docker Engine.

.EXAMPLE
./scripts/test.ps1

.EXAMPLE
./scripts/test.ps1 tests/test_coordinator.py -v
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$image = "ha-traffical-test"

docker version --format '{{.Server.Version}}' > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine is not reachable. Start Docker Desktop and retry."
}

docker build -t $image -f (Join-Path $repo "docker/test.Dockerfile") $repo
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed"
}

$pytest = @("-m", "pytest", "-p", "no:cacheprovider")
$pytest += if ($PytestArgs) { $PytestArgs } else { @("-q") }

docker run --rm -v "${repo}:/repo" -w /repo $image python @pytest
exit $LASTEXITCODE
