# Windows setup: install Python (if needed) and project requirements.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Refresh-Path {
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$user;$machine"
}

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Exe = "py"; Args = @("-3") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Exe = "python"; Args = @() }
    }
    return $null
}

Write-Host "== Clinical Cases LLMWiki: Windows setup =="

$root = Resolve-Path $PSScriptRoot
Push-Location $root

$py = Get-PythonCommand
if (-not $py) {
    Write-Host "Python not found. Installing..."

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $version = "3.12.6"
        $arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { "win32" }
        $installer = Join-Path $env:TEMP "python-$version-$arch.exe"
        $url = "https://www.python.org/ftp/python/$version/python-$version-$arch.exe"
        Write-Host "Downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $installer
        Start-Process -FilePath $installer -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1" -Wait
    }

    Refresh-Path
    $py = Get-PythonCommand
    if (-not $py) {
        Write-Error "Python install finished but python/py was not found in PATH. Restart PowerShell and run again."
        Pop-Location
        exit 1
    }
}

Write-Host ("Using Python: " + $py.Exe + " " + ($py.Args -join " "))
& $py.Exe @($py.Args) -m pip install --upgrade pip
& $py.Exe @($py.Args) -m pip install -r requirements.txt

Write-Host "Done."
Pop-Location
