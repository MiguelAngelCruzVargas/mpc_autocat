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

## 4.quater Obra vial: despejar el eje y no rematar el tramo

Sobre el eje de una calle corren varias cosas a la vez, y por defecto todas
caen en el mismo lugar. Hay que repartirlas a mano:

- `create_stationing(label_offset=1.50)` manda el número de cadenamiento a un
  lado; el rótulo de la tubería va al **opuesto**. Sin eso el 0+060 aterriza
  encima de "TUB. PEAD Ø 30..." y el 0+080 sobre la propia línea de eje.
- `create_road(cap_ends=False)` deja los extremos abiertos. La calle sigue más
  allá del dibujo: una línea transversal en el 0+000 se lee como final de obra.
  Con extremos abiertos no se puede achurar la calzada — el achurado necesita
  contorno cerrado y la tool lo dice.
- El sentido del flujo va con `create_flow_arrow`, no con un leader. Un leader
  cuyo primer tramo mida menos que el doble de la flecha sale **sin punta**:
  AutoCAD la suprime en silencio, y en un dibujo en metros con DIMASZ de
  fábrica eso pasa siempre.

## 4.ter Ejes de obra civil: SIEMPRE con `bulges`

Un eje con curva sale de `create_alignment`, que devuelve `points` **y**
`bulges`. Todo lo que después se ubique por cadenamiento —`create_road`,
`point_on_road`, `create_stationing`— necesita los dos. Sin los bulges la
distancia se mide sobre la cuerda y no sobre el arco: los pozos, las marcas y
todo lo que caiga después del principio de curva queda corrido, y el error no
se ve en pantalla, aparece en el replanteo.

## 4.bis Ejes: separación mínima 1.20 m

`create_axis_grid` fusiona solo los ejes más próximos que eso, porque dos
burbujas a 0.65 m se pisan y las cotas quedan ilegibles. Revisá el 'warning'
que devuelve: la separación fusionada va como **cota de detalle**, no como eje
propio.

**Acotar ANTES de tirar los ejes.** Cada cadena de cotas reserva la franja que
ocupa, así que la burbuja se corre para salir por afuera y la línea de eje
cruza las cotas — que es el dibujo correcto. Al revés también cierra (las
cotas se apilan afuera de los globos), pero se lee peor.

Y `set_display_options(linetype_scale=...)` es obligatorio para que los ejes se
vean como trazo-punto: dibujando en metros con LTSCALE=1 salen continuos.

## 4.quinquies Cortes y fachadas: `create_building_section`

Un corte se describe por **niveles**, no se deriva de `create_walls`: qué muro
corta de verdad el plano de corte (banda gruesa achurada) y cuál queda visto
de fondo (línea fina) es una decisión de quien proyecta, y este MCP no tiene
ningún concepto de altura/nivel en la planta como para inferirla sola. Se le
pasa la lista de `stories` ya resuelta, de abajo hacia arriba, cada una con su
`height` (piso a piso, **incluye** el espesor de su propia losa superior —
una azotea plana es simplemente el último nivel de la lista) y sus
`elements`: `cut_wall` (cortado, se achura), `window`/`door` (casi siempre del
muro de fondo, vistos más allá del plano de corte — la línea de corte se
elige justamente para no pasar por un vano) y `seen_wall` (silueta de fondo).

`view="corte"` achura y dibuja losas; `view="fachada"` **nunca** achura ni
dibuja losas (una fachada no muestra espesores) y los `cut_wall` pasan a ser
la envolvente exterior vista, no la banda cortada.

Acotar los niveles con `dimension_stories=True` en vez de calcular el offset a
mano — es el mismo `create_dimension_chain` de siempre, aplicado en vertical.
Los rótulos de nivel ("N.P.T. +2.90") se ubican solos del lado opuesto a la
cadena de cotas para no encimarse con ella.

Capas propias, para no chocar con lo que ya usan otras tools de corte:
`CORTES-ARQ` (cortado) y `CORTES-ARQ-VISTO` (visto) — **no** `CORTES`, que ya
es el detalle de capas de pavimento (`create_layer_section`), ni `SECCIONES`,
que ya son los cortes viales (`create_cross_sections`). `FACHADAS` para
`view="fachada"`.

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

## 6.bis Rotular: `place_labels`, nunca calculando la posición a mano

Todo rótulo que no sea de ambiente va con **`place_labels`**, que busca a
alrededor del elemento el primer lugar libre y registra el texto para que el
siguiente tampoco se encime:

```
place_labels(labels=[{"text": "Z-2 / D-1", "box": [x0, y0, x1, y1]},
                     {"text": "TL-1 (20x35)", "x": .., "y": .., "rotation": 90}],
             height=<mm de papel x escala>)
```

Ubicar el texto con una cuenta —"el eje más 0.15"— es el error que se repitió
en tres planos seguidos: el cadenamiento sobre la línea de eje, el dato de la
tubería encima del cadenamiento, la etiqueta de la zapata cruzada con la
trabe. Ninguno era un error de cálculo: era escribir sin mirar lo que ya
estaba. `create_walls` y `place_furniture` registran su huella solos; lo demás
se le pasa en `obstacles`.

Un muro separa ambientes, así que el rótulo **no se manda del otro lado**
aunque ahí haya lugar: `place_labels` descarta el lado cuando el segmento del
elemento a su texto cruza un muro de los que `create_walls` registró. No
alcanza con que el texto no *pise* el muro — puede quedar entero del lado
equivocado sin tocarlo, que se lee peor. Con `barriers` se agregan límites que
no son muros.

Revisá `cramped` en lo que devuelve: ahí van los que no encontraron lugar.

## 6. Mobiliario y rótulos

`place_furniture` dibuja todas las piezas en UNA llamada: pasarle la lista
entera del ambiente o de la casa, no una llamada por mueble.

`label_rooms` va DESPUÉS de `place_furniture`: usa las huellas que dejaron los
muebles para ubicar cada nombre donde no tape nada. Rotular antes de amueblar
deja los textos encima de las camas.

## 6.ter Color: nunca los puros 1-7 (salvo 7 y 8)

Los índices 1 a 7 son los colores puros de AutoCAD, pensados para la pantalla
negra del modelo. En un plano hay que evitarlos casi todos, y por razones
**opuestas**:

| Color | Qué le pasa |
|---|---|
| 2 amarillo, 4 cian, 3 verde | Muy claros: **se lavan al imprimir** en papel blanco. El cian y el amarillo son los peores. |
| 5 azul | Al revés: **imprime bien**, pero es tan oscuro que no se lee sobre el fondo del espacio modelo. |
| 1 rojo, 6 magenta | Chillones en pantalla, sin ganar nada. |
| 9 gris claro | Casi no imprime. |
| **7 blanco/negro y 8 gris** | Los únicos dos que se comportan igual en pantalla y en papel. Son la base. |

Del 10 al 249 están los mismos matices al 65% o 50% de intensidad, que se leen
bien en los dos medios. Equivalencias, ya aplicadas como default de la
biblioteca (`layers.py`):

| Para | Usar | En vez de |
|---|---|---|
| Ejes | **32** ámbar | 2 o 4 |
| Cotas | **12** rojo oscuro | 1 |
| Hidráulica, drenaje | **152** azul acero | 4 o 5 |
| Guarniciones, vegetación | **96** verde oliva | 3 |
| Pozos, registros | **172** violeta | 6 |
| Achurados, secundarios | **8** o **253** gris | 9 |

Si la lámina se traza en **monocromo** con un `.ctb` —lo habitual en obra— el
color solo define el grosor y nada de esto afecta la impresión. Igual hay que
elegirlo bien: el dibujo se trabaja en pantalla.

`layers.EVITAR` tiene el índice y el motivo de cada uno, para poder avisarlo.

## 6.quater Instalaciones: `place_devices` y `create_conduit`

La simbología eléctrica es normalizada y siempre igual —un círculo con cruz es
una salida de techo en cualquier plano— así que **no se arma con
`create_circle` + `create_line`**: sale distinta en cada lámina y no hay forma
de que dos planos se parezcan.

`place_devices` dibuja toda la instalación en UNA llamada: `lamp`, `switch`,
`outlet`, `gfci` y `panel`, cada uno con su `angle` apuntando al ambiente.
Los tamaños son medidas reales de obra (Ø0.30 la salida, Ø0.20 el apagador,
r=0.15 el contacto), no mm de papel. Devuelve la caja de cada dispositivo,
que es lo que después toma `place_labels` para rotularlos sin encimarse.

`create_conduit` traza la canalización en arco suave (`sag`) y le pone las
marcas de conductores: `'/'` cada fase, `'|'` cada neutro, `'T'` la tierra —
`conductors="//|T"` son dos fases, un neutro y tierra. Recta de aparato a
aparato la tubería se confunde con la muraria.

## 7. Capas

Una capa por tipo de elemento, creada con `set_layer` antes de dibujar (color y
grosor propios): `MUROS`, `EJES`, `COTAS`, `TEXTOS`, `MOBILIARIO`, `TERRENO`.
`create_sheet` ya crea `CAJON` y `ROTULO` — no dibujar nada del plano en esas
dos, para poder apagarlas y ver solo el dibujo.

**La capa que ya existe manda.** Si el proyecto trae su nomenclatura
(`VIAL_EJE`, `HIDRO_RED_DRENAJE`...), configurala con `set_layer` primero y
pasale el nombre a la tool: las tools solo aplican su color y grosor cuando
tienen que crear la capa, nunca pisan una ya configurada. `create_road` recibe
`axis_layer`, `pavement_layer`, `curb_layer` y `sidewalk_layer` justo para eso.

## 8. Cotas: `create_dimension_chain`, nunca cota por cota

Una planta se acota en **cadenas**, un nivel por tipo de dato: los huecos, los
ejes, el total. `create_dimension_chain` dibuja la corrida entera y **resuelve
el offset solo**, apilándose afuera de lo que ya haya en ese lado (incluidas
las burbujas de eje):

```
create_dimension_chain(positions=[x0, x_hueco1, x_hueco2, ..., x1],
                       side="bottom", reference=<y del paño inferior>)
create_dimension_chain(positions=[x0, x_eje, x1],
                       side="bottom", reference=<idem>, total=True)
```

Las cadenas salen a 10, 18 y 26 mm de papel, que es la separación de norma.
Elegir el `dim_line_y` a mano NO funciona: la burbuja de eje se mueve con el
tamaño del plano (radio = 2.5% del span), así que un offset fijo que cierra en
una casa de 9x12 cae adentro del globo en cuanto el plano crece. Ese fue el
error que dejaba las cotas encima de los círculos.

Para una **sección tipo** —banqueta, calzada, banqueta— van los tramos sueltos
en la misma línea, con `segments` en vez de `positions`:

```
create_dimension_chain(segments=[[3.65, 5.15], [-3.50, 3.50], [-5.15, -3.65]],
                       side="left", reference=<estación de la sección>)
```

Tres llamadas sueltas darían tres líneas de cota distintas.

`create_dimension` suelta queda para lo puntual: un detalle, una diagonal, un
hueco aislado. Si la ubicás a mano, verificá con `check_annotations` antes.

La cadena avisa cuando un tramo queda tan corto que el número no entra entre
las flechas — ese va a una cadena de detalle o a un leader, no apretado.

**El texto** se dimensiona en mm de papel × escala. En un plano 1:100 dibujado
en metros, un texto de 2.5mm de papel se crea con `height = 0.25`. Para cotas
ese rol lo cumple `scale`, que es *unidades del modelo por mm de papel* —
`create_sheet` ya lo deja registrado, así que la cadena lo toma sola y no hace
falta pasarlo.

## 8.bis Cuantificación de obra: `calculate_quantities`

Un cuadro de "volumen de obra" hecho de memoria repite el error que ya
resolvieron los rótulos y las cotas: el número que se anota no es
necesariamente el que mide el plano. `calculate_quantities` mide con
`calculate_area` los handles que YA quedaron dibujados (castillos, dalas,
zapatas, paños de muro) y aplica la fórmula de obra sobre esa medición, no
sobre un número recordado.

Lo único que el dibujo no muestra a escala es el **acero**: una varilla en
corte es un círculo esquemático de ~1cm, no la sección real. Ahí se toma la
especificación que ya quedó anotada en el plano (varillas, diámetro,
separación de estribos) — sigue siendo un dato del proyecto, no un supuesto
de la tool. Para el perímetro del estribo, pasale `stirrup_handle`: mide el
`length` real del estribo ya dibujado (Polyline cerrada) en vez de
recalcularlo a mano.

`create_quantities_table` dibuja el resultado tal cual — no vuelve a
calcular nada — con una columna que muestra CÓMO se llegó a cada número
(área medida, módulo, fórmula), para que se pueda verificar la cuenta sin
abrir el DWG.

**Es obligatorio, no opcional.** Todo plano que salga de esta biblioteca —no
solo el que lo pida explícitamente— lleva su cuadro de cuantificación igual
que lleva su cuadro de especificaciones: en cuanto haya concreto, tabique,
mortero o acero dibujado, corresponde un `calculate_quantities` +
`create_quantities_table` antes de dar el plano por terminado.

Si falta un dato para cuantificar algo con el que el dibujo no alcanza
—profundidad real de una sección, tipo y separación de varilla, % de
merma— **hay que preguntarlo**, no inventarlo. La tool ya rechaza el cálculo
sin esos datos (`ValueError` explícito), pero preguntar antes de dibujar
ahorra el redibujado.

## 9. Verificar antes de dar por terminado

`check_annotations` cierra el ciclo de los otros cuatro `check_*`: ellos miran
el proyecto, este mira el plano **como dibujo** — que las cotas, las burbujas
y los rótulos no se encimen. Sale limpio solo mientras se use
`create_dimension_chain`; da problemas cuando algo se ubicó a mano.

Después de dibujar, `zoom_extents` y `get_drawing_info` para confirmar la
cantidad de entidades. Si se creó geometría cerrada, `calculate_area` sobre las
polilíneas para chequear que las medidas dan lo que se pidió.

## Iterar el diseño del rótulo sin AutoCAD

`python mcp_server/preview_sheet.py salida.svg` renderiza el cajón + rótulo, y
`python mcp_server/preview_plan.py salida.svg` un plano completo con muros,
huecos y ejes. Los dos mockean el socket: no necesitan AutoCAD. Cambiar
`sheet.py` o `arch.py` y volver a correrlos es mucho más rápido que probar a
mano en AutoCAD.

El preview dibuja también las cotas (las descompone en sus líneas y su
número), así que el encimado se ve ahí y no recién al abrir el DWG.

Antes de dar por buena cualquier cambio en la geometría, correr `test_geom.py`,
`test_arch.py` y `test_annotation.py` — cubren el inglete de las esquinas, el
partido de los huecos, que los abatimientos barran 90° y que las cadenas de
cota y las burbujas no se pisen en ningún orden de dibujo.

## Espacio papel vs espacio modelo

`create_sheet` dibuja el cajón en el espacio modelo y alcanza para una lámina
única. Cuando el pedido implique **varias escalas en la misma lámina** o
**varias láminas del mismo modelo**, usar `create_layout` + `create_viewport`:
el dibujo queda una sola vez en el modelo y cada viewport lo muestra a su
escala. Dentro del layout las coordenadas son milímetros de papel, y
`create_viewport` necesita `model_units_per_mm` (1000 dibujando en metros) o la
escala sale mil veces mal.

## La fuente: nunca dejar `txt.shx`

AutoCAD trae `txt` de fábrica y esa fuente **no mapea acentos ni el símbolo de
diámetro**: "SECCIÓN" y "Ø 30 cm" salen con cuadraditos y no se nota hasta
abrir el DWG. Las tools de anotación lo detectan y pasan a una TrueType solas
la primera vez que escriben, pero **no pisan un estilo elegido a propósito** —
si vas a usar uno propio, creálo con `set_text_style` antes de dibujar.

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
