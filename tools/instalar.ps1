<#
.SYNOPSIS
  Instala AutoCAD IA en esta computadora: plugin de AutoCAD, servidor MCP,
  acceso directo al panel web y alta en los clientes de IA instalados.

.DESCRIPTION
  Sirve desde el paquete (carpeta o .zip descomprimido: trae el plugin ya
  compilado, no hace falta .NET) y desde el repo (compila el plugin).

  Pasos, y cada uno dice lo que hizo o por qué no:
    1. Detecta las versiones de AutoCAD instaladas (2019 en adelante).
    2. Busca Python 3.10+ (ofrece instalarlo con winget si falta).
    3. Crea el entorno virtual e instala las dependencias.
    4. Instala el plugin como App Bundle (AutoCAD debe estar cerrado).
    5. Crea el acceso directo "AutoCAD IA" en el escritorio: abre el panel
       web, donde se pone la clave de la IA que se quiera usar.
    6. Registra el servidor MCP en Claude Desktop, Claude Code y OpenCode
       (los que haya), sin pisar lo que ya tengan configurado.

  Nada se instala fuera del usuario actual, no pide administrador, y todo
  se puede deshacer con -Desinstalar.

.PARAMETER Clientes
  'auto' (default: los detectados), 'ninguno', o una lista separada por
  comas: claude-desktop, claude-code, opencode.
.PARAMETER SinPlugin
  No instala el plugin de AutoCAD.
.PARAMETER SinAtajo
  No crea el acceso directo del escritorio.
.PARAMETER Si
  No pregunta nada (acepta instalar Python con winget si falta).
.PARAMETER Desinstalar
  Quita el plugin, el acceso directo y el alta en los clientes.
.PARAMETER Destino
  Dónde queda el programa instalado (default: %LOCALAPPDATA%\AutoCadIA\app).
  Desde un paquete se COPIA ahí: así se puede borrar el .zip y la carpeta
  descomprimida sin romper nada.
.PARAMETER EnPlace
  No copiar: usar la carpeta donde está el instalador (modo desarrollo).
#>
[CmdletBinding()]
param(
    [string]$Clientes = 'auto',
    [switch]$SinPlugin,
    [switch]$SinAtajo,
    [switch]$Si,
    [switch]$Desinstalar,
    [string]$Destino = '',
    [switch]$EnPlace
)

$ErrorActionPreference = 'Stop'
$origen = Split-Path -Parent $PSScriptRoot
$raiz = $origen
# Desde un paquete (trae plugin-bundle) se instala en una carpeta permanente
# del usuario; desde el repo (sin plugin-bundle) se trabaja en el lugar.
$esPaquete = Test-Path (Join-Path $origen 'plugin-bundle\AutoCadMcp.bundle')
if ($esPaquete -and -not $EnPlace -and -not $Desinstalar) {
    $appDir = if ($Destino) { $Destino } else { Join-Path $env:LOCALAPPDATA 'AutoCadIA\app' }
    if ((Resolve-Path $origen).Path.TrimEnd('') -ne $appDir.TrimEnd('')) {
        Write-Host ""
        Write-Host "[0] Copiando el programa a $appDir" -ForegroundColor Cyan
        New-Item -ItemType Directory -Force -Path $appDir | Out-Null
        # /E copia todo; el entorno virtual (.venv) y las claves no se tocan al reinstalar.
        & robocopy $origen $appDir /E /XD '.venv' '__pycache__' /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw 'No se pudo copiar el programa.' }
        Write-Host "    OK  programa copiado" -ForegroundColor Green
    }
    $raiz = $appDir
} elseif ($Desinstalar -and $env:LOCALAPPDATA) {
    $cand = Join-Path $env:LOCALAPPDATA 'AutoCadIA\app'
    if (Test-Path $cand) { $raiz = $cand }
}
$venv = Join-Path $raiz 'mcp_server\.venv'
$pyVenv = Join-Path $venv 'Scripts\python.exe'
$server = Join-Path $raiz 'mcp_server\server.py'
$registrar = Join-Path $raiz 'tools\registrar_clientes.py'
$appdata = $env:APPDATA
$bundleDestino = Join-Path $appdata 'Autodesk\ApplicationPlugins\AutoCadMcp.bundle'
$escritorio = if ($env:AUTOCAD_IA_ESCRITORIO) { $env:AUTOCAD_IA_ESCRITORIO } else { [Environment]::GetFolderPath('Desktop') }
$atajo = Join-Path $escritorio 'AutoCAD IA.lnk'

function Paso($n, $texto) { Write-Host ""; Write-Host "[$n] $texto" -ForegroundColor Cyan }
function Ok($t) { Write-Host "    OK  $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "    !!  $t" -ForegroundColor Yellow }

$series = @{ 'R23.0' = '2019'; 'R23.1' = '2020'; 'R24.0' = '2021'; 'R24.1' = '2022';
             'R24.2' = '2023'; 'R24.3' = '2024'; 'R25.0' = '2025'; 'R25.1' = '2026'; 'R26.0' = '2027' }

function Get-AutoCadInstalados {
    $out = @()
    $base = 'HKLM:\SOFTWARE\Autodesk\AutoCAD'
    if (Test-Path $base) {
        foreach ($k in Get-ChildItem $base -ErrorAction SilentlyContinue) {
            $serie = $k.PSChildName
            if ($series.ContainsKey($serie)) { $out += [pscustomobject]@{ Serie = $serie; Anio = $series[$serie] } }
        }
    }
    return $out
}

# ---------------------------------------------------------------- desinstalar
if ($Desinstalar) {
    Paso 1 'Quitando AutoCAD IA'
    if (Get-Process acad -ErrorAction SilentlyContinue) { throw 'Cerrá AutoCAD antes de desinstalar el plugin.' }
    if (Test-Path $bundleDestino) { Remove-Item -Recurse -Force $bundleDestino; Ok 'plugin quitado' } else { Ok 'el plugin no estaba' }
    if (Test-Path $atajo) { Remove-Item -Force $atajo; Ok 'acceso directo quitado' }
    if (Test-Path $pyVenv) {
        & $pyVenv $registrar --quitar --clientes $(if ($Clientes -eq 'ninguno') { '' } else { $Clientes })
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python $registrar --quitar --clientes $(if ($Clientes -eq 'ninguno') { '' } else { $Clientes })
    }
    Write-Host ""
    Write-Host "Listo. Quedan sin borrar la carpeta del programa ($raiz) y tu clave guardada en %LOCALAPPDATA%\AutoCadMcp: borralas a mano si querés."

    return
}

# --------------------------------------------------------------------- 1
Paso 1 'AutoCAD instalado'
$acads = Get-AutoCadInstalados
if (-not $acads) {
    Aviso 'No encontré AutoCAD instalado (registro de Windows). Se instala igual: el plugin se carga cuando abras AutoCAD.'
} else {
    foreach ($a in $acads) {
        $nota = switch ($a.Serie) {
            'R25.1' { 'AutoCAD 2026: usa el plugin de .NET 8 (el de 2025). NO se probó en esta versión: si algo falla, avisá.' }
            'R26.0' { 'AutoCAD 2027: usa .NET 10 y este plugin NO lo soporta todavía.' }
            default { '' }
        }
        if ($nota) { Aviso "AutoCAD $($a.Anio): $nota" } else { Ok "AutoCAD $($a.Anio)" }
    }
}

# --------------------------------------------------------------------- 2
Paso 2 'Python 3.10 o superior'
function Get-PythonSistema {
    foreach ($cand in @(@('py', '-3'), @('python'))) {
        $exe = Get-Command $cand[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $args2 = @()
        if ($cand.Count -gt 1) { $args2 = $cand[1..($cand.Count - 1)] }
        try {
            $v = & $cand[0] @args2 -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($v -match '^(\d+)\.(\d+)$' -and ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10))) {
                return [pscustomobject]@{ Cmd = $cand[0]; Args = $args2; Version = $v }
            }
        } catch { }
    }
    return $null
}
$py = Get-PythonSistema
if (-not $py) {
    Aviso 'No encontré Python 3.10+.'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $resp = if ($Si) { 'S' } else { Read-Host '    ¿Lo instalo ahora con winget (Python 3.12, solo para tu usuario)? [S/n]' }
        if ($resp -eq '' -or $resp -match '^[sSyY]') {
            & winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
            $py = Get-PythonSistema
        }
    }
    if (-not $py) { throw 'Instalá Python 3.10 o superior desde https://www.python.org/downloads/ (marcá "Add python.exe to PATH") y volvé a correr este instalador.' }
}
Ok "Python $($py.Version)"

# --------------------------------------------------------------------- 3
Paso 3 'Entorno del servidor MCP'
if (-not (Test-Path $pyVenv)) {
    & $py.Cmd @($py.Args) -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno virtual.' }
}
& $pyVenv -m pip install --quiet --disable-pip-version-check -r (Join-Path $raiz 'mcp_server\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de dependencias (¿hay internet?).' }
Ok 'dependencias instaladas'

# --------------------------------------------------------------------- 4
Paso 4 'Plugin de AutoCAD'
if ($SinPlugin) {
    Ok 'omitido (-SinPlugin)'
} elseif (Get-Process acad -ErrorAction SilentlyContinue) {
    Aviso 'AutoCAD está abierto y tiene tomado el plugin. Cerralo y volvé a correr el instalador (o instalá solo el plugin con tools\install_bundle.ps1).'
} else {
    $listo = Join-Path $raiz 'plugin-bundle\AutoCadMcp.bundle'
    if (Test-Path $listo) {
        if (Test-Path $bundleDestino) { Remove-Item -Recurse -Force $bundleDestino }
        New-Item -ItemType Directory -Force -Path (Split-Path $bundleDestino) | Out-Null
        Copy-Item -Recurse $listo $bundleDestino
        Ok "plugin instalado en $bundleDestino"
    } elseif (Get-Command dotnet -ErrorAction SilentlyContinue) {
        & (Join-Path $raiz 'tools\install_bundle.ps1')
    } else {
        Aviso 'No hay plugin compilado en el paquete y falta .NET SDK para compilarlo.'
    }
}

# --------------------------------------------------------------------- 5
Paso 5 'Acceso directo al panel'
if ($SinAtajo) {
    Ok 'omitido (-SinAtajo)'
} else {
    $vbs = Join-Path $raiz 'AutoCAD-IA.vbs'
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($atajo)
    $lnk.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $lnk.Arguments = '"' + $vbs + '"'
    $lnk.WorkingDirectory = $raiz
    $lnk.Description = 'Panel web de AutoCAD IA: elegí la IA y poné tu clave'
    $acadExe = Get-ChildItem 'C:\Program Files\Autodesk\AutoCAD *\acad.exe' -ErrorAction SilentlyContinue | Select-Object -Last 1
    if ($acadExe) { $lnk.IconLocation = $acadExe.FullName + ',0' }
    $lnk.Save()
    Ok "creado: $atajo"
}

# --------------------------------------------------------------------- 6
Paso 6 'Clientes de IA (para que conozcan las herramientas de AutoCAD)'
if ($Clientes -eq 'ninguno') {
    Ok 'omitido'
} else {
    & $pyVenv $registrar --python $pyVenv --server $server --clientes $Clientes
    Write-Host '    Reiniciá esos programas para que tomen el cambio.'
    Write-Host '    ChatGPT de escritorio no carga herramientas locales: con esa IA usá el panel y tu clave de OpenAI.'
}

Write-Host ""
Write-Host '==============================================================' -ForegroundColor Green
Write-Host ' Listo.' -ForegroundColor Green
Write-Host '   1. Abrí AutoCAD: en la línea de comandos debe decir'
Write-Host '      [MCP] Plugin cargado. Escuchando en 127.0.0.1:8765'
Write-Host '   2. Doble clic en "AutoCAD IA" del escritorio: ahí elegís la IA'
Write-Host '      (OpenRouter, OpenAI, Anthropic, DeepSeek, local...) y pegás tu clave.'
Write-Host '   3. Para usar Claude Desktop, Claude Code u OpenCode directamente,'
Write-Host '      reinicialos: ya traen las herramientas de AutoCAD.'
Write-Host '   Aviso: es un asistente de ayuda; revisá siempre lo que dibuja.'
Write-Host '==============================================================' -ForegroundColor Green
