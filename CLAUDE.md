# Cómo dibujar planos con este MCP

Reglas de trabajo cuando alguien pide dibujar algo en AutoCAD con estas tools.

## 1. Siempre empezar por la lámina

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

## 2. Dibujar adentro del área útil

`create_sheet` devuelve dos rectángulos:

- `x1,y1,x2,y2` — la franja arriba del rótulo. Es el conservador, usalo por defecto.
- `full_x1..full_y2` — además usa la banda a la izquierda del rótulo. Sirve
  cuando el dibujo es apaisado y necesitás todo el ancho.

Para varias láminas, repetir `create_sheet` con `origin_x` corrido (p.ej.
+100 unidades entre hoja y hoja) en lugar de amontonarlas.

## 3. Muros: siempre `create_walls`

Un muro NO es una línea. Usar `create_walls` con el eje del muro y su espesor:
resuelve las esquinas a inglete y recorta los huecos de puertas y ventanas, que
es lo que hace que un plano se vea como un plano y no como un esquema.

`create_line` queda para ejes auxiliares, guías y trazos sueltos.

Espesores típicos dibujando en metros: muro exterior 0.15, muro de tabique 0.28,
divisorio interior 0.10. Puertas de 0.90 (acceso) / 0.80 (interior) / 0.70
(baño); ventanas de 1.20 a 1.50.

`distance` de un hueco se mide a lo largo del eje desde el arranque, siguiendo
las vueltas. Conviene calcularla sumando tramos, no a ojo.

## 4. Jerarquía de grosores

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

## 5. Capas

Una capa por tipo de elemento, creada con `set_layer` antes de dibujar (color y
grosor propios): `MUROS`, `EJES`, `COTAS`, `TEXTOS`, `MOBILIARIO`, `TERRENO`.
`create_sheet` ya crea `CAJON` y `ROTULO` — no dibujar nada del plano en esas
dos, para poder apagarlas y ver solo el dibujo.

## 6. Texto y cotas a escala

El texto se dimensiona en mm de papel × escala. En un plano 1:100 dibujado en
metros, un texto de 2.5mm de papel se crea con `height = 0.25`. Para cotas, el
parámetro `scale` de `create_dimension` cumple ese rol (en metros a 1:100,
arrancar en `0.1`).

## 7. Verificar antes de dar por terminado

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

## Antes de tocar el plugin C#

`python mcp_server/test_contract.py` chequea que cada tool tenga su `case` en
`Handlers.cs`. Cualquier cambio en `plugin/` obliga a recompilar **y volver a
hacer `NETLOAD` en la máquina con AutoCAD**; los cambios que se puedan hacer
del lado Python (como `sheet.py`) evitan ese viaje.
