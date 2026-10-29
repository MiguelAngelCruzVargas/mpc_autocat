<#
.SYNOPSIS
  Firma (Authenticode) el DLL del plugin de AutoCAD IA, para que AutoCAD deje de
  preguntar "Unsigned Executable File" cada vez que el plugin cambia.

.DESCRIPTION
  AutoCAD pregunta si carga un DLL sin firma cada vez que su contenido cambia
  (y en cada actualizacion). Un DLL firmado por un editor que ya es de confianza
  no pregunta. Hay dos formas de firmar:

  1) Certificado de firma de codigo REAL (un .pfx que se compra a una autoridad
     de certificacion):   -Pfx ruta.pfx -Contrasena "..."
     Es lo que hace falta para entregar el plugin a OTRAS personas: un
     certificado autofirmado solo lo reconoce la computadora donde se creo.

  2) -Autofirmado: crea (una sola vez) un certificado de firma de codigo
     AUTOFIRMADO en tu usuario ("Vigentra Architech (desarrollo)") y firma con
     el. Sirve para ESTE equipo. Para que Windows lo considere de confianza
     hace falta -Confiar, que lo agrega a "Editores de confianza" y a "Entidades
     de certificacion raiz" de TU usuario (Windows pide confirmarlo en pantalla
     la primera vez). Sin -Confiar no se toca ninguna lista de confianza.

  Por omision firma el plugin YA instalado en
  %APPDATA%\Autodesk\ApplicationPlugins\AutoCadMcp.bundle; con -Carpeta se firma
  otro bundle (p. ej. el que arma empaquetar.ps1).

  -SoloMostrar no cambia nada: lista que DLL firmaria y con que certificado.

.NOTES
  Estado: la sintaxis y el modo -SoloMostrar estan comprobados. SIN comprobar:
  que AutoCAD 2022/2027 deje de preguntar con un certificado autofirmado de
  confianza (depende de como cada version valida al editor). Con un certificado
  comprado a una autoridad reconocida es la via documentada por Autodesk.

.EXAMPLE
  .\tools\firmar_plugin.ps1 -Autofirmado -Confiar
  .\tools\firmar_plugin.ps1 -Pfx C:\claves\vigentra.pfx -Contrasena "secreto" -Carpeta .\dist\AutoCAD-IA-1.22.0\plugin-bundle\AutoCadMcp.bundle
#>
[CmdletBinding()]
param(
    [string]$Pfx = '',
    [string]$Contrasena = '',
    [switch]$Autofirmado,
    [switch]$Confiar,
    [string]$Carpeta = '',
    [string]$Sello = 'http://timestamp.digicert.com',
    [switch]$SoloMostrar
)

$ErrorActionPreference = 'Stop'
$nombreCert = 'Vigentra Architech (desarrollo)'

if (-not $Carpeta) { $Carpeta = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\AutoCadMcp.bundle' }
if (-not (Test-Path $Carpeta)) { throw "No existe la carpeta del plugin: $Carpeta" }
$dlls = @(Get-ChildItem -Path $Carpeta -Recurse -Filter 'AutoCadMcpPlugin.dll')
if ($dlls.Count -eq 0) { throw "No encuentro AutoCadMcpPlugin.dll dentro de $Carpeta" }
if (-not $Pfx -and -not $Autofirmado) { throw 'Indica con que firmar: -Pfx ruta.pfx (certificado real) o -Autofirmado (solo este equipo).' }

function Obtener-Certificado {
    if ($Pfx) {
        if (-not (Test-Path $Pfx)) { throw "No existe el certificado: $Pfx" }
        return New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList $Pfx, $Contrasena
    }
    $existente = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq "CN=$nombreCert" -and $_.NotAfter -gt (Get-Date) } | Select-Object -First 1
    if ($existente) { return $existente }
    if ($SoloMostrar) { return $null }
    Write-Output "Creando el certificado autofirmado '$nombreCert' (5 anios) en tu usuario..."
    return New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=$nombreCert" -CertStoreLocation Cert:\CurrentUser\My `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyUsage DigitalSignature -NotAfter (Get-Date).AddYears(5)
}

$cert = Obtener-Certificado

if ($SoloMostrar) {
    Write-Output 'Modo -SoloMostrar: no se cambia nada.'
    Write-Output ("Certificado: " + $(if ($cert) { $cert.Subject + ' (' + $cert.Thumbprint + ')' } else { "'$nombreCert' (se crearia al firmar)" }))
    $dlls | ForEach-Object { Write-Output ("Firmaria: " + $_.FullName) }
    if ($Confiar) { Write-Output 'Con -Confiar tambien lo agregaria a Editores de confianza y Entidades raiz de tu usuario.' }
    return
}

if ($Confiar -and -not $Pfx) {
    $cer = Join-Path $env:TEMP 'vigentra_firma.cer'
    Export-Certificate -Cert $cert -FilePath $cer -Force | Out-Null
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\CurrentUser\Root | Out-Null     # Windows pide confirmarlo
    Write-Output 'Certificado agregado a Editores de confianza y a Entidades raiz de tu usuario.'
}

foreach ($dll in $dlls) {
    $r = $null
    try {
        $r = Set-AuthenticodeSignature -FilePath $dll.FullName -Certificate $cert -HashAlgorithm SHA256 -TimestampServer $Sello
    } catch {
        Write-Warning "No se pudo sellar la hora con $Sello (sin internet?): se firma sin sello."
        $r = Set-AuthenticodeSignature -FilePath $dll.FullName -Certificate $cert -HashAlgorithm SHA256
    }
    $estado = (Get-AuthenticodeSignature $dll.FullName).Status
    Write-Output ("{0,-14} {1}" -f $estado, $dll.FullName)
}
Write-Output ''
Write-Output 'Listo. Estado "Valid" = firmado y de confianza; "UnknownError"/"NotTrusted" = firmado, pero este equipo no confia en el editor (usa -Confiar o un certificado real).'
