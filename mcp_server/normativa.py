"""País y normativa del proyecto.

Las reglas y valores que traen las tools de proyecto (mínimos de recintos,
instalación eléctrica, hidráulica, sanitaria, cimentación) están codificadas
con la normativa de MÉXICO (NOM-001-SEDE-2012, INIFED, Reglamento de
Construcciones y NTC de la CDMX). Eso es un dato del proyecto, no un
supuesto que se pueda dar por bueno: un plano para Perú o Colombia con notas
de norma mexicana es un plano con la norma equivocada.

Este módulo hace dos cosas:

  1. `resolver(pais)` dice qué normativa hay codificada para ese país y, si
     no la hay, lo dice con todas las letras y orienta a qué norma local
     consultar (orientativo: el usuario verifica nombre y versión vigente).
  2. `con_pais` es un decorador para las tools que dependen de norma: agrega
     los parámetros `country` y `accept_reference`, anota en el resultado
     qué normativa se aplicó, y se NIEGA a dibujar con la norma mexicana en
     un proyecto de otro país salvo que se acepte explícitamente como
     referencia.

Lo que NO hace: inventar los valores de otro país. Para eso hay que
codificar su perfil (ver PERFILES) con la fuente en la mano.
"""
from __future__ import annotations

import functools
import inspect
import typing
import unicodedata
from typing import Any, Callable, Optional

MX = "MX"

# Codificada = los valores de las tools salen de esa normativa.
PERFILES: dict[str, dict[str, Any]] = {
    "MX": {
        "nombre": "México",
        "estado": "codificada",
        "normas": [
            "NOM-001-SEDE-2012 (instalaciones eléctricas)",
            "INIFED (aparatos sanitarios y espacios educativos)",
            "Reglamento de Construcciones de la CDMX (RCDF) y sus NTC",
            "NTC de Proyecto Arquitectónico, Mampostería y Cimentaciones (CDMX)",
        ],
        "alcance": "Reglas de vivienda de la CDMX; fuera de la CDMX el "
                   "reglamento municipal o estatal puede pedir otros valores.",
    },
    # Sin codificar: solo orientación de qué buscar. Verificar versión vigente.
    "PE": {"nombre": "Perú", "estado": "no_codificada", "orientacion": [
        "RNE: A.010 (condiciones generales de diseño), A.020 (vivienda)",
        "RNE: EM.010 (instalaciones eléctricas), IS.010 (instalaciones sanitarias)",
        "RNE: E.050 (suelos y cimentaciones), E.060 (concreto armado), E.070 (albañilería)"]},
    "CO": {"nombre": "Colombia", "estado": "no_codificada", "orientacion": [
        "NSR-10 (sismo resistencia), RETIE (eléctrico), RETILAP (iluminación)",
        "Norma NTC 1500 (código de fontanería) y POT/normas urbanas del municipio"]},
    "AR": {"nombre": "Argentina", "estado": "no_codificada", "orientacion": [
        "AEA 90364 (instalaciones eléctricas), CIRSOC 201 (hormigón armado)",
        "Código de edificación del municipio"]},
    "CL": {"nombre": "Chile", "estado": "no_codificada", "orientacion": [
        "OGUC (Ordenanza General de Urbanismo y Construcciones)",
        "NCh Elec. 4/2003 (instalaciones eléctricas), NCh 430 (hormigón armado)"]},
    "ES": {"nombre": "España", "estado": "no_codificada", "orientacion": [
        "CTE (Código Técnico de la Edificación) y sus DB",
        "REBT (Reglamento Electrotécnico para Baja Tensión)"]},
    "US": {"nombre": "Estados Unidos", "estado": "no_codificada", "orientacion": [
        "IRC / IBC (códigos de construcción) y el código local de la jurisdicción",
        "NEC (NFPA 70) para eléctrica; IPC / UPC para plomería; ACI 318 para concreto"]},
}

_ALIAS = {
    "mexico": "MX", "mx": "MX", "mex": "MX", "cdmx": "MX",
    "peru": "PE", "pe": "PE",
    "colombia": "CO", "co": "CO",
    "argentina": "AR", "ar": "AR",
    "chile": "CL", "cl": "CL",
    "espana": "ES", "es": "ES", "spain": "ES",
    "estados unidos": "US", "eeuu": "US", "ee.uu.": "US", "usa": "US",
    "us": "US", "united states": "US",
}


def _limpio(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def paises() -> list[dict[str, str]]:
    return [{"codigo": k, "pais": v["nombre"], "estado": v["estado"]}
            for k, v in PERFILES.items()]


def pregunta() -> str:
    return ("¿De qué país es el proyecto? Las tools de proyecto traen la "
            "normativa de México; para otro país hay que decirlo y usar sus "
            "valores locales.")


def resolver(pais: Optional[str]) -> dict[str, Any]:
    """Qué normativa corresponde a 'pais'. Nunca inventa: si no hay perfil
    codificado, devuelve estado 'no_codificada' y la advertencia."""
    if pais is None or not str(pais).strip():
        return {
            "codigo": None, "pais": None, "estado": "sin_pais",
            "aplicada": "México (referencia por defecto)",
            "advertencia": "No se indicó el país. " + pregunta(),
        }
    codigo = _ALIAS.get(_limpio(str(pais)))
    if codigo is None:
        nombre = str(pais).strip()
        return {
            "codigo": None, "pais": nombre, "estado": "no_codificada",
            "aplicada": "México (solo referencia)",
            "advertencia": (
                f"No hay normativa de {nombre} codificada: los valores son "
                "los de México y NO valen para ese país. Hay que pedirle al "
                "usuario los valores de su normativa local."),
            "orientacion": [],
        }
    p = PERFILES[codigo]
    if p["estado"] == "codificada":
        return {"codigo": codigo, "pais": p["nombre"], "estado": "codificada",
                "aplicada": p["nombre"], "normas": p["normas"],
                "alcance": p.get("alcance", ""), "advertencia": None}
    return {
        "codigo": codigo, "pais": p["nombre"], "estado": "no_codificada",
        "aplicada": "México (solo referencia)",
        "advertencia": (
            f"La normativa de {p['nombre']} no está codificada en este "
            "servidor: los valores que devuelve la tool son los de México y "
            f"NO son válidos para {p['nombre']}. Decirle al usuario, y pedirle "
            "los mínimos y criterios de su norma local para aplicarlos."),
        "orientacion": p["orientacion"],
    }


NOTA_DOC = (
    "\n\n    NORMATIVA: los valores de esta tool son de MÉXICO. Preguntale al "
    "usuario de qué país es el proyecto y pasalo en `country` (p.ej. "
    "'México', 'Perú'). Para un país sin normativa codificada la tool lo "
    "avisa en `normativa` y NO dibuja salvo accept_reference=True (que el "
    "usuario acepte usar la norma mexicana solo como referencia)."
)


def con_pais(dibuja: Optional[str] = None) -> Callable:
    """Decorador para tools que dependen de norma.

    dibuja: nombre del parámetro booleano que decide si la tool dibuja
    (p.ej. 'draw', default True). None = la tool nunca dibuja.
    """
    def deco(fn: Callable) -> Callable:
        sig = inspect.signature(fn)
        draw_default = True
        if dibuja and dibuja in sig.parameters:
            d = sig.parameters[dibuja].default
            draw_default = True if d is inspect.Parameter.empty else bool(d)

        @functools.wraps(fn)
        def envoltura(*args: Any, **kwargs: Any) -> Any:
            country = kwargs.pop("country", None)
            acepta = bool(kwargs.pop("accept_reference", False))
            info = resolver(country)
            dibujara = False
            if dibuja:
                bound_draw = kwargs.get(dibuja, None)
                dibujara = draw_default if bound_draw is None else bool(bound_draw)
            if (dibujara and info["estado"] == "no_codificada" and not acepta):
                raise ValueError(
                    info["advertencia"]
                    + " No se dibuja con notas de norma ajenas: o el usuario "
                    "pasa los valores de su país, o acepta la norma mexicana "
                    "solo como referencia (accept_reference=True), o usá "
                    "draw=False para ver el proyecto sin dibujarlo.")
            res = fn(*args, **kwargs)
            if isinstance(res, dict):
                res = dict(res)
                res["normativa"] = info
                if info["advertencia"]:
                    avisos = list(res.get("warnings") or [])
                    avisos.append(info["advertencia"])
                    res["warnings"] = avisos
            return res

        extra = [
            inspect.Parameter("country", inspect.Parameter.KEYWORD_ONLY,
                              default=None, annotation=Optional[str]),
            inspect.Parameter("accept_reference", inspect.Parameter.KEYWORD_ONLY,
                              default=False, annotation=bool),
        ]
        # Las anotaciones de la tool vienen como texto (from __future__):
        # se resuelven acá, contra el módulo de la tool, porque pydantic
        # las evaluaría contra el de este decorador.
        try:
            hints = typing.get_type_hints(fn)
        except Exception:                       # noqa: BLE001
            hints = {}
        params = [p.replace(annotation=hints.get(p.name, p.annotation))
                  for p in sig.parameters.values()
                  if p.kind != inspect.Parameter.VAR_KEYWORD] + extra
        envoltura.__signature__ = sig.replace(
            parameters=params,
            return_annotation=hints.get("return", sig.return_annotation))  # type: ignore[attr-defined]
        envoltura.__doc__ = (fn.__doc__ or "") + NOTA_DOC
        return envoltura
    return deco
