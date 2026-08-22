"""Componer la lamina: donde va cada vista, no solo que no se pisen.

space.py resuelve que dos cosas no se encimen. Componer es otra cosa: es
alinear, repartir parejo y agrupar lo que se lee junto. La diferencia entre
"nada se pisa" y "esto esta disenado" es exactamente esa, y es la que separa
una lamina con las vistas tiradas al azar de una profesional.

Hasta ahora cada vista aterrizaba en una coordenada que inventaba quien
llamaba. El resultado tipico: una lamina vacia en dos tercios con el corte
abajo a la izquierda, el isometrico arriba al centro y la planta al medio,
sin una sola alineacion entre ellas.

El motor de ubicacion (plan_composition) es geometria pura -- no habla con
AutoCAD y por eso se prueba entero sin abrirlo. apply_composition es lo unico
que toca el dibujo.

Dos ideas que hacen el trabajo:

  - UNIDADES. Una vista que declara `below` se apila con la de arriba y las
    dos pasan a ser UNA unidad que se acomoda junta, con los centros en X
    alineados. Eso es la alineacion proyectiva: la planta debajo de su corte,
    compartiendo los ejes verticales, que es como se leen una con otra.
  - FILAS. Las unidades se acomodan de izquierda a derecha hasta que no entra
    una mas, y ahi empieza otra fila. Dentro de la fila se apoyan todas en la
    misma linea de base, que es lo que hace que la lamina se vea alineada.

Unidades: las del modelo. Los margenes se piden en mm de papel y se
convierten con la escala de la lamina.
"""
from __future__ import annotations

from typing import Any, Optional

import autocad_client as acad
import space

# Separacion entre vistas y entre filas, en mm de papel. 15 mm es un aire
# comodo en A1; por debajo de 8 la lamina se lee apretada.
GUTTER_MM = 15.0

# Alto que se reserva bajo cada vista para su titulo (nombre + subrayado +
# escala). Sale de create_view_title: 4 mm de nombre + 0.6*4 de escala + aire.
TITLE_BLOCK_MM = 11.0


def _caja(v: dict[str, Any], quien: str) -> tuple[float, float, float, float]:
    caja = v.get("box")
    if not caja or len(caja) != 4:
        raise ValueError(
            "La vista %r no trae 'box': [x0, y0, x1, y1] con donde esta "
            "dibujada AHORA. Sale de get_extents, calculate_area o de lo que "
            "devolvio la tool que la dibujo." % quien)
    x0, y0, x1, y1 = (float(c) for c in caja)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(
            "La caja de la vista %r esta invertida o es de area cero: %s"
            % (quien, caja))
    return x0, y0, x1, y1


class _Unidad:
    """Una vista suelta, o una pila de vistas alineadas por su centro en X."""

    def __init__(self, vistas: list[dict[str, Any]], gutter: float,
                 title_block: float) -> None:
        self.vistas = vistas
        self.gutter = gutter
        self.title_block = title_block
        self.altos: list[float] = []
        self.anchos: list[float] = []
        for v in vistas:
            x0, y0, x1, y1 = _caja(v, v.get("name", "?"))
            self.anchos.append(x1 - x0)
            alto = y1 - y0
            if v.get("title"):
                alto += title_block
            self.altos.append(alto)

    @property
    def width(self) -> float:
        return max(self.anchos)

    @property
    def height(self) -> float:
        return sum(self.altos) + self.gutter * (len(self.vistas) - 1)

    @property
    def name(self) -> str:
        return " + ".join(str(v.get("name", "?")) for v in self.vistas)


def _unidades(views: list[dict[str, Any]], gutter: float,
              title_block: float) -> list[_Unidad]:
    """Arma las unidades resolviendo las cadenas de 'below'.

    'below': "planta" quiere decir "esta vista va DEBAJO de planta". Se
    valida que la referencia exista, que no se apunte a si misma y que no
    haya ciclos -- un ciclo dejaria la composicion sin poder empezar por
    ninguna, y en silencio.
    """
    por_nombre: dict[str, dict[str, Any]] = {}
    for v in views:
        n = v.get("name")
        if not n:
            raise ValueError(
                "Toda vista necesita 'name': es como se la referencia desde "
                "'below' y como sale nombrada en el resultado.")
        if n in por_nombre:
            raise ValueError("Hay dos vistas llamadas %r." % n)
        por_nombre[n] = v

    hijos: dict[str, list[str]] = {}
    for v in views:
        arriba = v.get("below")
        if arriba is None:
            continue
        if arriba == v["name"]:
            raise ValueError(
                "La vista %r se declara debajo de si misma." % v["name"])
        if arriba not in por_nombre:
            raise ValueError(
                "La vista %r dice ir debajo de %r, que no esta en la lista. "
                "Vistas: %s" % (v["name"], arriba, sorted(por_nombre)))
        hijos.setdefault(arriba, []).append(v["name"])

    # Raices: las que no van debajo de nadie. Se conserva el orden pedido.
    raices = [v["name"] for v in views if v.get("below") is None]
    if not raices:
        raise ValueError(
            "Todas las vistas declaran 'below': hay un ciclo y la "
            "composicion no puede empezar por ninguna.")

    unidades: list[_Unidad] = []
    vistos: set[str] = set()
    for raiz in raices:
        pila: list[dict[str, Any]] = []
        actual: Optional[str] = raiz
        while actual is not None:
            if actual in vistos:
                raise ValueError(
                    "Ciclo en 'below' alrededor de %r." % actual)
            vistos.add(actual)
            pila.append(por_nombre[actual])
            siguientes = hijos.get(actual, [])
            if len(siguientes) > 1:
                raise ValueError(
                    "Mas de una vista dice ir debajo de %r (%s). Una pila es "
                    "una columna: solo una puede ir abajo de cada una."
                    % (actual, ", ".join(siguientes)))
            actual = siguientes[0] if siguientes else None
        unidades.append(_Unidad(pila, gutter, title_block))

    huerfanas = set(por_nombre) - vistos
    if huerfanas:
        raise ValueError(
            "Ciclo en 'below': quedaron sin acomodar %s."
            % ", ".join(sorted(huerfanas)))
    return unidades


def plan_composition(views: list[dict[str, Any]],
                     area: list[float],
                     gutter_mm: float = GUTTER_MM,
                     title_block_mm: float = TITLE_BLOCK_MM,
                     align: str = "bottom",
                     distribute: str = "center",
                     scale: Optional[float] = None) -> dict[str, Any]:
    """Calcula donde va cada vista. NO dibuja ni mueve nada.

    views: [{"name", "box": [x0,y0,x1,y1], "title"?, "below"?}]. La 'box' es
    donde la vista esta dibujada AHORA.
    area: [x0,y0,x1,y1] donde componer -- el drawArea de create_sheet.
    align: como se apoyan las vistas de una misma fila ('bottom' las deja
    sobre una linea de base comun, 'center' las centra verticalmente).
    distribute: 'center' centra el bloque de cada fila, 'left' lo pega a la
    izquierda, 'justify' lo estira para ocupar todo el ancho.

    Devuelve el destino de cada vista y el desplazamiento que hay que
    aplicarle. Si no entra, lo dice en 'fits' y en 'warnings' -- no achica
    nada: una vista fuera de escala no es una lamina, es un error.
    """
    if align not in ("bottom", "center"):
        raise ValueError("align tiene que ser 'bottom' o 'center'.")
    if distribute not in ("center", "left", "justify"):
        raise ValueError("distribute tiene que ser 'center', 'left' o 'justify'.")
    if not views:
        raise ValueError("No hay vistas que componer.")
    if not area or len(area) != 4:
        raise ValueError("area tiene que ser [x0, y0, x1, y1].")

    ax0, ay0, ax1, ay1 = (float(c) for c in area)
    W, H = ax1 - ax0, ay1 - ay0
    if W <= 0 or H <= 0:
        raise ValueError("El area de composicion tiene ancho o alto <= 0: %s"
                         % area)

    gutter = space.paper(gutter_mm, scale)
    title_block = space.paper(title_block_mm, scale)

    unidades = _unidades(views, gutter, title_block)
    avisos: list[str] = []

    # --- repartir en filas ------------------------------------------------
    filas: list[list[_Unidad]] = []
    actual: list[_Unidad] = []
    ancho_actual = 0.0
    for u in unidades:
        if u.width > W:
            avisos.append(
                "La vista %s mide %.2f de ancho y el area util %.2f: no entra "
                "ni sola. Subi el formato o bajá la escala." % (u.name, u.width, W))
        extra = u.width if not actual else gutter + u.width
        if actual and ancho_actual + extra > W:
            filas.append(actual)
            actual, ancho_actual = [u], u.width
        else:
            actual.append(u)
            ancho_actual += extra
    if actual:
        filas.append(actual)

    altos_fila = [max(u.height for u in f) for f in filas]
    alto_total = sum(altos_fila) + gutter * (len(filas) - 1)
    entra = alto_total <= H + 1e-9
    if not entra:
        avisos.append(
            "Las %d vistas ocupan %.2f de alto y el area util tiene %.2f: "
            "sobra %.2f. Van en dos laminas, o el formato tiene que crecer."
            % (len(views), alto_total, H, alto_total - H))

    # --- ubicar -----------------------------------------------------------
    # Se arranca desde ARRIBA del area: la primera vista de la lista queda
    # arriba a la izquierda, que es por donde se empieza a leer una lamina.
    colocaciones: list[dict[str, Any]] = []
    y_tope = ay1
    for fila, alto_fila in zip(filas, altos_fila):
        anchos = [u.width for u in fila]
        suma = sum(anchos)
        n = len(fila)

        if distribute == "justify" and n > 1:
            hueco = (W - suma) / (n - 1)
            x = ax0
        else:
            hueco = gutter
            libre = W - (suma + gutter * (n - 1))
            x = ax0 + (libre / 2.0 if distribute == "center" else 0.0)

        for u in fila:
            # Dentro de la fila: linea de base comun, o centrado vertical.
            if align == "bottom":
                # La fila apoya sobre una linea de base comun (y_tope -
                # alto_fila): una unidad mas baja que la fila arranca mas
                # abajo, no mas arriba.
                y_unidad_top = y_tope - (alto_fila - u.height)
            else:
                y_unidad_top = y_tope - (alto_fila - u.height) / 2.0

            # Las vistas de una pila se centran en X entre si: es la
            # alineacion proyectiva (la planta bajo su corte).
            cx = x + u.width / 2.0
            y_cursor = y_unidad_top
            for v, ancho, alto in zip(u.vistas, u.anchos, u.altos):
                bx0, by0, bx1, by1 = _caja(v, v["name"])
                destino_x0 = cx - ancho / 2.0
                alto_dibujo = by1 - by0
                # 'alto' incluye el bloque de titulo; el dibujo va arriba y
                # el titulo abajo, dentro de ese alto.
                destino_y1 = y_cursor
                destino_y0 = destino_y1 - alto_dibujo

                punto_titulo = None
                if v.get("title"):
                    punto_titulo = [cx, destino_y0 - space.paper(4.0, scale)]

                colocaciones.append({
                    "name": v["name"],
                    "box": [destino_x0, destino_y0,
                            destino_x0 + ancho, destino_y1],
                    "dx": destino_x0 - bx0,
                    "dy": destino_y1 - by1,
                    "titlePoint": punto_titulo,
                    "title": v.get("title"),
                    "scaleText": v.get("scale_text"),
                })
                y_cursor -= alto + gutter

            x += u.width + hueco

        y_tope -= alto_fila + gutter

    return {"placements": colocaciones,
            "rows": [[u.name for u in f] for f in filas],
            "usedHeight": alto_total, "availableHeight": H,
            "usedWidth": max((sum(u.width for u in f)
                              + gutter * (len(f) - 1)) for f in filas),
            "availableWidth": W,
            "fits": entra, "warnings": avisos}


# ===================================================== aplicar al dibujo

def _handles_de(v: dict[str, Any]) -> list[str]:
    """Los handles de una vista: los que se pasaron, o los que haya adentro
    de su caja.

    'inside' y no 'crossing' a proposito: lo que cruza el borde de la vista
    probablemente pertenezca a la de al lado, y llevarselo puesto al acomodar
    parte el dibujo del vecino.
    """
    dados = v.get("handles")
    if dados:
        return [str(h) for h in dados]
    x0, y0, x1, y1 = _caja(v, v["name"])
    r = acad.call("select_entities", {
        "x1": x0, "y1": y0, "x2": x1, "y2": y1,
        "layers": None, "types": None, "mode": "inside"})
    return [e["handle"] for e in r.get("entities", [])]


def _mover(handles: list[str], dx: float, dy: float) -> int:
    """Mueve en UNA llamada si el plugin lo soporta, si no una por una.

    move_entities es del plugin 0.5.0. Con un DLL anterior cargado, el
    comando no existe y hay que caer al de a uno -- funciona igual, solo que
    son N viajes por el socket en vez de uno.
    """
    if not handles:
        return 0
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return 0
    try:
        r = acad.call("move_entities", {"handles": handles, "dx": dx,
                                        "dy": dy, "dz": 0.0,
                                        "ignoreMissing": True})
        return int(r.get("moved", 0))
    except acad.AutoCadError as exc:
        if "no soportado" not in str(exc).lower():
            raise
    movidas = 0
    for h in handles:
        try:
            acad.call("move_entity", {"handle": h, "dx": dx, "dy": dy,
                                      "dz": 0.0})
            movidas += 1
        except acad.AutoCadError:
            pass
    return movidas


def compose_sheet(views: list[dict[str, Any]],
                  area: list[float],
                  gutter_mm: float = GUTTER_MM,
                  title_block_mm: float = TITLE_BLOCK_MM,
                  align: str = "bottom",
                  distribute: str = "center",
                  scale: Optional[float] = None,
                  draw_titles: bool = True,
                  dry_run: bool = False) -> dict[str, Any]:
    """Acomoda vistas YA DIBUJADAS y les pone su titulo.

    El flujo es: dibujar cada vista donde sea (apartadas entre si), anotar la
    caja de cada una, y llamar esto. Las mueve a su lugar en la lamina.

    dry_run=True devuelve el plan sin tocar nada -- conviene mirarlo antes,
    sobre todo el 'fits'.

    OJO con el estado de anotacion: al mover las vistas, las huellas y las
    franjas que space tenia registradas dejan de valer (todo cambio de
    lugar). Se reinician y se vuelven a registrar las cajas nuevas. Si habia
    cadenas de cota ya reservadas, hay que volver a acotar DESPUES de
    componer, no antes.
    """
    plan = plan_composition(views, area, gutter_mm=gutter_mm,
                            title_block_mm=title_block_mm, align=align,
                            distribute=distribute, scale=scale)
    if dry_run:
        plan["applied"] = False
        return plan

    por_nombre = {v["name"]: v for v in views}

    # Los handles se juntan ANTES de mover nada: si se moviera vista por
    # vista, la ventana de seleccion de la siguiente podria agarrar lo que
    # ya se acomodo adentro de ella.
    seleccion = {p["name"]: _handles_de(por_nombre[p["name"]])
                 for p in plan["placements"]}

    movidas = 0
    for p in plan["placements"]:
        movidas += _mover(seleccion[p["name"]], p["dx"], p["dy"])

    space.clear()
    for p in plan["placements"]:
        x0, y0, x1, y1 = p["box"]
        space.track(x0, y0, x1, y1, "vista " + p["name"])

    titulos = 0
    if draw_titles:
        import symbols
        for p in plan["placements"]:
            if not p.get("title") or not p.get("titlePoint"):
                continue
            symbols.create_view_title(
                x=p["titlePoint"][0], y=p["titlePoint"][1],
                title=p["title"], scale_text=p.get("scaleText"),
                height=space.paper(4.0, scale), align="center")
            titulos += 1

    plan["applied"] = True
    plan["movedEntities"] = movidas
    plan["titlesDrawn"] = titulos
    plan["warnings"] = list(plan["warnings"]) + [
        "Se reinicio el estado de anotacion (space): las vistas cambiaron de "
        "lugar. Acota y rotula DESPUES de componer."]
    return plan


# ============================================ una lamina por layout

# Milimetros reales que mide UNA unidad del modelo. Es lo que create_viewport
# llama model_units_per_mm, y sin eso la escala del viewport sale mil veces
# mal dibujando en metros.
_MM_POR_UNIDAD = {"m": 1000.0, "cm": 10.0, "mm": 1.0}


def _papel_de(nombre: str) -> tuple[float, float]:
    """Tamano real de la hoja del layout, preguntandoselo al dibujo.

    No se le pide al que llama: create_layout elige el papel por nombre
    ('A1', 'ARCH D') entre los del dispositivo, y el que sale puede no ser el
    que uno tenia en la cabeza. Componer sobre un tamano supuesto deja las
    vistas fuera de la hoja sin ningun error.
    """
    for lay in acad.call("list_layouts", {}).get("layouts", []):
        if lay.get("name") == nombre:
            return float(lay["paperWidth"]), float(lay["paperHeight"])
    raise ValueError(
        "No existe un layout llamado %r. Layouts: %s"
        % (nombre, [l.get("name") for l in
                    acad.call("list_layouts", {}).get("layouts", [])]))


def compose_layout(name: str,
                   views: list[dict[str, Any]],
                   model_units: str = "m",
                   margin_mm: float = 15.0,
                   gutter_mm: float = 15.0,
                   title_block_mm: float = 11.0,
                   reserved_right_mm: float = 0.0,
                   padding_mm: float = 4.0,
                   align: str = "bottom",
                   distribute: str = "center",
                   plot_config: Optional[str] = None,
                   paper_size: Optional[str] = None,
                   create: bool = True,
                   locked: bool = True,
                   draw_titles: bool = True,
                   dry_run: bool = False) -> dict[str, Any]:
    """Arma una lamina en ESPACIO PAPEL: un viewport por vista, a su escala.

    Es el flujo correcto cuando hay varias laminas del mismo proyecto: el
    dibujo vive UNA sola vez en el modelo y cada layout lo recorta. Es lo que
    hace un juego profesional -- el modelo se ve desordenado porque tiene
    todas las disciplinas encimadas, y cada lamina sale limpia porque su
    viewport muestra solo su pedazo.

    A diferencia de compose_sheet, esto NO mueve nada: el modelo queda como
    esta. Solo crea ventanas que lo miran.

    views: [{"name", "box": [x0,y0,x1,y1] del MODELO, "scale_denominator",
             "title"?, "scale_text"?, "below"?, "padding_mm"?}]
    reserved_right_mm: franja derecha que NO se usa para vistas. Es donde va
    la columna fija de localizacion / simbologia / rotulo que se repite igual
    en todas las laminas del juego.

    OJO: crear el PRIMER layout de un dibujo puede disparar un dialogo modal
    de AutoCAD que bloquea el socket. Si esto se cuelga, mira la pantalla.
    """
    if model_units not in _MM_POR_UNIDAD:
        raise ValueError(
            "model_units tiene que ser 'm', 'cm' o 'mm'; vino %r." % model_units)
    if not views:
        raise ValueError("No hay vistas que componer.")
    mm_unidad = _MM_POR_UNIDAD[model_units]

    if create and not dry_run:
        acad.call("create_layout", {"name": name, "plotConfig": plot_config,
                                    "paperSize": paper_size})
    ancho_hoja, alto_hoja = _papel_de(name)

    # Cada vista ocupa en PAPEL lo que mide en el modelo dividido su escala.
    # Un local de 16.60 m a 1:100 son 166 mm de papel.
    en_papel: list[dict[str, Any]] = []
    for v in views:
        denom = float(v.get("scale_denominator", 0) or 0)
        if denom <= 0:
            raise ValueError(
                "La vista %r no trae 'scale_denominator' (100 para 1:100). "
                "Sin escala no hay forma de saber cuanto papel ocupa."
                % v.get("name", "?"))
        x0, y0, x1, y1 = _caja(v, v.get("name", "?"))
        aire = float(v.get("padding_mm", padding_mm))
        w = (x1 - x0) * mm_unidad / denom + 2 * aire
        h = (y1 - y0) * mm_unidad / denom + 2 * aire
        en_papel.append({
            "name": v["name"], "box": [0.0, 0.0, w, h],
            "title": v.get("title"),
            "scale_text": v.get("scale_text") or "ESC. 1:%g" % denom,
            "below": v.get("below"),
            "_modelo": (x0, y0, x1, y1), "_denom": denom,
        })

    area = [margin_mm, margin_mm,
            ancho_hoja - margin_mm - reserved_right_mm, alto_hoja - margin_mm]

    # scale=1.0 porque acá TODO ya está en milímetros de papel: es el espacio
    # papel, no el modelo. space.paper(mm, 1.0) devuelve los mismos mm.
    plan = plan_composition(en_papel, area, gutter_mm=gutter_mm,
                            title_block_mm=title_block_mm, align=align,
                            distribute=distribute, scale=1.0)
    plan["layout"] = name
    plan["paper"] = [ancho_hoja, alto_hoja]
    if dry_run:
        plan["applied"] = False
        return plan

    por_nombre = {v["name"]: v for v in en_papel}
    viewports: list[dict[str, Any]] = []
    for p in plan["placements"]:
        v = por_nombre[p["name"]]
        mx0, my0, mx1, my1 = v["_modelo"]
        x0, y0, x1, y1 = p["box"]
        r = acad.call("create_viewport", {
            "layout": name,
            "centerX": (x0 + x1) / 2.0, "centerY": (y0 + y1) / 2.0,
            "width": x1 - x0, "height": y1 - y0,
            "viewCenterX": (mx0 + mx1) / 2.0,
            "viewCenterY": (my0 + my1) / 2.0,
            "scaleDenominator": v["_denom"],
            "modelUnitsPerMm": mm_unidad, "locked": locked})
        viewports.append({"name": p["name"], "handle": r.get("handle"),
                          "scale": "1:%g" % v["_denom"],
                          "paperBox": p["box"]})

    titulos = 0
    if draw_titles:
        import symbols
        # Los titulos van DENTRO del layout: todo se dibuja en el espacio
        # ACTIVO, asi que hay que pararse ahi y volver al terminar.
        previo = acad.call("list_layouts", {}).get("current")
        acad.call("set_current_layout", {"name": name})
        try:
            for p in plan["placements"]:
                if not p.get("title") or not p.get("titlePoint"):
                    continue
                # En papel, un milimetro es un milimetro: la altura va tal
                # cual, sin convertir por la escala de ninguna vista.
                symbols.create_view_title(
                    x=p["titlePoint"][0], y=p["titlePoint"][1],
                    title=p["title"], scale_text=p.get("scaleText"),
                    height=4.0, align="center")
                titulos += 1
        finally:
            if previo:
                acad.call("set_current_layout", {"name": previo})

    plan["applied"] = True
    plan["viewports"] = viewports
    plan["titlesDrawn"] = titulos
    return plan
