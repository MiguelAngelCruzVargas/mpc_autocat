# Cómo dibujar planos con este MCP

Reglas de trabajo cuando alguien pide dibujar algo en AutoCAD con estas tools.

## 0. Antes de dibujar: validar

**Para una vivienda entre medianeras, el partido no se inventa: `suggest_layout`.**
Con frente, fondo, recámaras y baños devuelve la distribución completa
(rooms/doors/windows) YA validada por `check_layout` y `check_geometry` —
banda social al frente, pasillo central, patio al fondo, baño principal
en-suite si son dos. Si el programa no entra lo dice con números en vez de
achicar recintos fuera de mínimo. Lo que devuelve es el punto de partida a
ajustar con el cliente, no un diseño terminado.

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

## 2.bis Guardar seguido: AutoCAD se puede caer a mitad de sesión

`Drawing1.dwg` (el que arranca sin nombre) vive solo en memoria. Un plano
entero — casa, escalera, lo que sea — se perdió una vez de golpe por un
`FATAL ERROR: Unhandled Access Violation` de AutoCAD a mitad de una sesión
larga: no fue un error de ninguna tool devolviendo algo controlado, fue el
proceso completo cayéndose, y con él todo lo dibujado sin guardar.

`save_drawing` después de cada bloque grande (la lámina recién creada, los
muros ya trazados, antes de arrancar la cuantificación) es la única defensa
real. El servidor lo vigila solo: pasadas ~40 operaciones de dibujo sin
guardar, las tools empiezan a devolver un `warning` recordándolo — hacele
caso.

`save_drawing()` sin `path` reusa el último path guardado o abierto en la
sesión (lo dice en `note`), así que ya no puede caer en el default de
AutoCAD (`Documents\Drawing1.dwg`) como pasó una vez. Igual, el primer
guardado de un dibujo nuevo necesita su `path` explícito.

`create_sheet` devuelve dos rectángulos:

- `x1,y1,x2,y2` — la franja arriba del rótulo. Es el conservador, usalo por defecto.
- `full_x1..full_y2` — además usa la banda a la izquierda del rótulo. Sirve
  cuando el dibujo es apaisado y necesitás todo el ancho.

Para varias láminas, repetir `create_sheet` con `origin_x` corrido (p.ej.
+100 unidades entre hoja y hoja) en lugar de amontonarlas.

## 2.ter Componer: dónde va cada vista

`space` evita que dos cosas se encimen. **Componer es otra cosa**: alinear,
repartir parejo y agrupar lo que se lee junto. La diferencia entre "nada se
pisa" y "esto está diseñado" es exactamente esa — y es lo que hacía que una
lámina saliera vacía en dos tercios con las vistas tiradas al azar.

**`compose_layout` es el camino por defecto.** Un proyecto con varias láminas
—que es casi siempre— va con un layout por lámina: el dibujo vive UNA sola vez
en el modelo y cada layout lo recorta con sus viewports. Así trabaja un juego
profesional: el modelo se ve desordenado porque tiene todas las disciplinas
encimadas, y cada lámina sale limpia porque su viewport muestra solo su pedazo.
No mueve nada del modelo.

```
compose_layout("E-01", views=[
    {"name": "planta", "box": [0, 0, 16.6, 29.1], "scale_denominator": 100,
     "title": "PLANTA ARQUITECTÓNICA"},
    {"name": "corte", "box": [40, 0, 56.6, 7.5], "scale_denominator": 100,
     "title": "CORTE A-A", "below": "planta"}],
    reserved_right_mm=160)
```

`reserved_right_mm` es la franja donde va la columna fija —localización,
simbología, rótulo— que se repite igual en todas las láminas del juego.

**`compose_sheet` es para el caso chico**: una lámina única con el cajón en el
modelo. Ahí sí mueve las vistas ya dibujadas a su lugar. Al mover, todo lo que
`space` tenía registrado deja de valer: **acotá y rotulá DESPUÉS de componer**.

Las dos comparten el mismo motor y las mismas dos ideas:

- **Filas.** Las vistas se acomodan de izquierda a derecha hasta que no entra
  una más, y ahí empieza otra fila. Dentro de la fila apoyan todas sobre una
  **línea de base común**, que es lo que hace que la lámina se vea alineada.
- **`below`.** Una vista que lo declara se apila con la de arriba y las dos
  comparten el centro en X. Esa es la alineación proyectiva —la planta debajo
  de su corte, compartiendo los ejes verticales— y es la única forma de que se
  puedan leer una con otra. Las dos se acomodan como UNA unidad.

Si no entra lo dicen en `fits` y en `warnings`, y **no achican nada**: una
vista fuera de escala no es una lámina, es un error. Probá con `dry_run=True`
antes.

## 3. Abrir, crear y cambiar de dibujo

Para **corregir un plano ya entregado** no hace falta ir a AutoCAD a abrirlo:
`open_document(path=...)` lo abre y lo deja activo. El ciclo completo de
corrección es `open_document` → `select_entities` sobre la zona a rehacer →
`delete_entities` → redibujar solo eso → `save_drawing(path=...)`. Tirar el
plano entero y empezar de cero es casi siempre el camino equivocado.

`new_document(template=...)` arranca un dibujo desde una plantilla propia (el
`.dwt` de la oficina, con sus capas y estilos ya armados). Nace sin nombre y
vive solo en memoria: `save_drawing` con `path` explícito antes de dibujar
nada serio.

`read_only=True` para mirar el plano de otro consultor sin riesgo de pisarlo.
Pero si lo que hace falta es su geometría **en este** dibujo, eso es
`attach_xref`, no abrirlo.

**Cambiar de dibujo tira lo cacheado del anterior, y eso importa.** Este
servidor recuerda cosas que describen UN dibujo: las huellas de mobiliario y
las franjas de anotación ya ocupadas (lo que hace que `place_labels` no
encime nada), y qué capas existen. `open_document`, `new_document` y
`set_active_document` las olvidan a propósito — si no, `place_labels`
esquivaría una cama que está en el OTRO plano y `set_layer` daría por
configurada una capa que solo existe allá. Las dos fallas son silenciosas.

La consecuencia práctica: al entrar a un dibujo ya dibujado, lo que hay en él
**no lo conoce nadie**. Si un rótulo nuevo tiene que esquivar algo que ya
estaba, pasáselo en `obstacles`. Y la escala NO se resetea (es un número por
lámina, no por dibujo): si esta lámina es otra escala, `create_sheet` antes de
anotar, o el texto sale del tamaño de la lámina anterior. Los `warnings` que
devuelven esas tres tools lo recuerdan.

## 4. Muros: siempre `create_walls`

Un muro NO es una línea. Usar `create_walls` con el eje del muro y su espesor:
resuelve las esquinas a inglete y recorta los huecos de puertas y ventanas, que
es lo que hace que un plano se vea como un plano y no como un esquema.

`create_line` queda para ejes auxiliares, guías y trazos sueltos.

Espesores típicos dibujando en metros: muro exterior 0.15, muro de tabique 0.28,
divisorio interior 0.10. Puertas de 0.90 (acceso) / 0.80 (interior) / 0.70
(baño); ventanas de 1.20 a 1.50.

Los huecos se ubican en forma DECLARATIVA, no sumando distancias de cabeza:
`{"segment": 1, "offset": 0.8}` (a 0.8 del arranque del tramo 1),
`"from": "end"` para medir desde el final, `{"at": "center"}` para centrarlo
en el tramo. La suma la hace el servidor y la distancia resuelta vuelve en
`openingDistances`. El `distance` crudo (a lo largo del eje desde el
arranque) sigue valiendo para cuando ya se conoce.

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
  fábrica eso pasa siempre — `create_leader` ahora lo detecta y lo avisa en
  `warning`.

## 4.quater-ter Norte, retícula y tipos de línea

**`create_north` va en TODO plano de terreno o de conjunto.** Sin norte una
planta no se orienta en el lote ni se sabe qué fachada toma el sol, y en un
plano que va a licencia es de lo primero que se revisa. `rotation_deg` se
mide desde arriba y antihorario (0 = norte arriba).

**`create_coordinate_grid`** dibuja la retícula de coordenadas de la vista
topográfica. Las cruces caen en los múltiplos exactos del espaciamiento, no
en el borde de la zona. Va en la vista CON coordenadas originales; la vista
de proyecto se dibuja sin ella — esa doble representación (una topográfica y
otra de proyecto, lado a lado) es la convención de cualquier juego serio.

**Tipos de línea: un plano se lee por el TRAZO, no solo por el color** —y en
monocromo el color ni existe. `layers.py` tiene las constantes:
`LT_EJE` (CENTER2, trazo-punto), `LT_OCULTO` (HIDDEN2, lo que va detrás),
`LT_PROYECCION` (DASHED2, lo que está arriba: volados, losas) y `LT_LIMITE`
(PHANTOM2, colindancia y área de proyecto). Si el AutoCAD está en castellano
y solo tiene CENTRO2/OCULTA2/TRAZOS2, `layers.ensure` cae solo al
equivalente en vez de fallar; si ninguno carga, crea la capa continua antes
que dejarla sin existir. Y acordate de `set_display_options(linetype_scale=)`
o dibujando en metros los trazos salen continuos igual.

## 4.quater-bis Terreno: `create_construction_table`

Todo plano de terreno en México lleva su **cuadro de construcción**: una fila
por lado del polígono con rumbo cuadrantal (N 45°30'20" W), distancia y
coordenadas del vértice, más superficie y perímetro al pie. Sin él, el plano
no se puede replantear en campo. La tool lo CALCULA de los vértices reales
(los de la polilínea ya dibujada, leídos con `get_entity`) — rumbos por
`atan2`, superficie por shoelace — y marca los vértices V1, V2... sobre el
polígono. Nada se escribe de memoria: el número que sale es el que mide el
dibujo. Formato copiado de un plano profesional real (INFONAVIT).

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

## 4.sexies Armado: la separación es un MÁXIMO, y no se inventa

`create_column_section` dibuja la sección TRANSVERSAL (estribo cerrado de
punta, varillas como puntos). `create_rebar_elevation` dibuja la otra vista:
las varillas longitudinales y los estribos como escalera. Esa segunda es la
que ocupa el grueso de un detalle de cimentación real, y la que separa un
corte de cajas vacías de un detalle constructivo.

Dos reglas que la tool aplica sola, para no depender de que quien dibuja se
acuerde:

- **`stirrup_spacing` no tiene default.** "est. del no. 3 (3/8") @ 20 cms"
  es un dato del proyecto. Sin él, `ValueError` — igual que
  `calculate_quantities` se niega a cuantificar sin la profundidad real.
- **La separación pedida es un MÁXIMO de obra.** Al cerrar parejo, el paso
  real redondea siempre hacia MÁS estribos, nunca hacia menos: uno de menos
  es un error estructural, uno de más son unos centímetros de acero. Si no
  cerró justo, lo avisa con el número real.

`confinement_length` + `confinement_spacing` juntan los estribos en los dos
extremos, que es como se arma una columna de verdad. Van los dos o ninguno.

**`depth` (la dimensión fuera del plano) hace falta para cuantificar.** Una
elevación no la ve, así que sin ella el perímetro del estribo sale `None` y
se avisa — un número inventado ahí se convierte en kilos de acero inventados
en el cuadro de cuantificación.

Devuelve el número REAL de estribos y el largo REAL de varilla, para que
`calculate_quantities` mida lo dibujado en vez de recordarlo.

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

## 6.quinquies Los símbolos de convención: nivel, título de vista, marca de corte

Tres cosas que aparecen en cualquier juego profesional y que **no se arman con
`create_text` + `create_line` sueltos**, por la misma razón que la simbología
eléctrica: un símbolo normalizado tiene que salir igual en todas las láminas.

- **`create_level_mark`** — la marca de N.P.T. de cortes y fachadas. Se le pasa
  la cota REAL del dibujo, no dónde quede lindo el texto: el símbolo apoya su
  punta ahí y el número sale al costado. Un nivel que flota sobre su cota
  miente, y eso es peor que no ponerlo. El cero sale con `±` porque es el nivel
  de referencia, no un `+0.00` cualquiera. Escrito a mano ya se encimó de
  verdad —"N.P.T. +1.40" contra "DESCANSO"— y `check_annotations` no lo vio
  porque nunca supo que ese texto existía.
- **`create_view_title`** — TODA vista lleva el suyo: nombre, subrayado grueso
  y `ESC. 1:50` debajo más chico. Es lo que convierte tres dibujos sueltos en
  una lámina. Sin jerarquía de texto, el nombre de la planta pesa lo mismo que
  una nota al pie. Por default separa las letras (`P L A N T A`), que es como
  se rotula en la mayoría de las oficinas.
- **`create_section_mark`** — lo único que liga una planta con su corte. Sin
  esto son dos dibujos sueltos: nada dice de dónde se sacó el corte ni hacia
  dónde se mira, que es la mitad de la información. La cola gruesa entra
  **hacia adentro** del dibujo a propósito; los extremos del corte caen fuera
  del edificio y una cola hacia afuera deja la marca flotando lejos de lo que
  corta.

Va en la capa `MARCAS-CORTE`, **no** en `CORTES` (que ya es el detalle de capas
de pavimento de `create_layer_section`) ni en `SECCIONES` (los cortes viales).

Los tres registran su huella en `space`, así que `place_labels` no les escribe
encima y `check_annotations` los revisa sin que haya que pasárselos.


## 5.bis Del partido al plano: `draw_layout` → `suggest_furniture` → `dimension_layout`

Tres tools encadenadas que van desde los `rooms` de `suggest_layout` hasta el
plano dibujado, sin que nadie calcule una coordenada:

- **`draw_layout`** dibuja la muraria completa: cada frontera UNA vez, puertas
  en su muro abriendo a su recinto, ventanas en el paño libre más grande, y
  **fusiona los contornos al terminar** — sin eso cada tramo es una polilínea
  cerrada y su línea de cierre queda atravesando el muro al que llega: el
  encuentro se ve como un cajón y el plano parece hecho a mano.
- **`suggest_furniture`** amuebla: nada contra el muro de una puerta, la pieza
  principal contra el muro libre más largo, y lo que no entra se reporta en vez
  de forzarlo. Dos reglas que costó descubrir mirando el dibujo de cerca: los
  muebles se apoyan en la **cara interior** del muro (los `rooms` vienen en
  EJES, y apoyar ahí mete el mueble media pared adentro), y la mesada de la
  cocina se dibuja **interrumpida** por el fregadero y la estufa — entera abajo
  de ellos deja tres contornos superpuestos y se ven líneas dobles.
- **`dimension_layout`** acota: cada lado acota **su propio paño**, o sea los
  recintos que apoyan en ese borde. Tomar todas las fronteras del plano metía
  en la cadena de abajo divisiones del fondo y los números salían encimados
  ("0.500.50").

**Mirar de cerca no es opcional.** Los cuatro defectos de arriba pasaron los
`check_*` y se veían bien en una captura del plano entero: aparecieron recién
al acercarse. Para eso `capture_viewport` acepta `min_x/min_y/max_x/max_y` —
una foto a la extensión completa sirve para el encuadre, no para juzgar la
calidad del dibujo.

**Las cotas necesitan su estilo o salen con el formato del sistema.**
`annotation.ensure_dim_style()` deja `MCP-COTAS` con punto decimal y dos
decimales; sin él, en una máquina en español las cotas salen "3,5". Ojo: las
medidas del estilo van en **mm de papel**, no en unidades del modelo — el
DIMSCALE que la cadena le pasa a cada cota hace la conversión, y guardarlas ya
convertidas las escala dos veces (el texto salió de 2 cm en un plano de 16 m).

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

**Coordinar disciplinas: xref, no copiar y pegar.** Cuando arquitectura,
estructura e instalaciones son archivos separados, la base se vincula con
`attach_xref` en vez de copiar su geometría a este DWG — `insert_block` con
`path` deja un bloque congelado en el momento de insertarlo; un xref se
actualiza con `reload_xref` cuando el otro consultor cambia su archivo.
`list_xrefs` antes de dar un plano por terminado, para saber si alguna
referencia quedó `Unresolved`/`FileNotFound` (rutas relativas que no
resuelven en la máquina de destino, típicamente).

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

**Al empezar el dibujo, `set_dim_style_family`.** Deja `COTAS25`, `COTAS50`,
`COTAS100` y `COTAS150` armados DENTRO del DWG, cada uno con la altura de texto
igual a los mismos milímetros de papel por su escala (dibujando en metros con
`paper_mm=2.0`: COTAS50 → 0.10, COTAS100 → 0.20). `create_dimension_chain`
resuelve la altura al vuelo y funciona, pero no deja nada en el archivo: quien
lo reciba y siga acotando no tiene con qué seguir la misma convención y la
segunda tanda sale de otro tamaño. Los 2 mm salen de medir un juego de planos
real; la ISO admite 2.5.

`create_dimension` suelta queda para lo puntual: un detalle, una diagonal, un
hueco aislado. Ahora registra sola su franja en el espacio de anotación, así
que `check_annotations` la ve y las cadenas siguientes se apilan afuera de
ella — pero seguí prefiriendo la cadena.

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

No es un catálogo cerrado de materiales — en obra real hay miles, y esta
tool no puede (ni debe) enumerarlos todos. Lo que sabe hacer son las
operaciones geométricas que cualquier material comparte: área×profundidad,
perímetro×longitud, módulo de pieza+merma. `area_finish` en particular
recibe `material` como texto libre (aplanado, piso, boquilla, lo que sea
del proyecto) y agrupa el total bajo ese nombre — el listado de conceptos lo
define la obra, no el código.

Tipos disponibles: `concrete_volume`, `brick_count`, `mortar_volume`,
`steel_weight` (varilla longitudinal + estribos + malla electrosoldada, ya
sumables en un mismo item), `earthwork` (excavación/relleno), `formwork`
(cimbra, por cara dibujada o por perímetro de sección) y `area_finish`
(aplanados, piso, pintura, impermeabilizante...). Todos aceptan `waste_pct`
(merma real de obra: desperdicio de colado, retazos de corte, sobrante de
mezcla) — por default 0.0, nunca se inventa una merma que el proyecto no
pidió.

Lo único que el dibujo no muestra a escala es el **acero**: una varilla en
corte es un círculo esquemático de ~1cm, no la sección real. Ahí se toma la
especificación que ya quedó anotada en el plano (varillas, diámetro,
separación de estribos) — sigue siendo un dato del proyecto, no un supuesto
de la tool. Para el perímetro del estribo, pasale `stirrup_handle`: mide el
`length` real del estribo ya dibujado (Polyline cerrada) en vez de
recalcularlo a mano. Lo mismo para la cimbra por sección: `section_handle`
mide el perímetro real de la sección ya dibujada. Y si la varilla
longitudinal supera el largo comercial (`commercial_length`), el traslape
se calcula en diámetros reales de barra (`lap_diam_factor`, típico 40-60),
no se asume una pieza continua que no existe en obra.

El relleno de una excavación (`earthwork` con `mode="backfill"`) se calcula
por diferencia real: volumen de la excavación menos `structure_volume`, el
volumen YA calculado en otro item de `concrete_volume` que ocupa el mismo
hueco — no se recalcula aparte, se pasa el número real.

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

`check_all` corre todos los checks de cierre en una llamada, incluidos los
xrefs (uno `Unresolved`/`FileNotFound` sale como problema). Y `export_pdf`
avisa si hubo dibujo nuevo desde el último `check_all`: exportar es entregar,
y un plano se revisa antes de entregarse.

`check_annotations` cierra el ciclo de los otros cuatro `check_*`: ellos miran
el proyecto, este mira el plano **como dibujo** — que las cotas, las burbujas
y los rótulos no se encimen. Sale limpio solo mientras se use
`create_dimension_chain`; da problemas cuando algo se ubicó a mano.

`create_table` es de lo que se ubica a mano: no sabe qué más hay dibujado, así
que un cuadro de especificaciones al lado de una ilustración (un detalle de
castillo, una planta) puede terminar tapándola sin ningún aviso — pasó de
verdad, con los nombres de la tabla encimados sobre el dibujo del detalle.
Si ya se conoce la caja de esa ilustración, pasarla en `avoid` y `create_table`
avisa en `warning` si la tabla cae encima, en vez de dibujarse en silencio.

Después de dibujar, `zoom_extents` y `get_drawing_info` para confirmar la
cantidad de entidades. Si se creó geometría cerrada, `calculate_area` sobre las
polilíneas para chequear que las medidas dan lo que se pidió.

Los `check_*` validan números y reglas, pero no reemplazan mirar el dibujo:
`capture_viewport` saca una foto PNG del espacio activo (o de un layout
puntual) para revisar visualmente que nada quedó encimado o fuera de lugar
antes de decir que un plano está terminado. Si una serie de llamadas salió
mal, `undo` deshace las últimas N sin tener que borrar entidad por entidad.

`check_drawing_hygiene` cierra otro ángulo: no valida el proyecto ni el
dibujo como plano, valida el ARCHIVO — capas creadas y nunca usadas, texto
que quedó en una fuente `.shx` (no mapea acentos), entidades duplicadas
exactas superpuestas. Correlo antes de entregar un DWG, no solo antes de
plotear.

## Iterar el diseño del rótulo sin AutoCAD

`python mcp_server/preview_sheet.py salida.svg` renderiza el cajón + rótulo, y
`python mcp_server/preview_plan.py salida.svg` un plano completo con muros,
huecos y ejes. Los dos mockean el socket: no necesitan AutoCAD. Cambiar
`sheet.py` o `arch.py` y volver a correrlos es mucho más rápido que probar a
mano en AutoCAD.

El preview dibuja también las cotas (las descompone en sus líneas y su
número), así que el encimado se ve ahí y no recién al abrir el DWG.

Antes de dar por buena cualquier cambio, correr `python mcp_server/run_tests.py`
— son las 25 suites que no necesitan AutoCAD, en unos 15 segundos. Cubren el
inglete de las esquinas, el partido de los huecos, que los abatimientos barran
90°, que las cadenas de cota y las burbujas no se pisen en ningún orden de
dibujo, y que cambiar de dibujo no arrastre el estado del anterior. Con AutoCAD
abierto, `--live` agrega `test_live.py`.

## Espacio papel vs espacio modelo

`create_sheet` dibuja el cajón en el espacio modelo y alcanza para una lámina
única. Cuando el pedido implique **varias escalas en la misma lámina** o
**varias láminas del mismo modelo**, usar `create_layout` + `create_viewport`:
el dibujo queda una sola vez en el modelo y cada viewport lo muestra a su
escala. Dentro del layout las coordenadas son milímetros de papel, y
`create_viewport` EXIGE `model_units_per_mm` (1000 dibujando en metros, 10 en
cm, 1 en mm) — antes tenía default 1.0 y la escala salía mil veces mal en
silencio; ahora sin el dato se niega.

Con el layout armado, `export_pdf(layout, path)` lo plotea a PDF por API con
la configuración que `create_layout` ya dejó guardada (papel, dispositivo) —
no hace falta ir a AutoCAD y hacer PLOT a mano para entregar la lámina.

**Cuándo usar layouts, en la práctica.** No es solo "varias escalas en la
misma hoja": un proyecto con **varios planos distintos en el mismo
archivo** (una casa + una escalera + un puente, por ejemplo) es el mismo
caso. Dibujar cada uno con su propio `create_sheet` en el modelo, corridos
a mano en X para que no se pisen, funciona pero no es lo correcto — el
camino es un `create_layout` por lámina, cada uno con su viewport (o
varios) apuntando a la parte del modelo que le toca. Se evita el
malabarismo de `get_extents`/`fit_sheet` a mano cada vez, y el modelo
queda un solo dibujo coherente en vez de piezas desperdigadas en
coordenadas arbitrarias.

**Nombrá cada layout con `name=` al crearlo** (p.ej. `"PV-01"`, no dejarlo
en el `"Layout1"`/`"Layout2"` que trae la plantilla de AutoCAD por
default) — un dibujo con pestañas sin nombre no dice nada al abrirlo.
Si esas pestañas por default quedan sin usar, `delete_layout` las saca en
vez de dejarlas como clutter.

**Tres cosas que pasaron de verdad, para no perder tiempo la próxima vez:**

- Abrir y cerrar documentos rápido por API dispara un bug del PROPIO
  AutoCAD 2022: `NullReferenceException` en su `CommandEditor` (evento
  Idle, el plugin ni aparece en el stack), y el diálogo de "Unhandled
  exception" que sale **congela el socket** hasta que alguien clickea
  Continue. Desde el plugin 1.3.0 un watchdog (hilo de fondo) le clickea
  Continue solo y lo anota en `%LOCALAPPDATA%\AutoCadMcp\dialogos.log` —
  `Application.ThreadException` NO alcanzaba, AutoCAD crea el diálogo
  directo. Si el socket se cuelga con un plugin más viejo, buscá ese
  diálogo en pantalla.

**Los errores transitorios se reintentan SOLOS — no reintentes a mano.**
`autocad_client.call` repite hasta 3 veces las fallas que se arreglan
esperando (plot ocupado, comando en curso, listener levantándose): siempre
si la conexión ni se estableció, y solo comandos de lectura/plot si la
falla fue después — lo que dibuja jamás se repite tras un timeout, porque
pudo haber llegado y quedaría duplicado. Si un comando falla dos veces
seguidas, es un error real: leé el mensaje, no insistas. Y `zoom_extents`
es síncrono desde el plugin 1.4.0: cuando responde, el zoom ya está hecho
(antes encolaba el comando y un `capture_viewport` inmediato moría con
`eInvalidInput`).
- Crear el **primer** layout de un dibujo puede disparar un diálogo modal
  de AutoCAD ("Configurar página" o similar) que bloquea el socket del
  plugin — cualquier comando, hasta `ping`, se cuelga con timeout hasta
  que alguien lo cierra a mano en pantalla. No es un error del plugin: si
  un comando se cuelga justo después de un `create_layout`, avisale al
  usuario que revise si hay un diálogo abierto antes de asumir que algo
  se rompió.
- La rotación del plot de un viewport puede salir heredada de ese mismo
  diálogo (90° sin haberlo pedido). Conviene `capture_viewport(layout=...)`
  el layout terminado y mirarlo antes de darlo por bueno — no asumir que
  la escala/orientación quedó como se pidió solo porque `create_viewport`
  no tiró error.

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
