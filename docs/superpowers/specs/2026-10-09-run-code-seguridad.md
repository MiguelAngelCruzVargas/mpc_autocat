# Cómo proteger `run_code` — opciones para decidir

Fecha: 2026-10-09 · Complementa `2026-10-09-motor-api-autocad-design.md` §2.

`run_code` compila y corre C# **dentro de acad.exe, con los permisos del
usuario**. No es solo "acceso total a AutoCAD": es acceso total a la
máquina (archivos, red, procesos, registro). La spec ya cubre los
accidentes (transacción abortada, autoguardado). Esto cubre **quién puede
llegar a mandar código** y qué se puede atajar antes de que corra.

## Por dónde puede entrar código que el usuario no quiso

| # | Vía | Hoy (sin run_code) | Con run_code |
|---|---|---|---|
| 1 | **Una página web cualquiera** abierta en el navegador hace `fetch` a la interfaz del agente (`127.0.0.1:8770/api/chat`). Un POST `text/plain` ni siquiera pasa por el preflight de CORS. | Gasta la API key y dibuja/borra en AutoCAD | Ejecuta código en la máquina |
| 2 | **Inyección por contenido**: texto que el modelo lee y obedece — una imagen de referencia, el texto de un DWG ajeno, un PDF, una página web. | Dibuja algo raro | Escribe el C# que el texto le dicte |
| 3 | **Otro proceso local** escribe en el socket del plugin (`127.0.0.1:8765`, sin autenticación). | Manda comandos de dibujo | Ejecuta código |
| 4 | **Error del modelo** (sin malicia): borra de más, bucle infinito, `AccessViolation`. | Acotado a los 66 comandos | Cualquier cosa |
| 5 | **Modelos baratos** desde `agent/`, que se equivocan más y no tienen el cuidado de Claude Code. | Idem 4 | Idem 4, más seguido |

**La vía 1 ya está cerrada** (sesion-muros, en `agent/web.py`):
`pedido_confiable()` exige que `Host` sea `127.0.0.1`/`localhost` del puerto
propio (corta el DNS rebinding) y que `Origin`/`Sec-Fetch-Site`, que el
navegador pone solo y una página no puede falsificar, sean de la propia
interfaz. Probado contra el servidor real: interfaz propia 200, página
ajena 403, Host ajeno 403. Valía la pena aunque `run_code` no salga.

## Medidas, con lo que ataja y lo que NO

| Medida | Ataja | No ataja | Costo |
|---|---|---|---|
| **A. Apagado por defecto.** `run_code` no existe hasta que el usuario lo habilita (variable de entorno o `config`); el plugin responde "deshabilitado". | Todo, mientras esté apagado | Nada una vez prendido | Bajo |
| **B. Token en el socket.** El plugin genera un secreto al arrancar en `%LOCALAPPDATA%\AutoCadMcp\token`; `autocad_client` lo manda en cada pedido; sin token, rechazo. | 3 desde otros usuarios / procesos que no leen ese archivo | Malware que ya corre como el usuario (puede leer el archivo) | Bajo: plugin + cliente |
| **C. Log de todo lo ejecutado** (código, `description`, quién, resultado) en `%LOCALAPPDATA%\AutoCadMcp\run_code.log`. | Nada en el momento; da auditoría | — | Bajo |
| **D. Lista de APIs prohibidas, por análisis semántico** (Roslyn `SemanticModel`, no por texto): `System.IO`, `System.Net`, `System.Diagnostics.Process`, `Microsoft.Win32`, `System.Reflection` (incluye `Assembly.Load`, `Emit`), `System.Runtime.InteropServices` (`DllImport`), `dynamic`, `Environment`, `AppDomain`; y de AutoCAD lo que toca disco o comandos: `Database.SaveAs`/`ReadDwgFile`, `DocumentManager.Open`/`Add`, `SendStringToExecute`, `Editor.Command` (AutoCAD tiene `SHELL`). Si aparece, no compila y el error dice qué tool usar en su lugar. | 4 y 5 casi por completo; 2 de esfuerzo bajo | Un atacante decidido: en proceso, una lista negra no es un sandbox | Medio: un recorrido de símbolos tras compilar |
| **E. Confirmación del usuario por ejecución**, mostrando el código. En Claude Code ya existe: es el permiso por tool — basta con **no** poner `run_code` en la allowlist. En la web del agente hace falta un diálogo. | 2, 4 y 5, si el usuario lee lo que aprueba | Cansancio de aprobar | Bajo en Claude Code; medio en la web |
| **F. Solo lectura por defecto.** `run_code(write=False)`: la transacción se aborta SIEMPRE al final, devuelva lo que devuelva. Para escribir hay que pedir `write=True` (y ahí entra E). `describe_api` y las consultas no necesitan más. | 4 en las consultas (la mayoría) | Lo que se hace con `write=True` | Bajo |
| **G. Autoguardado previo + marca de undo** (ya en la spec). | Pérdida de trabajo por 4 | — | Ya previsto |

## Recomendación

Lo mínimo para prender el motor, sin trabar el uso:

1. **A + B + C** (las tres de autocad-ia-24): baratas y sin efecto en el
   uso normal.
2. **D**: es lo que convierte "acceso total a la máquina" en "acceso total
   a AutoCAD", que es lo que el usuario pidió. El motor para dibujar no
   necesita leer archivos ni abrir sockets; si algún día hace falta, se
   agrega una tool de oficio para eso.
3. **F**: la mayoría de los `run_code` van a ser consultas; que no puedan
   romper nada sale casi gratis.
4. **E** en la web del agente antes de exponerle `run_code` (los modelos
   baratos son la vía 5), y en Claude Code no aprobarlo en bloque.

Con eso el riesgo residual queda acotado a: alguien que ya corre código
como el usuario (que ya podía hacer todo) y un usuario que aprueba sin
leer. Eso conviene decírselo al usuario tal cual, no prometer un sandbox.

Lo que el usuario tiene que decidir: si con A–G alcanza para habilitar
`run_code`, o si prefiere la alternativa sin código arbitrario (una
pasarela de objetos acotada) aunque cubra menos de la API.
