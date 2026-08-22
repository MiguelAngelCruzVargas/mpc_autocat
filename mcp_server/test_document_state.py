"""Tests de que cambiar de dibujo OLVIDA lo que se cacheó del anterior.

El bug real: varios módulos guardan estado de proceso que describe UN
dibujo — las huellas de mobiliario y las franjas de anotación ocupadas
(space), y el listado de capas que existen (layers, cacheado para no pedirlo
en cada set_layer). `set_active_document` cambiaba el dibujo en AutoCAD y no
tocaba nada de eso: con dos DWG abiertos, place_labels esquivaba una cama que
está en el OTRO plano, y set_layer daba por configurada una capa que solo
existe allá, dejándola sin color ni grosor.

Los dos fallan en silencio — el dibujo sale mal y ninguna tool da error. Por
eso van con test.

NO necesita AutoCAD.

Uso:  python test_document_state.py
"""
from __future__ import annotations

import sys

import layers
import server
import space

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _ensuciar() -> None:
    """Deja el estado como queda después de dibujar un plano entero."""
    space.clear()
    space.track(0, 0, 2, 1, "cama del OTRO dibujo")
    space.reserve(-1.5, -0.9, 12, -0.6, "cadena de cotas del OTRO dibujo")
    layers._EXISTING = {"MUROS", "EJES", "COTAS"}
    layers._TEXT_CHECKED[0] = True


def _mock(respuesta: dict) -> None:
    server.acad.call = lambda cmd, params=None: respuesta


def test_cambiar_de_dibujo_olvida_huellas_y_capas() -> None:
    _ensuciar()
    real = server.acad.call
    try:
        _mock({"active": "Puente.dwg", "changed": True})
        r = server.set_active_document("Puente.dwg")
        check("olvida las huellas de mobiliario", not space.FOOTPRINTS,
              space.FOOTPRINTS)
        check("olvida las franjas de anotación", not space.OCCUPIED,
              space.OCCUPIED)
        check("invalida el cache de capas", layers._EXISTING is None,
              layers._EXISTING)
        check("avisa lo que olvidó",
              any("dibujo anterior" in w for w in r.get("warnings", [])),
              r)
    finally:
        server.acad.call = real
        space.clear()
        layers.reset()


def test_reactivar_el_mismo_dibujo_no_borra_nada() -> None:
    """changed=False es 'ya estabas parado ahí': tirar el estado ahí sería
    perder el trabajo de la sesión por una llamada que no cambió nada."""
    _ensuciar()
    real = server.acad.call
    try:
        _mock({"active": "Casa.dwg", "changed": False})
        r = server.set_active_document("Casa.dwg")
        check("conserva las huellas", len(space.FOOTPRINTS) == 1,
              space.FOOTPRINTS)
        check("conserva las franjas", len(space.OCCUPIED) == 1, space.OCCUPIED)
        check("conserva el cache de capas", layers._EXISTING is not None,
              layers._EXISTING)
        check("no avisa nada", "warnings" not in r, r)
    finally:
        server.acad.call = real
        space.clear()
        layers.reset()


def test_open_document_arranca_limpio() -> None:
    _ensuciar()
    real = server.acad.call
    try:
        _mock({"active": "Zapata.dwg", "fullPath": "C:/x/Zapata.dwg",
               "alreadyOpen": False, "isReadOnly": False})
        r = server.open_document(path="C:/x/Zapata.dwg")
        check("open_document olvida el dibujo anterior",
              not space.FOOTPRINTS and not space.OCCUPIED
              and layers._EXISTING is None,
              f"{space.FOOTPRINTS} {space.OCCUPIED} {layers._EXISTING}")
        check("no pisa lo que devolvió el plugin",
              r["active"] == "Zapata.dwg" and r["alreadyOpen"] is False, r)
    finally:
        server.acad.call = real
        space.clear()
        layers.reset()


def test_new_document_tambien() -> None:
    _ensuciar()
    real = server.acad.call
    try:
        _mock({"active": "Drawing2.dwg", "fullPath": "Drawing2.dwg",
               "template": "(default)"})
        server.new_document()
        check("new_document olvida el dibujo anterior",
              not space.FOOTPRINTS and not space.OCCUPIED
              and layers._EXISTING is None,
              f"{space.FOOTPRINTS} {space.OCCUPIED} {layers._EXISTING}")
    finally:
        server.acad.call = real
        space.clear()
        layers.reset()


def test_la_escala_no_se_resetea_pero_se_avisa() -> None:
    """La escala es un número por LÁMINA, no por dibujo. Ponerla en un default
    al cambiar de DWG sería tan incorrecto como dejar la anterior — pero es
    justo el dato que no da error cuando está mal, así que se avisa."""
    space.set_scale(0.025)          # 1:25 dibujando en metros
    real = server.acad.call
    try:
        _mock({"active": "Otro.dwg", "changed": True})
        r = server.set_active_document("Otro.dwg")
        check("no inventa una escala", space.units_per_paper_mm() == 0.025,
              space.units_per_paper_mm())
        check("pero avisa cuál rige",
              any("escala" in w.lower() for w in r.get("warnings", [])), r)
    finally:
        server.acad.call = real
        space.set_scale(0.1)
        space.clear()
        layers.reset()


def main() -> int:
    for fn in [test_cambiar_de_dibujo_olvida_huellas_y_capas,
               test_reactivar_el_mismo_dibujo_no_borra_nada,
               test_open_document_arranca_limpio,
               test_new_document_tambien,
               test_la_escala_no_se_resetea_pero_se_avisa]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: cambiar de dibujo no arrastra el estado del anterior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
