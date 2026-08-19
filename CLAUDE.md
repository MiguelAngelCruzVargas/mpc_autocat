# Cómo dibujar planos con este MCP

Reglas de trabajo cuando alguien pide dibujar algo en AutoCAD con estas tools.

## 0. Antes de dibujar: validar

Con un terreno y un programa de ambientes, ANTES de trazar nada:

1. **`check_program`** — ¿el programa entra en el terreno? Si no entra, decirlo
   con el número y las opciones, y esperar la decisión del cliente. Un programa
   que no cierra no se arregla dibujando con cuidado.
2. **`check_layout`** — ¿la zonificación cumple? Verifica lo que la geometría no
   muestra y que hace inconstruible un plano bien dibujado.

3. **`check_geometry`** — ¿los recintos existen de verdad? Valida lo que el
   grafo no ve: dimensiones mínimas por uso, recintos que se pisan, puertas
   duplicadas, y puertas entre ambientes que **no comparten muro** (el recinto
   queda sellado aunque la puerta figure en el grafo).
4. **`check_walls`** — ¿la muraria cierra? Extremos de muro al aire, tramos por
   debajo del mínimo constructivo, muros dibujados dos veces sobre el mismo eje.

Los cuatro son complementarios y ninguno alcanza solo: `check_layout` valida la
lógica de uso, `check_geometry` que el espacio exista, `check_walls` que se
pueda levantar, `check_program` que quepa en el terreno.

Las reglas que valida, y que hay que respetar al proyectar:

- El acceso desde la calle **NUNCA** abre a una recámara o un baño: desemboca
  en sala, comedor o vestíbulo.
- El baño principal es **en-suite**: su puerta abre dentro de la recámara
  principal, no al pasillo.
- Al patio de servicio se entra desde la cocina o una circulación común, nunca
  cruzando un dormitorio.
- La cocina comunica directo con el comedor y no queda como paso entre
  recámaras.
- Todo ambiente tiene al menos un acceso.
- En muros de colindancia (x=0, x=ancho, y=fondo) no van ventanas, salvo patio
  de luz o retiro reglamentario.

## 0.bis Dónde va el marco: NUNCA sobre el dibujo

El cajón y el rótulo **no se dibujan encima del plano**. Dos formas correctas:

- **Espacio papel** (lo recomendado): `create_layout` → `set_current_layout` →
  dibujar el rótulo ahí → `create_viewport` para mostrar el modelo. Todos los
  comandos dibujan en el espacio ACTIVO, así que con el layout activo el rótulo
  va donde corresponde.
- **En el modelo, apartado**: si tiene que ir en el modelo, a más de 20 m del
  polígono del terreno, nunca solapado.

El orden es: dibujar → `get_extents` → `fit_sheet` → recién ahí el cajón, y
pasándole el `orientation` que devolvió `fit_sheet` o la hoja sale acostada.

## 1. Dibujar con las tools, NO escribiendo un script por plano

Un plano se dibuja llamando las tools del MCP (`create_sheet`, `create_walls`,
`place_furniture`, `label_rooms`, `create_dimension`) **directamente**. No crear
un `casa_tal.py` por cada pedido: por ese camino el repo termina con un archivo
por plano y el servidor MCP no sirvió de nada.

La divisoria es esta:

- **Va al repo** lo *reutilizable*: una capacidad nueva que sirva para cualquier
  plano (un tipo de mueble, un símbolo, una forma de acotar). Se agrega a
  `arch.py` / `furniture.py` / `sheet.py` y se expone como tool.
- **No va al repo** lo *puntual*: el plano de un cliente concreto. Se dibuja con
  las tools. Si hace falta un script intermedio para calcular algo, va al
  directorio temporal, no al proyecto.

Si dibujar algo obliga a escribir un script, eso es la señal de que **falta una
tool**: agregala a la biblioteca y exponela, en vez de dejar el script.

`examples/casa_9x12.py` es la única excepción, y está ahí como referencia de
cómo se compone un plano entero, no como forma de trabajo.

## 2. Siempre empezar por la lámina

**Antes de trazar una sola línea, llamar a `create_sheet`.** Define el formato,
la escala y el cuadro de rotulación, y devuelve el `drawArea` — el rectángulo
donde entra el dibujo. Nunca dibujar "al aire" y acomodar después.

Si no te dieron los datos de la obra, preguntá por los que faltan en UNA sola
tanda (nombre de la obra, ubicación, propietario, contenido de la lámina, quién
dibuja, fecha, número de lámina) en vez de inventarlos. Los campos que queden
vacíos salen como celda en blanco para llenar a mano, lo cual es preferible a
poner datos falsos en un plano.

Elegir formato y escala según lo que entre:

| Qué se dibuja | Escala típica | Formato |
|---|---|---|
| Conjunto / plano de ubicación | 1:200 – 1:500 | A1 |
| Planta arquitectónica, cortes, fachadas | 1:50 – 1:100 | A1 |
| Planta de un local chico | 1:50 | A2 / A3 |
| Detalles constructivos | 1:5 – 1:20 | A3 |

Verificá que el dibujo entre: el `drawArea` que devuelve `create_sheet` está en
unidades del modelo. Si el terreno mide 40x25m y el área útil da 80.6x51.8,
entra; si no entra, subí el denominador de escala o el formato — **nunca**
achiques el dibujo fuera de escala.

## 3. Dibujar adentro del área útil

`create_sheet` devuelve dos rectángulos:

- `x1,y1,x2,y2` — la franja arriba del rótulo. Es el conservador, usalo por defecto.
- `full_x1..full_y2` — además usa la banda a la izquierda del rótulo. Sirve
  cuando el dibujo es apaisado y necesitás todo el ancho.

Para varias láminas, repetir `create_sheet` con `origin_x` corrido (p.ej.
+100 unidades entre hoja y hoja) en lugar de amontonarlas.

## 4. Muros: siempre `create_walls`

Un muro NO es una línea. Usar `create_walls` con el eje del muro y su espesor:
resuelve las esquinas a inglete y recorta los huecos de puertas y ventanas, que
es lo que hace que un plano se vea como un plano y no como un esquema.

`create_line` queda para ejes auxiliares, guías y trazos sueltos.

Espesores típicos dibujando en metros: muro exterior 0.15, muro de tabique 0.28,
divisorio interior 0.10. Puertas de 0.90 (acceso) / 0.80 (interior) / 0.70
(baño); ventanas de 1.20 a 1.50.

`distance` de un hueco se mide a lo largo del eje desde el arranque, siguiendo
las vueltas. Conviene calcularla sumando tramos, no a ojo.

## 4.bis Ejes: separación mínima 1.20 m

`create_axis_grid` fusiona solo los ejes más próximos que eso, porque dos
burbujas a 0.65 m se pisan y las cotas quedan ilegibles. Revisá el 'warning'
que devuelve: la separación fusionada va como **cota de detalle**, no como eje
propio.

Y `set_display_options(linetype_scale=...)` es obligatorio para que los ejes se
vean como trazo-punto: dibujando en metros con LTSCALE=1 salen continuos.

## 5. Jerarquía de grosores

Un plano se lee por el contraste de trazos. Toda tool de creación acepta
`lineweight` en centésimas de mm:

| Qué | `lineweight` |
|---|---|
| Cajón / marco | 70 |
| Muros cortados, contorno de corte | 50 |
| Contornos vistos, mobiliario | 25–35 |
| Ejes, cotas, leaders, auxiliares | 13–18 |
| Achurados y rellenos | 5–13 |

Si todo sale con el mismo grosor, el plano no se lee. Cuando el usuario diga
que "se ve todo fino", revisar primero `set_display_options(lineweight_display=True)`.

Al terminar los muros, `union_regions` sobre sus handles: fusiona los tramos en
un solo contorno y los cruces quedan en T y no en cajón. Devuelve además el área
y el perímetro de mampostería. Hacerlo AL FINAL: el resultado es una Region y ya
no admite editar vértices.

## 6. Mobiliario y rótulos

`place_furniture` dibuja todas las piezas en UNA llamada: pasarle la lista
entera del ambiente o de la casa, no una llamada por mueble.

`label_rooms` va DESPUÉS de `place_furniture`: usa las huellas que dejaron los
muebles para ubicar cada nombre donde no tape nada. Rotular antes de amueblar
deja los textos encima de las camas.

## 7. Capas

Una capa por tipo de elemento, creada con `set_layer` antes de dibujar (color y
grosor propios): `MUROS`, `EJES`, `COTAS`, `TEXTOS`, `MOBILIARIO`, `TERRENO`.
`create_sheet` ya crea `CAJON` y `ROTULO` — no dibujar nada del plano en esas
dos, para poder apagarlas y ver solo el dibujo.

## 8. Texto y cotas a escala

El texto se dimensiona en mm de papel × escala. En un plano 1:100 dibujado en
metros, un texto de 2.5mm de papel se crea con `height = 0.25`. Para cotas, el
parámetro `scale` de `create_dimension` cumple ese rol (en metros a 1:100,
arrancar en `0.1`).

## 9. Verificar antes de dar por terminado

Después de dibujar, `zoom_extents` y `get_drawing_info` para confirmar la
cantidad de entidades. Si se creó geometría cerrada, `calculate_area` sobre las
polilíneas para chequear que las medidas dan lo que se pidió.

## Iterar el diseño del rótulo sin AutoCAD

`python mcp_server/preview_sheet.py salida.svg` renderiza el cajón + rótulo, y
`python mcp_server/preview_plan.py salida.svg` un plano completo con muros,
huecos y ejes. Los dos mockean el socket: no necesitan AutoCAD. Cambiar
`sheet.py` o `arch.py` y volver a correrlos es mucho más rápido que probar a
mano en AutoCAD.

Antes de dar por buena cualquier cambio en la geometría, correr `test_geom.py` y
`test_arch.py` — cubren el inglete de las esquinas, el partido de los huecos y
que los abatimientos barran 90°.

## Espacio papel vs espacio modelo

`create_sheet` dibuja el cajón en el espacio modelo y alcanza para una lámina
única. Cuando el pedido implique **varias escalas en la misma lámina** o
**varias láminas del mismo modelo**, usar `create_layout` + `create_viewport`:
el dibujo queda una sola vez en el modelo y cada viewport lo muestra a su
escala. Dentro del layout las coordenadas son milímetros de papel, y
`create_viewport` necesita `model_units_per_mm` (1000 dibujando en metros) o la
escala sale mil veces mal.

## Estilos antes que valores sueltos

Para un plano con más de un par de textos, crear primero `set_text_style` y
`set_dim_style` y después pasar `style="<nombre>"`. Cambiar el estilo reajusta
todo el plano de una; ir texto por texto no.

## Antes de tocar el plugin C#

`python mcp_server/test_contract.py` chequea que cada tool tenga su `case` en
`Handlers.cs`.

Cualquier cambio en `plugin/` obliga a **recompilar y reiniciar AutoCAD**: .NET
no permite descargar un assembly ya cargado, así que ni `NETLOAD` ni el bundle
toman una versión nueva sin cerrar el programa. Por eso, lo que se pueda
resolver del lado Python (`sheet.py`, `arch.py`, `furniture.py`) se resuelve
ahí: se prueba con los previews y no cuesta un reinicio.

`ping` devuelve la versión del plugin cargado — si un comando nuevo responde
"Comando no soportado", es que AutoCAD sigue con el DLL viejo.

Después de tocar el plugin, correr `python mcp_server/test_live.py` con AutoCAD
abierto: ejercita todo contra el dibujo real y limpia lo que dibujó.
