<#
.SYNOPSIS
  Arma el paquete instalable de AutoCAD IA (un .zip que se descomprime y se
  instala con doble clic en INSTALAR.bat), con el plugin YA compilado.

.DESCRIPTION
  Lo corre quien desarrolla, una vez por versión. Compila el plugin en
  Release (.NET Framework 4.8 y .NET 8), arma el App Bundle y copia solo lo
  que hace falta (sin pruebas, sin entornos virtuales, sin DWG de prueba).
  Quien reciba el .zip NO necesita .NET ni Visual Studio.

  Salida: dist\AutoCAD-IA-<version>\ y dist\AutoCAD-IA-<version>.zip
#>
[CmdletBinding()]
param([switch]$SinCompilar)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$proyecto = Join-Path $raiz 'plugin\AutoCadMcpPlugin'

[xml]$pc = Get-Content (Join-Path $raiz 'plugin\bundle\PackageContents.xml')
$version = $pc.ApplicationPackage.AppVersion
$nombre = "AutoCAD-IA-$version"
$dist = Join-Path $raiz 'dist'
$salida = Join-Path $dist $nombre

if (-not $SinCompilar) {
    Write-Output 'Compilando el plugin (Release)...'
    & dotnet build $proyecto -c Release --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Falló la compilación.' }
}
$net48 = Join-Path $proyecto 'bin\Release\net48'
$net8 = Join-Path $proyecto 'bin\Release\net8.0-windows'
foreach ($d in @($net48, $net8)) {
    if (-not (Test-Path (Join-Path $d 'AutoCadMcpPlugin.dll'))) { throw "Falta el DLL en $d" }
}

if (Test-Path $salida) { Remove-Item -Recurse -Force $salida }
New-Item -ItemType Directory -Force -Path $salida | Out-Null

# --- App Bundle ya armado
$bundle = Join-Path $salida 'plugin-bundle\AutoCadMcp.bundle'
New-Item -ItemType Directory -Force -Path (Join-Path $bundle 'Contents\net48'), (Join-Path $bundle 'Contents\net8') | Out-Null
Copy-Item (Join-Path $raiz 'plugin\bundle\PackageContents.xml') $bundle
Copy-Item (Join-Path $net48 '*.dll') (Join-Path $bundle 'Contents\net48')
Copy-Item (Join-Path $net8 '*.dll') (Join-Path $bundle 'Contents\net8')
$deps = Join-Path $net8 'AutoCadMcpPlugin.deps.json'
if (Test-Path $deps) { Copy-Item $deps (Join-Path $bundle 'Contents\net8') }

# --- Código Python: sin pruebas, caches, entornos ni salidas de corridas
function Copiar-Carpeta($origen, $destino, $excluir) {
    New-Item -ItemType Directory -Force -Path $destino | Out-Null
    Get-ChildItem $origen -Force | Where-Object { $excluir -notcontains $_.Name } | ForEach-Object {
        if ($_.PSIsContainer) { Copiar-Carpeta $_.FullName (Join-Path $destino $_.Name) $excluir }
        else { Copy-Item $_.FullName $destino }
    }
}
$basura = @('.venv', '__pycache__', '.pytest_cache', 'entregables', '.git')
Copiar-Carpeta (Join-Path $raiz 'mcp_server') (Join-Path $salida 'mcp_server') $basura
Get-ChildItem (Join-Path $salida 'mcp_server\*') -Include 'test_*.py', 'smoke_test.py', 'run_tests.py', 'preview*.py' -File | Remove-Item -Force
Copiar-Carpeta (Join-Path $raiz 'agent') (Join-Path $salida 'agent') ($basura + 'test_agent.py')
New-Item -ItemType Directory -Force -Path (Join-Path $salida 'tools') | Out-Null
foreach ($f in 'instalar.ps1', 'registrar_clientes.py', 'lanzar_silencioso.bat', 'run_code_acceso.py') {
    Copy-Item (Join-Path $raiz "tools\$f") (Join-Path $salida 'tools')
}
foreach ($f in 'iniciar.py', 'AutoCAD-IA.vbs', 'AutoCAD-IA.bat', 'CLAUDE.md', 'INSTALAR.bat', 'LEEME.txt') {
    $p = Join-Path $raiz $f
    if (Test-Path $p) { Copy-Item $p $salida }
}

# --- Zip
$zip = Join-Path $dist "$nombre.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $salida -DestinationPath $zip
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Output ""
Write-Output "Paquete: $zip ($mb MB)"
Write-Output "Quien lo reciba: descomprime y hace doble clic en INSTALAR.bat"
