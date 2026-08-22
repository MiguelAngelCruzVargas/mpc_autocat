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
estribo (o de la sección de un elemento para cimbra), en vez de
recalcularlo a mano, se mide con la misma `calculate_area`-hermana
`get_entity` sobre la propia Polyline ya dibujada (closed Polyline: su
'length' es el perímetro).

La merma (`waste_pct`) no es un invento de esta tool: es el mismo dato que
cualquier presupuesto de obra aplica (desperdicio de colado, retazos de
corte, sobrante de mezcla) y que si no se pide explícito, alguien lo suma
aparte con la calculadora — con el mismo riesgo de que no coincida con lo
que dice el plano. Por default es 0.0 en todos los tipos: no se inventa una
merma que el proyecto no pidió.

Unidades: las del modelo (metros si se dibuja en metros). Resultados en
m³ (concreto, mortero, excavación, relleno, acabados con espesor),
m² (cimbra, acabados por área), piezas (ladrillo) y kg (acero).
"""
from __future__ import annotations

import csv
import math
from typing import Any, Optional

import autocad_client as acad

VALID_TYPES = (
    "concrete_volume", "concrete_mix", "brick_count", "mortar_volume",
    "steel_weight", "earthwork", "formwork", "area_finish",
)

# Rendimiento típico por m³ de concreto -- referencia de obra para f'c=200
# kg/cm² con proporción aprox. 1:2:3 (cemento:arena:grava), NO un ensayo de
# laboratorio de este proyecto. concrete_mix los toma como default
# reemplazable: si el proyecto ya tiene su diseño de mezcla real, se pasan
# los coeficientes propios en vez de estos.
CEMENT_BAGS_PER_M3 = 7.5   # bolsas de 50kg
SAND_M3_PER_M3 = 0.50
GRAVEL_M3_PER_M3 = 0.80

# kg por metro lineal — peso nominal de varilla corrugada, tabla estándar de
# fabricante (área nominal × densidad del acero). No es un supuesto del
# proyecto, es una constante de materiales.
REBAR_KG_M = {
    "#2": 0.25, "#3": 0.56, "#4": 0.994, "#5": 1.552,
    "#6": 2.235, "#8": 3.973, "#9": 5.033, "#10": 6.404,
}

# Diámetro nominal en mm — misma tabla de fabricante, hace falta para el
# traslape (empalme) por diámetros: el criterio usual de obra es "N
# diámetros de longitud de traslape", no un largo fijo.
REBAR_DIAM_MM = {
    "#2": 6.35, "#3": 9.53, "#4": 12.70, "#5": 15.88,
    "#6": 19.05, "#8": 25.40, "#9": 28.65, "#10": 32.26,
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


def _perimeter(handle: str, label: str, what: str) -> float:
    try:
        return float(acad.call("get_entity", {"handle": handle})["length"])
    except acad.AutoCadError as exc:
        raise ValueError(f"'{label}': no se pudo medir el {what} {handle!r} ({exc}).")


def calculate_quantities(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuantifica materiales a partir de entidades YA DIBUJADAS.

    items: lista de conceptos, cada uno con 'type' y 'label', más los campos
    propios de su tipo:

    "concrete_mix" — bolsas de cemento, arena y grava que hacen falta para
    colar un volumen de concreto, por rendimiento (no un ensayo de
    laboratorio de este proyecto -- una referencia de obra reemplazable):
      {"type": "concrete_mix", "label": "Losa de escalera",
       "handles": ["h1"], "depth": 1.00, "cement_bags_per_m3": 7.5,
       "sand_m3_per_m3": 0.50, "gravel_m3_per_m3": 0.80, "waste_pct": 5.0}
      Mide igual que concrete_volume (handles+depth) si no se dibujó ya un
      item de concrete_volume para lo mismo; si ya se calculó ese volumen
      en otro item, pasalo directo con 'volume' en vez de volver a medir:
      {"type": "concrete_mix", "label": "Losa de escalera",
       "volume": 1.61, "waste_pct": 5.0}
      cement_bags_per_m3/sand_m3_per_m3/gravel_m3_per_m3 son de referencia
      para f'c≈200 kg/cm² proporción ~1:2:3 -- si el proyecto tiene su
      propio diseño de mezcla, van esos coeficientes en vez de los default.
      bolsas = volumen×cement_bags_per_m3 (redondeado hacia arriba, no se
      compra media bolsa); arena/grava en m³, con la misma merma.
    "concrete_volume" — volumen de concreto de lo que ya está dibujado como
    su sección real (castillos, dalas, zapatas):
      {"type": "concrete_volume", "label": "Castillos K-1 (3 pzas)",
       "handles": ["h1","h2","h3"], "depth": 0.15, "waste_pct": 5.0}
      El área de cada handle se mide con calculate_area; 'depth' es la
      profundidad real que ESA vista no muestra (en una elevación, el
      espesor hacia adentro del muro). 'waste_pct' (default 0) es el
      desperdicio real de colado.

    "brick_count" — piezas de tabique, de la superficie real del paño:
      {"type": "brick_count", "label": "Muro de ladrillo",
       "handles": ["h1","h2"], "brick_w": 0.28, "brick_h": 0.07,
       "joint": 0.015, "waste_pct": 5.0}
      pieces = área_medida / ((brick_w+joint)·(brick_h+joint)), con la merma.

    "mortar_volume" — mortero de junta, por diferencia real entre el volumen
    del muro y el volumen que ocupan las piezas de ladrillo:
      {"type": "mortar_volume", "label": "Mortero de junta",
       "handles": ["h1","h2"], "thickness": 0.14, "brick_w": 0.28,
       "brick_h": 0.07, "brick_depth": 0.14, "joint": 0.015,
       "waste_pct": 5.0}
      'waste_pct' (default 0) es el sobrante real de mezcla.

    "steel_weight" — acero de refuerzo, de la especificación ya anotada en
    el plano (no se puede medir la varilla a escala en el dibujo). Admite
    varilla longitudinal, estribos y/o malla electrosoldada de losa, los
    tres sumables en el mismo item:
      {"type": "steel_weight", "label": "Castillos K-1", "count": 3,
       "length": 2.5, "long_bars": 4, "long_bar_size": "#3",
       "commercial_length": 9.0, "lap_diam_factor": 40,
       "stirrup_size": "#2", "stirrup_spacing": 0.15,
       "stirrup_handle": "466", "waste_pct": 5.0}
      stirrup_handle mide el perímetro real del estribo YA dibujado
      (get_entity().length de esa Polyline cerrada); stirrup_perimeter
      lo reemplaza si no hay un estribo dibujado para medir.
      'commercial_length' (largo comercial de la varilla, p.ej. 9 o 12m) y
      'lap_diam_factor' (traslape en diámetros de barra, típico 40-60) son
      opcionales: si 'length' supera el largo comercial, se suma el
      traslape real en vez de asumir una sola pieza continua que no existe
      en obra. 'waste_pct' (default 0) es el retazo de corte y amarre.
      Para malla electrosoldada de losa, en vez de (o además de) lo
      anterior:
      {"type": "steel_weight", "label": "Malla losa entrepiso",
       "handles": ["losa1"], "mesh_kg_m2": 2.86, "waste_pct": 3.0}
      kg = área medida × mesh_kg_m2 (el peso por m² es el dato de catálogo
      de la malla especificada en el plano, no algo que la tool deduzca).

    "earthwork" — movimiento de tierra de lo que ya está dibujado en planta
    (el polígono de excavación de una zapata o cepa):
      Excavación: {"type": "earthwork", "mode": "excavation",
       "label": "Excavación zapatas Z-1", "handles": ["h1"], "depth": 0.60,
       "swell_pct": 25.0}
      volume = área medida × depth; 'swell_pct' (esponjamiento/abundamiento
      del material al sacarlo del banco) es opcional y solo informa
      'volumeSwollen', para calcular acarreo — el volumen de banco
      (facturable como excavación) es el que no lleva esponjar.
      Relleno: {"type": "earthwork", "mode": "backfill",
       "label": "Relleno zapatas Z-1", "handles": ["h1"], "depth": 0.60,
       "structure_volume": 0.42}
      volume = (área medida × depth) − structure_volume — estructura_volume
      es el volumen YA calculado en otro item de concrete_volume que ocupa
      el mismo hueco; no se recalcula acá, se pasa el número real.

    "formwork" — cimbra/encofrado, el área de contacto real. Dos formas de
    medirla según lo que haya dibujado:
      Cara ya dibujada directo (losa, muro): {"type": "formwork",
       "label": "Cimbra losa entrepiso", "handles": ["h1"], "faces": 1,
       "waste_pct": 5.0}
      area = suma de áreas medidas × faces (2 si la cimbra va a ambos lados
      y solo se dibujó una cara).
      Por sección (castillo, dala, trabe): {"type": "formwork",
       "label": "Cimbra castillos K-1", "count": 3, "length": 2.5,
       "section_handle": "h1", "waste_pct": 5.0}
      area = count × perímetro MEDIDO de la sección ya dibujada × length —
      mismo criterio que el perímetro del estribo en steel_weight.

    "area_finish" — acabados por área (aplanados, piso, pintura,
    impermeabilizante), de la superficie real ya dibujada:
      {"type": "area_finish", "label": "Aplanado fino interior",
       "material": "aplanado", "handles": ["h1","h2"], "coats": 1,
       "thickness": 0.015, "waste_pct": 5.0}
      'material' agrupa el total (aplanado_m2, pintura_m2, etc.) — es
      texto libre, no una lista cerrada, porque el catálogo de acabados de
      un proyecto no lo fija esta tool. 'coats' (manos, default 1) escala
      el área a cubrir para materiales que se aplican en varias pasadas
      (pintura); 'thickness' es opcional y agrega el volumen (aplanados,
      pastas) además del área.

    Devuelve 'items' (una fila resuelta por concepto, con el detalle de la
    medición) y 'totals' (sumado por material: concreto_m3, ladrillo_piezas,
    mortero_m3, acero_kg, excavacion_m3, relleno_m3, cimbra_m2, y un par
    <material>_m2/<material>_m3 por cada 'material' usado en area_finish)."""
    if not items:
        raise ValueError("Hay que pasar al menos un item.")

    filas: list[dict[str, Any]] = []
    totales: dict[str, float] = {}

    def _sumar(clave: str, valor: float) -> None:
        totales[clave] = totales.get(clave, 0.0) + valor

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
            waste_pct = float(item.get("waste_pct", 0.0))
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            volumen = area * depth * (1 + waste_pct / 100.0)
            filas.append({"label": label, "type": tipo,
                          "areas": [round(a, 4) for a in areas],
                          "area": round(area, 4), "depth": depth,
                          "wastePct": waste_pct,
                          "volume": round(volumen, 4), "unit": "m3"})
            _sumar("concreto_m3", volumen)

        elif tipo == "concrete_mix":
            cement_per_m3 = float(item.get("cement_bags_per_m3", CEMENT_BAGS_PER_M3))
            sand_per_m3 = float(item.get("sand_m3_per_m3", SAND_M3_PER_M3))
            gravel_per_m3 = float(item.get("gravel_m3_per_m3", GRAVEL_M3_PER_M3))
            waste_pct = float(item.get("waste_pct", 0.0))

            areas = None
            if item.get("handles"):
                depth = item.get("depth")
                if not depth or depth <= 0:
                    raise ValueError(
                        f"'{label}': concrete_mix con 'handles' necesita "
                        "'depth' > 0 (la profundidad real que esta vista "
                        "no muestra).")
                areas = _areas(item["handles"], label)
                volumen = sum(areas) * depth
            else:
                volumen = item.get("volume")
                if not volumen or volumen <= 0:
                    raise ValueError(
                        f"'{label}': concrete_mix necesita 'handles'+"
                        "'depth' (para medirlo) o 'volume' (el m³ ya "
                        "calculado en otro item de concrete_volume -- no "
                        "se remide lo mismo dos veces).")

            volumen_merma = volumen * (1 + waste_pct / 100.0)
            bolsas = math.ceil(volumen_merma * cement_per_m3)
            arena = volumen_merma * sand_per_m3
            grava = volumen_merma * gravel_per_m3

            fila = {"label": label, "type": tipo, "volume": round(volumen, 4),
                    "wastePct": waste_pct,
                    "volumeWithWaste": round(volumen_merma, 4),
                    "cementBagsPerM3": cement_per_m3, "sandM3PerM3": sand_per_m3,
                    "gravelM3PerM3": gravel_per_m3, "cementBags": bolsas,
                    "sandM3": round(arena, 3), "gravelM3": round(grava, 3)}
            if areas is not None:
                fila["areas"] = [round(a, 4) for a in areas]
                fila["depth"] = item["depth"]
            filas.append(fila)
            _sumar("cemento_bolsas", bolsas)
            _sumar("arena_m3", arena)
            _sumar("grava_m3", grava)

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
            _sumar("ladrillo_piezas", piezas)

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
            waste_pct = float(item.get("waste_pct", 0.0))
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            wall_vol = area * thickness
            modulo = (brick_w + joint) * (brick_h + joint)
            piezas_sin_merma = area / modulo  # el mortero llena juntas reales, sin inflar por merma
            unit_brick_vol = brick_w * brick_h * brick_depth
            brick_vol = piezas_sin_merma * unit_brick_vol
            mortero = max(wall_vol - brick_vol, 0.0) * (1 + waste_pct / 100.0)
            filas.append({"label": label, "type": tipo,
                          "areas": [round(a, 4) for a in areas],
                          "wallArea": round(area, 4), "thickness": thickness,
                          "wallVolume": round(wall_vol, 4),
                          "piecesExact": round(piezas_sin_merma, 2),
                          "unitBrickVolume": round(unit_brick_vol, 6),
                          "brickVolume": round(brick_vol, 4),
                          "wastePct": waste_pct,
                          "mortarVolume": round(mortero, 4), "unit": "m3"})
            _sumar("mortero_m3", mortero)

        elif tipo == "steel_weight":
            peso = 0.0
            detalle: dict[str, Any] = {}
            count = item.get("count")
            length = item.get("length")

            long_bars = int(item.get("long_bars", 0) or 0)
            long_size = item.get("long_bar_size")
            stirrup_size = item.get("stirrup_size")
            stirrup_spacing = item.get("stirrup_spacing")
            mesh_kg_m2 = item.get("mesh_kg_m2")

            necesita_lineal = bool((long_bars and long_size) or
                                   (stirrup_size and stirrup_spacing))
            if necesita_lineal:
                if not count or count <= 0:
                    raise ValueError(f"'{label}': steel_weight necesita 'count' > 0.")
                if not length or length <= 0:
                    raise ValueError(f"'{label}': steel_weight necesita 'length' > 0.")

            if long_bars and long_size:
                if long_size not in REBAR_KG_M:
                    raise ValueError(
                        f"'{label}': long_bar_size {long_size!r} no está en la "
                        f"tabla ({sorted(REBAR_KG_M)}).")
                kg_m = REBAR_KG_M[long_size]
                effective_length = length
                lap_info: dict[str, Any] = {}
                commercial_length = item.get("commercial_length")
                if commercial_length and commercial_length > 0:
                    splices = max(math.ceil(length / commercial_length) - 1, 0)
                    if splices:
                        diam_mm = REBAR_DIAM_MM.get(long_size)
                        if diam_mm is None:
                            raise ValueError(
                                f"'{label}': no hay diámetro tabulado para "
                                f"{long_size!r}, no se puede calcular el traslape.")
                        lap_diam_factor = float(item.get("lap_diam_factor", 40.0))
                        lap_len = diam_mm / 1000.0 * lap_diam_factor
                        effective_length = length + splices * lap_len
                        lap_info = {
                            "commercialLength": commercial_length,
                            "splicesPerBar": splices,
                            "lapDiamFactor": lap_diam_factor,
                            "lapLengthEach": round(lap_len, 3),
                        }
                kg_long = count * long_bars * effective_length * kg_m
                peso += kg_long
                detalle["longitudinal"] = {
                    "bars": long_bars, "size": long_size,
                    "lengthEach": length,
                    "effectiveLength": round(effective_length, 3),
                    "kgM": kg_m, "kg": round(kg_long, 2), **lap_info}

            if stirrup_size and stirrup_spacing:
                if stirrup_size not in REBAR_KG_M:
                    raise ValueError(
                        f"'{label}': stirrup_size {stirrup_size!r} no está en la "
                        f"tabla ({sorted(REBAR_KG_M)}).")
                stirrup_handle = item.get("stirrup_handle")
                if stirrup_handle:
                    perim = _perimeter(stirrup_handle, label, "estribo")
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

            if mesh_kg_m2:
                handles = item.get("handles")
                if not handles:
                    raise ValueError(
                        f"'{label}': mesh_kg_m2 necesita 'handles' del área de "
                        "losa ya dibujada.")
                areas = _areas(handles, label)
                area = sum(areas)
                kg_mesh = area * float(mesh_kg_m2)
                peso += kg_mesh
                detalle["mesh"] = {"areas": [round(a, 4) for a in areas],
                                   "area": round(area, 4),
                                   "kgM2": float(mesh_kg_m2),
                                   "kg": round(kg_mesh, 2)}

            if not detalle:
                raise ValueError(
                    f"'{label}': steel_weight necesita longitudinales "
                    "(long_bars + long_bar_size), estribos (stirrup_size + "
                    "stirrup_spacing) o malla (mesh_kg_m2 + handles) — al menos "
                    "uno de los tres.")

            waste_pct = float(item.get("waste_pct", 0.0))
            peso *= (1 + waste_pct / 100.0)

            filas.append({"label": label, "type": tipo, "count": count,
                          "detail": detalle, "wastePct": waste_pct,
                          "weight": round(peso, 2), "unit": "kg"})
            _sumar("acero_kg", peso)

        elif tipo == "earthwork":
            mode = item.get("mode")
            if mode not in ("excavation", "backfill"):
                raise ValueError(
                    f"'{label}': earthwork necesita 'mode' = 'excavation' o "
                    f"'backfill', no {mode!r}.")
            depth = item.get("depth")
            if not depth or depth <= 0:
                raise ValueError(f"'{label}': earthwork necesita 'depth' > 0.")
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            excav_vol = area * depth

            if mode == "excavation":
                swell_pct = float(item.get("swell_pct", 0.0))
                fila = {"label": label, "type": tipo, "mode": mode,
                        "areas": [round(a, 4) for a in areas],
                        "area": round(area, 4), "depth": depth,
                        "volume": round(excav_vol, 4), "unit": "m3"}
                _sumar("excavacion_m3", excav_vol)
                if swell_pct:
                    volumen_esponjada = excav_vol * (1 + swell_pct / 100.0)
                    fila["swellPct"] = swell_pct
                    fila["volumeSwollen"] = round(volumen_esponjada, 4)
                    _sumar("excavacion_esponjada_m3", volumen_esponjada)
                filas.append(fila)
            else:  # backfill
                structure_volume = item.get("structure_volume")
                if structure_volume is None or structure_volume < 0:
                    raise ValueError(
                        f"'{label}': earthwork (backfill) necesita "
                        "'structure_volume' — el volumen YA calculado (p.ej. con "
                        "un item concrete_volume) que ocupa el mismo hueco.")
                relleno = max(excav_vol - float(structure_volume), 0.0)
                filas.append({"label": label, "type": tipo, "mode": mode,
                              "areas": [round(a, 4) for a in areas],
                              "area": round(area, 4), "depth": depth,
                              "excavationVolume": round(excav_vol, 4),
                              "structureVolume": float(structure_volume),
                              "volume": round(relleno, 4), "unit": "m3"})
                _sumar("relleno_m3", relleno)

        elif tipo == "formwork":
            waste_pct = float(item.get("waste_pct", 0.0))
            faces = int(item.get("faces", 1) or 1)
            handles = item.get("handles")
            if handles:
                areas = _areas(handles, label)
                area = sum(areas)
                area_total = area * faces * (1 + waste_pct / 100.0)
                filas.append({"label": label, "type": tipo, "source": "handles",
                              "areas": [round(a, 4) for a in areas],
                              "area": round(area, 4), "faces": faces,
                              "wastePct": waste_pct,
                              "areaTotal": round(area_total, 4), "unit": "m2"})
            else:
                section_handle = item.get("section_handle")
                count = item.get("count")
                length = item.get("length")
                if not section_handle or not count or not length:
                    raise ValueError(
                        f"'{label}': formwork necesita 'handles' (área de "
                        "contacto ya dibujada) o 'section_handle'+'count'+"
                        "'length' (perímetro de la sección medido × longitud).")
                perim = _perimeter(section_handle, label, "corte de sección")
                area = count * perim * length
                area_total = area * faces * (1 + waste_pct / 100.0)
                filas.append({"label": label, "type": tipo, "source": "section",
                              "count": count, "perimeter": round(perim, 3),
                              "length": length, "area": round(area, 4),
                              "faces": faces, "wastePct": waste_pct,
                              "areaTotal": round(area_total, 4), "unit": "m2"})
            _sumar("cimbra_m2", area_total)

        elif tipo == "area_finish":
            material = item.get("material")
            if not material:
                raise ValueError(
                    f"'{label}': area_finish necesita 'material' (p.ej. "
                    "'aplanado', 'piso', 'pintura', 'impermeabilizante') para "
                    "totalizar por concepto.")
            areas = _areas(item.get("handles") or [], label)
            area = sum(areas)
            coats = int(item.get("coats", 1) or 1)
            if coats <= 0:
                raise ValueError(f"'{label}': 'coats' tiene que ser >= 1.")
            waste_pct = float(item.get("waste_pct", 0.0))
            area_total = area * coats
            billable_area = area_total * (1 + waste_pct / 100.0)
            thickness = item.get("thickness")
            volumen = None
            if thickness:
                volumen = area * float(thickness) * (1 + waste_pct / 100.0)

            fila = {"label": label, "type": tipo, "material": material,
                    "areas": [round(a, 4) for a in areas], "area": round(area, 4),
                    "coats": coats, "wastePct": waste_pct,
                    "billableArea": round(billable_area, 4), "unit": "m2"}
            if volumen is not None:
                fila["thickness"] = float(thickness)
                fila["volume"] = round(volumen, 4)
            filas.append(fila)

            slug = str(material).strip().lower().replace(" ", "_")
            _sumar(f"{slug}_m2", billable_area)
            if volumen is not None:
                _sumar(f"{slug}_m3", volumen)

    return {
        "items": filas,
        "totals": {k: (round(v, 3) if isinstance(v, float) else v)
                  for k, v in totales.items()},
    }


def _suma_areas(areas: list[float]) -> str:
    """'0.375' si es un solo handle; '0.375+0.375+0.375=1.125' si son varios
    — la operación, no el total ya hecho.

    Con muchos handles del mismo elemento repetido (35 castillos, todos de
    0.0225 m²) escribir cada sumando aparte da una fila que necesita 50 m de
    columna para una tabla real -- inservible. Si son más de 4 y todas miden
    lo mismo (redondeado), se colapsa a 'Nx0.022 = total', que es como se
    anota a mano y ocupa lo que tiene que ocupar."""
    if len(areas) == 1:
        return f"{areas[0]:.3f}"
    primero = round(areas[0], 3)
    if len(areas) > 4 and all(round(a, 3) == primero for a in areas):
        return f"{len(areas)}x{primero:.3f} = {sum(areas):.3f}"
    return " + ".join(f"{a:.3f}" for a in areas) + f" = {sum(areas):.3f}"


def _merma(texto: str, waste_pct: float, resultado: str) -> str:
    """Agrega la merma a la operación solo si hay (0% no ensucia la fila)."""
    if waste_pct:
        return f"{texto} (+{waste_pct:g}% merma) = {resultado}"
    return f"{texto} = {resultado}"


def _fmt_item(item: dict[str, Any]) -> str:
    """Cómo se llegó al número — la tabla muestra la operación completa,
    no el resultado ya sumado."""
    tipo = item["type"]

    if tipo == "concrete_volume":
        base = f"{_suma_areas(item['areas'])} m² × {item['depth']:.2f} m"
        return _merma(base, item["wastePct"], f"{item['volume']:.3f} m³")

    if tipo == "concrete_mix":
        if "areas" in item:
            base = f"{_suma_areas(item['areas'])} m² × {item['depth']:.2f} m"
        else:
            base = f"{item['volume']:.3f} m³ (ya calculado)"
        vol = _merma(base, item["wastePct"], f"{item['volumeWithWaste']:.3f} m³")
        return (f"{vol} × {item['cementBagsPerM3']:g} bolsas/m³ = "
                f"{item['cementBags']} bolsas ; × {item['sandM3PerM3']:g} "
                f"m³ arena/m³ = {item['sandM3']:.3f} m³ arena ; × "
                f"{item['gravelM3PerM3']:g} m³ grava/m³ = "
                f"{item['gravelM3']:.3f} m³ grava")

    if tipo == "brick_count":
        modulo_op = (f"({item['brickW']:.3f}+{item['joint']:.3f})×"
                    f"({item['brickH']:.3f}+{item['joint']:.3f})="
                    f"{item['moduleArea']:.4f}")
        return (f"{_suma_areas(item['areas'])} m² / {modulo_op} m² "
                f"(+{item['wastePct']:g}% merma) = {item['pieces']} pzas")

    if tipo == "mortar_volume":
        base = (f"{_suma_areas(item['areas'])} m² × {item['thickness']:.2f} m = "
                f"{item['wallVolume']:.3f} m³ muro − ({item['piecesExact']:.1f} "
                f"pzas × {item['unitBrickVolume']:.5f} m³/pza = "
                f"{item['brickVolume']:.3f} m³ ladrillo)")
        return _merma(base, item["wastePct"], f"{item['mortarVolume']:.3f} m³")

    if tipo == "earthwork":
        if item["mode"] == "excavation":
            base = (f"{_suma_areas(item['areas'])} m² × {item['depth']:.2f} m = "
                    f"{item['volume']:.3f} m³")
            if item.get("swellPct"):
                base += (f" (+{item['swellPct']:g}% esponjamiento = "
                         f"{item['volumeSwollen']:.3f} m³ para acarreo)")
            return base
        return (f"{_suma_areas(item['areas'])} m² × {item['depth']:.2f} m = "
                f"{item['excavationVolume']:.3f} m³ excavación − "
                f"{item['structureVolume']:.3f} m³ estructura = "
                f"{item['volume']:.3f} m³")

    if tipo == "formwork":
        if item["source"] == "handles":
            base = f"{_suma_areas(item['areas'])} m² × {item['faces']} cara(s)"
        else:
            base = (f"{item['count']}pzas×{item['perimeter']:.2f}m×"
                    f"{item['length']:.2f}m × {item['faces']} cara(s)")
        return _merma(base, item["wastePct"], f"{item['areaTotal']:.3f} m²")

    if tipo == "area_finish":
        base = f"{_suma_areas(item['areas'])} m² × {item['coats']} mano(s)"
        texto = _merma(base, item["wastePct"], f"{item['billableArea']:.3f} m²")
        if "volume" in item:
            texto += f", espesor {item['thickness']:.3f} m = {item['volume']:.3f} m³"
        return texto

    # steel_weight
    partes = []
    for clave, d in item["detail"].items():
        if clave == "longitudinal":
            if d.get("splicesPerBar"):
                partes.append(
                    f"{item['count']}pzas×{d['bars']}{d['size']}×"
                    f"({d['lengthEach']:.2f}m+{d['splicesPerBar']}emp.×"
                    f"{d['lapLengthEach']:.2f}m={d['effectiveLength']:.2f}m)×"
                    f"{d['kgM']:.2f}kg/m={d['kg']:.2f}kg")
            else:
                partes.append(f"{item['count']}pzas×{d['bars']}{d['size']}×"
                              f"{d['lengthEach']:.2f}m×{d['kgM']:.2f}kg/m="
                              f"{d['kg']:.2f}kg")
        elif clave == "estribos":
            partes.append(f"{item['count']}pzas×{d['count']}E{d['size']}"
                          f"(@{d['spacing']:.2f}m en {d['lengthTotal']:.2f}m)×"
                          f"{d['perimeter']:.2f}m×{d['kgM']:.2f}kg/m="
                          f"{d['kg']:.2f}kg")
        else:  # mesh
            partes.append(f"{_suma_areas(d['areas'])} m²×{d['kgM2']:.2f}kg/m²="
                          f"{d['kg']:.2f}kg")
    texto = " + ".join(partes)
    if item["wastePct"]:
        texto += f" (+{item['wastePct']:g}% merma)"
    return f"{texto} = {item['weight']:.1f} kg"


_ETIQUETAS_TOTALES = {
    "concreto_m3": "TOTAL CONCRETO", "ladrillo_piezas": "TOTAL LADRILLO",
    "mortero_m3": "TOTAL MORTERO", "acero_kg": "TOTAL ACERO",
    "excavacion_m3": "TOTAL EXCAVACIÓN",
    "excavacion_esponjada_m3": "TOTAL EXCAVACIÓN (ESPONJADA, ACARREO)",
    "relleno_m3": "TOTAL RELLENO", "cimbra_m2": "TOTAL CIMBRA",
    "cemento_bolsas": "TOTAL CEMENTO",
}
_UNIDADES_TOTALES = {
    "concreto_m3": "m³", "ladrillo_piezas": "pzas",
    "mortero_m3": "m³", "acero_kg": "kg",
    "excavacion_m3": "m³", "excavacion_esponjada_m3": "m³",
    "relleno_m3": "m³", "cimbra_m2": "m²",
    "cemento_bolsas": "bolsas",
}


def _etiqueta_unidad_total(clave: str) -> tuple[str, str]:
    """Nombre y unidad de una fila de 'totals' — mismo criterio para la tabla
    dibujada y para el CSV, así no se puede leer distinto en cada salida."""
    if clave in _ETIQUETAS_TOTALES:
        return _ETIQUETAS_TOTALES[clave], _UNIDADES_TOTALES[clave]
    if clave.endswith("_m2"):
        return "TOTAL " + clave[:-3].upper().replace("_", " "), "m²"
    if clave.endswith("_m3"):
        return "TOTAL " + clave[:-3].upper().replace("_", " "), "m³"
    return clave.upper(), ""


# type -> (campo del resultado con la cantidad principal, su unidad)
_CAMPO_CANTIDAD = {
    "concrete_volume": ("volume", "m3"),
    "concrete_mix": ("cementBags", "bolsas"),
    "brick_count": ("pieces", "pzas"),
    "mortar_volume": ("mortarVolume", "m3"),
    "steel_weight": ("weight", "kg"),
    "earthwork": ("volume", "m3"),
    "formwork": ("areaTotal", "m2"),
    "area_finish": ("billableArea", "m2"),
}


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

    for clave, valor in result["totals"].items():
        etiqueta, unidad = _etiqueta_unidad_total(clave)
        rows.append([etiqueta, f"{valor:g} {unidad}".strip()])

    return ann_mod.create_table(
        x=x, y=y, rows=rows, col_widths=col_widths, row_height=0.4,
        text_height=text_height, title=title, header=True, layer=layer)


def export_quantities_csv(result: dict[str, Any], path: str) -> dict[str, Any]:
    """Vuelca 'items'/'totals' de calculate_quantities a un .csv real, para
    armar el presupuesto en Excel/Sheets afuera de AutoCAD — no vuelve a
    calcular nada, escribe los mismos números que ya devolvió la tool.

    No necesita AutoCAD abierto: es un volcado del resultado en memoria, así
    que se puede llamar aunque el plugin no esté conectado.

    Columnas: CONCEPTO, TIPO, MATERIAL (vacío salvo en area_finish),
    MEDICIÓN Y CÁLCULO (la misma fórmula que muestra create_quantities_table,
    para poder verificar el número sin volver al DWG), CANTIDAD, UNIDAD. Al
    final, una fila en blanco y las filas de 'totals'.

    Si un item de area_finish trae 'thickness' (y por lo tanto 'volume'),
    se agrega una fila extra con el volumen — la cantidad por área y la
    cantidad por volumen son dos renglones de presupuesto distintos."""
    filas: list[list[Any]] = [
        ["CONCEPTO", "TIPO", "MATERIAL", "MEDICIÓN Y CÁLCULO", "CANTIDAD", "UNIDAD"]]

    for item in result["items"]:
        campo, unidad = _CAMPO_CANTIDAD[item["type"]]
        material = item.get("material", "")
        filas.append([item["label"], item["type"], material,
                      _fmt_item(item), item[campo], unidad])
        if item["type"] == "area_finish" and "volume" in item:
            filas.append([f"{item['label']} (volumen)", item["type"], material,
                          _fmt_item(item), item["volume"], "m3"])
        if item["type"] == "concrete_mix":
            filas.append([f"{item['label']} (arena)", item["type"], material,
                          _fmt_item(item), item["sandM3"], "m3"])
            filas.append([f"{item['label']} (grava)", item["type"], material,
                          _fmt_item(item), item["gravelM3"], "m3"])

    filas.append([])
    filas.append(["TOTALES", "", "", "", "", ""])
    for clave, valor in result["totals"].items():
        etiqueta, unidad = _etiqueta_unidad_total(clave)
        filas.append([etiqueta, "", "", "", valor, unidad])

    # utf-8-sig: Excel en Windows detecta el BOM y no rompe los acentos
    # (CONCEPCIÓN, m², etc.) como pasa abriendo un .csv en utf-8 a secas.
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerows(filas)

    return {"path": path, "rows": len(result["items"]),
           "totals": len(result["totals"])}
