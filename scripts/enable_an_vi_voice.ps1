# Run this script as Administrator to expose Microsoft An (OneCore) to SAPI5 Desktop.
# pyttsx3 on Windows reads from HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens.

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Please run PowerShell as Administrator."
    }
}

function Copy-RegistryValues {
    param(
        [Parameter(Mandatory = $true)] [string] $SourcePath,
        [Parameter(Mandatory = $true)] [string] $DestinationPath
    )

    if (-not (Test-Path $DestinationPath)) {
        New-Item -Path $DestinationPath -Force | Out-Null
    }

    $props = Get-ItemProperty -Path $SourcePath
    foreach ($p in $props.PSObject.Properties) {
        if ($p.Name -in @("PSPath", "PSParentPath", "PSChildName", "PSDrive", "PSProvider")) {
            continue
        }
        New-ItemProperty -Path $DestinationPath -Name $p.Name -Value $p.Value -Force | Out-Null
    }
}

Assert-Admin

$oneCoreRoot = "HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
$oneCoreToken = Join-Path $oneCoreRoot "MSTTS_V110_viVN_An"

if (-not (Test-Path $oneCoreToken)) {
    throw "Microsoft An OneCore voice not found at: $oneCoreToken"
}

$desktopRoot = "HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens"
$desktopToken = Join-Path $desktopRoot "TTS_MS_vi-VN_AN_11.0"

Copy-RegistryValues -SourcePath $oneCoreToken -DestinationPath $desktopToken

$srcAttrs = Join-Path $oneCoreToken "Attributes"
$dstAttrs = Join-Path $desktopToken "Attributes"
if (Test-Path $srcAttrs) {
    Copy-RegistryValues -SourcePath $srcAttrs -DestinationPath $dstAttrs
}

Write-Host "Done. Restart the app and call GET /v1/tts/voices to verify Microsoft An is available." -ForegroundColor Green
