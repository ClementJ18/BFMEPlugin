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
