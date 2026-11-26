"""Base de normas CITABLES para el modo análisis (tool `consultar_norma`).

El modo análisis tiene que fundamentar cada observación. El peor error posible
es una cita falsa con apariencia de verdadera («según el art. 123 de la NTC...»
cuando ese artículo no dice eso o no existe). Por eso el modelo NO cita de
memoria: pregunta aquí, y aquí solo hay lo que el sistema tiene respaldado.

Cada entrada dice su ESTATUS, y el modelo lo tiene que decir igual:
  - "norma":          el texto oficial respalda el valor; se cita con su artículo.
  - "práctica":       criterio usual de proyecto en México, no obligación normativa.
  - "sin verificar":  el sistema lo usa, pero no se encontró el texto oficial que
                      lo respalde: se dice así y se recomienda verificarlo.

Los valores salen de las MISMAS constantes que usan las tools de proyecto
(instalaciones.NORMA, rules.MINIMOS): si una cambia, la cita cambia con ella.
Fuera de la CDMX manda el reglamento del estado o municipio: se advierte siempre.
"""
from __future__ import annotations

import unicodedata
from typing import Any

import instalaciones
import rules

NOM = "NOM-001-SEDE-2012 (Instalaciones eléctricas, utilización)"
NOM_URL = "https://sidof.segob.gob.mx/notas/docFuente/5280607"
NTC = "NTC para el Proyecto Arquitectónico CDMX (GODF 08-02-2011) §6.1"
NTC_URL = "https://paot.mx/centro/leyes/df/pdf/GODF/GODF_08_02_2011_02.pdf"
INIFED = "INIFED, Normas y Especificaciones Vol. 5 Tomo II, Instalaciones Hidrosanitarias (rev. 2022)"

AVISO_LOCAL = ("Las referencias de la CDMX e INIFED son la base del sistema; fuera de la CDMX manda el reglamento "
               "de construcción del estado o municipio. Verifica la versión vigente antes de tomar una decisión.")

_N = instalaciones.NORMA


def _e(id_: str, tema: str, regla: str, fuente: str, articulo: str, estatus: str = "norma",
       url: str = "", claves: str = "") -> dict[str, Any]:
    return {"id": id_, "tema": tema, "regla": regla, "fuente": fuente, "articulo": articulo,
            "estatus": estatus, "url": url, "claves": claves}


ENTRADAS: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- eléctrica
    _e("elec-contacto-distancia", "eléctrica",
       f"Ningún punto a lo largo del muro puede quedar a más de {_N['contacto_max_m']} m de un contacto.",
       NOM, "210-52(a)(1)", url=NOM_URL, claves="contactos separación muro distancia"),
    _e("elec-muro-minimo", "eléctrica",
       f"Cuenta para la regla de contactos todo muro de {_N['muro_min_contacto_m']} m o más.",
       NOM, "210-52(a)(2)", url=NOM_URL, claves="contactos muro"),
    _e("elec-cubierta-cocina", "eléctrica",
       f"Sobre la cubierta de cocina, ningún punto a más de {_N['cubierta_max_m']} m de un contacto.",
       NOM, "210-52(c)(1)", url=NOM_URL, claves="cocina cubierta barra contactos"),
    _e("elec-lavabo", "eléctrica",
       f"En el baño, contacto a no más de {_N['lavabo_contacto_m']} m del lavabo.",
       NOM, "210-52(d)", url=NOM_URL, claves="baño lavabo contacto"),
    _e("elec-pasillo", "eléctrica",
       f"Un pasillo de {_N['pasillo_min_m']} m o más lleva al menos un contacto.",
       NOM, "210-52(h)", url=NOM_URL, claves="pasillo contacto"),
    _e("elec-exterior", "eléctrica",
       f"Contacto exterior al frente y atrás de la vivienda, a no más de {_N['exterior_max_altura_m']} m de altura.",
       NOM, "210-52(e)", url=NOM_URL, claves="exterior contacto fachada patio"),
    _e("elec-alumbrado-va", "eléctrica",
       f"Carga de alumbrado en vivienda: {_N['va_m2_alumbrado']:.0f} VA/m²; incluye los contactos de uso general.",
       NOM, "Tabla 220-12 y 220-14(j)", url=NOM_URL, claves="carga alumbrado va m2 demanda"),
    _e("elec-circuito-20a", "eléctrica",
       f"Circuitos de pequeños aparatos y de lavado: {_N['va_circuito_20a']:.0f} VA cada uno.",
       NOM, "220-52(a)/(b)", url=NOM_URL, claves="circuito cocina lavado pequeños aparatos"),
    _e("elec-demanda", "eléctrica",
       f"Factor de demanda del alumbrado: primeros {_N['demanda_100_va']:.0f} VA al 100 %, de ahí a 120 000 VA al "
       f"{_N['demanda_resto'] * 100:.0f} %.",
       NOM, "220-42", url=NOM_URL, claves="demanda carga factor"),
    _e("elec-carga-continua", "eléctrica",
       f"Una carga continua no debe pasar del {_N['factor_continua'] * 100:.0f} % de la capacidad del circuito.",
       NOM, "210-19(a) y 210-20(a)", url=NOM_URL, claves="carga continua capacidad protección"),
    _e("elec-calibre", "eléctrica",
       "Conductor mínimo: calibre 14 AWG en circuito de 15 A y 12 AWG en circuito de 20 A.",
       NOM, "240-4(d) (equivalente a NEC 240.4(D))", estatus="sin verificar", url=NOM_URL,
       claves="calibre conductor awg cable 15a 20a"),
    _e("elec-tension", "eléctrica",
       f"Tensión nominal de cálculo: {_N['tension_v']:.0f} V (CFE suministra 127 V).",
       NOM, "texto de la norma", estatus="sin verificar", url=NOM_URL, claves="tensión voltaje 127 120"),

    # ---------------------------------------------------------------- sanitaria / hidráulica
    _e("san-pendiente", "sanitaria",
       f"Pendiente mínima de las tuberías de desagüe: {_N['pendiente_drenaje'] * 100:.0f} %.",
       NTC, "6.1.3.1", url=NTC_URL, claves="pendiente drenaje desagüe tubería"),
    _e("san-desague-minimo", "sanitaria",
       f"Ninguna tubería de desagüe menor de {_N['desague_min_mm']} mm.",
       NTC, "6.1.3.1", url=NTC_URL, claves="diámetro desagüe mínimo"),
    _e("san-albanal", "sanitaria",
       f"Albañal fuera del predio: diámetro mínimo {_N['albanal_min_mm'] / 10:.0f} cm.",
       NTC, "6.1.3.2-I", url=NTC_URL, claves="albañal diámetro"),
    _e("san-registros", "sanitaria",
       f"Registros a no más de {_N['registro_max_m']:.0f} m entre sí y en cada cambio de dirección del albañal.",
       NTC, "6.1.3.2-V", url=NTC_URL, claves="registro distancia cambio dirección"),
    _e("san-registro-medida", "sanitaria",
       f"Registros de 40 × 60 cm hasta {_N['registro_40x60_hasta_m']:.0f} m de profundidad.",
       NTC, "6.1.3.2-VI", url=NTC_URL, claves="registro dimensión profundidad"),
    _e("san-ventilador", "sanitaria",
       f"Tubo ventilador de al menos {_N['ventilador_min_mm'] / 10:.0f} cm en el origen del albañal.",
       NTC, "6.1.3.2-III", url=NTC_URL, claves="ventilación tubo ventilador"),
    _e("hid-tinaco", "hidráulica",
       f"La salida del tinaco, al menos {_N['tinaco_sobre_regadera_m']:.0f} m sobre la regadera más alta.",
       NTC, "6.1.2", url=NTC_URL, claves="tinaco altura regadera presión"),
    _e("hid-retorno-ac", "hidráulica",
       f"Retorno de agua caliente cuando el recorrido pasa de {_N['retorno_ac_m']:.0f} m.",
       INIFED, "§2.8", claves="agua caliente retorno recorrido"),
    _e("san-descarga-muebles", "sanitaria",
       "Diámetro mínimo de descarga: " + ", ".join(f"{k} {v} mm" for k, v in instalaciones.DESCARGA_MM.items())
       + " (el fregadero no figura en la tabla: 50 mm es práctica).",
       INIFED, "Tabla 3.1", claves="descarga mueble wc lavabo regadera diámetro"),
    _e("san-ramal", "sanitaria",
       "Diámetro del ramal horizontal según unidades de descarga acumuladas: "
       + ", ".join(f"hasta {ud} UD → {mm} mm" for ud, mm in instalaciones.DIAMETRO_RAMAL) + ".",
       INIFED, "Tabla 3.3", claves="ramal unidades descarga diámetro"),
]

# ---------------------------------------------------------------- arquitectura: mínimos de recintos
# rules.MINIMOS los usa check_geometry, pero el sistema NO tiene cargado el artículo que los respalde: se dicen
# como criterio del sistema, con la referencia a consultar. Inventarles un artículo sería lo peor que puede pasar.
for _clave, _m in rules.MINIMOS.items():
    ENTRADAS.append(_e(
        "arq-minimo-" + _clave, "arquitectura",
        f"{_m['nombre'].capitalize()}: lado útil mínimo {_m['lado']:.2f} m"
        + (f" y superficie mínima {_m['area']:.2f} m²." if _m.get("area") else "."),
        "Criterio del sistema (check_geometry)",
        "sin artículo cargado: comparar con la tabla de dimensiones mínimas de la NTC para el Proyecto "
        "Arquitectónico (CDMX) o el reglamento local",
        estatus="sin verificar", claves="dimensión mínima superficie área recinto " + _m["nombre"]))


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def consultar(tema: str = "", texto: str = "", limite: int = 12) -> dict[str, Any]:
    """Las entradas que coinciden con el tema y/o las palabras del texto."""
    t = _sin_acentos(tema or "")
    palabras = [p for p in _sin_acentos(texto or "").replace(",", " ").split() if len(p) > 2]
    resultado = []
    for e in ENTRADAS:
        if t and t not in _sin_acentos(e["tema"]):
            continue
        heno = _sin_acentos(" ".join((e["regla"], e["claves"], e["articulo"], e["tema"])))
        puntos = sum(1 for p in palabras if p in heno)
        if palabras and puntos == 0:
            continue
        resultado.append((puntos, e))
    resultado.sort(key=lambda x: -x[0])
    encontradas = [e for _, e in resultado[:max(1, min(limite, 40))]]
    return {
        "encontradas": encontradas,
        "count": len(encontradas),
        "temas": sorted({e["tema"] for e in ENTRADAS}),
        "como_citar": ("Cita SOLO estas entradas y con su estatus: «norma» con fuente y artículo; «práctica» como "
                       "criterio usual (no obligación); «sin verificar» diciendo que no hay texto oficial cargado y "
                       "que conviene verificarlo. Si lo que necesitas no aparece, dilo así: NO cites un artículo de "
                       "memoria."),
        "aviso": AVISO_LOCAL,
    }
