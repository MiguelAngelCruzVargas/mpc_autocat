"""Tests del estado de sesión: guardado, cotas manuales, viewport y leader.

Cubre las defensas nuevas contra errores que pasaron de verdad:
- el plano entero perdido por un crash de AutoCAD sin save_drawing,
- el save sin path que caía en Documents\\Drawing1.dwg,
- la cota manual invisible para check_annotations,
- el viewport con la escala mil veces mal en silencio,
- el leader que sale sin punta.

NO necesita AutoCAD.

Uso:  python test_session.py
"""
from __future__ import annotations

import sys

import autocad_client
import server
import session
import space

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_conteo_de_operaciones() -> None:
    session.reset()
    session.after_call("create_line", {}, {"handle": "A"})
    session.after_call("create_polyline", {}, {"handle": "B"})
    check("dos mutaciones se cuentan", session.ops_since_save() == 2,
          str(session.ops_since_save()))
    session.after_call("list_layers", {}, {"layers": []})
    session.after_call("get_extents", {}, {})
    session.after_call("ping", {}, {})
    check("mirar no ensucia", session.ops_since_save() == 2,
          str(session.ops_since_save()))
    session.after_call("save_drawing", {"path": "C:/x/casa.dwg"}, {})
    check("guardar resetea el conteo", session.ops_since_save() == 0,
          str(session.ops_since_save()))
    check("y recuerda el path", session.last_save_path() == "C:/x/casa.dwg",
          str(session.last_save_path()))


def test_aviso_al_cruzar_el_umbral() -> None:
    session.reset()
    con_aviso = 0
    for _ in range(session.UMBRAL_SIN_GUARDAR * 2):
        r = session.after_call("create_line", {}, {"handle": "A"})
        if "warning" in r:
            con_aviso += 1
            check("el aviso dice cuántas van y qué hacer",
                  "save_drawing" in r["warning"], r["warning"])
    check("avisa exactamente al cruzar cada umbral", con_aviso == 2,
          str(con_aviso))


def test_no_pisa_un_warning_existente() -> None:
    session.reset()
    for _ in range(session.UMBRAL_SIN_GUARDAR - 1):
        session.after_call("create_line", {}, {"handle": "A"})
    r = session.after_call("create_walls_x", {}, {"warning": "machones"})
    check("un warning de la tool no se pisa", r["warning"] == "machones", r)


def test_save_sin_path_reusa_el_ultimo() -> None:
    session.reset()
    session.note_saved("C:/obra/casa.dwg")
    capturado = {}
    real = server.acad.call

    def mock(cmd, params=None):
        capturado.update({"cmd": cmd, **(params or {})})
        return {"saved": True}

    try:
        server.acad.call = mock
        r = server.save_drawing()
        check("reusa el path recordado",
              capturado.get("path") == "C:/obra/casa.dwg", str(capturado))
        check("pisa su propio archivo sin pedir permiso",
              capturado.get("overwrite") is True, str(capturado))
        check("y lo dice en el resultado", "casa.dwg" in r.get("note", ""), r)

        capturado.clear()
        server.save_drawing(path="C:/obra/casa_v2.dwg")
        check("un path explícito manda",
              capturado.get("path") == "C:/obra/casa_v2.dwg", str(capturado))
        check("y queda como el nuevo recordado",
              session.last_save_path() == "C:/obra/casa_v2.dwg",
              str(session.last_save_path()))
    finally:
        server.acad.call = real
        session.reset()


def test_save_sin_ningun_path_no_inventa() -> None:
    session.reset()
    capturado = {}
    real = server.acad.call
    try:
        server.acad.call = lambda cmd, params=None: (
            capturado.update(params or {}) or {"saved": True})
        r = server.save_drawing()
        check("sin path recordado no inventa ninguno",
              capturado.get("path") is None, str(capturado))
        check("ni fuerza overwrite", capturado.get("overwrite") is False,
              str(capturado))
        check("ni agrega nota", "note" not in r, r)
    finally:
        server.acad.call = real
        session.reset()


def test_open_document_siembra_el_path() -> None:
    session.reset()
    real = server.acad.call
    try:
        server.acad.call = lambda cmd, params=None: {"active": "Zapata.dwg"}
        server.open_document(path="C:/x/Zapata.dwg")
        check("abrir un DWG deja su path como destino de guardado",
              session.last_save_path() == "C:/x/Zapata.dwg",
              str(session.last_save_path()))
        server.open_document(path="C:/y/Ajeno.dwg", read_only=True)
        check("read_only NO siembra el path (no es para escribir)",
              session.last_save_path() is None,
              str(session.last_save_path()))
    finally:
        server.acad.call = real
        session.reset()


def test_cambiar_de_dibujo_olvida_la_sesion() -> None:
    session.reset()
    session.note_saved("C:/x/casa.dwg")
    session.after_call("create_line", {}, {})
    real = server.acad.call
    try:
        server.acad.call = lambda cmd, params=None: {
            "active": "Puente.dwg", "changed": True}
        server.set_active_document("Puente.dwg")
        check("el path recordado no vale para otro dibujo",
              session.last_save_path() is None,
              str(session.last_save_path()))
        check("el conteo arranca de cero", session.ops_since_save() == 0,
              str(session.ops_since_save()))
    finally:
        server.acad.call = real
        session.reset()


def test_export_pdf_reclama_el_check() -> None:
    session.reset()
    session.after_call("create_line", {}, {})     # hay dibujo sin revisar
    real = server.acad.call
    try:
        server.acad.call = lambda cmd, params=None: {"path": "x.pdf"}
        r = server.export_pdf(layout="E-01", path="C:/x.pdf")
        check("exportar sin check_all avisa",
              "check_all" in r.get("warning", ""), r)
        session.note_checked()
        r = server.export_pdf(layout="E-01", path="C:/x.pdf")
        check("con el check corrido no molesta", "warning" not in r, r)
    finally:
        server.acad.call = real
        session.reset()


def test_cota_manual_deja_huella() -> None:
    space.clear()
    real = server.acad.call
    try:
        server.acad.call = lambda cmd, params=None: {"handle": "D1"}
        server.create_dimension(0, 0, 5, 0, dim_line_x=2.5, dim_line_y=-1.0,
                                scale=0.1)
        bandas = [b for b in space.OCCUPIED
                  if "cota manual" in b.get("what", "")]
        check("la cota suelta reserva su franja", len(bandas) == 1,
              str(space.OCCUPIED))
        if bandas:
            b = bandas[0]
            check("la franja está sobre la línea de cota, no sobre los puntos",
                  b["y0"] < -0.5 and b["y1"] > -1.5 and b["x0"] < 0.1
                  and b["x1"] > 4.9, str(b))
        server.create_dimension_rotated(0, 0, 3, 2, dim_line_x=0.0,
                                        dim_line_y=4.0, angle_deg=0.0,
                                        scale=0.1, text="VARIABLE")
        bandas = [b for b in space.OCCUPIED if "VARIABLE" in b.get("what", "")]
        check("la rotada también, con su texto", len(bandas) == 1,
              str(space.OCCUPIED))
    finally:
        server.acad.call = real
        space.clear()


def test_viewport_exige_unidades() -> None:
    try:
        server.create_viewport(layout="E-01", center_x=100, center_y=100,
                               width=150, height=100)
    except ValueError as exc:
        check("create_viewport sin model_units_per_mm se niega",
              "obligatorio" in str(exc) and "1000" in str(exc), str(exc))
    else:
        check("create_viewport sin model_units_per_mm se niega", False,
              "no dio error")


def test_leader_corto_avisa() -> None:
    real = server.acad.call
    try:
        server.acad.call = lambda cmd, params=None: {"handle": "L1"}
        r = server.create_leader(points=[[0, 0], [0.1, 0.1]], text="TL-1",
                                 text_height=2.5)
        check("primer tramo menor a 2x la flecha avisa",
              "punta" in r.get("warning", ""), r)
        r = server.create_leader(points=[[0, 0], [10, 0]], text="TL-1",
                                 text_height=2.5)
        check("un tramo largo no molesta", "warning" not in r, r)
    finally:
        server.acad.call = real
        space.clear()


def _con_transporte_falso(secuencia, cmd):
    """Corre autocad_client.call con _do_call reemplazado por una secuencia
    de errores/resultados, sin esperas reales. Devuelve (resultado o
    excepción, cuántos intentos hizo)."""
    llamadas = [0]
    real_do, real_sleep = autocad_client._do_call, autocad_client.time.sleep

    def falso(cmd_, params=None):
        paso = secuencia[min(llamadas[0], len(secuencia) - 1)]
        llamadas[0] += 1
        if isinstance(paso, Exception):
            raise paso
        return paso

    try:
        autocad_client._do_call = falso
        autocad_client.time.sleep = lambda s: None
        try:
            return autocad_client.call(cmd), llamadas[0]
        except autocad_client.AutoCadError as exc:
            return exc, llamadas[0]
    finally:
        autocad_client._do_call = real_do
        autocad_client.time.sleep = real_sleep


def test_reintento_transitorio_en_lectura() -> None:
    """El eInvalidInput del plot que se arregla solo: el cliente reintenta,
    no el agente."""
    r, intentos = _con_transporte_falso(
        [autocad_client.AutoCadError("eInvalidInput"), {"path": "x.png"}],
        "capture_viewport")
    check("capture_viewport con eInvalidInput reintenta y sale",
          r == {"path": "x.png"} and intentos == 2, f"{r} en {intentos}")


def test_no_reintenta_lo_que_dibuja() -> None:
    """Un create_line tras timeout pudo haber llegado: repetirlo duplica."""
    r, intentos = _con_transporte_falso(
        [autocad_client.AutoCadError("AutoCAD no procesó el comando a tiempo."),
         {"handle": "A"}],
        "create_line")
    check("create_line con timeout NO se reintenta",
          isinstance(r, autocad_client.AutoCadError) and intentos == 1,
          f"{r} en {intentos}")


def test_sin_conexion_reintenta_todo() -> None:
    """Si la conexión ni se estableció, nada llegó: repetir es seguro
    incluso para lo que dibuja."""
    r, intentos = _con_transporte_falso(
        [autocad_client.AutoCadConnectionError("refused"), {"handle": "A"}],
        "create_line")
    check("create_line sin conexión sí se reintenta",
          r == {"handle": "A"} and intentos == 2, f"{r} en {intentos}")


def test_error_real_no_se_reintenta() -> None:
    """'No existe el layout' no se arregla esperando: fallar rápido."""
    r, intentos = _con_transporte_falso(
        [autocad_client.AutoCadError("No existe un layout llamado 'X'.")],
        "list_layouts")
    check("un error real de lectura falla a la primera",
          isinstance(r, autocad_client.AutoCadError) and intentos == 1,
          f"{r} en {intentos}")


def main() -> int:
    for fn in [test_conteo_de_operaciones, test_aviso_al_cruzar_el_umbral,
               test_no_pisa_un_warning_existente,
               test_save_sin_path_reusa_el_ultimo,
               test_save_sin_ningun_path_no_inventa,
               test_open_document_siembra_el_path,
               test_cambiar_de_dibujo_olvida_la_sesion,
               test_export_pdf_reclama_el_check,
               test_cota_manual_deja_huella,
               test_viewport_exige_unidades,
               test_leader_corto_avisa,
               test_reintento_transitorio_en_lectura,
               test_no_reintenta_lo_que_dibuja,
               test_sin_conexion_reintenta_todo,
               test_error_real_no_se_reintenta]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: la sesión vigila lo que las reglas en prosa no podían.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
