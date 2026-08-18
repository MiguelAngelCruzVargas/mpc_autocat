# AutoCAD MCP — esqueleto

Plugin de AutoCAD 2022 que queda **corriendo en vivo dentro de AutoCAD**, escuchando
en un socket local, más un servidor MCP en Python que traduce tool calls de Claude
en comandos hacia ese plugin. Mismo patrón que los MCP servers de Blender: nada de
generar código para que lo abras a mano — Claude ejecuta directo sobre el dibujo abierto.

```
Claude Code / Claude Desktop
        │  (MCP, stdio)
        ▼
mcp_server/server.py  (Python)
        │  (TCP local, JSON por línea)
        ▼
plugin/AutoCadMcpPlugin  (C#, corre DENTRO del proceso de AutoCAD)
        │  (.NET API)
        ▼
Dibujo abierto en AutoCAD 2022
```

## 1. Compilar el plugin

El proyecto está *multi-target*: un solo `dotnet build` genera dos DLLs, una por
generación de AutoCAD. No hace falta tener AutoCAD instalado en la máquina donde
compilás — las referencias vienen de NuGet con `CopyLocal=false` (AutoCAD pone
las suyas reales en runtime).

```powershell
cd plugin\AutoCadMcpPlugin
dotnet restore
dotnet build -c Debug
```

Salidas:

| DLL | Para qué versión de AutoCAD |
|---|---|
| `bin\Debug\net48\AutoCadMcpPlugin.dll` | AutoCAD ~2019 a 2024 (API .NET Framework) |
| `bin\Debug\net8.0-windows\AutoCadMcpPlugin.dll` | AutoCAD 2025 en adelante (API .NET 8) |

En la máquina que sí tiene AutoCAD, copiá **las dos** carpetas (o el proyecto
entero) y usá la que corresponda a la versión real instalada.

> Si en esa máquina el build falla en el paquete NuGet del framework que no vas a
> usar (por ejemplo no existe una versión exacta de `ModPlus.AutoCAD.API.2025`
> disponible en ese momento), se puede compilar un solo target con
> `dotnet build -f net48` (o `-f net8.0-windows`) para no bloquearse por el otro.

## 2. Cargar el plugin en AutoCAD

1. Abrí AutoCAD (la versión que sea) con un dibujo (nuevo o existente).
2. En la línea de comandos: `NETLOAD`
3. Seleccioná el `AutoCadMcpPlugin.dll` que corresponda a esa versión (tabla de
   arriba — `net48` para 2019-2024, `net8.0-windows` para 2025+).
4. Deberías ver en la línea de comandos:
   ```
   [MCP] Plugin cargado. Escuchando en 127.0.0.1:8765
   ```

Si el DLL no carga (error de versión de ensamblado), es señal de que esa versión
puntual de AutoCAD necesita su propio paquete NuGet en el `.csproj` en vez de
compartir el de 2022/2025 — el código de los comandos no cambia, solo las
referencias del framework correspondiente.

Si querés que se cargue solo al abrir AutoCAD (sin NETLOAD manual cada vez), el
siguiente paso natural es un *App Bundle* / registro en `acad.rx` — no está en
este esqueleto todavía.

## 3. Probar el pipeline plugin↔socket (sin Claude)

Con el plugin ya cargado:

```powershell
cd mcp_server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python test_contract.py   # no necesita AutoCAD: chequea server.py <-> Handlers.cs
python smoke_test.py      # este si: dibuja sobre el dibujo abierto
```

> **El `.venv` no se copia entre máquinas.** Adentro guarda la ruta absoluta al
> Python que lo creó, así que traído de otra PC falla con
> `No Python at 'C:\Users\...'`. Al cambiar de máquina: borrá `mcp_server\.venv`
> y volvé a correr los tres comandos de arriba.

Si todo anda, vas a ver una capa "MUROS" nueva, una línea, un cuadrado, un
círculo y un texto en el dibujo abierto, y las respuestas de cada llamada
impresas en consola.

## 4. Conectar el servidor MCP a Claude Code

El repo ya trae un [`.mcp.json`](.mcp.json) con rutas **relativas** a la raíz
del proyecto, así que abriendo Claude Code desde esta carpeta el server se
levanta solo — sin reconfigurar nada al cambiar de máquina. Si por algún motivo
no lo tomara, la alternativa explícita es:

```powershell
claude mcp add autocad -- .\mcp_server\.venv\Scripts\python.exe .\mcp_server\server.py
```

Con AutoCAD abierto y el plugin cargado, ya podés pedirle a Claude cosas como
"creá una polilínea cerrada de 200x100 en la capa MUROS y decime el área".

## Tools disponibles ahora

| Categoría | Tool | Qué hace |
|---|---|---|
| Geometría | `create_line` | Línea entre dos puntos 3D |
| | `create_polyline` | Polilínea 2D a partir de una lista de puntos, abierta o cerrada |
| | `create_circle` | Círculo por centro y radio |
| | `create_arc` | Arco por centro, radio y ángulos inicial/final |
| Anotación | `create_text` | Texto de una línea (DBText) |
| | `create_mtext` | Texto multilínea con ancho de ajuste |
| | `create_dimension` | Cota alineada entre dos puntos |
| | `create_leader` | Línea de referencia con flecha + texto (callout hacia un detalle) |
| | `create_hatch` | Rellena una entidad cerrada con un patrón (SOLID para leyendas, ANSI31/AR-CONC etc. para materiales) |
| Bloques / imágenes | `insert_block` | Inserta un símbolo (bloque), con atributos e importación desde un `.dwg` externo si hace falta |
| | `define_block` | Captura entidades ya dibujadas (por handle) como un bloque reutilizable — sin archivo externo, sirve para armar símbolos propios (norte, registros, etc.) una vez y repetirlos |
| | `attach_image` | Inserta una imagen raster ya existente en disco (logo, mapa de microlocalización) — no genera el contenido, solo la coloca |
| Capas | `set_layer` | Crea/configura una capa: color ACI, tipo de línea, grosor (simbología/normas) |
| | `list_layers` | Lista capas con sus propiedades |
| Edición | `move_entity` / `copy_entity` / `rotate_entity` / `scale_entity` / `delete_entity` | Transformaciones básicas sobre una entidad existente, por handle |
| | `offset_entity` | Curva paralela a otra a una distancia dada (p.ej. guarnición paralela al eje de una calle) |
| Consulta | `list_entities` | Lista entidades del espacio modelo (filtro opcional por tipo) |
| | `get_entity` | Propiedades completas de una entidad por handle |
| | `calculate_area` | Área de una Polyline cerrada / Region / Circle |
| | `get_drawing_info` | Nombre de archivo, unidades, capa actual, cantidad de entidades |
| Vista | `zoom_extents` | Zoom a extensión completa (stub simple vía línea de comandos) |
| | `set_display_options` | Activa/desactiva la visualización de grosores (LWDISPLAY) y fija el grosor por defecto (LWDEFAULT) |

## Grosores de línea (por qué se veía todo fino)

Dos cosas distintas, y las dos hacen falta:

1. **Que el grosor exista.** Toda tool de creación acepta ahora `lineweight` en
   centésimas de mm (`50` = 0.50mm) que pisa el de la capa solo para esa
   entidad, y `color_index` (ACI) para lo mismo con el color. Sin pasarlos, la
   entidad queda `ByLayer` — y una capa recién creada nace con el grosor por
   defecto del dibujo, que es fino. Jerarquía típica de un plano:

   | Qué | `lineweight` |
   |---|---|
   | Muros cortados, contorno de corte | 50-70 |
   | Contornos vistos, mobiliario | 25-35 |
   | Ejes, cotas, leaders, auxiliares | 13-18 |
   | Achurados / rellenos | 5-13 |

2. **Que el grosor se vea.** AutoCAD trae `LWDISPLAY` apagado de fábrica: sin
   eso, un dibujo con capas de 0.50mm se sigue viendo todo a 1 píxel. El plugin
   ahora la prende al cargarse y cada vez que se activa un dibujo (la variable
   se guarda *por dibujo*, así que un DWG viejo la puede traer apagada). Para
   forzarlo a mano: `set_display_options(lineweight_display=True)`.

Ojo con la unidad del dibujo: los grosores son absolutos en mm de papel, no
escalan con el dibujo. Lo que sí escala es el texto/cotas — para eso está el
parámetro `scale` de `create_dimension`.

## Próximos pasos (no implementados todavía)

- Layouts / viewports reales para cortes y vistas con nombre (`zoom_extents` es
  un placeholder de esto).
- Estilos de texto/cota con nombre (hoy usan el estilo por defecto del dibujo).
- Splines (para trazos curvos que no sean arcos circulares).
- Reconexión / múltiples documentos abiertos a la vez.
- Autocarga del plugin (App Bundle) en vez de `NETLOAD` manual.

**Sin probar contra AutoCAD real todavía** (compilan, pero no hay forma de
correrlas sin AutoCAD instalado acá — probar estas primero cuando llegues a la
otra máquina):
- `insert_block` con importación desde DWG externo (usa `Database.Insert`).
- `attach_image` (API de `RasterImageDef`/`RasterImage`, la más áspera de toda la tanda).
- `create_hatch` y `create_leader`.
- `offset_entity` en curvas con más de un resultado posible (arcos cerrados, etc.).

## Notas de diseño

- **Un socket TCP en loopback** (`127.0.0.1:8765`, configurable con la variable de
  entorno `ACAD_MCP_PORT`) en vez de named pipes: más fácil de debuggear a mano
  (hasta con `telnet`/`nc`), menos fricción con el hilo de UI de AutoCAD.
- **Todo comando se marshaliza al hilo de documento** vía
  `Application.DocumentManager.ExecuteInCommandContextAsync` + `LockDocument()`
  — tocar la `Database` desde el hilo del socket directamente crasheás AutoCAD.
- **El timeout del cliente tiene que ser mayor que el del plugin.** El plugin
  espera hasta 60s a que AutoCAD ejecute el comando (`ACAD_MCP_EXEC_TIMEOUT`) y
  el cliente Python espera 75s (`ACAD_MCP_TIMEOUT`). Al revés, el cliente
  abandona primero, cierra el socket, y el plugin termina escribiendo sobre una
  conexión muerta.
- **Ninguna excepción puede escapar del hilo del socket.** Una excepción no
  atrapada en un hilo de fondo mata el proceso — o sea, se cae AutoCAD con el
  dibujo del usuario adentro. Por eso `TcpServer.SafeHandleClient` envuelve
  todo, y el log de errores de ese hilo va a `Trace` y no al `Editor` (tocar la
  API de AutoCAD desde ahí es justo lo que estamos evitando).
- **`System.Text.Json` en vez de `Newtonsoft.Json`** en el lado C# para evitar
  choques de versión con el `Newtonsoft.Json` que AutoCAD ya trae cargado.
