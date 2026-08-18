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
python test_geom.py       # tampoco: geometria de muros (inglete, tramos)
python test_arch.py       # tampoco: muros, huecos, abatimientos, ejes
python smoke_test.py      # este si: dibuja sobre el dibujo abierto
python demo_plan.py       # este tambien: plano completo de punta a punta
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
| **Lámina** | **`create_sheet`** | **Cajón (marco + márgenes) y cuadro de rotulación con los datos de la obra. Es el primer paso de todo plano: devuelve el área útil donde va el dibujo** |
| **Arquitectura** | **`create_walls`** | **Muros con espesor real (doble línea), esquinas a inglete y huecos de puertas/ventanas ya recortados** |
| | `create_axis_grid` | Ejes estructurales con globos: verticales 1,2,3 y horizontales A,B,C |
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
| Mobiliario | `place_furniture` | Camas, sillones, comedor, cocina y sanitarios en planta; varias piezas por llamada |
| | `label_rooms` | Rotula ambientes con nombre y superficie, esquivando el mobiliario |
| Capas | `set_layer` | Crea/configura una capa: color ACI, tipo de línea, grosor (simbología/normas) |
| | `list_layers` | Lista capas con sus propiedades |
| Edición | `move_entity` / `copy_entity` / `rotate_entity` / `scale_entity` / `delete_entity` | Transformaciones básicas sobre una entidad existente, por handle |
| | `offset_entity` | Curva paralela a otra a una distancia dada (p.ej. guarnición paralela al eje de una calle) |
| Consulta | `list_entities` | Lista entidades del espacio modelo (filtro opcional por tipo) |
| | `get_entity` | Propiedades completas de una entidad por handle |
| | `calculate_area` | Área de una Polyline cerrada / Region / Circle |
| | `get_drawing_info` | Nombre de archivo, unidades, capa actual, cantidad de entidades |
| Curvas | `create_spline` | Curva suave que pasa por los puntos dados (curvas de nivel, trazos irregulares) |
| Layouts | `create_layout` | Crea una lámina de espacio papel, con dispositivo y tamaño de papel |
| | `create_viewport` | Ventana del layout que muestra el modelo a escala fija |
| | `list_layouts` / `set_current_layout` | Lista las láminas y cambia la activa |
| Estilos | `set_text_style` | Estilo de texto con nombre (fuente, ancho, oblicuidad) |
| | `set_dim_style` | Estilo de cota con nombre (texto, flechas, decimales, factor de unidades) |
| | `list_styles` | Lista estilos de texto y cota, marcando los activos |
| Documentos | `list_documents` / `set_active_document` | Varios dibujos abiertos: lista y elige sobre cuál operar |
| | `ping` | Confirma que el plugin responde y con qué versión está cargado |
| Vista | `zoom_extents` | Zoom a extensión completa (stub simple vía línea de comandos) |
| | `set_display_options` | Activa/desactiva la visualización de grosores (LWDISPLAY) y fija el grosor por defecto (LWDEFAULT) |

## La lámina: cajón y rotulación

Todo plano arranca con `create_sheet`, que dibuja el **cajón** (borde de hoja +
marco con márgenes, 25mm a la izquierda para encuadernar) y el **cuadro de
rotulación** abajo a la derecha:

```
OBRA            <nombre de la obra>
UBICACIÓN       <dirección>
PROPIETARIO     <cliente>
CONTENIDO       <qué muestra esta lámina>
ESCALA │ FECHA │ DIBUJÓ │ REVISÓ │ LÁMINA
```

Los campos vacíos salen como celda en blanco para llenar a mano.

El formato se piensa en **milímetros de papel** (un A1 son 841x594mm impresos) y
la tool los convierte a unidades del modelo según la escala y la unidad en la
que dibujás:

```
unidades_modelo = mm_papel × escala ÷ mm_por_unidad
```

Un A1 a 1:100 dibujando en metros mide 84.1 x 59.4 unidades; el mismo A1 a 1:100
en milímetros mide 84100 x 59400. Por eso `create_sheet` pide `model_units`
(`m`, `cm` o `mm`) — sin eso el cajón sale mil veces más grande o más chico que
el dibujo.

Devuelve el **área útil** (`drawArea`): el rectángulo donde entra el dibujo, ya
descontando márgenes y rótulo. Para varias láminas, repetir la llamada con
`origin_x` corrido.

Está implementado en Python ([`mcp_server/sheet.py`](mcp_server/sheet.py))
componiendo las tools básicas, no como comando del plugin — así el diseño del
rótulo se cambia sin recompilar el DLL. Para iterarlo sin AutoCAD:

```powershell
python mcp_server\preview_sheet.py salida.svg   # solo el cajon + rotulo
python mcp_server\preview_plan.py  salida.svg   # un plano completo
```

que mockean el socket y renderizan a un SVG.

## Muros, puertas y ventanas

`create_walls` es la tool para dibujar muros — no `create_line`, que da una
línea sola sin espesor. Recibe el eje por donde pasa el **centro** del muro y su
espesor, y resuelve:

- **Las esquinas a inglete**: dos tramos que se cruzan cierran limpio, sin
  escalón ni superposición. La matemática está en
  [`mcp_server/geom.py`](mcp_server/geom.py) y tiene sus tests.
- **Los huecos**: cada puerta o ventana parte el muro en tramos, así que el vano
  queda realmente abierto en vez de tener el símbolo dibujado encima.
- **Los símbolos**: la puerta sale con su hoja y su arco de abatimiento (que
  barre 90°, no 270 — hay un test para eso); la ventana, con el vidrio.

```python
create_walls(
    points=[[0,0], [9,0], [9,7], [0,7]],
    thickness=0.15,
    closed=True,
    openings=[
        {"distance": 2.0, "width": 0.90, "type": "door",
         "swing": "left", "side": "left"},
        {"distance": 5.5, "width": 1.50, "type": "window"},
    ],
)
```

`distance` se mide **a lo largo del eje** desde el arranque: si el muro dobla,
la distancia sigue la vuelta. En un perímetro cerrado, el tramo que cruza el
punto de arranque se fusiona para que no quede una junta falsa ahí. Si un hueco
se sale del muro o dos se pisan, tira un error explicando qué pasó en vez de
dibujar algo roto.

`create_axis_grid` agrega los ejes estructurales con sus globos, en línea de eje
y trazo.

## Cómo se dibuja un plano

Con las tools, no escribiendo un script por plano. El orden es siempre el mismo:

1. `create_sheet` — el cajón y el rótulo; devuelve el área útil.
2. `create_walls` — un llamado por muro o tramo de muros, con sus huecos.
3. `place_furniture` — todas las piezas de una vez.
4. `label_rooms` — los nombres, que esquivan lo ya dibujado.
5. `create_dimension` — las cotas.

Una casa de tres recámaras sale en unas quince llamadas, porque cada tool
resuelve una pieza entera: `create_walls` con cinco huecos es *un* llamado, no
cuarenta líneas de geometría.

Si algo obliga a escribir un script, es señal de que **falta una tool**: la
capacidad va a `arch.py` / `furniture.py` / `sheet.py` y se expone. Lo que no
va al repo es el plano puntual de un cliente — eso se dibuja y queda en el DWG.

[`examples/casa_9x12.py`](examples/casa_9x12.py) está como referencia de cómo se
compone un plano completo, no como la forma de trabajar.

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

## Espacio papel: layouts y viewports

Hay dos formas de armar una lámina y conviene saber cuál se está usando:

- **`create_sheet`** dibuja el cajón y el rótulo *en el espacio modelo*, a la
  escala que le pases. Es lo más simple y alcanza para una lámina única.
- **`create_layout` + `create_viewport`** usa espacio papel de verdad: el
  dibujo vive una sola vez en el modelo y cada viewport lo muestra a la escala
  que corresponda. Es lo que hace falta cuando una misma lámina lleva la planta
  a 1:100 y un detalle a 1:20, o cuando querés varias láminas del mismo modelo.

Dentro de un layout se trabaja en **milímetros de papel**, con el origen en la
esquina inferior izquierda de la hoja. La escala del viewport necesita saber
cuánto mide una unidad del modelo:

```python
create_layout(name="PLANTA", paper_size="A2")
create_viewport(
    layout="PLANTA",
    center_x=290, center_y=200, width=520, height=360,   # mm de papel
    view_center_x=4.5, view_center_y=6.0,                # punto del modelo
    scale_denominator=50,
    model_units_per_mm=1000,   # 1 unidad = 1 metro = 1000mm
)
```

`locked=True` (el default) deja el viewport bloqueado para que un zoom
accidental no le cambie la escala.

## Estilos con nombre

Sin estilos propios, textos y cotas salen con el `Standard` de la plantilla,
que cambia de un DWG a otro: el mismo plano se ve distinto según con qué
archivo arrancaste. `set_text_style` y `set_dim_style` los crean, y después se
usan pasando `style="<nombre>"` a `create_text`, `create_mtext` o
`create_dimension`. Si el estilo no existe, el error lo dice y sugiere crearlo
en vez de dibujar con otro por lo bajo.

## Autocarga: instalar como App Bundle

Para que AutoCAD cargue el plugin solo al arrancar, sin `NETLOAD` cada vez:

```powershell
.\tools\install_bundle.ps1
```

Compila y copia el bundle a
`%APPDATA%\Autodesk\ApplicationPlugins\AutoCadMcp.bundle`, con los dos DLLs
adentro — AutoCAD elige el que corresponde a su versión. **Los bundles se leen
solo al arrancar**, así que hay que cerrar y volver a abrir AutoCAD; y como
.NET no permite descargar un assembly ya cargado, cualquier cambio en el plugin
también obliga a reiniciar.

Para sacarlo: `.\tools\install_bundle.ps1 -Uninstall`.

## Probar contra AutoCAD real

```powershell
python mcp_server\test_live.py          # prueba y limpia lo que dibujo
python mcp_server\test_live.py --keep   # deja el resultado para mirarlo
```

Ejercita lo que no se puede verificar sin AutoCAD: achurados, leaders, offsets
en curvas ambiguas, bloques, imágenes raster, splines, layouts, viewports,
estilos y documentos. Dibuja lejos del origen (x=500) para no pisar tu trabajo.

Dos pruebas necesitan archivos que dependen de la máquina y se saltean si no
están:

```powershell
$env:ACAD_TEST_DWG   = "C:\ruta\a\un\bloque.dwg"
$env:ACAD_TEST_IMAGE = "C:\ruta\a\una\imagen.png"
```

## Próximos pasos

- Cotas encadenadas y por coordenadas (hoy `create_dimension` hace una alineada
  por vez).
- Tablas (cuadro de acabados, cuantificación) como objeto `Table` nativo.
- Exportar a PDF desde un layout (`PLOT` por API).
- Bloques dinámicos y atributos multilínea.

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
