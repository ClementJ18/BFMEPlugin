# Get the folder this script is in
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Absolute path to plugin folder
$PluginFolder = Join-Path $ScriptDir "BFMEPlugin"

# Absolute path for output package
$OutputFile = Join-Path $ScriptDir "BFMEPlugin.sublime-package"

# Remove old package if it exists
if (Test-Path $OutputFile) {
    Remove-Item $OutputFile -Force
}

# Load compression tools
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Create package (zip)
[System.IO.Compression.ZipFile]::CreateFromDirectory($PluginFolder, $OutputFile)

Write-Host "Packaged $PluginFolder into $OutputFile"
 
# Copy package to Sublime Text Installed Packages directory
$SublimeInstalledPackages = "$env:APPDATA\Sublime Text\Installed Packages"
if (Test-Path $SublimeInstalledPackages) {
    Copy-Item $OutputFile -Destination $SublimeInstalledPackages -Force
    Write-Host "Copied $OutputFile to $SublimeInstalledPackages"
} else {
    Write-Host "Sublime Text Installed Packages directory not found: $SublimeInstalledPackages"
}
