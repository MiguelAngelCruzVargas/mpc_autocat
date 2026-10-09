# Motor de API de AutoCAD (`run_code`) + 3D desde la planta

Fecha: 2026-10-09 · Rama: `motor-api-autocad` · Respaldo: tag `respaldo-2026-10-09`

## Qué quiere el usuario (dicho por él)

No quiere "un MCP más". Quiere poder decirle a la IA *"hazme este plano,
estas son mis medidas, el terreno es así, ocupo estos materiales"* y que la
IA, apoyada en esta herramienta, **manipule AutoCAD sin límite**: incluido
pasar el diseño a 3D, cosa que hoy no puede.

El problema que señala: cada capacidad nueva hoy cuesta una cadena entera
—comando C# → recompilar → reiniciar AutoCAD → tool Python → descripción →
párrafo en `CLAUDE.md`— y "las herramientas tienen a veces más prompt que
código". Con 66 comandos fijos y ninguno 3D, la IA solo puede hacer lo que
alguien le fabricó de antemano.

## La idea en una línea

Una sola puerta genérica a toda la API .NET de AutoCAD (`run_code`), y que
las capacidades nuevas se escriban **del lado Python como plantillas de
código** que pasan por esa puerta: sin recompilar el plugin, sin reiniciar
AutoCAD, sin agregar prosa al prompt.

## Capas

```
IA
 │  pide resultados ("la casa en 3D") o, si no hay tool, escribe código
 ▼
Capa de oficio (Python, ya existe + lo nuevo)
 │  suggest_layout, draw_layout, checks, cuantificación…
 │  NUEVO: create_3d_model (3D desde la planta) — plantilla C# sobre run_code
 ▼
Capa de acceso total (NUEVO)
 │  run_code      → ejecuta C# contra la API de AutoCAD, devuelve datos
 │  describe_api  → la IA consulta tipos/miembros de la API cuando los necesita
 │  api_guide     → guías cortas por tema, bajo demanda (no en cada vuelta)
 ▼
Plugin C# (un comando nuevo: run_code) → AutoCAD
```

Las 138 tools actuales no se tocan: siguen siendo los atajos que saben de
oficio. `run_code` cubre todo lo demás.

## 1. `run_code` en el plugin

Un `case "run_code"` en `Handlers.cs` y una clase `RunCodeCommand`.

**Entrada:** `code` (cuerpo de un método C#), `description` (qué intenta,
para el log), `compile_only` (bool, default false).

**Cómo se ejecuta.** El cuerpo se envuelve en una clase plantilla con
`using` de los espacios de nombres de AutoCAD y estas variables ya listas:

| Variable | Qué es |
|---|---|
| `doc`, `db`, `ed` | documento activo, su base de datos, su editor |
| `tr` | transacción ya abierta |
| `space` | el `BlockTableRecord` del espacio activo, abierto para escritura |
| `H("2A3")` | `ObjectId` a partir de un handle |
| `Add(entity)` | agrega al espacio + a la transacción y devuelve el handle |
| `Print(...)` | texto que vuelve en la respuesta |

Se compila en memoria con Roslyn (`Microsoft.CodeAnalysis.CSharp`, que
compila para net48 y net8) y se corre en el hilo del documento, con el
documento bloqueado, como cualquier otro comando del plugin.

**Atomicidad.** Todo corre dentro de una marca de undo y de UNA transacción:
si el código tira una excepción, la transacción se aborta y el dibujo queda
exactamente como estaba. Un `undo` después de un `run_code` exitoso lo
deshace entero.

**Salida:**

- `result`: lo que devuelva el código, serializado (números, textos, listas,
  `ObjectId` → handle, `Point3d` → `[x,y,z]`, entidad → resumen con tipo,
  capa y caja).
- `output`: lo impreso con `Print`.
- `created`: handles y cajas de lo que se agregó a la base de datos (se
  detecta con el evento `ObjectAppended`, no confiando en el código).
- `errors`: si no compila, cada error con línea, columna y mensaje
  **referidos al código que mandó la IA**, no a la plantilla. Es lo que le
  permite corregirse sola.
- `elapsedMs`.

**Caché.** Lo compilado se guarda por hash del código: la plantilla de 3D
que se corre veinte veces se compila una.

## 2. Red de seguridad

`run_code` da acceso total, así que puede hacer daño total. Lo que se
puede atajar se ataja; lo que no, se dice.

- **Excepción .NET** → transacción abortada, dibujo intacto, error devuelto.
- **Caída de AutoCAD** (un `AccessViolation` no se puede atrapar): antes de
  cada `run_code`, si el dibujo tiene cambios sin guardar y un path
  conocido, el servidor Python llama a `save_drawing` solo. Si es un
  `Drawing1` sin nombre, lo devuelve en `warning` y no ejecuta hasta que
  haya path, salvo `force=True`.
- **Bucle infinito**: no se puede cortar un código que corre en el hilo de
  AutoCAD. El dispatcher ya devuelve timeout al cliente; se documenta que
  AutoCAD queda ocupado hasta que termine.
- **Memoria**: en net48 un assembly cargado no se descarga; cada código
  distinto suma unos KB. Con la caché por hash, despreciable en una sesión.
- **Alcance**: no hay sandbox; es el AutoCAD local del usuario, el mismo
  nivel de acceso que ya tiene quien maneja la IA. Escucha solo en
  loopback, igual que hoy.

## 3. `describe_api` y `api_guide`: el conocimiento bajo demanda

El motivo de fondo del pedido es que el prompt no siga creciendo.

- **`describe_api(type_name, filter="")`** — por reflexión, dentro de
  AutoCAD (implementada como una plantilla de `run_code`, sin comando C#
  propio): constructores, métodos con su firma, propiedades con su tipo.
  `describe_api("Solid3d", "Extrude")` devuelve las sobrecargas reales de
  la versión de AutoCAD instalada, no las que el modelo recuerde.
- **`api_guide(topic)`** — guías cortas en `mcp_server/guias/*.md`, una por
  tema (`3d`, `seleccion`, `bloques`, `capas-y-estilos`, `layouts`,
  `errores-comunes`). Sin `topic` devuelve el índice. Se leen cuando hacen
  falta, no viajan en cada vuelta.

`CLAUDE.md` gana un párrafo: *"si no hay tool para lo que necesitás, usá
`api_guide` + `describe_api` + `run_code`"*. Adelgazar el resto de
`CLAUDE.md` pasándolo a guías es la etapa siguiente, no esta.

## 4. Primera capacidad sobre el motor: `create_3d_model`

La prueba de que el modelo funciona: una tool de oficio nueva **escrita
solo en Python**, que genera C# y lo corre con `run_code`. No toca el
plugin ni pide reiniciar AutoCAD.

**Entrada:** los mismos `rooms`/`doors`/`windows` que usan `draw_layout` y
`suggest_layout`, más alturas con default de obra:
`wall_height` 2.50, `door_height` 2.10, `sill_height` 0.90,
`window_head` 2.10, `slab_thickness` 0.12, y `base_z` 0.

**Qué dibuja:**

1. **Muros:** los lazos de `wall_network.resolve` (los mismos contornos ya
   rematados de la planta) → `Region` → `Solid3d.Extrude` a `wall_height`.
2. **Vanos:** por cada puerta, una caja de su ancho × espesor del muro ×
   `door_height` restada del muro (`BooleanOperation Subtract`); por cada
   ventana, una caja entre `sill_height` y `window_head`.
3. **Losa:** el contorno exterior extruido `slab_thickness` sobre
   `wall_height`. Opcional con `slab=False`.
4. **Capas:** `3D-MUROS`, `3D-LOSA`, con color de la paleta del proyecto
   (no los colores puros 1-7).
5. **Vista:** el modelo va a una zona aparte del modelo 2D (corrido en X
   lo que indique `offset`, default 1.5 × el ancho del terreno), y la tool
   devuelve una vista isométrica SO con estilo visual realista, lista para
   `capture_viewport`.

**Devuelve:** handles por categoría, volumen de mampostería y de losa (de
`Solid3d.MassProperties`, que sirven para cuantificar), y avisos si algún
vano no se pudo restar.

Fuera de esta etapa, a propósito: techos inclinados, escaleras 3D,
materiales de render, cimentación en 3D. Con el motor andando, cada una es
otra plantilla Python.

## 5. Integración con lo que ya existe

- **Huellas**: lo que devuelva `created` se registra en `space` como hoy
  hace cada tool, así `place_labels` y `check_annotations` lo ven.
- **Contador de guardado** (`session.py`): `run_code` cuenta como una
  operación de dibujo.
- **Contrato** (`test_contract.py`): `run_code` tiene su `case`; las tools
  que son plantillas (`describe_api`, `create_3d_model`) se marcan como
  "sin comando propio", igual que las tools compuestas de hoy.
- **Agente propio** (`agent/`): `run_code`, `describe_api` y `api_guide`
  entran en todos los perfiles; `create_3d_model` en `arquitectura`.

## 6. Pruebas

- **Primero una prueba de factibilidad**: cargar Roslyn dentro del AutoCAD
  2022 real y correr `return 1 + 1;`. Es el mayor riesgo técnico: Roslyn
  en net48 trae `System.Collections.Immutable` y `System.Reflection.Metadata`,
  que pueden chocar con versiones que AutoCAD ya tiene cargadas. Si choca,
  el plan B para net48 es `CSharpCodeProvider` (viene con .NET Framework,
  sin dependencias, pero solo C# 5: se avisa en el error de compilación).
- **Offline** (las suites de siempre, sin AutoCAD): la generación de las
  plantillas C# de `create_3d_model` y `describe_api`, el armado de la
  respuesta, el mapeo de errores de compilación a líneas del código de la
  IA, el autoguardado previo.
- **Compilación de plantillas sin AutoCAD**: `run_code` con
  `compile_only=True` en `test_live`, para que una plantilla rota se
  detecte antes de usarla.
- **En vivo** (`test_live.py`, con AutoCAD abierto y el turno de AutoCAD
  tomado en el tablero de coordinación): `run_code` crea, falla y aborta
  sin dejar rastro, y `undo` lo deshace; `create_3d_model` sobre la casa de
  `suggest_layout` da sólidos con el volumen esperado; captura de la vista
  3D para mirarla.

## 7. Orden de trabajo

1. Prueba de factibilidad de Roslyn en AutoCAD 2022 (decide Roslyn o
   CodeDom en net48).
2. `run_code` en el plugin + tool Python + red de seguridad.
3. `describe_api` + `api_guide` con las primeras guías (`3d` primero).
4. `create_3d_model`.
5. Recompilar, instalar bundle, **reiniciar AutoCAD una vez**, `test_live`.

A partir de ahí, una capacidad nueva de AutoCAD es Python + guía, sin
tocar el plugin.

## Lo que no entra en esta etapa

- Adelgazar `CLAUDE.md` y partir `server.py` (etapa siguiente).
- Reconocer planos ajenos (muros/recintos en un DWG que no dibujó el MCP).
- Ejecutar AutoLISP o comandos de línea; si hace falta, es otra plantilla.
