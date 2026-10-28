# Install Holdback on Windows: irm https://taylorurl.com/holdback.ps1 | iex
#
# Installs the holdback command with pipx or uv (installing uv into your home folder if
# neither is there), adds the bin folder to your user PATH, then runs `holdback setup` and
# `holdback doctor`. Nothing is installed system-wide and administrator rights are never
# needed.
#
# Arguments for `holdback setup` need the script as a script block, for example:
#   & ([scriptblock]::Create((irm https://taylorurl.com/holdback.ps1))) --no-appeal --yes
# Environment: HOLDBACK_REF (branch, tag or commit; default main),
#              HOLDBACK_INSTALLER (pipx or uv, to choose one).
#
# Works in Windows PowerShell 5.1 and PowerShell 7. It runs inside your own session
# (that's what iex does), so everything is inside one script block that leaves no variables
# or functions behind, it never calls exit, and holdback works in this window as soon as it
# finishes.

& {
$ErrorActionPreference = 'Stop'

$Repo = 'https://github.com/bradley-t-t/holdback'
$Pkg = 'claude-holdback'
# install.ps1 records the folder it adds to the user PATH here, so `holdback uninstall
# --all` removes that entry and never one you or another tool added.
$MarkKey = 'HKCU:\Software\Holdback'
$SetupArgs = @($args)

function Say([string]$Text) { Write-Host $Text }
function Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Ok([string]$Text) { Write-Host 'ok  ' -ForegroundColor Green -NoNewline; Write-Host $Text }
function Note([string]$Text) { Write-Host 'note  ' -ForegroundColor Yellow -NoNewline; Write-Host $Text }
function Have([string]$Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

# A terminal to ask questions in. irm | iex keeps the console as input, unlike curl | sh.
$Tty = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected

# Ask 'Question' $true -> $true for yes. Without a terminal the default is used.
function Ask([string]$Question, [bool]$Default) {
    if (-not $Tty) { return $Default }
    $hint = if ($Default) { '[Y/n]' } else { '[y/N]' }
    $reply = Read-Host "$Question $hint"
    if ($reply -match '^[Yy]') { return $true }
    if ($reply -match '^[Nn]') { return $false }
    return $Default
}

# Run a program in this console, so it can ask questions and show colors. Returns its exit
# code. (A program PowerShell runs with & inside a function may have its output captured,
# and then it can't tell it's talking to a terminal.)
function Invoke-Interactive([string]$Exe, [string[]]$Arguments) {
    # Windows' quoting rules: backslashes double before a quote and at the end.
    $quoted = foreach ($a in $Arguments) {
        if ($a -notmatch '[\s"]' -and $a -ne '') { $a; continue }
        '"' + (($a -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
    }
    $info = New-Object Diagnostics.ProcessStartInfo $Exe
    $info.UseShellExecute = $false
    $info.Arguments = $quoted -join ' '
    $process = [Diagnostics.Process]::Start($info)
    $process.WaitForExit()
    return $process.ExitCode
}

# Run a program and collect its output and exit code. Windows PowerShell 5.1 turns a
# program's stderr into errors, which 'Stop' would make fatal, so they're collected too.
function Invoke-Program([string]$Exe, [string[]]$Arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $saved
    }
    [pscustomobject]@{ Code = $code; Output = @($out) }
}

function Test-PipxHas { (Have 'pipx') -and ((Invoke-Program 'pipx' @('list', '--short')).Output -match "^$Pkg ") }
function Test-UvHas { (Have 'uv') -and ((Invoke-Program 'uv' @('tool', 'list', '--color', 'never')).Output -match "^$Pkg ") }

function Select-Installer {
    Step 'Choosing an installer'
    switch ($env:HOLDBACK_INSTALLER) {
        'pipx' { if (-not (Have 'pipx')) { throw "HOLDBACK_INSTALLER=pipx but pipx isn't installed" }; return 'pipx' }
        'uv' { if (-not (Have 'uv')) { Install-Uv }; return 'uv' }
        { $_ } { throw 'HOLDBACK_INSTALLER must be pipx or uv' }
    }
    if (Test-PipxHas) { $how = 'pipx' }
    elseif (Test-UvHas) { $how = 'uv' }
    elseif (Have 'pipx') { $how = 'pipx' }
    elseif (Have 'uv') { $how = 'uv' }
    else {
        Say 'Holdback installs with pipx or uv, and neither is here.'
        Say 'uv is a single program from Astral. Its installer puts it in ~\.local\bin.'
        if (-not (Ask 'Install uv now?' $true)) { throw 'Install pipx or uv, then run this again.' }
        Install-Uv
        $how = 'uv'
    }
    Ok "Using $how"
    return $how
}

function Install-Uv {
    Say 'Installing uv from https://astral.sh/uv'
    # Astral's installer stops unless scripts may run, and exits when it fails, so it gets
    # its own PowerShell with the policy relaxed for that process only, as Astral suggests.
    $saved = $env:UV_NO_MODIFY_PATH
    $env:UV_NO_MODIFY_PATH = '1'  # Holdback adds its own bin folder, the same one, below
    try {
        $shell = (Get-Process -Id $PID).Path
        $r = Invoke-Program $shell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', "irm 'https://astral.sh/uv/install.ps1' | iex")
    } finally {
        $env:UV_NO_MODIFY_PATH = $saved
    }
    if ($r.Code -ne 0) { $r.Output | Write-Host; throw "uv's installer failed." }
    foreach ($d in @($env:XDG_BIN_HOME, (Join-Path $HOME '.local\bin'), (Join-Path $HOME '.cargo\bin'))) {
        if ($d -and (Test-Path -LiteralPath (Join-Path $d 'uv.exe'))) { $env:Path = "$d;$env:Path"; break }
    }
    if (-not (Have 'uv')) { throw "uv was installed but can't be found. Open a new terminal and run this again." }
    Ok "Installed $((Invoke-Program 'uv' @('--version')).Output)"
}

function Get-SourceUrl {
    $ref = if ($env:HOLDBACK_REF) { $env:HOLDBACK_REF } else { 'main' }
    if (Have 'git') { return "git+$Repo.git@$ref" }
    # No git: GitHub's tarball of the same ref works without it.
    return "$Repo/archive/$ref.tar.gz"
}

# The holdback program in a bin folder: holdback.exe on Windows (holdback elsewhere, for
# the tests).
function Find-Holdback([string]$Dir) {
    foreach ($name in 'holdback.exe', 'holdback') {
        $p = Join-Path $Dir $name
        if (Test-Path -LiteralPath $p -PathType Leaf) { return $p }
    }
    return $null
}

# holdback\package.py runs these same install commands when Holdback updates itself.
function Install-HoldbackPackage([string]$How) {
    $url = Get-SourceUrl
    Step 'Installing Holdback'
    Say "from $url"
    if ($How -eq 'pipx') {
        if (Test-PipxHas) { Say "Holdback is already installed with pipx, so it's reinstalled." }
        $r = Invoke-Program 'pipx' @('install', '--force', $url)
        if ($r.Code -ne 0) { $r.Output | Write-Host; throw 'pipx install failed.' }
        $bin = ((Invoke-Program 'pipx' @('environment', '--value', 'PIPX_BIN_DIR')).Output | Select-Object -Last 1)
        if (-not $bin) { $bin = Join-Path $HOME '.local\bin' }
    } else {
        if (Test-UvHas) { Say "Holdback is already installed with uv, so it's reinstalled." }
        $r = Invoke-Program 'uv' @('tool', 'install', '--force', '--reinstall', $url)
        if ($r.Code -ne 0) { $r.Output | Write-Host; throw 'uv tool install failed.' }
        $bin = (Invoke-Program 'uv' @('tool', 'dir', '--bin', '--color', 'never')).Output | Select-Object -Last 1
    }
    $bin = "$bin".Trim()
    $holdback = Find-Holdback $bin
    if (-not $holdback) { throw "Installed, but there's no holdback program in $bin." }
    Ok "$((Invoke-Program $holdback @('--version')).Output) in $bin"
    return $bin
}

# True when the ;-separated list holds the folder. Entries may use %VARIABLES% and a
# trailing backslash; case doesn't matter.
function Test-PathList([string]$List, [string]$Dir) {
    $want = [Environment]::ExpandEnvironmentVariables($Dir).TrimEnd('\', '/')
    foreach ($entry in ($List -split ';')) {
        $e = [Environment]::ExpandEnvironmentVariables($entry.Trim()).TrimEnd('\', '/')
        if ($e -and $e -ieq $want) { return $true }
    }
    return $false
}

# The user PATH as stored, with %VARIABLES% left unexpanded so writing it back keeps them.
function Get-UserPath {
    $key = Get-Item -LiteralPath 'HKCU:\Environment'
    return [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
}

function Set-UserPath([string]$Value) {
    Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name 'Path' -Value $Value -Type ExpandString
    # Setting a variable through .NET announces the change, so terminals opened from now on
    # see the new PATH. This one is set and removed again just for that.
    [Environment]::SetEnvironmentVariable('HOLDBACK_PATH_REFRESH', '1', 'User')
    [Environment]::SetEnvironmentVariable('HOLDBACK_PATH_REFRESH', $null, 'User')
}

function Save-PathMark([string]$Dir) {
    New-Item -Path $MarkKey -Force | Out-Null
    Set-ItemProperty -LiteralPath $MarkKey -Name 'PathAdded' -Value $Dir
}

function Get-MachinePath { [string][Environment]::GetEnvironmentVariable('Path', 'Machine') }

# Put the bin folder on the user PATH, for new terminals, and on this session's PATH.
# Returns $true when the user PATH was changed.
function Add-BinToPath([string]$Bin) {
    if (-not (Test-PathList $env:Path $Bin)) { $env:Path = "$Bin;$env:Path" }
    $user = Get-UserPath
    if ((Test-PathList $user $Bin) -or (Test-PathList (Get-MachinePath) $Bin)) { return $false }
    Step 'PATH'
    $new = if ($user.Trim(';')) { "$Bin;$($user.TrimStart(';'))" } else { $Bin }
    Set-UserPath $new
    Save-PathMark $Bin
    Ok "Added $Bin to your user PATH"
    return $true
}

function Invoke-Setup([string]$Holdback, [object[]]$Arguments) {
    Step 'Setting up'
    $full = if ($Tty) { @('setup') + $Arguments } else { @('setup', '--yes') + $Arguments }
    if ((Invoke-Interactive $Holdback $full) -ne 0) { throw "holdback setup didn't finish. Run ``holdback setup`` to try again." }
}

function Install-Holdback([object[]]$Arguments) {
    Write-Host 'Holdback installer' -ForegroundColor White
    try {
        if (-not $Tty) { Note 'No terminal found, so nothing will be asked.' }
        $how = Select-Installer
        $bin = Install-HoldbackPackage $how
        $holdback = Find-Holdback $bin
        $added = Add-BinToPath $bin
        Invoke-Setup $holdback $Arguments
        Step 'Checking'
        Invoke-Interactive $holdback @('doctor') | Out-Null
        Write-Host ''
        Write-Host 'Done. Start a new Claude Code session to use Holdback.' -ForegroundColor White
        Say 'To remove it later: holdback uninstall --all'
        if ($added) {
            Write-Host ''
            Write-Host 'holdback works in this window now. Terminals that were already open need to be reopened to find it.' -ForegroundColor White
        }
        $global:LASTEXITCODE = 0
    } catch {
        Write-Host 'error  ' -ForegroundColor Red -NoNewline
        Write-Host $_.Exception.Message
        $global:LASTEXITCODE = 1
    }
}

# HOLDBACK_INSTALL_TEST=<file> runs that file with these functions instead of installing,
# for the tests.
if ($env:HOLDBACK_INSTALL_TEST) { . $env:HOLDBACK_INSTALL_TEST } else { Install-Holdback $SetupArgs }
} @args
