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

.PARAMETER CloseAutoCad
  Cierra AutoCAD antes de instalar. Sin esto, con AutoCAD abierto el script
  se niega: los DLL estan tomados y el bundle se rehace de cero, asi que
  instalar ahi lo dejaria a medio copiar.

  Le pide a AutoCAD que cierre como si apretaras la X. Si hay cambios sin
  guardar, AutoCAD pregunta y el script espera. NUNCA lo mata.

.PARAMETER Reopen
  Vuelve a abrir AutoCAD despues de instalar (solo si lo cerro el script).

.EXAMPLE
  .\tools\install_bundle.ps1
  .\tools\install_bundle.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$SkipBuild,
    [switch]$CloseAutoCad,
    [switch]$Reopen,
    [int]$CloseTimeoutSeconds = 90
)

function Get-AutoCadProcess {
    Get-Process acad -ErrorAction SilentlyContinue
}

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

# --- 0. AutoCAD abierto? -------------------------------------------------
# El bundle se rehace de cero (Remove-Item + copiar). Con AutoCAD abierto los
# DLL estan tomados: el borrado falla a mitad y queda un bundle roto, que es
# peor que no instalar. Por eso se chequea ANTES de tocar nada.
$acadPath = $null
$cerradoPorNosotros = $false
$acad = Get-AutoCadProcess

if ($acad) {
    if (-not $CloseAutoCad) {
        throw @"
AutoCAD esta abierto y tiene tomado el DLL del plugin.

  install_bundle.ps1 -CloseAutoCad           cierra AutoCAD e instala
  install_bundle.ps1 -CloseAutoCad -Reopen   ademas lo vuelve a abrir

-CloseAutoCad le pide a AutoCAD que cierre como si apretaras la X: si hay
cambios sin guardar, AutoCAD pregunta y el script espera. Nunca lo mata.
"@
    }

    $acadPath = ($acad | Select-Object -First 1).Path
    Write-Output "Cerrando AutoCAD ($($acad.Count) proceso(s))..."
    foreach ($p in $acad) { $null = $p.CloseMainWindow() }

    $limite = (Get-Date).AddSeconds($CloseTimeoutSeconds)
    while ((Get-AutoCadProcess) -and (Get-Date) -lt $limite) {
        Start-Sleep -Milliseconds 500
    }
    if (Get-AutoCadProcess) {
        throw ("AutoCAD sigue abierto despues de $CloseTimeoutSeconds s.`n`n" +
               "Puede ser por dos motivos:`n" +
               "  1. Hay un dialogo esperando respuesta (guardar los cambios?).`n" +
               "     Miralo en pantalla, resolvelo, y volve a correr esto.`n" +
               "  2. AutoCAD ignoro el pedido de cierre. Pasa: CloseMainWindow`n" +
               "     manda un WM_CLOSE y AutoCAD no siempre lo atiende.`n`n" +
               "En los dos casos la salida es la misma: cerralo a mano y corre`n" +
               "install_bundle.ps1 sin -CloseAutoCad.")
    }
    Write-Output "AutoCAD cerrado."
    $cerradoPorNosotros = $true
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
if ($Reopen -and $cerradoPorNosotros -and $acadPath) {
    Write-Output "Volviendo a abrir AutoCAD..."
    Start-Process -FilePath $acadPath | Out-Null
    Write-Output "AutoCAD abriendo. Fijate en la linea de comandos:"
} else {
    Write-Output "CERRA Y VOLVE A ABRIR AutoCAD: los bundles se leen solo al arrancar."
    Write-Output "Al abrir deberias ver en la linea de comandos:"
}
Write-Output "  [MCP] Plugin cargado. Escuchando en 127.0.0.1:8765"
Write-Output ""
Write-Output "Para desinstalarlo: .\tools\install_bundle.ps1 -Uninstall"
