# Shared by setup.ps1: PATH for user-local tools, uv settings, and where the environment lives.
# Dot-sourced; Windows PowerShell 5.1 compatible.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# The uv and pnpm installers put their binaries here and only edit the registry PATH, so this
# run needs the prefix itself.
$env:PNPM_HOME = Join-Path $env:LOCALAPPDATA 'pnpm'
$env:Path = "$env:USERPROFILE\.local\bin;$env:PNPM_HOME;$env:Path"
# The environment's Python is uv's own 3.12 (.python-version), never a system one.
$env:UV_MANAGED_PYTHON = '1'
$env:PYTHONUTF8 = '1'

function Say([string]$Text) { [Console]::Error.WriteLine($Text) }
function Fail([string]$Text) { Say "error: $Text"; exit 1 }
function Have([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

# Native commands never throw in PowerShell 5.1, so every step checks the exit code itself.
function Step([string]$Name, [scriptblock]$Block) {
  Say ''
  Say "==> $Name"
  $global:LASTEXITCODE = 0
  & $Block
  if ($LASTEXITCODE) {
    Fail "$Name failed (exit $LASTEXITCODE). Fix it and run setup.cmd again; finished steps are skipped."
  }
}

# OneDrive plays the role iCloud plays on a Mac: keep the environment outside a synced folder.
function In-OneDrive {
  foreach ($root in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer)) {
    if ($root -and $PWD.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}

# An explicit UV_PROJECT_ENVIRONMENT, else what an earlier run pointed .venv at, else outside
# the repo under OneDrive, else .\.venv.
function Get-VenvDir {
  if ($env:UV_PROJECT_ENVIRONMENT) { return $env:UV_PROJECT_ENVIRONMENT }
  $item = Get-Item .venv -ErrorAction SilentlyContinue
  if ($item -and $item.LinkType) { return @($item.Target)[0] }
  if (In-OneDrive) { return Join-Path $env:USERPROFILE ".venvs\$(Split-Path -Leaf $PWD.Path)" }
  return Join-Path $PWD.Path '.venv'
}
$env:UV_PROJECT_ENVIRONMENT = Get-VenvDir
