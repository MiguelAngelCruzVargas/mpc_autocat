# Licencias de AutoCAD IA

Sistema para vender el producto con **pago único (perpetua)**, **anual** o **mensual**, más una **prueba gratis de 7 días**.

## Cómo funciona

```
 Cliente compra ─► tú generas una clave (admin.py) ─► se la mandas
 Cliente: activate_license("AIA-XXXXX-…") ─► servidor ─► token firmado (7 días) ─► licencia.json
 Cada comando a AutoCAD: el PLUGIN verifica el token (sin internet, con la clave pública)
 Cada ~4 días con internet: el token se renueva solo
```

- **Servidor** (`licencias/servidor/servidor.py`): guarda solo el *hash* de cada clave, a cuántos equipos se activó, y firma tokens con la **clave privada** (ECDSA P-256). Solo biblioteca estándar + `cryptography`.
- **Cliente** (`mcp_server/licencia.py`): activa, guarda el token en `%LOCALAPPDATA%\AutoCadMcp\licencia.json`, lo renueva. Tools MCP: `license_status`, `activate_license`, `start_trial`.
- **Plugin** (`plugin/AutoCadMcpPlugin/LicenciaGuard.cs`): **es el que hace cumplir.** Verifica firma, equipo, vencimiento y reloj antes de ejecutar cualquier comando. Solo exige licencia en el build vendido (`-p:Licencia=true`, lo hace `tools/empaquetar.ps1`); el build de desarrollo informa y no bloquea.
- Una clave se ata a **2 equipos** por defecto (`--equipos N`). Un token robado no sirve en otra máquina (lleva el hash del equipo). Sin internet el producto sigue hasta 7 días.
- Revocar (reembolso, abuso) surte efecto cuando el token del cliente se renueve: máximo 7 días.

## Puesta en marcha (una sola vez)

1. **Claves.** Ya generadas: la privada está en `licencias/secreto/privada.pem` (no se sube a git) y hay una **copia en `%USERPROFILE%\.autocad-ia-licencias\privada.pem`**. **Guárdala además en un gestor de contraseñas:** si la pierdes no se pueden emitir más licencias y hay que republicar el producto con otra clave pública; si se filtra, cualquiera fabrica licencias. La pública ya está dentro de `licencia.py` y `LicenciaGuard.cs`.
2. **Servidor — YA DESPLEGADO** en tu VPS: `https://vigentra-architech.vigentra.mx` (respaldo: `https://licencias.169-58-78-148.sslip.io`). Corre como contenedor Docker en `/opt/autocad-ia-licencias` (puerto 127.0.0.1:8780, Caddy delante con HTTPS automático; la base SQLite vive en el volumen `licencias-datos`). Los secretos están en `/opt/autocad-ia-licencias/.env` del VPS y el token de administración en `%USERPROFILE%\.autocad-ia-licenciasdmin_token.txt`. Para actualizar el servidor: copiar `licencias/servidor/*` al VPS y `docker compose up -d --build`. **Haz copia periódica del volumen** (`docker run --rm -v autocad-ia-licencias_licencias-datos:/d -v $PWD:/b alpine tar czf /b/licencias.tgz -C /d .`): es tu registro de ventas.
   Alternativa en Render (u otro hosting con disco persistente):
   - *New > Blueprint* sobre este repositorio (usa `licencias/servidor/render.yaml`). Hace falta el plan de pago más bajo: el gratis duerme y **no tiene disco**, y sin disco cada reinicio borra las licencias vendidas.
   - En el panel (*Environment*) carga `LICENCIA_CLAVE_PRIVADA` (el contenido del `.pem`) y `LICENCIA_ADMIN_TOKEN` (`python -c "import secrets;print(secrets.token_urlsafe(32))"`).
   - Comprueba `https://TU-SERVIDOR/salud` → `{"ok": true}`.
   - Haz copias de `/data/licencias.db` (descarga periódica): es tu registro de ventas.
3. **Paquete.**
   ```
   powershell -File tools\empaquetar.ps1
   ```
   Genera `dist\AutoCAD-IA-<versión>.zip` con el plugin que exige licencia (la dirección del servidor ya viene en `licencia.py`; `-ServidorLicencias <url>` la cambia). El administrador: `set LICENCIA_URL=https://vigentra-architech.vigentra.mx` y `set LICENCIA_ADMIN_TOKEN=<contenido de admin_token.txt>`.

## Vender

1. El cliente paga (Gumroad, Lemon Squeezy, Hotmart, transferencia…).
2. Tú: `python licencias/admin.py crear anual --nota "Nombre correo"` (o `mensual`, `perpetua`). Imprime la clave **una sola vez**.
3. Le mandas la clave y el `.zip`. Él instala y ejecuta `activate_license` (o le pide a su IA «activa mi licencia con la clave …»).
4. Renovación: `extender <kid> 365`. Cambio de PC: `liberar <kid>`.

Más adelante se puede conectar el webhook de la pasarela para que la clave salga y se envíe sola; hoy es manual a propósito (menos piezas que fallen).

## Planes y precios

El código no fija precios, solo plazos: `perpetua` (sin vencimiento), `anual` (365 días), `mensual` (30), `prueba` (7, una vez por equipo). Cualquier otro plazo: `--dias`. Los precios los pones tú en la pasarela.

## Límites honestos

- La verificación corre en la máquina del cliente. Quien se lo proponga puede **parchear el plugin** (un `.dll` de .NET se descompila fácil). Esto frena copiar el zip, usar una clave en muchos equipos, seguir después de vencer, y permite revocar. **No es a prueba de un crackeador decidido.** Lo que sí es sólido: nadie puede **fabricar** una licencia sin la clave privada.
- Mejoras posibles, de más a menos útiles: ofuscar el plugin; **firmar el código** con un certificado (quita el aviso «Unsigned Executable File» de AutoCAD y da confianza al comprar); ata la prueba gratis a una cuenta/correo.
- Antes de vender: términos de uso, aviso de que **no es un producto de Autodesk** (y que el cliente necesita su propia licencia de AutoCAD), y revisar qué datos guarda el servidor (hash de clave, hash de equipo, nombre del PC).

## Cobro con Stripe (compra en linea)

- Flujo: `https://vigentra.mx/comprar` -> Stripe Checkout -> webhook firmado `https://vigentra-architech.vigentra.mx/stripe/webhook` -> la licencia se crea SOLO con el pago confirmado -> `https://vigentra.mx/gracias` muestra la clave y la descarga (`/descargas/AutoCAD-IA-<version>.zip`, con su SHA-256).
- Precios (MXN, IVA incluido, en centavos) en `licencias/servidor/configurar_stripe.py` (`PRECIOS`): mensual 349, anual 2,290, perpetua 5,800 (lanzamiento). Para cambiarlos: editar y volver a correr el script en el VPS.
- La llave de Stripe se lee del `.env` de la consola (`/opt/vigentra-nube/.env`), asi Access y Architech comparten modo. **Con `sk_test_` el servidor no vende nada** (planes vacios, `/comprar` dice «pronto», los pagos de prueba no crean licencias). Para salir a produccion: poner la llave `sk_live_` en la consola (`nube/configurar-stripe.sh`) y despues correr en el VPS `cd /opt/autocad-ia-licencias && python3 configurar_stripe.py` (crea el webhook del modo real y reinicia).
- Al publicar una version nueva: reconstruir el zip, subirlo a `/opt/landing-vigentra/sitio/descargas/` y actualizar version y SHA-256 en `landing/gracias.html`.
- Probado con Stripe falso (`mcp_server/test_cobro.py`) y en el VPS con la llave de prueba (planes, sesion de Checkout real, firma falsa rechazada, webhook firmado -> clave entregada; esa licencia de verificacion se revoco).

### Recibo, factura, correo y renovacion (cobro con Stripe)

- **Recibo y factura-recibo:** el Checkout pide a Stripe `invoice_creation` y `tax_id_collection` (RFC): Stripe manda el recibo y la factura en PDF. **No es CFDI**: la factura fiscal del SAT la emite un PAC; hoy se pide por correo (vigentra.inf@gmail.com con la constancia fiscal). Conectar un PAC (Facturama, etc.) es un trabajo aparte.
- **Correo con la clave:** `licencias/servidor/correo.py` manda la clave por SMTP al correo del pago (en un hilo; si falla, la clave sigue en `/gracias`). Se activa en el VPS con `printf '%s\n' "$CONTRASENA" | python3 configurar_correo.py HOST PUERTO USUARIO "Vigentra Technologies <licencias@vigentra.mx>" CORREO_DE_PRUEBA` (manda un correo de prueba antes de guardar). Sin SMTP el cobro funciona igual. Con proveedor (Resend, Brevo) hay que verificar vigentra.mx en Cloudflare (SPF/DKIM/DMARC); con Gmail basta una contrasena de aplicacion.
- **Renovacion:** en `/comprar` el cliente pega su clave y el periodo se suma a la MISMA licencia (`Servicio.renovar`); solo el mismo plan; la perpetua no se renueva. En el Checkout viaja el `kid`, nunca la clave.
- Politica publicada en `/terminos`: devolucion 7 dias si no se activo (o falla irresoluble), perpetua con actualizaciones de la serie 1.x. **Pendiente revision de un abogado.**
