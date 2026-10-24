"""Re-encuadrar el viewport de una lámina sobre una caja del modelo.

Cuando un detalle se redibuja (otra zapata, otra pilastra) su caja en el modelo cambia de tamaño o de lugar y el
viewport que lo mostraba queda cortando el dibujo o enseñando un pedazo vecino. Reencuadrarlo era un script
suelto: leer las propiedades del viewport, desbloquearlo, cambiar centro y ancho, volver a bloquearlo. Acá es
una operación con reglas fijas, la misma siempre:

  - el centro de la vista va al centro de la caja;
  - la escala no se toca, salvo que se pida una (scale_denominator + model_units_per_mm);
  - 'resize': 'none' deja el tamaño del viewport; 'grow' lo agranda SOLO si la caja no entra (con su margen al crecer; nunca lo achica,
    para no mover el resto de la lámina); 'fit' lo deja justo a la caja más el margen;
  - el viewport vuelve a quedar bloqueado como estaba, y el layout activo vuelve al de antes.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

import autocad_client as acad
import propiedades as prop

NOMBRES = ["Width", "Height", "ViewCenter", "CustomScale", "CenterPoint", "Locked"]


class ViewportError(ValueError):
    pass


def _leer(handle: str) -> dict[str, Any]:
    return prop.get_properties([handle], NOMBRES)["objects"][handle]["properties"]


def _ventana(p: dict[str, Any]) -> tuple[float, float, float, float]:
    """Zona del MODELO que muestra el viewport: x0, y0, x1, y1."""
    cs = float(p["CustomScale"])
    cx, cy = p["ViewCenter"][0], p["ViewCenter"][1]
    hw, hh = float(p["Width"]) / cs / 2.0, float(p["Height"]) / cs / 2.0
    return cx - hw, cy - hh, cx + hw, cy + hh


def _solape(a: Sequence[float], b: Sequence[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _buscar(layout: str, caja: Sequence[float]) -> str:
    """El viewport del layout que mejor cubre la caja (el 'overall' del espacio papel no cuenta)."""
    ents = acad.call("select_entities", {"x1": None, "y1": None, "x2": None, "y2": None, "layers": None,
                                         "types": ["Viewport"], "mode": "inside"}).get("entities", [])
    candidatos = []
    for e in ents[1:]:
        try:
            p = _leer(e["handle"])
        except Exception:
            continue
        candidatos.append((_solape(_ventana(p), caja), e["handle"]))
    if not candidatos:
        raise ViewportError(f"El layout '{layout}' no tiene viewports además del general.")
    candidatos.sort(reverse=True)
    if candidatos[0][0] <= 0:
        raise ViewportError("Ningún viewport del layout muestra esa caja: pasá 'handle' del que querés reencuadrar. "
                            f"Viewports: {[h for _, h in candidatos]}")
    if len(candidatos) > 1 and abs(candidatos[0][0] - candidatos[1][0]) < 1e-9:
        raise ViewportError("Dos viewports cubren la caja por igual: pasá 'handle'. "
                            f"Candidatos: {[h for _, h in candidatos[:2]]}")
    return candidatos[0][1]


def refit_viewport(layout: str, box: Sequence[float], handle: Optional[str] = None,
                   scale_denominator: Optional[float] = None, model_units_per_mm: Optional[float] = None,
                   resize: str = "grow", margin: float = 0.25) -> dict[str, Any]:
    """Centra el viewport en la caja [x0, y0, x1, y1] del modelo. Devuelve antes, después y si la caja entra."""
    if len(box) != 4 or not (box[2] > box[0] and box[3] > box[1]):
        raise ViewportError("box tiene que ser [x0, y0, x1, y1] con x1 > x0 e y1 > y0 (unidades del modelo).")
    if resize not in ("none", "grow", "fit"):
        raise ViewportError("resize: 'none', 'grow' o 'fit'.")
    if (scale_denominator is None) != (model_units_per_mm is None):
        raise ViewportError("scale_denominator y model_units_per_mm van los dos o ninguno "
                            "(1000 dibujando en metros: sin eso la escala sale mal en silencio).")
    previo = None
    try:
        previo = acad.call("get_editor_state", {}).get("layout")
    except Exception:
        pass
    acad.call("set_current_layout", {"name": layout})
    try:
        h = handle or _buscar(layout, box)
        antes = _leer(h)
        cs = float(antes["CustomScale"])
        if scale_denominator is not None:
            cs = float(model_units_per_mm) / float(scale_denominator)      # mm de papel por unidad del modelo
        bw, bh = box[2] - box[0], box[3] - box[1]
        necesita_w, necesita_h = (bw + 2 * margin) * cs, (bh + 2 * margin) * cs
        cambios: dict[str, Any] = {}
        if resize == "fit":
            cambios = {"Width": round(necesita_w, 3), "Height": round(necesita_h, 3)}
        elif resize == "grow":              # solo si la caja misma no entra; al crecer, deja el margen
            if bw * cs > float(antes["Width"]) + 1e-6:
                cambios["Width"] = round(necesita_w, 3)
            if bh * cs > float(antes["Height"]) + 1e-6:
                cambios["Height"] = round(necesita_h, 3)
        bloqueado = prop_bool(antes.get("Locked", True))
        prop.set_properties([h], {"Locked": False})
        try:
            if cambios or scale_denominator is not None:
                prop.set_properties([h], {**cambios, "CustomScale": cs})
            prop.set_properties([h], {"CustomScale": cs, "ViewCenter": [round((box[0] + box[2]) / 2, 4),
                                                                         round((box[1] + box[3]) / 2, 4)]})
        finally:
            prop.set_properties([h], {"Locked": bloqueado})
        despues = _leer(h)
        entra = necesita_w - 2 * margin * cs <= float(despues["Width"]) + 1e-6 and \
            necesita_h - 2 * margin * cs <= float(despues["Height"]) + 1e-6
        return {"handle": h, "layout": layout, "antes": antes, "despues": despues, "caja_entra": entra,
                "caja_en_papel_mm": [round(bw * cs, 1), round(bh * cs, 1)]}
    finally:
        if previo and previo != layout:
            acad.call("set_current_layout", {"name": previo})


def prop_bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "", "no")
    return bool(v)
