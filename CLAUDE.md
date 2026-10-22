# Cómo dibujar planos con este MCP

Reglas de trabajo cuando alguien pide dibujar algo en AutoCAD con estas tools.

## 000. Qué tool va: `list_tool_categories` (el mapa, ordenado como la cinta de AutoCAD)

Con 250+ tools, buscar a ciegas gasta turnos. `list_tool_categories()` las ordena en dos familias: las **genéricas**, con el nombre de los paneles de la cinta de AutoCAD (`dibujo`, `modificar`, `anotacion`, `capas`, `bloques`, `propiedades`, `utilidades`, `vista`, `modelado3d`, `layouts`, `xref`, `sistema`), y las de **proyecto**, por tipo de trabajo (`p_arq` casa, `p_est` estructura, `p_inst` instalaciones, `p_civil` vial y terreno, `p_det` detalles, `p_3d`, `p_entrega`). `category=<clave>` lista sus tools con una línea de qué hacen y los comandos de AutoCAD que cubren; **`workflow=casa|estructura|instalaciones|vial|3d|laminas` da los pasos EN ORDEN con la tool de cada uno** (qué se requiere para hacer una casa); `query=<texto>` busca. Una tool nueva se registra en `mcp_server/categorias.py` (`test_categorias.py` falla si falta o sobra una).

**Cobertura contra AutoCAD, leída y no recordada:** `python tools/mapa_cinta.py` extrae la cinta real (`acad.cuix`: pestaña > panel > comando, 360 comandos distintos) y `python tools/cobertura_cinta.py` la cruza con las tools y escribe `COBERTURA_CINTA.md`: ✔ tool propia, ◐ alcanzable por reflexión (`create_object`/`call_object_method`/`set_object_properties`), ○ solo con interfaz, ▫ fuera de alcance, ✖ pendiente (con su familia: restricciones paramétricas, superficies y mallas, underlays...). Es la lista de qué falta, ordenada como la ve quien usa AutoCAD.

## Si no hay tool para lo que necesitás: `api_guide` → `describe_api` → `run_code`

Las tools de oficio van primero. Para lo que ninguna cubre (3D, por ejemplo),
`run_code` ejecuta C# contra la API de AutoCAD: antes leé la guía del tema
(`api_guide()` da el índice) y confirmá firmas con `describe_api(tipo, filtro)`
en vez de escribirlas de memoria. **Está apagado** salvo que el usuario lo
active él mismo (`python tools/run_code_acceso.py activar`, con contraseña):
si responde apagado, decíselo y seguí con las tools; nunca intentes activarlo
ni pedir la contraseña. Red de seguridad: corre en una transacción (si falla,
el dibujo queda intacto) y antes guarda solo; sin archivo no ejecuta salvo
`force=True`.

## 0.0 Primero: ¿de qué país es el proyecto?

Las reglas y los valores de las tools de proyecto (mínimos de recintos,
instalación eléctrica, hidráulica, sanitaria, cimentación) están codificados
con la normativa de **México**: NOM-001-SEDE-2012, INIFED, Reglamento de
Construcciones y NTC de la CDMX. Si el proyecto es de otro lugar, esos números
no valen, y un plano con notas de norma ajena es un plano con la norma
equivocada.

Por eso, **antes de proyectar, preguntar el país** (o llamar a
`get_normative`) y pasarlo en `country` a las tools que dependen de norma
(`suggest_layout`, `check_program`, `check_layout`, `check_geometry`,
`suggest_electrical`, `suggest_hydraulic`, `suggest_sanitary`,
`design_footing`). El resultado trae `normativa` con lo que se aplicó:

- **México** → `codificada`: se usa tal cual.
- **Otro país** → `no_codificada`: la tool NO dibuja (ni notas ni valores
  ajenos) salvo que el usuario acepte la norma mexicana solo como referencia
  (`accept_reference=True`) o se use `draw=False`. **Hay que investigar la
  norma vigente del país** con WebSearch/WebFetch en fuentes oficiales (el
  resultado trae el plan en `investigar`): nunca de memoria, anotando norma,
  artículo/tabla, año y URL de cada valor, y confirmando con el usuario antes
  de aplicarlo (puede variar por ciudad). Lo confirmado se pasa en
  `local_norms={"fuente": "...", "minimos": {"recamara": {"lado": 2.7,
  "area": 8.0}}}`: sin `fuente` se rechaza, y hoy lo aplica `check_geometry`
  (mínimos por uso). Lo demás (eléctrica, sanitaria, cimentación) se
  investiga igual y se dibuja con las tools manuales; `local_norms` rechaza
  una clave que no sabe aplicar en vez de fingir que la usó.
- **Perú, solo `suggest_sanitary` (desagüe)**: codificado con el RNE IS.010
  (DS 017-2012-VIVIENDA, texto oficial de vivienda.gob.pe): pendiente 1 % en
  Ø≥100 y 1,5 % en Ø≤75, cajas de registro cada 15 m, inodoro Ø100, unidades
  de descarga y diámetros de los anexos 6 y 8, notas de la norma en el plano.
  El resultado trae `normativa.verificar`: los anexos son imagen escaneada de
  baja resolución, y eso se le dice al usuario. Agua, eléctrica y el resto de
  Perú siguen sin codificar (investigar, como arriba). Un dominio nuevo de
  un país = su perfil en `normativa.PERFILES[..]["dominios"]` y la tool con
  `dominio=...` en `con_pais`.
- Sin `country` la tool corre con la referencia de México y lo advierte.

Un país que se usa seguido conviene codificarlo en `normativa.py` (perfil +
valores en las reglas) con la fuente en la mano; nunca inventarlos.

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

   **El terreno casi nunca es un rectángulo.** Cuando no lo sea, pasá
   `lot_points` con el polígono real en vez de `lot_width`/`lot_depth`: la
   superficie sale por shoelace de los vértices. Un lote de "26 x 60" con
   laterales de 64.00 y 62.30 no mide 1,560 m² — describirlo como rectángulo
   regala decenas de m² que no existen, y sobre ese número se decide si el
   programa entra. `check_layout` acepta el mismo `lot_points` y verifica que
   cada recinto caiga DENTRO del terreno y no dentro del rectángulo que lo
   envuelve: en un terreno irregular no es lo mismo, y en uno cóncavo (en L)
   no alcanza ni con que las cuatro esquinas estén adentro.
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

**El `drawArea` no es informativo: es dónde va el dibujo.** Trazar en el origen
mientras el cajón quedó en otro lado deja la planta cruzando el marco, y eso ya
pasó. `check_sheet` lo verifica al cierre, pero el momento de acertarle es al
empezar: las coordenadas del plano salen del `drawArea`, no de (0,0).

**No hagas esa cuenta a mano: `sheet_origin`.** Se le pasa cuánto va a medir el
dibujo y devuelve el punto donde apoyar su esquina inferior izquierda, ya con
el margen descontado (en **mm de papel**, no del modelo — la confusión de
siempre). Si no entra lo dice con los números y sugiere el denominador de
escala; nunca propone achicar el dibujo. Calcular el origen a mano en un
script es exactamente lo que hacía que este error volviera.

Verificá que el dibujo entre: el `drawArea` que devuelve `create_sheet` está en
unidades del modelo. Si el terreno mide 40x25m y el área útil da 80.6x51.8,
entra; si no entra, subí el denominador de escala o el formato — **nunca**
achiques el dibujo fuera de escala.

## 2.pre Regla fija: al empezar un plano, guardarlo CON NOMBRE

Antes de dibujar la primera entidad (y siempre antes de reiniciar AutoCAD,
instalar el plugin o correr algo que pueda tirarlo): `save_drawing(path=...)`
con un nombre propio. Nunca trabajar sobre `Drawing1.dwg`. Un reinicio de
AutoCAD tira lo que solo vive en memoria.

Para trabajos de la escuela el nombre sigue el formato que pide la plataforma:
`ApellidoP_ApellidoM_Nombres_S<n>.dwg` (S4 = sesión 4).

**Datos del autor — no se vuelven a preguntar.** Salen en el rótulo
(`create_sheet`: `drawn_by`, `location`, `client`, `date`, `sheet_number`) y en
el nombre del archivo:

- Alumno: JOSUE DANIEL DIAZ PEREZ (en el rótulo, si el nombre no cabe en la
  celda, `J. D. DIAZ PEREZ`; el nombre completo va en el nombre del archivo y
  en la carátula).
- Escuela: UNID (la plataforma de la materia "14956-EMIQ-INR19 Dibujo y Diseño
  en Ingeniería").

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

## 3.bis Preguntarle al dibujo: `query_entities` / `aggregate_entities`

Para «¿cuántas líneas hay por capa?», «¿qué polilíneas cerradas miden más de 12 m²?» o «¿cuántos metros de
muro hay?» NO se cuenta a mano lo que devuelve `list_entities` ni se escribe un script: `aggregate_entities`
cuenta, suma, promedia y busca extremos (`count sum avg min max minabs maxabs`, con `group_by`), y
`query_entities` devuelve las entidades que cumplen un filtro de propiedades
(`layer = MUROS AND length > 3`, `type = Polyline AND closed = true AND area > 12`,
`text contains "NPT"`). `describe_entity_fields` dice qué campos existen por tipo y cuánto cuesta cada uno:
llamala antes de consultar un tipo que no conocés.

Lo que hay que saber: el handle, el tipo, la capa, la caja (`bboxArea`, `width`...) y el texto salen de UNA
llamada; el resto (`length`, `area`, `blockName`...) se lee en detalle, en lotes, y **solo de lo que sobrevive
a las condiciones baratas**. Si quedan más de `hydrate_limit` (500) el resultado es PARCIAL y lo avisa en
`notices`/`partial`: se acota (entity_type, layer, bboxArea) en vez de subir el tope a ciegas. Un campo que
falta no cumple ninguna comparación. Es de solo lectura y no necesita plugin nuevo (usa `list_entities` y el
comando `batch` con `get_entity`). Diseño tomado del servidor MCP nativo de la 2027 (consulta por tipo y
filtro con agregaciones), escrito desde cero. `mcp_server/test_consulta.py` lo prueba sin AutoCAD; **probado en vivo** en la 2027 sobre el pórtico (2484 entidades): el conteo total coincide con `get_drawing_info` y `list_entities`, la suma de largos de 84 polilíneas de PORT-CONCRETO (394.390938) coincide al decimal con sumar `get_entity` una por una, y 401 polilíneas se leen en detalle en 0.4 s (el comando `batch` cuesta mucho menos de lo que se temía). Verificado también en la 2022 (`verificar_version.py`).

## 3.ter Variables de sistema y estado del editor (plugin 1.10.0)

AutoCAD tiene cientos de variables de sistema (LTSCALE, OSMODE, DIMSCALE, LUNITS, INSUNITS, PICKFIRST...) y el
plugin solo tocaba unas pocas, escondidas dentro de otras tools. `get_system_variables(names)` lee hasta 100 en
una llamada (las que no existen salen en `errors`); `set_system_variable(name, value)` cambia UNA y devuelve el
valor anterior para restaurarla (varias se guardan EN el dibujo, así que modifican el DWG). Las que gobiernan
seguridad o qué se carga solo (SECURELOAD, TRUSTEDPATHS, TRUSTEDDOMAINS, LEGACYCODESEARCH, DEMANDLOAD, STARTUP,
FILEDIA...) no se pueden cambiar desde una tool: las cambia una persona. `get_editor_state` dice en qué está
AutoCAD (comando en curso, editor de bloques, REFEDIT, layout, cambios sin guardar) y `busy`: mirarlo primero
cuando un comando se cuelga o falla sin motivo, casi siempre es un comando a medias de la persona.

Esto sale de leer el servidor MCP nativo de la 2027 (ver `Desktop\Autodesk_descompilado`), que antes de ejecutar
rechaza en milisegundos si hay un comando en curso, el editor de bloques o una edición en sitio abierta. Las
guardas de ESTADO todavía no se aplican a las demás tools del plugin: están como lectura (`get_editor_state`),
no como rechazo automático. **Probadas en vivo en la 2027** (plugin 1.10.0, sobre el DWG del pórtico): `set_system_variable` cambia y restaura LTSCALE, y rechaza SECURELOAD (protegida), ACADVER (solo lectura), un valor que no es número y una variable inexistente; `get_editor_state` y `get_system_variables` responden (las inexistentes salen en `errors`). Verificado también en la 2022 (`verificar_version.py`).

**Ejecutar cualquier comando nativo de AutoCAD (`run_command`) NO está conectado.** Hay un diseño escrito (un
comando registrado `MCPRUNJOB` que corre `Editor.Command` con los tokens, tras la contraseña de run_code y una
lista de comandos prohibidos) pero se dejó fuera del repo a propósito: es una puerta de ejecución y hay que
decidirla con el usuario. Es lo que hace Autodesk con su módulo nativo `AcMCPCore.crx`.

## 3.quater Edición con el motor nativo: `trim_entity`, `extend_entity`, `fillet_entities`, `join_entities`, `overkill_entities`

Recortar contra bordes, extender, empalmar con radio, unir tramos y borrar superpuestos son problemas de
intersección con muchos casos (arcos, bulges, bordes implícitos). AutoCAD ya los resuelve: estas tools le
mandan la operación a SU comando (`TRIM`, `EXTEND`, `FILLET`, `JOIN`, `-OVERKILL`) en vez de reescribirla. Se usan
para CORREGIR sin rehacer: un muro que sobra, una esquina que no cierra, tramos sueltos que hay que unir para
achurar o medir, líneas duplicadas que duplican el largo cuantificado (`overkill_entities(all=True)` antes de
`calculate_quantities`).

No son un ejecutor de comandos: cada operación tiene su comando FIJO en el plugin (`NativeOpsCommand.cs`) y solo
recibe handles de entidades que existen y números; nadie elige qué comando corre. Devuelven `created`, `deleted`
y `modified` (la caja antes/después) para verificar, y si no cambió nada lo dicen en `warning` (punto que no cae
sobre el tramo, bordes que no cortan —`extend_edges=True`—, capa bloqueada). **`undo` las revierte, de a un paso y verificando.** Descubierto en vivo (2027): cada llamada de LECTURA que abre una transacción (`get_entity`, `list_entities`, `get_drawing_info`...) deja un paso vacío en el historial de UNDO de AutoCAD —`ping` y las variables de sistema no—, así que contar pasos no sirve: tras un join con 2-3 lecturas en medio hacían falta 2, 3 o 4 pasos. Por eso `undo` deshace una operación nativa de a UN paso y comprueba después de cada uno si volvió lo que cambió (borradas, creadas, cajas de las modificadas; `deshacer` en `edicion.py`), con tope de 3 pasos para no deshacer operaciones ajenas. Verificado en la 2027 con JOIN, FILLET, TRIM y OVERKILL: 1 paso cada una. **Límite conocido:** una tool de dibujo (`create_line`...) con lecturas entre medio y el `undo` NO se deshace a la primera (un paso se va en la lectura); sin lecturas en medio sí. La causa está en código nativo de AutoCAD (el `StartTransaction` administrado es una llamada directa a su tabla de funciones: no se ve por descompilación). El plugin 1.10.1 apaga el registro de UNDO durante las lecturas, pero no alcanzó: sigue pasando. Con plugin anterior a 1.10.1 `undo` pide 2 pasos sin verificar y avisa.
Rechazan con motivo si hay un comando en curso, el editor de bloques abierto o la vista no está en planta
(`zoom_extents` la devuelve a planta). Los puntos (`point`, `point1`...) se llevan solos a la curva y la vista se
encuadra un instante alrededor porque el cursor de selección mide en píxeles; se restaura al terminar.
Corren en un comando registrado (`MCPNATIVEOP`) porque `Editor.Command` no anda desde el evento Idle: la tool
espera el resultado (`wait_s`, 30 s) y, si tarda más, queda en curso: `native_status`, **no repetir**.

Plugin nuevo (1.10.0): hay que reinstalar el bundle. **Probadas en vivo en la 2027** sobre líneas de prueba en un dibujo nuevo: TRIM recortó una línea de 10 a 5 contra un borde, EXTEND alargó de 3 a 6, FILLET radio 0 cerró la esquina y radio 2 creó el arco de centro (68,42), JOIN unió dos líneas en una (la otra se borró) y OVERKILL borró la línea duplicada y dejó las otras; FILLETRAD se restauró. Verificado también en la 2022; los tests offline (`test_edicion.py`) cubren solo las validaciones y el puente.

## 3.quinquies Propiedades de CUALQUIER objeto: `get_object_properties`, `set_object_properties`, `list_object_properties` (plugin 1.11.0)

La API de objetos de AutoCAD tiene miles de propiedades (código descompilado, ver `Desktop\Autodesk_descompilado\notas\G_catalogo_api.md`:
73 clases de entidad, ~3.700 propiedades escribibles contando lo heredado por cada una). Escribir una tool por propiedad no escala y un
comando C# por propiedad obligaba a recompilar y reiniciar. Estas tres tools las descubren por REFLEXIÓN sobre la clase real del objeto en la
versión instalada (lo que no existe en una versión no aparece: 2022 y 2027 no tienen que coincidir):

- `list_object_properties(entity_type | handle)`: qué propiedades tiene (nombre, tipo, si se escribe, de qué clase viene; las enumeraciones
  traen sus valores). Línea 41/17 escribibles, círculo 42/21, texto 46/27, MText 61/38, achurado 55/28, polilínea 46/21, cota rotada 152/122,
  Viewport 90/62, Solid3d 35/15, Light 56/38, capa (`LayerTableRecord`) 26/14.
- `get_object_properties(handles, names?)`: lee hasta 500 objetos; sin `names`, todas las que se saben leer.
- `set_object_properties(handles, {nombre: valor}, dry_run?)`: cambia varias propiedades de varios objetos en UNA transacción. Se valida
  TODO antes de escribir (existe, es escribible, el valor convierte al tipo); si algo falla (capa inexistente, valor inválido) no queda nada a
  medias. Devuelve `before`/`after` por objeto. `dry_run` muestra qué cambiaría.

Valores: números, texto, booleanos, puntos `[x,y,z]`, vectores, escalas, colores (índice 1-255, `"ByLayer"`, `"ByBlock"` o `[r,g,b]`) y
enumeraciones por nombre (`"LineWeight050"`). Lo que no es de esos tipos (colecciones, objetos anidados) no se maneja y el error lo dice. Los
nombres no distinguen mayúsculas; los de infraestructura (`Database`, `ObjectId`...) nunca se escriben. Es de PROPIEDADES: no ejecuta
métodos ni llama a nada estático. Para elegir los objetos: `query_entities`; para cambiar muchos de una vez: sus handles a `set_object_properties`.

Verificado en vivo (2027) sobre línea, círculo, arco, polilínea, texto, MText y achurado: cambió extremos, capa, color (índice y RGB),
espesor de línea por nombre, escala de tipo de línea, radio (el área se recalculó), texto, altura, rotación, cierre de polilínea y escala de
patrón; rechazó con motivo una propiedad de solo lectura, una inexistente, un tipo equivocado, una enumeración inválida y una capa que no
existe, sin tocar nada; la llamada con una propiedad buena y una mala no cambió ninguna. `undo` la revierte si no hay lecturas entre medio
(misma limitación que arriba). Verificado también en la 2022 (ver `verificar_version.py` abajo).

## 3.sexies Métodos de cualquier objeto: `list_object_methods`, `call_object_method` (plugin 1.12.1)

La otra mitad de la API: una curva sabe desfasarse (`GetOffsetCurves`), partirse (`GetSplitCurves`), dar su punto más cercano a otro
(`GetClosestPointTo`), cortarse con otra entidad (`IntersectWith`), dar el punto de un parámetro (`GetPointAtParameter`), invertirse
(`ReverseCurve`), extenderse (`Extend`), explotarse (`Explode`)... AutoCAD ya lo resuelve; reescribirlo es el error geométrico de siempre.
Por reflexión sobre la clase real del objeto, como las propiedades: línea/círculo/arco 60 sobrecargas admitidas, polilínea 78, texto 44, MText 51,
achurado 53, bloque 46, cota 50, Solid3d 56, Region 42 (de 120-170 métodos públicos cada una).

- `list_object_methods(entity_type | handle, filter?)`: qué métodos hay, con parámetros tipados (enumeraciones con sus valores; un objeto del
  dibujo se pasa por su handle), qué devuelven y si se abren en `read` o `write`.
- `call_object_method(handle, method, args, add_results_to_space?, mode?)`: invoca uno. Los parámetros de salida y el marcador gráfico se
  crean solos y vuelven en `out`; una colección que el método RECIBE (los puntos de `GetSplitCurves`) va como último argumento. Lo NUEVO que
  devuelve un método (curvas de `GetOffsetCurves`, pedazos de `GetSplitCurves`, `Explode`) se descarta salvo `add_results_to_space=True`: entonces
  se agrega al espacio activo y vuelven sus handles. Una transacción: si AutoCAD rechaza la llamada no queda nada a medias; una lectura se aborta
  y no deja rastro en el deshacer.

Qué se permite: lista BLANCA de forma —solo métodos públicos de INSTANCIA declarados por la API de AutoCAD, no genéricos, con parámetros
simples (números, texto, booleanos, puntos, vectores, escalas, enumeraciones) o un objeto del dibujo por handle— y lista NEGRA de nombres: sin
el ciclo de vida (`Dispose`, `Close`, `Open`, `UpgradeOpen`, `SwapIdWith`...), sin lo que guarda/exporta/carga/ejecuta (`Save*`, `Export*`,
`DxfOut`, `Plot*`, `Load*`, `Execute*`...) y sin parámetros que parezcan rutas o direcciones. Nada estático, nada de `System.*`. No es un ejecutor
de comandos ni de código: solo operaciones de los objetos del dibujo.

Verificado en vivo (2027): punto más cercano, punto en un parámetro, distancia a un parámetro (polilínea, 15 en el parámetro 1.5),
intersecciones línea×línea (5,0) y círculo×línea (2 puntos), desfase con y sin agregar, `Extend`, `ReverseCurve` (extremos intercambiados),
`Explode` (2 líneas) y `GetSplitCurves` por puntos y por parámetros (3 pedazos); rechazó con motivo un método inexistente, `Dispose`, `Close`, un
argumento de tipo equivocado y un handle inexistente.

**3D real, verificado en vivo (2027, plugin 1.13.2).** `Solid3d`: `MassProperties` se lee como objeto (volumen 500 de una caja 10×10×5, centroide, extensiones, momentos de inercia, radios de giro: el volumen REAL del modelo para cuantificar), `CheckInterference`, `TransformBy` con una matriz 4×4 (`[[1,0,0,10],[0,1,0,0],[0,0,1,0],[0,0,0,1]]` movió el centroide a 15,5,2.5), `OffsetBody` (volumen 1008 = 12×12×7), `Slice` con un plano `{"point":[..],"normal":[..]}` (la mitad negativa vuelve como sólido nuevo con `add_results_to_space`), `BooleanOperation` con `BoolUnite` (1500), `BoolSubtract` (500) y `BoolIntersect` (500); `Region`: área y perímetro como propiedades, `Explode` (8 líneas) y `BooleanOperation` entre regiones (150 − solape 50 = 100); malla `SubDMesh`: vértices/caras/aristas como propiedades, `ComputeVolume`, `ComputeSurfaceArea`, `GetVertexAt`, `SubdDivideUp` y `ConvertToSolid`. Tipos nuevos soportados: matriz 4×4 (16 números o 4 filas) y plano; las estructuras de solo lectura con campos simples (`Solid3dMassProperties`) se leen como `{campo: valor}`.

**Una llamada mal armada puede TUMBAR AutoCAD, no solo fallar.** Pasó en vivo: `BooleanOperation` con el segundo sólido abierto en LECTURA (lo consume, necesita escritura) cerró AutoCAD sin excepción. Desde 1.13.2 los objetos que van como argumento se abren en escritura si el método escribe; pero cualquier método nativo puede tener una precondición que esta capa no conoce. **Probar un método nuevo en un dibujo descartable y con el trabajo guardado**, no sobre un plano en curso. Los parámetros de tipo `Surface`/`Plane` en `Slice` con superficie, `Extrude` desde región y las primitivas (`CreateBox`...) sin probar. `IntersectWith` con `ExtendBoth` entre una línea y una polilínea
devolvió 0 puntos: sin investigar.

## 3.sexies-bis Crear cualquier entidad: `create_object` (plugin 1.14.0)

`create_object(entity_type, properties?, init_method?, init_args?)` crea una entidad de CUALQUIER clase de AutoCAD (`Line`, `Circle`, `Solid3d`, `SubDMesh`, `PlaneSurface`...) por reflexión, con sus propiedades validadas ENTERAS antes de crear (si algo falla no queda nada), y la agrega al espacio activo. Cierra el círculo con `get/set_object_properties` y `call_object_method`: lo que no es una propiedad se hace con `init_method`. Las primitivas 3D son así: `create_object('Solid3d', init_method='CreateBox', init_args=[10,5,3])`; `CreateSphere [r]`, `CreateTorus [R, r]`, `CreateWedge`, `CreatePyramid`, `CreateFrustum`. Si el método de inicio falla, la entidad vacía se borra. No se crean de la nada las que necesitan más que propiedades (`Viewport`, OLE, imágenes, referencias de atributos). `Solid3d.Extrude(region, altura, ahusado)` sobre un sólido vacío levanta una región; `Slice(superficie, True)` corta con una `PlaneSurface` (`create_object('PlaneSurface')` + `CreateFromRegion(region)` + `TransformBy`).

Verificado en vivo con `mcp_server/prueba_primitivas_3d.py` (dibujo descartable): **16/16 en AutoCAD 2022 y 16/16 en 2027** (caja 10×5×3 = 150, esfera r=2 ≈ 33.51, cuña 10×4×6 = 120, toro, región de 175 m² extruida 4 = 700, corte con superficie → el original queda en 500).

## 3.sexies-ter Recorrer el dibujo y la base de datos: `list_children` y `DATABASE` (plugin 1.15.0)

Las propiedades y los métodos de CUALQUIER objeto ya se alcanzaban por handle, pero una capa, un estilo, un bloque o un layout no tenían tool que diera su handle. `list_children(target)` los da: `target` es `'DATABASE'` (la raíz: los contenedores y sus nombres cortos), un nombre corto —`layers`, `textstyles`, `dimstyles`, `linetypes`, `blocks`, `regapps`, `ucs`, `views`, `viewports`, `layouts`, `mleaderstyles`, `tablestyles`, `mlinestyles`, `materials`, `visualstyles`, `groups`, `named`, `plotsettings`, `plotstyles`— o el handle de una tabla, un diccionario o un bloque. De una tabla o un diccionario devuelve `{name, handle, type}`; de un bloque, sus entidades `{handle, type, layer}` (`*Model_Space` lista el espacio modelo, `*Paper_Space*` los de las láminas), paginado (`skip`/`take`, `hasMore`).

`'DATABASE'` también vale como handle en `get_object_properties` / `set_object_properties`: es la base de datos del dibujo (302 propiedades legibles: unidades `Insunits`, `Lunits`, `Ltscale`, las variables de cota por defecto `Dimxxx`...). Escribir en `DATABASE` y en objetos en la misma llamada es todo o nada: si falla lo de los objetos, `DATABASE` vuelve a su valor. Con esto cada capa (29 propiedades), estilo de cota (85), layout (47), estilo de directriz o material queda al alcance de las tools de propiedades y métodos.

Verificado en vivo con `mcp_server/prueba_navegacion.py`: **26/26 en AutoCAD 2022 y 26/26 en 2027**. Sobre el DWG del pórtico (solo lectura): 33 capas, 3 estilos de texto, 7 de cota, 6 tipos de línea, 112 bloques, 7 layouts, `*Model_Space` con sus 2484 entidades; y sobre un dibujo nuevo: bloquear y describir una capa, ponerle color RGB, cambiar `Dimtxt` de un estilo de cota, `Ltscale` de `DATABASE` (y restaurarlo), y la atomicidad. Todavía NO hay forma de CREAR o BORRAR esos objetos (una capa, un estilo) ni de tocar lo que la reflexión no maneja (colecciones: propiedades de bloques dinámicos; estáticos: configuración de impresión).

## 3.sexies-quater Crear y borrar lo que no es una entidad: `create_database_object`, `delete_database_object` (plugin 1.16.1)

Capas, estilos de texto y de cota, **definiciones de bloque**, aplicaciones registradas y sistemas de coordenadas: `create_database_object(kind, name, properties)` con `kind` = `layer` | `textstyle` | `dimstyle` | `block` | `regapp` | `ucs`. Las propiedades se validan ENTERAS antes de crear y todo va en una transacción (si algo falla, no queda nada). Un bloque nace vacío: sus entidades se agregan con `create_object(..., container='NOMBRE')` y se inserta con `insert_block`. `delete_database_object(kind, name | handle)` borra por nombre o por handle.

Las barreras: nombre sin `< > / \ " : ; ? * | , = `` ni espacios en los bordes ni `*` inicial; no se crea uno repetido; no se tocan los del sistema (capa 0 y Defpoints, estilo Standard, `*Model_Space`, bloques anónimos) ni el ACTUAL. **«En uso» lo decide AutoCAD con la prueba de PURGE** (`Database.Purge`): lo que el dibujo todavía referencia —una capa con objetos, un estilo con texto, un bloque insertado— se rechaza con motivo. Dos cosas que descubrió la prueba en vivo y que habrían hecho daño: (1) `Erase` a secas BORRABA una capa con objetos y los dejaba apuntando a una capa borrada; (2) la descripción de una capa se perdía si las propiedades se fijaban antes de agregar el registro a la tabla (ahora van después, dentro de la misma transacción).

Verificado en vivo con `mcp_server/prueba_crear_objetos.py`: **38/38 en AutoCAD 2022 y 38/38 en 2027** (capa con color RGB, espesor y descripción; dibujar en ella; rechazos de repetida, nombre inválido, propiedad inexistente, valor inválido, capa con objetos, capa 0, capa actual, estilo Standard, `*Model_Space`, bloque insertado; estilo de texto con fuente; estilo de cota con `Dimtxt`/`Dimscale`; un bloque de 3 entidades armado, insertado y borrado). Sin crear: layouts, estilos de directriz/tabla/multilínea, materiales, tipos de línea (se cargan de un archivo).

## 3.sexies-quinquies Lote 1.17.0: purga, grupos, XData, datos propios, atributos, escalas de anotación, impresión y bloques dinámicos

**ESTADO: verificado en vivo, 134/134 en AutoCAD 2022 y 134/134 en 2027** (`python mcp_server/verificar_lote_1_17.py`; plugin 1.18.0, que cubre también las tools de 1.17.0), y compila en 2019-2027 (`tools/matriz_api.py`); 2019-2021 y 2023-2026 siguen sin probarse en un AutoCAD real. Las que escriben van en transacción (todo o nada) y validan antes de tocar el dibujo.

- **`purge_database_objects(kinds, dry_run)`** — usa `Database.Purge`, la misma prueba de «en uso» de PURGE: bloques, estilos de cota y texto, tipos de línea, capas, regapps, UCS y vistas. Salta los del sistema (capa 0, Defpoints, Standard, `*`) y los actuales. `dry_run=True` solo lista.
- **`set_current(kind, name)`** — capa, estilo de texto, de cota o tipo de línea actual (lo que antes era un `set_system_variable` a ciegas).
- **`create_group` / `delete_group` / `modify_group`** — grupos nombrados (`GROUP`): agregar y quitar miembros por handle.
- **`get_xdata` / `set_xdata` / `clear_xdata`** — datos extendidos por aplicación (regapp), con tipos explícitos (texto 1000, capa 1003, handle 1005, punto 1010, real 1040, distancia 1041, escala 1042, entero 1070/1071). `set_xdata` registra la aplicación si no existe.
- **`get_custom_data` / `set_custom_data` / `delete_custom_data`** — registros propios (`Xrecord` en el diccionario de extensión de la entidad o en el NOD): texto, punto, real, enteros, booleano.
- **`get_block_attributes` / `set_block_attributes`** — atributos de una referencia de bloque por etiqueta.
- **`list_annotation_scales` / `add_annotation_scale` / `set_current_annotation_scale` / `remove_annotation_scale`** — la lista de escalas de anotación del dibujo (`ACDB_ANNOTATIONSCALES`).
- **`list_plot_options(layout)` / `configure_layout(...)`** — dispositivo, papel, tabla de estilos de trazado, unidades, rotación, centrado, área (extensión, límites, ventana) y escala, con el **PlotSettingsValidator** nativo: dispositivo y papel se validan contra la lista real del dispositivo. No imprime; para eso está `export_pdf`.
- **`get_dynamic_block_properties` / `set_dynamic_block_properties`** — bloques dinámicos: estados de visibilidad, medidas de lista, etc., con los valores permitidos que informa AutoCAD.
- **`create_database_object` / `delete_database_object`** ahora aceptan `kind` = `tablestyle` | `mleaderstyle` (se crean con `PostTableStyleToDatabase` / `PostMLeaderStyleToDb`).

**Plugin 1.18.0 (verificado en vivo en 2022 y 2027)** — capas, láminas y copias. Salió de leer `AcLayerTools`, `AcExportLayoutEx` y `acdbmgd` descompilados (ahí aparecieron `LayerStateManager`, `Viewport.FreezeLayersInViewport` y `Database.DxfOut`, que no se conocían):

- **`merge_layers(sources, target)`** (LAYMRG) — pasa TODO lo de las capas de origen —modelo, láminas y definiciones de bloque— a la de destino y borra las de origen; la prueba de «en uso» es `Database.Purge`. **`delete_layer_with_objects(name, confirm)`** (LAYDEL) — destructivo: sin `confirm=true` solo cuenta lo que borraría, por tipo.
- **`save_layer_state` / `restore_layer_state` / `list_layer_states` / `delete_layer_state`** — el administrador NATIVO de estados de capa (`Database.LayerStateManager`): quedan en el dibujo y se ven en el cuadro de AutoCAD. **`isolate_layers` / `unisolate_layers`** (LAYISO/LAYUNISO) guardan el estado previo en `_MCP_ISOLATE`; no se anidan. Sin probar: la política `turn_off_others` (1 = apagar las no mencionadas) sale de leer la firma, no de documentación.
- **`set_viewport_layers(handle, freeze, thaw, thaw_all, freeze_all_except)`** (VPLAYER) — congelar capas SOLO en un viewport: es lo que permite una lámina por disciplina desde un único modelo.
- **`copy_layout` / `rename_layout`** — `LayoutManager.CopyLayout/RenameLayout`; copiar conserva viewports e impresión.
- **`export_copy(path, version, precision, overwrite)`** — copia en DWG de una versión anterior (2013, 2010, 2007, 2004, 2000) o DXF, sin tocar el dibujo abierto; en DWG relee la copia y compara entidades y láminas (`verify.match`). Dato que salió de comparar `DwgVersion` en las nueve versiones: **de AutoCAD 2018 a 2027 el formato de archivo es el mismo (AC1032)**; bajar la versión solo hace falta para quien tenga una 2017 o anterior.

Más de 1.18.0, también verificado en vivo:

- **Xrefs**: `bind_xref(name|names, insert)` (BIND/XBIND: deja el DWG autocontenido; `insert=True` mezcla capas y estilos sin prefijo, `False` los deja con `xref$0$`) y `unload_xref`. Se rechaza un xref no resuelto.
- **Propiedades del dibujo**: `get_drawing_properties` / `set_drawing_properties` (título, asunto, autor, palabras clave, comentarios, base de hipervínculos y propiedades personalizadas; `custom={"k": null}` borra). Es lo que el Explorador de Windows muestra del DWG.
- **Edición por API** (`EditExtraCommands.cs`, cada una en una transacción y validada entera): `explode_entities` (EXPLODE; no descompone xrefs), `break_curve` (parte una curva en puntos), `divide_curve` (DIVIDE/MEASURE, con puntos o con un bloque girado según la curva), `create_boundary` (BOUNDARY, usa `Editor.TraceBoundary`: lo que está A LA VISTA, hacer `zoom_window` antes) y `match_properties` (`SetPropertiesFrom` o propiedades sueltas).
- **Primitivas** (`primitivas.py`, sin plugin nuevo; sobre `create_polyline` y `create_object`): `create_rectangle` (con esquinas redondeadas), `create_polygon` (inscrito o circunscrito), `create_ellipse` (`Ellipse.Set`), `create_construction_line` (Xline/Ray) y `create_point`. `create_ellipse` tiene comando propio (`CreateEllipseCommand.cs`): una `Ellipse` o `Spline` construida vacía es NULA (`IsNull`, visto en el descompilado) y agregarla al dibujo cierra AutoCAD con una violación de acceso, por eso `create_object` ya no las admite.

- **Sólidos desde perfiles ya dibujados** (`Solid3dOpsCommands.cs`): `extrude_solid` (EXTRUDE por altura o vector, con ahusado; es como pasar una planta 2D a volumen), `revolve_solid` (REVOLVE sobre un eje), `sweep_solid` (SWEEP a lo largo de una trayectoria) y `loft_solid` (LOFT entre 2 o más secciones, con guías o trayectoria). El perfil tiene que estar CERRADO; el sólido toma la capa del perfil. Complementan a `extrude_profile` (que dibuja el contorno desde puntos) y a las primitivas de `create_object`.

**Revisión independiente del código nuevo (1.17.0/1.18.0).** Un revisor leyó los archivos contra el descompilado y encontró defectos que se corrigieron antes de probar: `modify_group` usaba `Group.GetIndex` (lanza si la entidad no está: `add` casi nunca andaba); objetos en CAPA BLOQUEADA no se podían abrir para escribir (ahora `GetObject(..., forceOpenOnLockedLayer: true)`); `purge_database_objects` sin lista ya NO purga vistas ni UCS (PURGE tampoco) y salta símbolos de xref; `merge_layers` restaura la capa actual si falla y también mueve los `AttributeReference`; `isolate_layers` deja VISIBLES las capas aisladas aunque estuvieran apagadas; `set_viewport_layers(freeze_all_except)` descongela las que se mantienen; `save_layer_state(replace)` ya no pierde el estado viejo si falla; `set_block_attributes` rechaza etiquetas repetidas y llama `AdjustAlignment`/`UpdateMTextAttribute`; los enteros de un Xrecord se validan en rango; `export_copy` borra la copia si no se puede releer y avisa que WBLOCK * puede omitir lo que no se usa. Sigue en DUDA (solo la prueba en vivo lo dice): si `RestoreLayerState` recrea capas borradas, y si AutoCAD rechaza borrar una escala de anotación en uso.

**Plugin 1.19.0 (verificado en vivo en 2022 y 2027: 155/155)** — se sacaron de la lista de pendientes de la cinta (`COBERTURA_CINTA.md`): `chamfer_entities` (CHAMFER por el motor nativo, como el empalme; restaura CHAMFERA/B/MODE), `stretch_entities` (STRETCH con ventana: mueve vértices de líneas y polilíneas y lo que cuelga), `lengthen_curve` (LENGTHEN: delta, total o porcentaje), `align_entities` (ALIGN con uno o dos pares de puntos, con escala opcional), `create_wipeout` (máscara; se le da forma con `SetFrom` ANTES de agregarla, dato que salió de `tools/precondiciones.py`) y `attach_pdf_underlay` (calco PDF: `PdfDefinition` en `ACAD_PDFDEFINITIONS` + `PdfReference`; hay que calibrar la escala con una cota conocida).

**Plugin 1.20.0 (verificado en vivo en 2022 y 2027: 174/174) — superficies y mallas.** `create_surface(kind=plane|extrude|revolve|sweep|loft)` (PLANESURF, y EXTRUDE/REVOLVE/SWEEP/LOFT con perfil ABIERTO; `loft ruled=True` es RULESURF, `revolve` es REVSURF, `extrude` es TABSURF), `offset_surface` (SURFOFFSET), `create_nurb_surface` (cuadrícula de puntos de control: terreno, cubiertas curvas), `create_mesh_from_faces` (vértices y caras: un TIN), `create_mesh` (MESH: caja, esfera, cilindro, cono, pirámide, toro, cuña), `mesh_smooth` (MESHSMOOTHMORE/LESS, MESHREFINE) y `convert_mesh` (CONVTOSOLID/CONVTOSURFACE). Las clases de superficie se crean vacías y un método `Create*` de instancia les da forma ANTES de agregarlas (dato de `tools/precondiciones.py`); `create_mesh` y `mesh_smooth` van sobre `create_object`/`call_object_method`. Lo que sigue pendiente de esa familia pide elegir CARAS o ARISTAS (`FullSubentityPath`): MESHEXTRUDE, MESHSPLIT, MESHMERGE, MESHCREASE por arista, SURFTRIM, SURFBLEND, SURFFILLET, SURFEXTEND.

`python mcp_server/verificar_lote_1_17.py` (cubre 1.17.0 a 1.20.0) es la comprobación en vivo: dibujo nuevo descartable, una línea por verificación, sale con 1 si algo falla.

**La API que usa este proyecto es estable de 2019 a 2027.** `tools/api_diff.py` compara miembro por miembro los ensamblados de referencia de las nueve versiones (informe en `Desktop\Autodesk_descompilado\notas\J_api_por_version.md`): los 66 miembros que el plugin llama por nombre existen en todas; lo que cambia entre versiones son clases de interfaz (bloques, paletas, nube) y, en `Application`, la desaparición de `IsSteelInstalled` en 2021. Los saltos grandes de métodos 2024→2025 y 2026→2027 son un efecto del descompilado de los paquetes ModPlus (net8), no cambios reales.

## 3.sexies-sexies Los ojos: `diagnose_autocad` y por qué ya no hay que adivinar qué pasó

Antes, ante un timeout o un AutoCAD cerrado, lo único que había era «no se pudo conectar» y quien llamaba gastaba turnos averiguando (¿diálogo abierto? ¿se cayó? ¿qué comando fue?). Pasó en vivo con `list_plot_options`: AutoCAD mostró «INTERNAL ERROR: !dbobji.cpp@8673: eNotOpenForWrite» y se cerró; la causa era `PlotSettingsValidator.RefreshLists` sobre un layout abierto en LECTURA (modifica el objeto; en lectura no es una excepción sino una aserción fatal). Ahora la herramienta lo ve sola (`ojos.py`, `Bitacora.cs`):

- **Desde afuera de AutoCAD** (así anda aun con AutoCAD bloqueado por un diálogo modal): las ventanas abiertas con su texto, `acad.err` (en el directorio de trabajo de `acad.exe`), volcados `.dmp` y `dialogos.log`.
- **Desde adentro** (plugin 1.18.0): `Bitacora` deja en `%LOCALAPPDATA%\AutoCadMcp\ultimo_comando.json` el comando que está ejecutando («corriendo» → «ok»/«error»). Si AutoCAD muere, el que quedó «corriendo» es el culpable, aunque otro proceso lo haya mandado. No guarda el código de `run_code`.
- **Del lado del servidor**: los últimos 40 comandos enviados con su resultado.
- Las fallas de conexión y los cortes (`AutoCadConnectionError`, «se cortó la conexión», «cerró sin responder») traen pegado un `DIAGNÓSTICO:` con la conclusión en una frase («AutoCAD MURIÓ ejecutando «list_plot_options» … Error de AutoCAD: «eNotOpenForWrite»»). `diagnose_autocad()` lo da a pedido, y es lo PRIMERO que se llama ante un cuelgue, antes de repetir nada.

**Regla antes de escribir una herramienta nueva sobre la API: `python tools/precondiciones.py <Clase> ...`.** Lee el descompilado y marca, por clase: si NACE NULA (`IsNull`: Ellipse, Spline, Region, Body, Solid3d), si tiene constructor vacío y otros con datos (usar el de datos), si no tiene constructor público (se obtiene de la base de datos), qué métodos MODIFICAN, y cuáles modifican un ARGUMENTO que es objeto de la base de datos (ese argumento tiene que estar abierto para ESCRITURA o ser una copia suelta; en lectura es una aserción fatal que cierra AutoCAD, no una excepción: así cayó `RefreshLists`). `--catalogo` barre todo (`Desktop\Autodesk_descompilado
otas\K_precondiciones.md`). Es una heurística de dónde mirar, no un veredicto: el descompilado es un envoltorio sobre código nativo y no dice qué exige cada método por dentro; lo que marca como sospechoso se prueba en un dibujo descartable y lo comprobado queda anotado en `CONOCIDO` (Ellipse cierra AutoCAD; Solid3d, Region y Body vacíos se pueden agregar). `test_precondiciones.py` lo cubre sin AutoCAD.

Lo que NO ve todavía: la salida de la línea de comandos de AutoCAD (no hay evento administrado que la entregue; Autodesk la captura con código nativo). Solo lee: no cierra diálogos ni mata procesos.

## 3.septies Verificar una versión de AutoCAD en vivo: `mcp_server/verificar_version.py`

Corre 31 comprobaciones sobre el AutoCAD abierto (consulta y agregados, variables de sistema, propiedades y métodos 2D, las cinco operaciones nativas con su `undo` verificado, y 3D: volumen real de sólidos, matriz, desfase, booleanas, corte, regiones y malla). Trabaja en un dibujo NUEVO descartable y lo cierra: **no usarlo con un plano en curso.** Resultado (plugin 1.13.2): **31/31 en AutoCAD 2022 y 31/31 en AutoCAD 2027.** Para otra versión (2019-2021, 2023-2026): abrirla con el bundle instalado (`tools/install_bundle.ps1`) y correr el script; es lo que falta para poder decir «probado» y no solo «compila» (`tools/matriz_api.py`).

Dos cosas que descubrió esto: (1) con el AutoCAD recién arrancado las operaciones nativas (`trim_entity`, `join_entities`...) pueden tardar minutos en ejecutarse —en la 2027 tardó 139 s— porque corren por la cola de comandos y AutoCAD todavía está cargando: esperar a que termine de arrancar antes de editar, y si pasa de `wait_s` no repetir (`native_status`); (2) `run_code` rechaza un dibujo sin guardar salvo `force=True`.

## 4. Muros: una planta entera es `create_wall_network`

Un muro NO es una línea. Los muros de una planta van en **UNA** llamada a
`create_wall_network`, con el eje y el espesor de cada uno: remata cada
encuentro como un dibujante (L con la esquina exterior cerrada, T que termina
contra la CARA del muro que la recibe, cruces limpios, cualquier ángulo) y
recorta los huecos de puertas y ventanas. Sale en polilíneas cerradas,
editables, con el área de mampostería ya calculada.

Varias `create_walls` sueltas NO sirven para una planta: cada una termina su
muro en el eje sin saber de los otros, y en cada encuentro **las líneas se
cruzan y sobran puntas**. `union_regions` borra las puntas pero deja la
esquina exterior de cada L mordida (medio espesor por medio espesor que nadie
cubre). Se vio en planos reales y era lo primero que delataba el dibujo.
`create_walls` queda para un muro aislado (una barda, un pretil).

Un muro que llega a otro termina en el **eje** del otro, no en su cara: el
remate lo hace la tool. Si un extremo quedó a centímetros del muro al que
iba, `snap` lo ajusta y lo informa en `snapped` — revisalo. Un hueco que
cae justo donde llega otro muro sale en `warnings`: es un error de proyecto.

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

**Y al revés: `traverse`.** Del cuadro impreso de un plano ajeno a las
coordenadas — rumbo + distancia por lado, recorridos en orden. Es el inverso
exacto de `create_construction_table`, y con los dos se cierra el ciclo: se
lee el cuadro de un plano de otro estudio, se reconstruyen los vértices y se
vuelve a dibujar el terreno, sin resolver trigonometría a mano.

Lee el rumbo como sale impreso (`N 45°30'20" W`, con símbolos o sin ellos, y
**E/O** además de E/W: en castellano el oeste se escribe O, y ese detalle
rompía la lectura de planos mexicanos). Acepta `azimuth` en grados decimales
como alternativa.

Lo que de verdad devuelve es el **error de cierre**: cuánto le falta al último
lado para volver al arranque. Un cuadro bien copiado cierra con centímetros
(la tolerancia es 1/5000 del perímetro); si no cierra, el dato está mal leído
y dibujarlo sería propagar el error. Pasó en la primera prueba: cuatro rumbos
tipeados de una imagen borrosa daban 4.29 m de error — 125 veces la
tolerancia — y la tool lo dijo en vez de dibujar un terreno inventado.

Ojo con la precisión del formato: un cuadro se escribe en segundos enteros,
así que la ida y vuelta vértices→rumbos→vértices tiene hasta medio segundo de
redondeo. Sobre un lado de 60 m son 0.15 mm; despreciable, pero no es cero.

## 4.ter Ejes de obra civil: SIEMPRE con `bulges`

Un eje con curva sale de `create_alignment`, que devuelve `points` **y**
`bulges`. Todo lo que después se ubique por cadenamiento —`create_road`,
`point_on_road`, `create_stationing`— necesita los dos. Sin los bulges la
distancia se mide sobre la cuerda y no sobre el arco: los pozos, las marcas y
todo lo que caiga después del principio de curva queda corrido, y el error no
se ve en pantalla, aparece en el replanteo.

## 4.bis Ejes: qué planos los llevan, y separación mínima 1.20 m

**Llevan ejes:** la planta arquitectónica (se acota "a ejes"), la planta de
cimentación y las estructurales (losas, trabes), con LOS MISMOS ejes en todas
—un formato municipal real (Juárez, N.L.) exige que los ejes estructurales
coincidan con los del arquitectónico, y en la práctica los arquitectónicos
rigen sobre los estructurales—. Cortes y fachadas pueden referenciarlos
(opcional). **No llevan ejes** las plantas de instalaciones: van sobre la
base arquitectónica limpia para que se lean los símbolos. Se preguntó si
"solo la cimentación lleva ejes": no, el arquitectónico también.


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

## 4.septies Detalles constructivos: se COMPONEN con materiales, piedras, tierra y varillas

Un detalle constructivo (cimentación, muro de contención, corte de
banqueta, pila, registro) no se dibuja con rectángulos y un patrón
adivinado. Se compone con cuatro primitivas que saben de oficio, no de
proyecto — y por eso sirven para cualquier detalle, incluido el que todavía
no tiene tool propia:

- **`create_material_section`** — un polígono CUALQUIERA (trapecio con
  talud, losa con pendiente) + un material del catálogo (`concreto`,
  `concreto_pobre`, `block`, `tabique`, `tierra`, `relleno`, `grava`,
  `arena`, `acero`, `piedra_bola`, `mamposteria`, `ciclopeo`...). Pone el
  contorno al grosor que le toca y la textura a una escala **calibrada con
  la lámina**. Eso último es la clave: los patrones de `acad.pat` están en
  pulgadas nominales, y ANSI31 a `scale=1` dibujando en metros raya cada
  12.5 cm — en una plantilla de 10 cm no entra ni una línea y el corte sale
  "sin textura". El módulo se pide EN PAPEL (1.2–3 mm) y la tool hace la
  cuenta. `create_hatch` acepta lo mismo con `paper_mm` / `real_size`.
  **Y hay dos archivos de patrones con los mismos nombres**: `acad.pat`
  (pulgadas) y `acadiso.pat` (milímetros, 25.4 veces más grande a la misma
  escala). Cuál usa el dibujo lo decide su plantilla; `materials.py` lo
  detecta por las unidades de `get_drawing_info` y se cachea por dibujo. Se
  descubrió en AutoCAD real: con la escala "de pulgadas" en un dibujo
  métrico, AR-CONC salía como relleno sólido y EARTH como tres rayas
  sueltas, y `get_entity` decía que todo estaba bien.
  Si el patrón no carga cae al de respaldo y lo dice en `warnings`; **nunca
  devuelve `None` en silencio** — así se perdió el achurado de un corte
  entero sin que nadie se enterara.
- **`create_stone_fill`** — piedras irregulares que caen y se apoyan unas
  en otras dentro de cualquier contorno, con junta de mortero. AutoCAD no
  trae textura de piedra suelta, y unos círculos tirados en una caja se leen
  como círculos: pasó, y era la diferencia entre el dibujo del MCP y el de
  referencia. `redonda` (canto rodado) o `angulosa` (piedra braza).
- **`create_soil_section`** — la masa de terreno alrededor de lo enterrado,
  con las piezas como islas, la línea de terreno natural cortada donde algo
  SALE del suelo (el muro) y **sin caja exterior**: el contorno auxiliar se
  borra después de achurar. Una caja cerrada alrededor se lee como otra
  pieza de concreto, que es exactamente lo que pasaba.
- **`create_rebar`** — UNA varilla por su trayectoria, con dobleces a radio
  (6db, 4db en estribos) y ganchos normalizados (90°: 12db, 135°: 6db,
  180°: 4db, ACI 318 25.3). Devuelve la longitud DESARROLLADA real para
  cuantificar. `closed=True` es un estribo con sus dos ganchos a 135°.
  `create_rebar_dots` para las barras vistas de punta. Una varilla no es
  una línea: la transversal de una zapata se dobla en las puntas, el
  arranque se ancla en L, y eso se ve en el corte.

`create_footing_section` es la composición de ejemplo: zapata con talud +
dado + cadena + muro, piedra bola o concreto armado, con tierra, acero,
rótulos con especificación (`specs`) y título con globo. Lo que no entre
ahí se arma con las cuatro primitivas directamente — **no** con
`create_polyline` + `create_hatch` a mano.

Un corte de cimentación es TRANSVERSAL: las barras que cruzan el muro se
ven como líneas con gancho, las que corren a lo largo se ven de punta. Al
revés no es un corte.

**Mirar de cerca es parte del trabajo.** Los `check_*` no ven que las
piedras no llenan la zanja ni que la textura no cayó. `capture_viewport`
acotado al detalle, y sin AutoCAD `python mcp_server/preview_footing.py`
renderiza los dos cortes con sus achurados (el preview ahora los dibuja).

## 4.octies Zapatas: `design_footing` → `draw_footing_detail`

Una zapata no se dimensiona "a ojo" ni se dibuja con `create_footing_section`
(esa queda para cimientos de muro sencillos). El capítulo de zapatas
(`zapatas.py`, `zapatas_dibujo.py`, `zapatas_combinada.py`,
`zapatas_cuadros.py`) tiene seis tipos: aislada, aislada con dado, lindero,
esquina, corrida bajo muro (con dala por NTC Mampostería) y combinada.

- **`design_footing`** diseña por ACI 318-19 y devuelve cada revisión con su
  número y su artículo. Sin capacidad del E.M.S., f'c, desplante o peso del
  relleno RECHAZA: no se suponen. Lindero/esquina devuelven el momento que
  tiene que tomar la contratrabe de liga. Los volados salen en cm redondos
  para que la cadena de cotas sume igual que la total.
- **`draw_footing_detail`** dibuja corte, planta y cuadros (zapatas,
  revisión estructural, especificaciones, cuantificación) y devuelve la caja
  de cada vista para `compose_layout`.
- Primitivas de grafismo que sirven para cualquier detalle (`detalle.py`):
  `create_callouts` (llamadas en columna que nunca se cruzan),
  `create_break_line`, `create_construction_joint`.

**Lotes.** Dentro de `with autocad_client.lote():` los comandos de dibujo
viajan juntos (comando `batch`, plugin 1.8.7+): un detalle de 200 entidades
pasa de ~2 min a ~10 s. Es lo que permite probar en AutoCAD y corregir sobre
la marcha.

**Texto siempre con grosor 0.** El cliente lo fuerza en todo `create_text`:
con pluma y LWDISPLAY encendido AutoCAD traza el contorno de cada letra
TrueType y, chica en pantalla, sale hueca ("ESC. 1:20" se leía "CJO, 7:00").

**A0 apaisado:** DWG To PDF trae el A0 solo vertical; `compose_layout(...,
paper_size="A0", orientation="horizontal")` rota el plot 90° (plugin 1.8.9).

## 4.nonies 3D para mostrar: `create_3d_model` → `dress_3d_model` → `set_3d_view`

`create_3d_model` levanta muros, vanos y losas en gris: sirve para revisar
volúmenes, no para mostrarle la casa a nadie. `dress_3d_model` le pone
encima, con los MISMOS rooms/doors/windows de cada nivel: ladrillo aparente
en fachada (textura real a escala, generada en Python porque run_code no
escribe archivos), aplanado y plafón blancos, piso cerámico, vidrio con marco
en ventanas, puertas de madera, muebles por piezas (con `furniture` = los
items de `suggest_furniture`), pasto, banqueta y árboles. Los vanos ABIERTOS
(la cochera) quedan libres: el forro los tapaba.

`set_3d_view(camera, target, lens)` pone la cámara en perspectiva: interior
con el ojo a 1.60 m y lente 18-24; exterior lente 30-50; `roof_visible=False`
para el corte sin techo. Aísla el 3D (los planos 2D flotaban en el cielo) y
`isolate_3d=False` vuelve a prender todo: hacelo antes de guardar. Un zoom de
planta (plugin 1.9.2+) vuelve solo a la vista 2D.

Lo que no se ve en el interior es por la luz: la de AutoCAD viene de arriba y
el techo salía negro; el plafón tiene autoiluminación por eso.

Detalle que separa una maqueta de un 3D profesional, ya resuelto en la tool:
piso por USO (duela en recámaras, loseta en baño/cocina, concreto pulido en
cochera, porcelanato lo demás; `floors` por nivel manda), azulejo en baños a
2.10, cancelería negra, baño con cancel de vidrio, mueble de lavabo y espejo,
cocina con alacena, campana y lambrín. Opcionales: `cladding` (lambrín de
madera en fachada), `canopies` (marquesina), `hedges` (setos).

**Barandal de escalera: continuo y cerrado.** Lo marcó el usuario mirando el
3D: los postes de altura fija contra un pasamanos inclinado quedaban unos
cortos y otros pasados, sin barrotes se veía a medias, y en el descanso y al
llegar arriba el tubo se cortaba. Ahora el pasamanos va a 0.90 sobre la línea
de narices, los barrotes (claro ≤ 10 cm) nacen en su escalón y mueren EN el
pasamanos, cada rampa se une con la siguiente por el descanso, el barandal
de planta alta se pega al final del pasamanos y cada quiebre lleva su codo.
**Mirarlo de cerca** (cámara a 1 m de la unión): de lejos todo se ve unido.
Los árboles achican la copa para no atravesar la fachada.

## 4.decies Estructura de la casa: bajada de cargas → trabe → losa → plantas; dinteles y arcos

La cadena de cálculo de una estructura de marcos de concreto vive en
`estructura.py` y SE USA EN ESTE ORDEN, cada paso con la salida del anterior:

1. **`design_two_way_slab`** — espesor y armado de cada tablero (Rankine-
   Grashof por franjas, ACI 318-19 8.3.1.2 / 8.6.1.1 / 8.7.2.2). Si `h` no
   cumple el mínimo lo dice: subir `h`, no apretar el acero.
2. **`panel_edge_loads`** — reparte el tablero (kg/m²) a sus cuatro trabes
   por líneas a 45° (triángulo al corto, trapecio al largo): kg/m por trabe.
3. **`continuous_beam`** — la trabe continua sobre columnas por rigideces:
   momentos en apoyos y claros, cortantes, reacciones (que bajan a
   `design_footing`).
4. **`design_beam`** — la sección b×h por ACI 318-19 (flexión, mínimos,
   estribos con la exención de 9.6.3.1 cuando Vu ≤ φVc/2, peralte mínimo
   9.3.1.1). Con `ValueError` si la sección no da: se crece, no se fuerza.
5. **`draw_foundation_plan`** / **`draw_framing_plan`** — las plantas de
   cimentación y de trabes/losas desde esos diseños, sin escribir una medida
   a mano. Detalles: `create_column_section` (misma sección rectangular),
   `create_rebar_elevation`.

**Dinteles (`design_lintel`)**: el cerramiento sobre puertas y ventanas toma
el triángulo de descarga a 60° del muro si hay altura para él (efecto arco de
la mampostería, marcado como PRÁCTICA) o el muro completo si no, más losa o
trabe que llegue (`extra_load_kg_m`), y se diseña con `design_beam`. El
apoyo (`bearing`) es dato del proyecto: la norma local fija el mínimo.

**Arcos (`arcos.py`)**: `arch_geometry` traza medio punto, rebajado
(escarzano), apuntado (ojival) y carpanel (tres centros) por luz y flecha
—centros, radios, intradós/extradós con bulges, dovelas con clave centrada—
y `create_arch` lo dibuja Y LO ANOTA solo (cotas de luz y flecha, tipo, L/f/e
y, con `load_kg_m`, el empuje H y el veredicto): el detalle sale de la tool,
no de quien la llama. `check_masonry_arch` es análisis límite (Heyman): peso
propio que SIGUE el arco + sobrecarga, línea de presiones M(x)/H con las
rótulas libres dentro de la junta de arranque, y se busca el empuje que la
deja lo más cerca del eje; la excentricidad se mide SOBRE LA JUNTA (radial),
no en vertical. Tercio central (e ≤ t/6, junta toda comprimida), estabilidad
(e ≤ t/2) y esfuerzo contra f'm/3 solo si se da f'm. Reproduce el límite de
Heyman para el medio punto (t/R ≈ 0.11-0.13; es algo conservador) y es
PRELIMINAR: no es el análisis de una bóveda. Dos errores que ya pasaron:
comparar con la parábola de carga uniforme condenaba cualquier medio punto, y
tomar "el arco más alto" en la clave de un apuntado daba e = 141 cm.

**Dintel dibujado (`draw_lintel_detail`)**: desde el dict de `design_lintel`
arma elevación con estribos, apoyos achurados, cotas, corte armado y rótulos,
y devuelve su caja para ir a 1:10 en su propio viewport de `compose_layout`.

**El juego completo en dos llamadas (`conjunto_estructural.py`)**:
`design_frame_structure` (ejes, cargas, f'c, suelo → losa iterada, bajada,
trabes continuas, UNA sección de trabe, zapata, contratrabes, con `decisions`
que dicen qué eligió y por qué) y `draw_structural_set` (las dos plantas sin
pisarse + `compose_layout` de la lámina con rótulo). Existe para que un
modelo chico produzca la misma lámina que uno grande encadenando tools.
`compose_layout` registra la lámina como layout, así `check_sheet` no la
compara contra el cajón de un `create_sheet` viejo o persistido.

**`design_pool`** (`alberca.py`): volumen, recirculación, succión, drenes y
muro contra suelo y agua. Sin f'c (y sin peso del suelo si está enterrada)
rechaza.

## 4.undecies Pórtico de acceso con arco y barda: `portico_arco` → `portico_dibujo` → `portico_cuadros`

Un pórtico con arco (pilastras con frontón, cornisa de teja, portón de herrería) y su barda se
calcula y se dibuja en módulos propios, sin escribir un script por plano:

- **`portico_arco.py`** — `design_gate_portal` (marco plano por rigideces con base empotrada y
  articulada, frontón como carga, hoja del portón como par de fuerzas en las bisagras, viento y
  sismo fuera del plano, pilastra por interacción P-M, zapata RECTANGULAR de menor volumen con
  contacto real sin tensión; prueba con y sin trabe de liga y elige la que ahorra más de 5 %) y
  `design_fence` (pilastra de barda y cimiento corrido con momento). Rechaza sin capacidad del
  suelo, f'c, desplante o peso del relleno. Lo que no es dato del proyecto (viento, sismo, peso
  de la hoja, peso del frontón) va en `supuestos` y en el plano.
- **La forma sale de la FOTO del cliente**, no de la imaginación: `PERFIL_FOTO` y `FOTO`
  (`portico_dibujo.py`) guardan las medidas calcadas de la referencia con el claro de 5.00 m como
  escala. Cambiar el diseño estructural no toca esa forma. Para verificar, superponer el dibujo
  (capturado con `capture_viewport` a la misma ventana) sobre la foto.
- **`portico_dibujo.py` / `portico_detalles*.py`** — alzado, planta, estructura, armado de la
  trabe curva desarrollada, pilastras, cimentación. **`portico_3d.py`** — el modelo con
  `extrude_profile(plane="xz")` (alzado extruido a lo largo de Y; requiere plugin recompilado).
- **`portico_cuadros.py`** — cantidades NETAS (sin merma) y materiales: cemento, arena, grava y
  agua por mezcla. Dosificación de referencia por ACI 211.1 con f'cr de ACI 318-19 (f'c 250 →
  410 kg de cemento por m³) y mortero 1:4 por volumen absoluto; el diseño de mezcla del
  proveedor manda. Arena y grava en volumen suelto.
- La captura 3D (`capture_viewport` no sirve para perspectiva): traer AutoCAD al frente y tomar la
  pantalla; `set_3d_view(isolate_3d=False)` antes de guardar.

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

Los encuentros de muros los resuelve `create_wall_network` (y `draw_layout`,
que la usa): no hace falta `union_regions` después, y no conviene — su
resultado es una Region que ya no admite editar vértices, y deja mordida la
esquina exterior de cada L. `union_regions` queda para contornos que no son
muros.

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

## 6.quater-bis Instalaciones de la vivienda: `suggest_electrical` / `suggest_hydraulic` / `suggest_sanitary`

Van DESPUÉS de `draw_layout` + `suggest_furniture` y toman de ahí recintos,
puertas y muebles. Cada criterio sale de `instalaciones.NORMA` con su fuente
(NOM-001-SEDE-2012, NTC CDMX, INIFED); lo que es práctica y no norma está
marcado así. Las redes son árboles ortogonales: cada tramo sabe qué muebles
alimenta o drena, y eso define su diámetro.

- **Eléctrica**: circuitos por RECINTO COMPLETO, canalización por el árbol
  más corto dentro de cada circuito y flecha de llegada al tablero con su
  número. Encadenar todo desde el tablero dibujaba arcos de 15 m cruzando la
  casa. Lo del patio va sobre la FACHADA de la casa: "atrás" en 210-52(e) es
  atrás de la vivienda, no la barda del fondo.
- **Todas dibujan su SIMBOLOGÍA con NOTAS** a la derecha de la planta
  (`legend=False` para no hacerlo, `create_installation_legend` para ponerla
  en otro lado). Sin ella el plano solo lo lee quien lo dibujó. Los símbolos
  salen de las mismas funciones que la planta, y las notas solo dicen lo que
  respalda una norma. El material, la marca y las alturas de montaje van en
  `notes` cuando el proyecto los defina; no se inventan.

**Un plano, UNA pestaña.** Corregir es borrar las capas de instalaciones y
redibujarlas en el mismo dibujo, no abrir un `Drawing` nuevo por corrida.
Pasó: quedaron cuatro pestañas abiertas en AutoCAD, una de ellas en solo
lectura con una corrida dibujada encima de otra. `test_live_instalaciones.py`
trabaja así: reusa la pestaña del plano, y si la base ya está, no la rehace.

## 6.sexies Piezas 3D sueltas: `create_phone_3d` y los comandos de sólidos

Un objeto 3D (teléfono, carcasa, pieza) se modela con tools, **no con
`run_code`** (apagado por defecto): `extrude_profile` (contorno cerrado de
líneas y arcos con `bulges` -> sólido, el equivalente a líneas+arcos unidos con
JOIN), `solid_boolean` (`subtract` / `union` / `intersect`) y
`fillet_solid_edges` (canto redondeado real, aristas elegidas por geometría).

**`create_phone_3d`** (módulo `phone3d.py`) arma un teléfono completo a partir
de DIMENSIONES: caja (`width`, `height`, `thickness`), `corner_radius`,
`edge_radius`, `screen` (marco, espesor del vidrio, isla), `plateau` de
cámara, `lenses` y `buttons`. Ningún modelo viene cableado: las medidas las
trae el pedido, y si falta una (radio de esquina, tamaño de lente...) se
pregunta o se informa que es una estimación — nunca se inventa en silencio.
Cada pieza es un sólido aparte en su capa `3D-TEL-*` y su color; `finish`
(`grafito`/`plata`/`dorado`/`azul`) trae la paleta y `colors={"body": 150}`
pisa piezas sueltas. Todo se valida antes de dibujar (lente fuera del plateau,
marco que se come la pantalla, fillet mayor que medio espesor) y, si algo
falla a mitad, borra lo creado. Para mirarlo: `set_3d_view`.

Estos comandos viven en el plugin (`SolidCommands.cs`): recompilar y reiniciar
AutoCAD, y guardar el DWG con nombre ANTES de reiniciar
(`tools/install_bundle.ps1 -CloseAutoCad -Reopen`).

## 6.septies Estacionamientos y fachadas con ornamento

Dos familias de primitivas paramétricas, para láminas que se repiten con otras
medidas (nada de un edificio concreto vive en el código):

- **Estacionamientos** (`parking.py`): `create_parking_stalls` (una fila de
  cajones con número en círculo y coche en planta, cada línea UNA vez, numeración
  con `start_number`/`number_step`), `create_car_symbol`, `create_ramp_track`
  (rampa en anillo entre dos contornos redondeados, con líneas radiales) y
  `create_ramp_arc` (tramo curvo). `create_axis_grid(y_top_down=True)` pone la A
  ARRIBA, como en muchos planos.
- **Fachadas** (`facade.py`): `create_crenellation`, `create_arched_opening`
  (vano con arco, marcos y divisiones), `create_lattice_panel` (celosía de
  rombos recortada al panel), `create_facade_column`, `create_balustrade`,
  `create_steps`. Una fachada se compone llamándolas con sus medidas.

**`vectorize_image`** (`vectorize.py`) CALCA una captura de un plano de líneas
finas sobre fondo oscuro a polilíneas reales, por color y a su capa `TRAZO-*`.
Es lo único que reproduce un dibujo ajeno con fidelidad visual (~1 px), pero es
un calco: no paramétrico, con ruido de JPEG en las texturas, y la escala hay que
calibrarla con una cota conocida de la imagen. Hay que decírselo al usuario.
Dependencias opcionales: numpy, opencv-python-headless, scikit-image.

Lo que NO hacen las primitivas paramétricas: leer medidas de una captura. Las dimensiones salen del proyecto
o de cotas que alguien lea; una réplica de un plano ajeno es una aproximación
de su estructura, no una copia.

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
calcular nada — como el **cuadro de volúmenes** de un plano: No. |
CONCEPTO | UNIDAD | CANTIDAD, bandas de partida, cantidades a la derecha
con dos decimales (piezas y bolsas enteras), encabezado sombreado, marco
grueso y totales por material al pie. **Ponele `group` a cada item**
("Preliminares", "Cimentación", "Estructura", "Albañilería", "Acabados"):
así salen numerados 1.1, 1.2... bajo su partida, que es como se presenta
un presupuesto. Los conceptos largos se parten en dos líneas solos; el
tamaño sale de la escala de la lámina (2 mm de papel), no de un número
fijo en metros — la versión anterior era una lista de dos columnas de 22 m
de ancho con la fórmula en texto corrido, y eso no es un cuadro. La
operación completa (área medida, módulo, kg/m) sigue disponible con
`show_calc=True` para revisar, y siempre en `export_quantities_csv`.
`python mcp_server/preview_quantities.py` lo renderiza sin AutoCAD.

`create_table` genérica tiene lo mismo: `align` por columna, `wrap`,
`group_rows`, `total_rows`, `header_fill`, y con `text_height=0` toma 2 mm
de papel a la escala registrada.

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

**Y cierra con el presupuesto sin precios: `export_concept_catalog`.** Del
mismo resultado sale el catálogo de conceptos en .xlsx (clave, concepto
redactado, unidad, cantidad; el P.U. en blanco y el importe, subtotales, IVA
y total ya formulados). No es el cuadro de volúmenes: cantidades netas (la
merma va en el P.U.), sin insumos (block, mortero, cemento van dentro del
P.U.), muro en m², pintura por superficie. Lo que la obra necesita y el
dibujo no mide va en `extra_concepts` con `quantity=None` → POR CUANTIFICAR.
Ponele `group` a cada item: las partidas se ordenan solas en orden de obra.

## 8.ter Errores que ya salieron en un entregable (y qué los ataja)

| Lo que pasó | Qué lo ataja ahora |
|---|---|
| Rótulo "ESCALA 1:1" en una planta a 1:75 (cajón en un layout) | `create_sheet(scale_label="1:75" o "INDICADA")`; sin él avisa |
| Títulos de vista escritos con `create_text` sobre el borde del viewport | Títulos con `create_view_title` / `compose_layout`, nunca texto suelto; el marco del viewport ya no se imprime |
| Números de cotas cortas encimados ("0.431.50") | La cadena los saca a un renglón propio |
| La cadena impresa suma 6.86 y el total dice 6.85 | La cadena avisa (`roundingMismatch`): vanos en cm enteros |
| Cotas en `txt.shx`, número cruzado por la línea | `MCP-COTAS` usa la TrueType del dibujo, número encima y alineado |
| PDF cortado (plotea A2 sobre el papel por defecto) | `export_pdf` conserva el papel de la lámina |
| Superficie de un espacio sin muros (cochera) descontando medio muro | `label_rooms` descuenta solo donde hay muro; esquiva las cotas |
| "145.57 m² × 0.15 = 17.85 m³" (la cuenta no cierra) | La medición escribe el área neta y las caras con que se calculó |

## 8.quater Cierre de TODO plano: lámina → check_all → PDF → guardar → cerrar

Un plano no está terminado hasta que pasa por estos pasos, **siempre**, aunque
nadie los pida:

1. **La lámina.** Un layout con nombre por lámina (`IE-01`, `A-01`...) con
   `compose_layout(..., sheet={"project", "location", "client", "content",
   "drawn_by", "reviewed_by", "date", "sheet_number"})`. Dibuja el cajón y
   el rótulo al tamaño real de la hoja y deja las vistas a escala, adentro
   del cajón y a la izquierda del rótulo. Si falta un dato, la celda queda
   en blanco (`blankFields`), nunca con un dato inventado.
2. **`check_all`.**
3. **`export_pdf`** de cada lámina, al lado del DWG.
4. **`save_drawing`.**
5. **Cerrar el dibujo.** AutoCAD queda como estaba antes.
6. **`package_deliverables`.** Crea una carpeta con el NOMBRE DEL PROYECTO y
   reparte los archivos por tipo: `DWG/` (para abrir en AutoCAD), `PDF/`
   (una lámina por archivo) y `XLSX/`. Además une el juego completo en UN
   PDF, `<proyecto> - JUEGO COMPLETO.pdf`, ordenado A, E, IE, IH, IS, IG, C.
   No se borra nada: los individuales quedan y lo que ya existe no se pisa.

Dos trampas que salieron al hacerlo en vivo:

- **AutoCAD crea su PROPIO viewport la primera vez que se activa un layout**
  (`LAYOUTCREATEVIEWPORT`). Muestra el modelo entero a una escala cualquiera
  y quedaba debajo del nuestro: dos plantas encimadas en la lámina, con
  todos los checks en verde. `compose_layout` ahora lo borra solo.
- **Layout1/Layout2 se borran DESPUÉS de crear las láminas propias.** Si se
  borra el último layout de papel, AutoCAD crea otro `Layout1`.

## 9. Verificar antes de dar por terminado

`check_all` corre todos los checks de cierre en una llamada, incluidos los
xrefs (uno `Unresolved`/`FileNotFound` sale como problema). Y `export_pdf`
avisa si hubo dibujo nuevo desde el último `check_all`: exportar es entregar,
y un plano se revisa antes de entregarse.

`check_sheet` responde la pregunta que ningún otro check podía: **¿el dibujo
entra en el área útil de su propia lámina?** `create_sheet` devuelve
`drawArea` y hasta ahora nadie lo verificaba — pasó de verdad que la planta se
trazó en el origen mientras el cajón estaba en otra parte, y la casa terminó
cruzando el marco con todos los demás `check_*` en verde, porque cada tool
había hecho bien SU parte. Distingue los dos casos, que se arreglan distinto:
si el dibujo **entra pero está corrido** se mueve (`move_entities`, o rehacer
la lámina con `get_extents` + `fit_sheet`); si **no entra ni centrado** hay
que subir el formato o el denominador de escala, nunca achicar el dibujo.

`check_annotations` cierra el ciclo de los otros cuatro `check_*`: ellos miran
el proyecto, este mira el plano **como dibujo** — que las cotas, las burbujas
y los rótulos no se encimen. Revisa por dos caminos: la memoria de la sesión
(lo que reservaron las cadenas y los ejes) **y el DWG**, preguntándole a
AutoCAD la caja de cada texto. El segundo es el único que sirve en un plano
que dibujó OTRO proceso — otra sesión de la interfaz, otro agente: sin él
devolvía "limpio" con siete `RECÁMARA PRINCIPAL 11.2 m2` encimados a la
vista. Cuesta ~0.5 s por texto (es una consulta al plugin por cada uno), así
que en un plano grande tarda: `drawing=False` mira solo la memoria.

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
— son las 47 suites que no necesitan AutoCAD, en alrededor de un minuto. Cubren el
inglete de las esquinas, el partido de los huecos, que los abatimientos barran
90°, que las cadenas de cota y las burbujas no se pisen en ningún orden de
dibujo, y que cambiar de dibujo no arrastre el estado del anterior. Con AutoCAD
abierto corre **solo** además `test_live.py` (`--no-live` para que no lo haga),
y ese dibuja sobre el **dibujo activo** — el del usuario — y tarda ~3 min.
Limpia lo suyo al final, pero si la corrida se corta o AutoCAD se cae, lo que
dibujó se queda ahí (pasó: 133 entidades de prueba dentro del plano de una
casa). Con el plano de un cliente activo: guardarlo antes, o `--no-live`.

`test_live_mejoras.py` (también en `--live`) verifica en AutoCAD real cada
arreglo que salió de un entregable: guardado sobre el mismo archivo, cotas
(número afuera, encima y alineado, sin txt.shx), rotación de lámina, marco
de viewport sin imprimir, PDF en el papel de la lámina, superficie sin
muros, estándar de oficina en todos los espacios y las rutas del panel web.
Trabaja en un dibujo NUEVO y lo cierra al final. Ya pagó lo suyo: encontró
tres fallas que las suites offline daban por buenas.

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
- **Cada plot lanzaba un `acad.exe` hijo** que vivía ~40 s: con
  `BACKGROUNDPLOT` en su valor de fábrica, el `PublishEngine` manda el
  trabajo a otro proceso, y mientras ese hijo vive `ProcessPlotState` no
  vuelve a `NotPlotting` — el siguiente `capture_viewport` esperaba al
  anterior y **todo lo demás** (`zoom_extents`, `get_extents`) se encolaba
  detrás: una captura pasaba de 7 s a 40-80 s en cuanto había dos seguidas,
  y el visor de la interfaz se veía en blanco todo ese rato. Desde el plugin
  1.7.0 `PlotHelper` fuerza `BACKGROUNDPLOT=0` durante el plot y lo restaura
  al salir. Si `ping` devuelve una versión anterior y ves `acad.exe` hijos
  en el administrador de tareas, es eso.
- **Cada comando al plugin cuesta ~0.5 s aunque no haga nada** (`ping`
  incluido): la cola `MainThreadQueue` se vacía en `Application.Idle`, y ese
  evento tiene esa cadencia. No es la red ni AutoCAD: es el diseño de la
  cola. Por eso todo lo que itera entidades (`check_annotations` contra el
  DWG, la limpieza de `test_live`) tiene que agrupar en UNA llamada
  (`delete_entities`, cache de `get_entity`) en vez de hacer N viajes.

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
**Versiones de AutoCAD:** probado en vivo en **2022** (net48) y **2027** (R26.0, .NET 10); `test_live.py`
da 71/71 en las dos, `test_live_mejoras.py` pasa en la 2027, y las láminas del pórtico de Mixtan
exportadas por la 2027 salen idénticas píxel a píxel a las de la 2022. 2019-2021 y 2023-2024 comparten el DLL de net48 y 2025-2026 el de .NET 8.
`python tools/matriz_api.py` compila el código contra la API oficial de CADA versión 2019-2027 (NuGet, sin
instalar nada) y da 0 errores en las nueve: la API que usa el plugin existe con la misma firma. Eso prueba
que COMPILA, no que ande en vivo: 2019-2021 y 2023-2026 siguen sin probarse en un AutoCAD real, y no se
vende como «probado» hasta tenerlo. El DLL de .NET 10 se compila contra los DLL de la propia instalación
(`AcadDir2027`, incluye `acdbmgdbrep.dll`); `tools/install_bundle.ps1` copia los tres. Un AutoCAD en
castellano usa CENTRO2/OCULTA2: cualquier tool que pida un tipo de línea tiene que pasar por
`layers.ensure`, nunca llamar `set_layer` con el nombre en inglés. La primera vez, AutoCAD 2027 pide iniciar
sesión con el ID de Autodesk: esa ventana bloquea el socket hasta que la persona entre ella misma.

**Servidor MCP nativo de AutoCAD 2027 (sin lograr usarlo):** la 2027 instala `AutoCAD-MCP-Server-2027.bundle`
(`acmcp.dll`, carga bajo demanda, sin comandos registrados en su manifiesto). Dentro del DLL hay comandos
`MCPHTTPSTART`, `MCPHTTPSTOP` y `MCPCONFIG` y un servidor HTTP en `http://localhost:<puerto>/mcp` (apagado por
omisión, `EnableHttpServer`), pero en una prueba real los tres salieron "desconocido" aun después de
`NETLOAD`, y ningún puerto nuevo se abrió. Autodesk lo da como vista previa técnica y no documenta cómo
habilitar el HTTP. Leyendo el DLL (a pedido del usuario, en su máquina; nada se copia al repo) el motivo es
este: los comandos llevan una condición que los oculta salvo que exista la variable de entorno
`ACMCP_TOOLS_CONFIG_FILE` (ruta absoluta a un JSON `{"toolsConfiguration": {"enableHttpServer": true}}`),
y esa misma variable es la única fuente de la configuración. Con ella puesta ANTES de abrir AutoCAD, al
cargar `acmcp.dll` el servidor HTTP queda en `http://localhost:<5001-5050>/mcp` (sin autenticación; CORS solo
para dominios de Autodesk). Sin verificar en vivo todavía; no es parte de lo que este repo necesita.


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
