<#
.SYNOPSIS
  Banco de pruebas de modelos: les hace los mismos pedidos (circulo, casa 9x12, borrar lineas, exportar PDF) con el MISMO
  agente del panel y mide si lo lograron, cuanto tardaron y cuanto gastaron. Deja un informe .md.

.DESCRIPTION
  Sin -Vivo solo muestra el plan. Con -Vivo necesita AutoCAD abierto con el plugin cargado y claves guardadas de cada proveedor:
  crea un dibujo NUEVO en AutoCAD y trabaja SOLO ahi (nunca toca el que tengas abierto), y lo cierra sin guardar al terminar.
  Gasta de la cuenta de cada modelo (tope por caso: -Tope dolares).

  .\tools\banco_modelos.ps1                                              vista previa
  .\tools\banco_modelos.ps1 -Vivo                                        gpt-oss-120b de Groq, los 4 casos
  .\tools\banco_modelos.ps1 -Vivo -Modelos "groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,anthropic:claude-sonnet-5-5"
  .\tools\banco_modelos.ps1 -Vivo -Casos circulo,pdf -Tope 0.20
#>
param(
    [string]$Modelos = "groq:openai/gpt-oss-120b",
    [string]$Casos = "circulo,casa,borrar,pdf",
    [string]$Perfil = "descubrir",
    [double]$Tope = 0.50,
    [int]$Puerto = 8781,
    [switch]$Vivo
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$banco = Join-Path $raiz "plugin\BancoModelos"

if (-not $Vivo) {
    dotnet run --project $banco -c Release --nologo -- --modelos $Modelos --casos $Casos --tope $Tope
    return
}

if (-not (Get-Process acad -ErrorAction SilentlyContinue)) { throw "AutoCAD no esta abierto: abrelo (con el plugin cargado) y vuelve a correr esto." }

# el servidor de herramientas de Python (el mismo que usa el panel), con el AutoCAD de verdad
$py = (Get-Command python).Source
# Start-Process junta los argumentos con espacios SIN comillas: el código de -c (que lleva espacios) llegaba partido a
# Python y el servidor nunca arrancaba. Se pasa como UNA cadena con el código entre comillas dobles.
$codigo = "import sys; sys.path.insert(0, r'$raiz'); sys.path.insert(0, r'$raiz\mcp_server'); from agent import web; web.iniciar(puerto=$Puerto, abrir=False, en_autocad=False)"
$srv = Start-Process $py -ArgumentList ('-c "' + $codigo + '"') -PassThru -WindowStyle Hidden
try {
    $listo = $false
    for ($i = 0; $i -lt 30 -and -not $listo; $i++) {
        try { $listo = (Invoke-WebRequest "http://127.0.0.1:$Puerto/api/estado" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { Start-Sleep 1 }
    }
    if (-not $listo) { throw "El servidor de herramientas no arranco en el puerto $Puerto." }
    dotnet run --project $banco -c Release --nologo -- --vivo --url "http://127.0.0.1:$Puerto" --modelos $Modelos --casos $Casos --perfil $Perfil --tope $Tope
}
finally {
    Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue
    Get-NetTCPConnection -LocalPort $Puerto -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
