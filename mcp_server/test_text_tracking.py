"""Tests de que create_text/create_mtext/create_leader se auto-registran, y
que check_annotations los revisa SIN que haga falta pasarlos a mano.

El caso real que motiva esto: dos textos puestos con create_text directo
(NPT +1.40 y DESCANSO) terminaron encimados en un plano real, y
check_annotations no avisó nada porque nunca supo que esos textos existían
-- solo revisaba lo que create_dimension_chain/create_axis_grid reservan
solas. Si el agente que dibuja no usa place_labels (y nada lo obliga a
usarlo, sea cual sea el modelo que esté operando el MCP), el chequeo de
cierre tiene que agarrarlo igual.

NO necesita AutoCAD.

Uso:  python test_text_tracking.py
"""
from __future__ import annotations

import sys

import server
import space

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _mock() -> None:
    def fake(cmd, params=None):
        return {"handle": "H", "status": "ok"}
    server.acad.call = fake


def test_dos_textos_encimados_se_detectan_solos() -> None:
    """El caso real: dos create_text puestos a mano, cerca, sin pasar por
    place_labels ni avisarle nada a check_annotations -- tiene que
    detectarlo igual."""
    space.clear()
    real = server.acad.call
    try:
        _mock()
        server.create_text(text="N.P.T. +1.40 (DESCANSO)", x=1.96, y=-6.45, height=0.13)
        server.create_text(text="DESCANSO", x=2.0, y=-6.5, height=0.1)
        r = server.check_annotations()
        check("detecta el choque", not r["ok"], str(r))
        check("nombra los dos textos",
              any("DESCANSO" in p["problem"] for p in r["problems"]),
              r["problems"])
    finally:
        server.acad.call = real
        space.clear()


def test_textos_separados_no_avisa() -> None:
    space.clear()
    real = server.acad.call
    try:
        _mock()
        server.create_text(text="N.P.T. +0.00", x=0, y=0, height=0.13)
        server.create_text(text="N.P.T. +2.80", x=20, y=20, height=0.13)
        r = server.check_annotations()
        check("no inventa un choque", r["ok"], str(r["problems"]))
    finally:
        server.acad.call = real
        space.clear()


def test_leader_se_registra_en_el_ultimo_punto() -> None:
    """El texto de un leader arranca en el ultimo punto, no en el primero
    (que es la punta de flecha) -- la huella tiene que salir de ahi."""
    space.clear()
    real = server.acad.call
    try:
        _mock()
        server.create_leader(points=[[0.0, 0.0], [3.0, 3.0]],
                             text="8 CH TÍP. @ 17.5cm", text_height=0.12)
        server.create_text(text="ENCIMADO", x=3.0, y=3.0, height=0.12)
        r = server.check_annotations()
        check("detecta el choque con el texto del leader", not r["ok"], str(r))
    finally:
        server.acad.call = real
        space.clear()


def test_mtext_usa_el_ancho_pasado_no_una_estimacion_por_caracter() -> None:
    """Un mtext angosto (width chico) no debe registrar una huella ancha
    solo porque el texto en si es largo -- 'width' es el dato real."""
    space.clear()
    real = server.acad.call
    try:
        _mock()
        server.create_mtext(text="Texto bastante largo que ajusta en poco ancho",
                            x=0, y=0, height=0.15, width=1.0)
        huellas = space.text_footprints()
        check("una sola huella registrada", len(huellas) == 1, huellas)
        check("el ancho de la huella es el 'width' pasado, no una estimacion",
              abs(huellas[0]["x1"] - huellas[0]["x0"] - 1.0) < 1e-6,
              huellas[0])
    finally:
        server.acad.call = real
        space.clear()


def test_check_annotations_sigue_aceptando_items_a_mano() -> None:
    """El uso previo (pasar 'items' a mano para preguntar ANTES de dibujar)
    sigue andando igual, combinado con lo que ya se auto-registro."""
    space.clear()
    real = server.acad.call
    try:
        _mock()
        server.create_text(text="YA DIBUJADO", x=0, y=0, height=0.15)
        r = server.check_annotations(
            items=[{"x0": 0.05, "y0": 0.05, "x1": 1.0, "y1": 0.5, "what": "propuesto"}])
        check("detecta el choque contra lo propuesto", not r["ok"], str(r))
    finally:
        server.acad.call = real
        space.clear()


def main() -> int:
    for fn in [test_dos_textos_encimados_se_detectan_solos,
               test_textos_separados_no_avisa,
               test_leader_se_registra_en_el_ultimo_punto,
               test_mtext_usa_el_ancho_pasado_no_una_estimacion_por_caracter,
               test_check_annotations_sigue_aceptando_items_a_mano]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: un texto puesto a mano queda atrapado igual, sin depender "
          "de que quien dibuja se acuerde de place_labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
