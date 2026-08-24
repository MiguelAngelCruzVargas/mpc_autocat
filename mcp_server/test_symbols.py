"""Tests de symbols.py y de la familia de estilos de cota. NO necesita AutoCAD.

Lo que fijan estos tests, en orden de importancia:

  - La marca de nivel apoya su punta EN la cota real. Si el simbolo flota,
    el numero anotado deja de corresponder al punto del dibujo y la marca
    miente, que es peor que no tenerla.
  - El titulo de vista subraya el ancho REAL del texto y centra la escala
    debajo. Un subrayado que no llega al final se ve peor que ninguno.
  - La flecha de la marca de corte apunta al lado que dice 'direction'.
    Invertida, manda a leer el corte desde el lado contrario.
  - La familia de cotas reproduce las alturas DEFINIDAS en el juego de
    planos de referencia: COTAS50 -> 0.10 en metros, o sea 2 mm de papel por
    escala. Ojo: en ese plano esos estilos estan definidos y SIN USAR -- las
    1003 cotas van con 'CaB' o 'Standard' y con ocho alturas distintas. La
    convencion es buena; lo que el plano real demuestra es el problema de no
    tenerla.

Uso:  python test_symbols.py
"""
from __future__ import annotations

import annotation
import autocad_client as acad
import layers
import space
import symbols

FAILED: list[str] = []

# Ancho por caracter que devuelve el measure_text mockeado. Fijo y conocido
# para poder verificar el largo del subrayado con una cuenta, no a ojo.
ANCHO_POR_CHAR = 0.6


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


class Grabadora:
    """Reemplaza acad.call y guarda todo lo que se le pidio dibujar."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._n = 0

    def __call__(self, cmd, params=None):
        params = params or {}
        self.calls.append((cmd, params))
        self._n += 1
        if cmd == "measure_text":
            return {"width": len(params.get("text", "")) * ANCHO_POR_CHAR}
        if cmd == "list_layers":
            return {"layers": []}
        if cmd == "list_styles":
            # Estilo activo ya elegido: layers.ensure_text_style no lo pisa.
            return {"textStyles": [{"name": "ARIAL", "font": "arial.ttf",
                                    "isCurrent": True}]}
        return {"handle": "H%d" % self._n}

    def de(self, cmd: str) -> list[dict]:
        return [p for c, p in self.calls if c == cmd]


def con_mock(fn):
    """Corre fn con acad.call mockeado y el estado limpio."""
    def envuelto():
        real = acad.call
        g = Grabadora()
        space.clear()
        layers.reset()
        try:
            acad.call = g
            annotation.acad.call = g
            symbols.acad.call = g
            layers.acad.call = g
            fn(g)
        finally:
            acad.call = real
            annotation.acad.call = real
            symbols.acad.call = real
            layers.acad.call = real
            space.clear()
            layers.reset()
    envuelto.__name__ = fn.__name__
    return envuelto


# --------------------------------------------------------- marca de nivel

def test_fmt_elevacion() -> None:
    check("nivel positivo", symbols._fmt_elevacion(5.0, 2) == "+ 5.00",
          symbols._fmt_elevacion(5.0, 2))
    check("nivel negativo", symbols._fmt_elevacion(-1.2, 2) == "- 1.20",
          symbols._fmt_elevacion(-1.2, 2))
    check("el cero lleva mas-menos, no +",
          symbols._fmt_elevacion(0.0, 2).startswith("±"),
          symbols._fmt_elevacion(0.0, 2))


@con_mock
def test_nivel_apoya_la_punta_en_la_cota_real(g: Grabadora) -> None:
    """Si el simbolo flota sobre la cota, el numero deja de corresponder al
    punto del dibujo. Es el unico punto que no puede estar aproximado."""
    r = symbols.create_level_mark(x=2.0, y=5.0, elevation=5.0, height=0.1)

    tri = g.de("create_polyline")
    check("dibuja el triangulo", len(tri) == 1, tri)
    if tri:
        apice = tri[0]["points"][0]
        check("la punta esta EN la cota",
              cerca(apice[0], 2.0) and cerca(apice[1], 5.0), apice)

    lineas = g.de("create_line")
    check("la linea de referencia va al nivel exacto",
          any(cerca(p["y1"], 5.0) and cerca(p["y2"], 5.0) for p in lineas),
          lineas)

    txt = g.de("create_text")
    check("el texto dice el nivel", txt and "+ 5.00" in txt[0]["text"], txt)
    check("y va ARRIBA de la linea", txt and txt[0]["y"] > 5.0, txt)
    check("registra su huella en space", len(space.FOOTPRINTS) == 1,
          space.FOOTPRINTS)
    check("devuelve la caja", len(r["box"]) == 4, r)


@con_mock
def test_nivel_hacia_la_izquierda(g: Grabadora) -> None:
    symbols.create_level_mark(x=0.0, y=0.0, elevation=0.0, height=0.1,
                              side="left")
    lineas = [p for p in g.de("create_line") if cerca(p["y1"], 0.0)]
    check("la linea sale hacia la izquierda",
          any(p["x2"] < 0 for p in lineas), lineas)


@con_mock
def test_nivel_rechaza_parametros_invalidos(g: Grabadora) -> None:
    for kwargs, que in [({"side": "arriba"}, "side"),
                        ({"style": "cuadrado"}, "style")]:
        try:
            symbols.create_level_mark(x=0, y=0, elevation=0, height=0.1,
                                      **kwargs)
            check("rechaza %s invalido" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s invalido" % que, True)


# -------------------------------------------------------- titulo de vista

@con_mock
def test_titulo_subraya_el_ancho_real(g: Grabadora) -> None:
    r = symbols.create_view_title(x=0.0, y=0.0, title="PLANTA",
                                  scale_text="ESC. 1:50", height=0.4)

    txt = g.de("create_text")
    check("separa las letras", txt and txt[0]["text"] == "P L A N T A",
          txt[0]["text"] if txt else None)

    ancho = len("P L A N T A") * ANCHO_POR_CHAR
    lineas = g.de("create_line")
    check("subraya", len(lineas) == 1, lineas)
    if lineas:
        largo = lineas[0]["x2"] - lineas[0]["x1"]
        check("el subrayado mide el ancho REAL del texto",
              cerca(largo, ancho), f"{largo} vs {ancho}")
        check("y va debajo del texto", lineas[0]["y1"] < 0.0, lineas[0])
    check("devuelve el ancho", cerca(r["width"], ancho), r["width"])


@con_mock
def test_titulo_centra_la_escala_bajo_el_nombre(g: Grabadora) -> None:
    symbols.create_view_title(x=0.0, y=0.0, title="PLANTA",
                              scale_text="ESC. 1:50", height=0.4)
    txt = g.de("create_text")
    check("escribe titulo y escala", len(txt) == 2, txt)
    if len(txt) == 2:
        ancho_t = len(txt[0]["text"]) * ANCHO_POR_CHAR
        ancho_e = len(txt[1]["text"]) * ANCHO_POR_CHAR
        centro_t = txt[0]["x"] + ancho_t / 2.0
        centro_e = txt[1]["x"] + ancho_e / 2.0
        check("los dos comparten el eje vertical",
              cerca(centro_t, centro_e), f"{centro_t} vs {centro_e}")
        check("la escala es mas chica", txt[1]["height"] < txt[0]["height"],
              txt)
        check("y va abajo de todo", txt[1]["y"] < txt[0]["y"], txt)


@con_mock
def test_titulo_centrado_reparte_a_los_dos_lados(g: Grabadora) -> None:
    symbols.create_view_title(x=10.0, y=0.0, title="CORTE", height=0.4,
                              align="center", scale_text=None)
    txt = g.de("create_text")
    ancho = len(txt[0]["text"]) * ANCHO_POR_CHAR
    check("x es el CENTRO, no el borde",
          cerca(txt[0]["x"] + ancho / 2.0, 10.0), txt[0]["x"])


@con_mock
def test_titulo_vacio_es_error(g: Grabadora) -> None:
    try:
        symbols.create_view_title(x=0, y=0, title="", height=0.4)
        check("rechaza titulo vacio", False, "no tiro ValueError")
    except ValueError:
        check("rechaza titulo vacio", True)


# --------------------------------------------------------- marca de corte

@con_mock
def test_corte_dibuja_los_dos_extremos(g: Grabadora) -> None:
    r = symbols.create_section_mark(x1=0.0, y1=0.0, x2=10.0, y2=0.0,
                                    label="A", height=0.3)
    circ = g.de("create_circle")
    check("un globo por extremo", len(circ) == 2, circ)
    tri = g.de("create_polyline")
    check("una punta de flecha por extremo", len(tri) == 2, tri)
    txt = g.de("create_text")
    check("la letra en los dos globos",
          len(txt) == 2 and all(t["text"] == "A" for t in txt), txt)
    check("no traza la linea del medio por defecto",
          not any(cerca(p["x1"], 0.0) and cerca(p["x2"], 10.0)
                  for p in g.de("create_line")), g.de("create_line"))
    check("devuelve la direccion", r["direction"] == "left", r)


@con_mock
def test_corte_la_flecha_apunta_al_lado_pedido(g: Grabadora) -> None:
    """Invertida, manda a leer el corte desde el lado contrario. Con el corte
    de izquierda a derecha, 'left' es hacia +Y."""
    symbols.create_section_mark(x1=0.0, y1=0.0, x2=10.0, y2=0.0,
                                label="A", height=0.3, direction="left")
    izq = [c["y"] for c in g.de("create_circle")]
    check("direction='left' manda los globos hacia +Y",
          all(y > 0 for y in izq), izq)


@con_mock
def test_corte_direction_right_invierte(g: Grabadora) -> None:
    symbols.create_section_mark(x1=0.0, y1=0.0, x2=10.0, y2=0.0,
                                label="B", height=0.3, direction="right")
    der = [c["y"] for c in g.de("create_circle")]
    check("direction='right' los manda hacia -Y", all(y < 0 for y in der),
          der)


@con_mock
def test_corte_largo_cero_es_error(g: Grabadora) -> None:
    try:
        symbols.create_section_mark(x1=1.0, y1=1.0, x2=1.0, y2=1.0,
                                    height=0.3)
        check("rechaza largo cero", False, "no tiro ValueError")
    except ValueError as exc:
        check("rechaza largo cero", "mismo punto" in str(exc), str(exc))


# ------------------------------------------------- familia de dimstyles

@con_mock
def test_familia_reproduce_las_alturas_del_plano_de_referencia(
        g: Grabadora) -> None:
    """COTAS25=0.05, COTAS50=0.10, COTAS100=0.20, COTAS150=0.30 son las
    alturas DEFINIDAS en el juego de planos de referencia. Ojo con lo que
    esto prueba y lo que no: leyendo despues las 1003 cotas de ese plano
    resulto que NINGUNA usa esos estilos -- todas van con 'CaB' o
    'Standard', y con ocho alturas distintas. La familia esta definida y sin
    usar, herencia de una plantilla.

    O sea: estos numeros son una convencion coherente (2 mm de papel por
    escala), no una practica observada. Se conservan porque la convencion es
    buena; lo que el plano real demuestra es justamente el problema de NO
    tenerla."""
    r = annotation.set_dim_style_family(model_units="m", paper_mm=2.0)
    esperado = {"COTAS25": 0.05, "COTAS50": 0.10,
                "COTAS100": 0.20, "COTAS150": 0.30}
    por_nombre = {e["name"]: e["textHeight"] for e in r["styles"]}
    check("crea los cuatro estilos", set(por_nombre) == set(esperado),
          sorted(por_nombre))
    for nombre, alto in esperado.items():
        check("%s -> %.2f" % (nombre, alto),
              nombre in por_nombre and cerca(por_nombre[nombre], alto, 1e-12),
              por_nombre.get(nombre))

    enviados = {p["name"]: p["textHeight"] for p in g.de("set_dim_style")}
    check("y se los manda asi a AutoCAD", enviados == por_nombre, enviados)


@con_mock
def test_familia_en_centimetros_y_milimetros(g: Grabadora) -> None:
    cm = annotation.set_dim_style_family(scales=[50], model_units="cm",
                                         paper_mm=2.0)
    check("en cm, 1:50 -> 10.0", cerca(cm["styles"][0]["textHeight"], 10.0),
          cm["styles"][0])
    mm = annotation.set_dim_style_family(scales=[50], model_units="mm",
                                         paper_mm=2.0)
    check("en mm, 1:50 -> 100.0", cerca(mm["styles"][0]["textHeight"], 100.0),
          mm["styles"][0])


@con_mock
def test_familia_deja_activo_el_de_la_lamina(g: Grabadora) -> None:
    r = annotation.set_dim_style_family(model_units="m", current_scale=50)
    activos = [e["name"] for e in r["styles"] if e["isCurrent"]]
    check("deja activo COTAS50", activos == ["COTAS50"], activos)
    check("sin aviso", r["warning"] is None, r["warning"])

    r2 = annotation.set_dim_style_family(model_units="m", current_scale=75)
    check("avisa si la escala pedida no esta en la familia",
          r2["warning"] is not None, r2["warning"])


@con_mock
def test_familia_rechaza_unidades_y_escalas_invalidas(g: Grabadora) -> None:
    for kwargs, que in [({"model_units": "pulgadas"}, "unidades"),
                        ({"paper_mm": 0}, "paper_mm"),
                        ({"scales": [0]}, "escala 0")]:
        try:
            annotation.set_dim_style_family(**kwargs)
            check("rechaza %s" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s" % que, True)


# --------------------------------------------------------------- norte

@con_mock
def test_norte_apunta_arriba(g) -> None:
    """rotation 0 = la punta hacia +Y. Es el caso por default y el que se
    usa en el 95% de los planos."""
    r = symbols.create_north(100.0, 50.0, radius=2.0)
    poligonos = g.de("create_polyline")
    check("dibuja las dos mitades de la aguja", len(poligonos) == 2,
          str(len(poligonos)))
    check("dibuja su circulo", len(g.de("create_circle")) == 1,
          str(len(g.de("create_circle"))))
    check("rellena una sola mitad",
          len([p for p in g.de("create_hatch")
               if p.get("pattern") == "SOLID"]) == 1,
          str(g.de("create_hatch")))
    # La punta es el vertice mas alto de cualquiera de las dos mitades.
    ys = [p[1] for poly in poligonos for p in poly["points"]]
    xs = [p[0] for poly in poligonos for p in poly["points"]]
    check("la punta va hacia arriba", cerca(max(ys), 50.0 + 2.0 * 0.92, 1e-6),
          str(max(ys)))
    check("y esta centrada en x", cerca(max(xs) - 100.0, 100.0 - min(xs), 1e-6),
          f"{min(xs)}..{max(xs)}")
    check("devuelve el radio usado", cerca(r["radius"], 2.0), str(r["radius"]))
    letras = [p for p in g.de("create_text") if p["text"] == "N"]
    check("rotula la N", len(letras) == 1, str(g.de("create_text")))
    check("la N va sobre la punta", letras and letras[0]["y"] > 50.0,
          str(letras))


@con_mock
def test_norte_rotado(g) -> None:
    """rotation_deg se mide desde arriba y ANTIHORARIO: 90 manda la punta
    hacia -X (el oeste), no hacia +X."""
    symbols.create_north(0.0, 0.0, radius=2.0, rotation_deg=90.0)
    pts = [p for poly in g.de("create_polyline") for p in poly["points"]]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    check("la punta se fue a -X", cerca(min(xs), -2.0 * 0.92, 1e-6), str(min(xs)))
    check("y ya no apunta hacia arriba", max(ys) < 2.0 * 0.92, str(max(ys)))


@con_mock
def test_norte_registra_huella(g) -> None:
    """Sin huella, place_labels le escribiria encima."""
    symbols.create_north(10.0, 10.0, radius=1.0)
    huellas = [h for h in space.FOOTPRINTS if h.get("what") == "norte"]
    check("registra su huella", len(huellas) == 1, str(space.FOOTPRINTS))
    if huellas:
        h = huellas[0]
        check("la huella cubre el simbolo entero",
              h["x0"] < 9.0 and h["x1"] > 11.0, str(h))


@con_mock
def test_norte_style_invalido(g) -> None:
    try:
        symbols.create_north(0.0, 0.0, radius=1.0, style="rosa")
    except ValueError as exc:
        check("un style desconocido se niega", "arrow" in str(exc), str(exc))
    else:
        check("un style desconocido se niega", False, "no dio error")


def main() -> int:
    for fn in [test_fmt_elevacion,
               test_nivel_apoya_la_punta_en_la_cota_real,
               test_nivel_hacia_la_izquierda,
               test_nivel_rechaza_parametros_invalidos,
               test_titulo_subraya_el_ancho_real,
               test_titulo_centra_la_escala_bajo_el_nombre,
               test_titulo_centrado_reparte_a_los_dos_lados,
               test_titulo_vacio_es_error,
               test_corte_dibuja_los_dos_extremos,
               test_corte_la_flecha_apunta_al_lado_pedido,
               test_corte_direction_right_invierte,
               test_corte_largo_cero_es_error,
               test_familia_reproduce_las_alturas_del_plano_de_referencia,
               test_familia_en_centimetros_y_milimetros,
               test_familia_deja_activo_el_de_la_lamina,
               test_familia_rechaza_unidades_y_escalas_invalidas,
               test_norte_apunta_arriba, test_norte_rotado,
               test_norte_registra_huella, test_norte_style_invalido]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: niveles, titulos, marcas de corte y la familia de cotas "
          "coherente por escala.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
