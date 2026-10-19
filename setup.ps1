#Requires -Version 5.1
<#
One-command setup for Windows. Run setup.cmd (it starts this script with the right policy):

  setup.cmd [--dev] [--yes] [--skip-login] [--account EMAIL] [--browser chrome|msedge]

It installs uv (which brings Python 3.12), pnpm and Node when they are missing, the Python
packages from uv.lock, and builds the web app; `brightlearn setup` then makes the home folder,
logs in to NotebookLM (opens your browser) and reports the optional model CLIs. --dev also
installs pytest and ruff; every other argument goes to `brightlearn setup`.
#>
param(
  [switch]$Dev,
  [switch]$Yes,
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)
Set-Location $PSScriptRoot
. "$PSScriptRoot\scripts\env.ps1"

$pass = @()
foreach ($a in $Rest) {
  switch ($a) {
    '--dev' { $Dev = $true }
    '--yes' { $Yes = $true; $pass += $a }
    '-y' { $Yes = $true; $pass += $a }
    default { $pass += $a }
  }
}

function Confirm-Step([string]$Question) {
  if ($Yes) { return $true }
  $answer = Read-Host "$Question [Y/n]"
  return ($answer -notmatch '^(n|no)$')
}

# 1. uv: the official installer when it is missing or too old to know --managed-python.
$uvOk = $false
if (Have uv) { $uvOk = [bool]((& uv sync --help 2>$null) -match '--managed-python') }
if (-not $uvOk) {
  Step 'Installing uv (user-local, from astral.sh)' {
    if (-not (Confirm-Step 'Install uv?')) { Fail 'uv is required: https://docs.astral.sh/uv/' }
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  }
}
Say "uv: $(& uv --version)"

# 2. Where the Python environment lives (scripts/env.ps1 decided).
$inRepo = Join-Path $PWD.Path '.venv'
if ($env:UV_PROJECT_ENVIRONMENT -ne $inRepo) {
  New-Item -ItemType Directory -Force (Split-Path $env:UV_PROJECT_ENVIRONMENT) | Out-Null
  $existing = Get-Item .venv -ErrorAction SilentlyContinue
  if ($existing -and -not $existing.LinkType -and (Test-Path .venv\pyvenv.cfg)) {
    Remove-Item .venv -Recurse -Force
  }
  if (-not (Test-Path .venv)) { cmd /c mklink /J .venv "$env:UV_PROJECT_ENVIRONMENT" | Out-Null }
  Say "Python env: $env:UV_PROJECT_ENVIRONMENT (outside this OneDrive folder; .venv is a junction to it)"
}

# 3. pnpm, and Node 22.12 or newer (what the web build needs).
if (-not (Have pnpm)) {
  Step 'Installing pnpm (user-local, from get.pnpm.io)' {
    if (-not (Confirm-Step 'Install pnpm?')) { Fail 'pnpm is required: https://pnpm.io/installation' }
    Invoke-WebRequest https://get.pnpm.io/install.ps1 -UseBasicParsing | Invoke-Expression
  }
}
function Test-Node {
  if (-not (Have node)) { return $false }
  & node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=12)?0:1)' 2>$null
  return ($LASTEXITCODE -eq 0)
}
if (-not (Test-Node)) {
  Step 'Installing Node LTS with pnpm' {
    if (-not (Confirm-Step 'Install Node LTS?')) { Fail 'Node 22.12 or newer is required: https://nodejs.org/' }
    & pnpm env use --global lts
  }
}
Say "pnpm $(& pnpm --version), node $(& node --version)"

# 4. Python packages, exactly as uv.lock says (uv downloads Python 3.12 the first time).
Step 'Python environment' {
  if ($Dev) { & uv sync --locked } else { & uv sync --locked --no-dev }
}

# 5. The web app.
Step 'Web app' {
  & pnpm --dir web install --frozen-lockfile
  if ($LASTEXITCODE -eq 0) { & pnpm --dir web build }
}

# 6. Home folder, NotebookLM login, optional model CLIs, doctor.
Step 'brightlearn setup' { & uv run --no-sync brightlearn setup @pass }
