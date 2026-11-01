param([ValidateSet('dev','build')][string]$Mode = 'dev')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (Test-Path -LiteralPath '.tools\cargo\bin\cargo.exe') {
    $env:CARGO_HOME = Join-Path $PWD '.tools\cargo'
    $env:RUSTUP_HOME = Join-Path $PWD '.tools\rustup'
    $env:PATH = (Join-Path $PWD '.tools\cargo\bin') + ';' + $env:PATH
}
if ($Mode -eq 'build') { npm.cmd run desktop:build } else { npm.cmd run desktop:dev }
if ($LASTEXITCODE -ne 0) { throw 'Desktop command failed' }
