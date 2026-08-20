"""Cuantificación de materiales: mide lo YA DIBUJADO, no supone.

Un cuadro de "cuantificación" que sale de memoria repite el error de toda
esta biblioteca antes de tener tools: alguien calcula a mano el área de un
muro que ya está dibujado, y el número que pone en la tabla no es
necesariamente el que mide el plano. Acá el área sale de `calculate_area`
sobre los handles reales, no de una cuenta aparte.

Lo único que el dibujo no puede dar solo es el ACERO: una varilla en corte es
un círculo de 1cm de diámetro dibujado esquemático, no a escala real de
longitud. Para eso se usa la especificación que ya quedó anotada en el
plano (varillas, diámetro, separación de estribos) — sigue siendo un dato
real del proyecto, no un supuesto de esta tool. Y para el perímetro del
estribo, en vez de recalcularlo a mano, se mide con la misma
`calculate_area`-hermana `get_entity` sobre el propio estribo ya dibujado
(closed Polyline: su 'length' es el perímetro).

Unidades: las del modelo (metros si se dibuja en metros). Resultados en
m³ (concreto, mortero), piezas (ladrillo) y kg (acero).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad

VALID_TYPES = ("concrete_volume", "brick_count", "mortar_volume", "steel_weight")

# kg por metro lineal — peso nominal de varilla corrugada, tabla estándar de
# fabricante (área nominal × densidad del acero). No es un supuesto del
# proyecto, es una constante de materiales.
REBAR_KG_M = {
    "#2": 0.25, "#3": 0.56, "#4": 0.994, "#5": 1.552,
    "#6": 2.235, "#8": 3.973, "#9": 5.033, "#10": 6.404,
}


def _area(handle: str) -> float:
    return acad.call("calculate_area", {"handle": handle})["area"]


def _areas(handles: list[str], label: str) -> list[float]:
    """Área de cada handle por separado — se guarda así, no solo la suma,
    para que la tabla pueda mostrar la operación completa (0.375+0.375+0.375,
    no un 1.125 que cae de la nada)."""
    if not handles:
        raise ValueError(f"'{label}': hacen falta 'handles' — la tool mide, no adivina.")
    out = []
    for h in handles:
        try:
            out.append(_area(h))
        except acad.AutoCadError as exc:
            raise ValueError(f"'{label}': no se pudo medir el handle {h!r} ({exc}).")
    return out


def calculate_quantities(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuantifica materiales a partir de entidades YA DIBUJADAS.

    items: lista de conceptos, cada uno con 'type' y 'label', más los campos
    propios de su tipo:

    "concrete_volume" — volumen de concreto de lo que ya está dibujado como
    su sección real (castillos, dalas, zapatas):
      {"type": "concrete_volume", "label": "Castillos K-1 (3 pzas)",
       "handles": ["h1","h2","h3"], "depth": 0.15}
      El área de cada handle se mide con calculate_area; 'depth' es la
      profundidad real que ESA vista no muestra (en una elevación, el
      espesor hacia adentro del muro).

    "brick_count" — piezas de tabique, de la superficie real del paño:
      {"type": "brick_count", "label": "Muro de ladrillo",
       "handles": ["h1","h2"], "brick_w": 0.28, "brick_h": 0.07,
       "joint": 0.015, "waste_pct": 5.0}
      pieces = área_medida / ((brick_w+joint)·(brick_h+joint)), con la merma.

    "mortar_volume" — mortero de junta, por diferencia real entre el volumen
    del muro y el volumen que ocupan las piezas de ladrillo:
      {"type": "mortar_volume", "label": "Mortero de junta",
       "handles": ["h1","h2"], "thickness": 0.14, "brick_w": 0.28,
       "brick_h": 0.07, "brick_depth": 0.14, "joint": 0.015}

    "steel_weight" — acero de refuerzo, de la especificación ya anotada en
    el plano (no se puede medir la varilla a escala en el dibujo):
      {"type": "steel_weight", "label": "Castillos K-1", "count": 3,
       "length": 2.5, "long_bars": 4, "long_bar_size": "#3",
       "stirrup_size": "#2", "stirrup_spacing": 0.15,
       "stirrup_handle": "466"}
      stirrup_handle mide el perímetro real del estribo YA dibujado
      (get_entity().length de esa Polyline cerrada); stirrup_perimeter
      lo reemplaza si no hay un estribo dibujado para medir.

    Devuelve 'items' (una fila resuelta por concepto, con el detalle de la
    medición) y 'totals' (sumado por material: concreto_m3, ladrillo_piezas,
    mortero_m3, acero_kg)."""
    if not items:
        raise ValueError("Hay que pasar al menos un item.")

    filas: list[dict[str, Any]] = []
    totales: dict[str, float] = {}

    for i, item in enumerate(items):
        tipo = item.get("type")
        if tipo not in VALID_TYPES:
            raise ValueError(
                f"Item #{i + 1}: type tiene que ser uno de {VALID_TYPES}, no {tipo!r}.")
        label = str(item.get("label", f"Item {i + 1}"))

        if tipo == "concrete_volume":
            depth = item.get("depth")
            if not depth or depth <= 0:
                raise ValueError(
                    f"'{label}': concrete_volume necesita 'depth' > 0 (la "
                    "profundidad real que esta vista no muestra).")
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            volumen = area * depth
            filas.append({"label": label, "type": tipo,
                          "areas": [round(a, 4) for a in areas],
                          "area": round(area, 4), "depth": depth,
                          "volume": round(volumen, 4), "unit": "m3"})
            totales["concreto_m3"] = totales.get("concreto_m3", 0.0) + volumen

        elif tipo == "brick_count":
            brick_w = float(item.get("brick_w", 0.28))
            brick_h = float(item.get("brick_h", 0.07))
            joint = float(item.get("joint", 0.015))
            waste_pct = float(item.get("waste_pct", 5.0))
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            modulo = (brick_w + joint) * (brick_h + joint)
            piezas = math.ceil(area / modulo * (1 + waste_pct / 100.0))
            filas.append({"label": label, "type": tipo,
                          "areas": [round(a, 4) for a in areas],
                          "wallArea": round(area, 4),
                          "brickW": brick_w, "brickH": brick_h, "joint": joint,
                          "moduleArea": round(modulo, 5), "wastePct": waste_pct,
                          "pieces": piezas})
            totales["ladrillo_piezas"] = totales.get("ladrillo_piezas", 0) + piezas

        elif tipo == "mortar_volume":
            thickness = item.get("thickness")
            if not thickness or thickness <= 0:
                raise ValueError(
                    f"'{label}': mortar_volume necesita 'thickness' > 0 "
                    "(espesor real del muro).")
            brick_w = float(item.get("brick_w", 0.28))
            brick_h = float(item.get("brick_h", 0.07))
            brick_depth = float(item.get("brick_depth", thickness))
            joint = float(item.get("joint", 0.015))
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            wall_vol = area * thickness
            modulo = (brick_w + joint) * (brick_h + joint)
            piezas_sin_merma = area / modulo  # el mortero llena juntas reales, sin inflar por merma
            unit_brick_vol = brick_w * brick_h * brick_depth
            brick_vol = piezas_sin_merma * unit_brick_vol
            mortero = max(wall_vol - brick_vol, 0.0)
            filas.append({"label": label, "type": tipo,
                          "areas": [round(a, 4) for a in areas],
                          "wallArea": round(area, 4), "thickness": thickness,
                          "wallVolume": round(wall_vol, 4),
                          "piecesExact": round(piezas_sin_merma, 2),
                          "unitBrickVolume": round(unit_brick_vol, 6),
                          "brickVolume": round(brick_vol, 4),
                          "mortarVolume": round(mortero, 4), "unit": "m3"})
            totales["mortero_m3"] = totales.get("mortero_m3", 0.0) + mortero

        elif tipo == "steel_weight":
            count = item.get("count")
            length = item.get("length")
            if not count or count <= 0:
                raise ValueError(f"'{label}': steel_weight necesita 'count' > 0.")
            if not length or length <= 0:
                raise ValueError(f"'{label}': steel_weight necesita 'length' > 0.")

            peso = 0.0
            detalle: dict[str, Any] = {}

            long_bars = int(item.get("long_bars", 0) or 0)
            long_size = item.get("long_bar_size")
            if long_bars and long_size:
                if long_size not in REBAR_KG_M:
                    raise ValueError(
                        f"'{label}': long_bar_size {long_size!r} no está en la "
                        f"tabla ({sorted(REBAR_KG_M)}).")
                kg_m = REBAR_KG_M[long_size]
                kg_long = count * long_bars * length * kg_m
                peso += kg_long
                detalle["longitudinal"] = {"bars": long_bars, "size": long_size,
                                           "lengthEach": length, "kgM": kg_m,
                                           "kg": round(kg_long, 2)}

            stirrup_size = item.get("stirrup_size")
            stirrup_spacing = item.get("stirrup_spacing")
            if stirrup_size and stirrup_spacing:
                if stirrup_size not in REBAR_KG_M:
                    raise ValueError(
                        f"'{label}': stirrup_size {stirrup_size!r} no está en la "
                        f"tabla ({sorted(REBAR_KG_M)}).")
                stirrup_handle = item.get("stirrup_handle")
                if stirrup_handle:
                    perim = float(acad.call(
                        "get_entity", {"handle": stirrup_handle})["length"])
                elif item.get("stirrup_perimeter"):
                    perim = float(item["stirrup_perimeter"])
                else:
                    raise ValueError(
                        f"'{label}': los estribos necesitan 'stirrup_handle' "
                        "(medido del estribo ya dibujado) o 'stirrup_perimeter'.")
                num_estribos = math.ceil(length / float(stirrup_spacing)) + 1
                kg_m = REBAR_KG_M[stirrup_size]
                kg_estribos = count * num_estribos * perim * kg_m
                peso += kg_estribos
                detalle["estribos"] = {"count": num_estribos, "size": stirrup_size,
                                       "spacing": float(stirrup_spacing),
                                       "lengthTotal": length,
                                       "perimeter": round(perim, 3), "kgM": kg_m,
                                       "kg": round(kg_estribos, 2)}

            if not detalle:
                raise ValueError(
                    f"'{label}': steel_weight necesita longitudinales "
                    "(long_bars + long_bar_size) o estribos (stirrup_size + "
                    "stirrup_spacing), o los dos.")

            filas.append({"label": label, "type": tipo, "count": count,
                          "detail": detalle, "weight": round(peso, 2), "unit": "kg"})
            totales["acero_kg"] = totales.get("acero_kg", 0.0) + peso

    return {
        "items": filas,
        "totals": {k: (round(v, 3) if isinstance(v, float) else v)
                  for k, v in totales.items()},
    }


def _suma_areas(areas: list[float]) -> str:
    """'0.375' si es un solo handle; '0.375+0.375+0.375=1.125' si son varios
    — la operación, no el total ya hecho."""
    if len(areas) == 1:
        return f"{areas[0]:.3f}"
    return " + ".join(f"{a:.3f}" for a in areas) + f" = {sum(areas):.3f}"


def _fmt_item(item: dict[str, Any]) -> str:
    """Cómo se llegó al número — la tabla muestra la operación completa,
    no el resultado ya sumado."""
    tipo = item["type"]

    if tipo == "concrete_volume":
        return (f"{_suma_areas(item['areas'])} m² × {item['depth']:.2f} m = "
                f"{item['volume']:.3f} m³")

    if tipo == "brick_count":
        modulo_op = (f"({item['brickW']:.3f}+{item['joint']:.3f})×"
                    f"({item['brickH']:.3f}+{item['joint']:.3f})="
                    f"{item['moduleArea']:.4f}")
        return (f"{_suma_areas(item['areas'])} m² / {modulo_op} m² "
                f"(+{item['wastePct']:g}% merma) = {item['pieces']} pzas")

    if tipo == "mortar_volume":
        return (f"{_suma_areas(item['areas'])} m² × {item['thickness']:.2f} m = "
                f"{item['wallVolume']:.3f} m³ muro − ({item['piecesExact']:.1f} "
                f"pzas × {item['unitBrickVolume']:.5f} m³/pza = "
                f"{item['brickVolume']:.3f} m³ ladrillo) = "
                f"{item['mortarVolume']:.3f} m³")

    # steel_weight
    partes = []
    for clave, d in item["detail"].items():
        if clave == "longitudinal":
            partes.append(f"{item['count']}pzas×{d['bars']}{d['size']}×"
                          f"{d['lengthEach']:.2f}m×{d['kgM']:.2f}kg/m="
                          f"{d['kg']:.2f}kg")
        else:
            partes.append(f"{item['count']}pzas×{d['count']}E{d['size']}"
                          f"(@{d['spacing']:.2f}m en {d['lengthTotal']:.2f}m)×"
                          f"{d['perimeter']:.2f}m×{d['kgM']:.2f}kg/m="
                          f"{d['kg']:.2f}kg")
    return " + ".join(partes) + f" = {item['weight']:.1f} kg"


def create_quantities_table(x: float, y: float, result: dict[str, Any],
                            text_height: float,
                            title: str = "CUANTIFICACIÓN DE OBRA (MEDIDA DEL PLANO)",
                            layer: str = "TABLAS",
                            col_widths: Optional[list[float]] = None) -> dict[str, Any]:
    """Dibuja el resultado de calculate_quantities como tabla.

    No repite el cálculo: toma 'items'/'totals' tal como los devolvió
    calculate_quantities y solo los tabula, con una columna que muestra CÓMO
    se midió cada número (área real, módulo, etc.), no solo el resultado.

    col_widths: [concepto, medición]. La columna de medición trae la fórmula
    completa (p.ej. "11.97 m² / módulo 0.0251 m² = 502 pzas"), así que por
    defecto sale ancha (8.5 m); si algún texto no entra, create_table avisa
    en 'warning' cuánto necesita — agrandá col_widths o acortá el label."""
    import annotation as ann_mod
    if col_widths is None:
        col_widths = [5.5, 17.0]

    rows = [["CONCEPTO", "MEDICIÓN Y CÁLCULO"]]
    for item in result["items"]:
        rows.append([item["label"], _fmt_item(item)])

    etiquetas_totales = {
        "concreto_m3": "TOTAL CONCRETO", "ladrillo_piezas": "TOTAL LADRILLO",
        "mortero_m3": "TOTAL MORTERO", "acero_kg": "TOTAL ACERO",
    }
    unidades_totales = {
        "concreto_m3": "m³", "ladrillo_piezas": "pzas",
        "mortero_m3": "m³", "acero_kg": "kg",
    }
    for clave, valor in result["totals"].items():
        etiqueta = etiquetas_totales.get(clave, clave.upper())
        unidad = unidades_totales.get(clave, "")
        rows.append([etiqueta, f"{valor:g} {unidad}".strip()])

    return ann_mod.create_table(
        x=x, y=y, rows=rows, col_widths=col_widths, row_height=0.4,
        text_height=text_height, title=title, header=True, layer=layer)
