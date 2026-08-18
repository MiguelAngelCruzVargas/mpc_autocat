<#
.SYNOPSIS
  Compila el plugin y lo instala como App Bundle, para que AutoCAD lo cargue
  solo al arrancar (se acabó el NETLOAD manual cada vez).

.DESCRIPTION
  Arma %APPDATA%\Autodesk\ApplicationPlugins\AutoCadMcp.bundle con los dos
  DLLs (net48 para AutoCAD 2019-2024, net8 para 2025+) y sus dependencias.
  AutoCAD elige solo cuál cargar según su versión.

  AutoCAD lee los bundles UNA VEZ al arrancar: hay que cerrarlo y volver a
  abrirlo para que tome cambios.

.PARAMETER Uninstall
  Borra el bundle instalado en vez de instalarlo.

.PARAMETER SkipBuild
  Usa los DLL ya compilados en bin\Debug en lugar de recompilar.

.EXAMPLE
  .\tools\install_bundle.ps1
  .\tools\install_bundle.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$projectDir = Join-Path $repoRoot 'plugin\AutoCadMcpPlugin'
$bundleSource = Join-Path $repoRoot 'plugin\bundle'
$target = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\AutoCadMcp.bundle'

if ($Uninstall) {
    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
        Write-Output "Bundle desinstalado: $target"
        Write-Output "Reinicia AutoCAD para que deje de cargarlo."
    } else {
        Write-Output "No habia nada instalado en $target"
    }
    return
}

# --- 1. Compilar ---------------------------------------------------------
if (-not $SkipBuild) {
    Write-Output "Compilando el plugin..."
    & dotnet build $projectDir -c Debug --nologo
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la compilacion; no se instala nada."
    }
}

$net48 = Join-Path $projectDir 'bin\Debug\net48'
$net8 = Join-Path $projectDir 'bin\Debug\net8.0-windows'

if (-not (Test-Path (Join-Path $net48 'AutoCadMcpPlugin.dll'))) {
    throw "No se encontro el DLL de net48. Compila primero (sin -SkipBuild)."
}

# --- 2. Armar la estructura del bundle -----------------------------------
# Se rehace de cero: si quedaran DLLs de una version anterior, AutoCAD podria
# cargar una mezcla y los sintomas son incomprensibles.
if (Test-Path $target) {
    Remove-Item -Recurse -Force $target
}
New-Item -ItemType Directory -Force -Path $target | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $target 'Contents\net48') | Out-Null

Copy-Item (Join-Path $bundleSource 'PackageContents.xml') $target

# El plugin y sus dependencias NuGet (System.Text.Json y compania): el
# AssemblyResolve de PluginEntry las busca al lado del DLL.
Copy-Item (Join-Path $net48 '*.dll') (Join-Path $target 'Contents\net48')
$pdb48 = Join-Path $net48 'AutoCadMcpPlugin.pdb'
if (Test-Path $pdb48) { Copy-Item $pdb48 (Join-Path $target 'Contents\net48') }

if (Test-Path (Join-Path $net8 'AutoCadMcpPlugin.dll')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $target 'Contents\net8') | Out-Null
    Copy-Item (Join-Path $net8 '*.dll') (Join-Path $target 'Contents\net8')
    $deps = Join-Path $net8 'AutoCadMcpPlugin.deps.json'
    if (Test-Path $deps) { Copy-Item $deps (Join-Path $target 'Contents\net8') }
} else {
    Write-Warning "No hay DLL de net8: el bundle solo servira para AutoCAD 2019-2024."
}

# --- 3. Reportar ---------------------------------------------------------
$count = (Get-ChildItem -Recurse -File $target | Measure-Object).Count
Write-Output ""
Write-Output "Bundle instalado en: $target"
Write-Output "  $count archivos"
Write-Output ""
Write-Output "CERRA Y VOLVE A ABRIR AutoCAD: los bundles se leen solo al arrancar."
Write-Output "Al abrir deberias ver en la linea de comandos:"
Write-Output "  [MCP] Plugin cargado. Escuchando en 127.0.0.1:8765"
Write-Output ""
Write-Output "Para desinstalarlo: .\tools\install_bundle.ps1 -Uninstall"
