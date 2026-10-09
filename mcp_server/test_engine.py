"""Tests del motor de acceso total (engine.py): run_code, describe_api, api_guide.

Lo que se verifica es lo que vive del lado Python y que el plugin no puede
hacer: que sin la clave del usuario NI se llame al plugin, que la clave viaje
en cada pedido, la red de seguridad (guardar antes; negarse sin archivo), que
lo creado quede en space y cuente en session solo si de verdad cambió algo,
que los errores salgan legibles, y que describe_api no use lo que el filtro
bloquea.

NO necesita AutoCAD: acad.call se reemplaza por un mock. LOCALAPPDATA se
apunta a un directorio temporal ANTES de importar nada, para no tocar la
configuración real de run_code del usuario (ni su escala ni su puerto).

Uso:  python test_engine.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_TMP = tempfile.TemporaryDirectory(prefix="test_engine_")
os.environ["LOCALAPPDATA"] = _TMP.name

import autocad_client  # noqa: E402
import engine  # noqa: E402
import session  # noqa: E402
import space  # noqa: E402

acceso = engine.acceso

FAILED: list[str] = []
CLAVE = "clave-de-prueba-123"


def check(name: str, ok: bool, detalle: object = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


if sys.platform != "win32":
    # Sin DPAPI: un "cifrado" reversible alcanza para probar el circuito.
    acceso._dpapi = lambda datos, proteger: bytes(b ^ 0x5A for b in datos)


class Mock:
    """Reemplaza acad.call: anota cada comando y responde por tabla."""

    def __init__(self, respuestas: dict) -> None:
        self.respuestas = respuestas
        self.llamadas: list[tuple[str, dict]] = []

    def __call__(self, cmd, params=None):
        self.llamadas.append((cmd, dict(params or {})))
        r = self.respuestas.get(cmd, {})
        if isinstance(r, Exception):
            raise r
        return r(params) if callable(r) else r

    def cmds(self) -> list[str]:
        return [c for c, _ in self.llamadas]

    def params(self, cmd: str) -> dict:
        return next((p for c, p in self.llamadas if c == cmd), {})


def _archivo_dwg() -> str:
    ruta = os.path.join(_TMP.name, "casa.dwg")
    with open(ruta, "wb") as fh:
        fh.write(b"AC1032")
    return ruta


def _doc(full: str, sucio: bool) -> dict:
    return {"documents": [{"name": os.path.basename(full), "fullPath": full,
                           "isActive": True, "isReadOnly": False,
                           "hasUnsavedChanges": sucio}], "count": 1}


def _ok(created=None) -> dict:
    return {"compiled": True, "engine": "roslyn", "result": 42, "output": "",
            "created": created or [], "errors": [], "blocked": [],
            "exception": None, "aborted": False, "elapsedMs": 12}


def _con(mock: Mock, fn):
    real = engine.acad.call
    engine.acad.call = mock
    try:
        return fn()
    finally:
        engine.acad.call = real


def _limpio() -> None:
    session.reset()
    space.clear_footprints()


# ------------------------------------------------------------------ tests

def test_apagado_sin_clave() -> None:
    _limpio()
    acceso._borrar_clave()
    m = Mock({"run_code": _ok()})
    r = _con(m, lambda: engine.run_code("return 1;"))
    check("sin clave NO se llama al plugin", m.llamadas == [], m.llamadas)
    check("y lo dice como apagado", r.get("disabled") is True
          and r.get("executed") is False, r)
    check("el mensaje dice cómo lo activa el USUARIO",
          "run_code_acceso.py activar" in r.get("message", ""), r)


def test_manda_la_contrasena() -> None:
    _limpio()
    acceso.guardar_clave(CLAVE)
    m = Mock({"list_documents": _doc(_archivo_dwg(), sucio=False),
              "run_code": _ok()})
    r = _con(m, lambda: engine.run_code("return 42;", description="prueba"))
    p = m.params("run_code")
    check("la contraseña viaja en 'password'", p.get("password") == CLAVE,
          sorted(p))
    check("con code, description y compile_only",
          p.get("code") == "return 42;" and p.get("description") == "prueba"
          and p.get("compile_only") is False, p)
    check("y el resultado vuelve", r.get("result") == 42
          and r.get("executed") is True, r)
    check("sin cambios sin guardar no guarda", "save_drawing" not in m.cmds(),
          m.cmds())


def test_autoguardado_con_path_de_la_sesion() -> None:
    _limpio()
    session.note_saved("C:/obra/casa.dwg")
    session.note_mutation()
    m = Mock({"list_documents": _doc("Drawing1.dwg", sucio=True),
              "save_drawing": {"saved": True}, "run_code": _ok()})
    r = _con(m, lambda: engine.run_code("return 1;"))
    cmds = m.cmds()
    check("guarda ANTES de ejecutar",
          "save_drawing" in cmds and "run_code" in cmds
          and cmds.index("save_drawing") < cmds.index("run_code"), cmds)
    p = m.params("save_drawing")
    check("como save_drawing() sin path: el de la sesión, pisándolo",
          p == {"path": "C:/obra/casa.dwg", "overwrite": True}, p)
    check("y lo cuenta en warnings",
          any("casa.dwg" in w for w in r.get("warnings", [])), r)


def test_autoguardado_con_el_archivo_del_documento() -> None:
    _limpio()
    ruta = _archivo_dwg()
    m = Mock({"list_documents": _doc(ruta, sucio=True),
              "save_drawing": {"saved": True}, "run_code": _ok()})
    _con(m, lambda: engine.run_code("return 1;"))
    p = m.params("save_drawing")
    check("sin path de sesión guarda sobre su propio archivo",
          p == {"path": None, "overwrite": False}, p)
    check("y ese archivo queda como el path recordado",
          session.last_save_path() == ruta, session.last_save_path())


def test_niega_sin_path_salvo_force() -> None:
    _limpio()
    m = Mock({"list_documents": _doc("Drawing1.dwg", sucio=True),
              "run_code": _ok()})
    r = _con(m, lambda: engine.run_code("return 1;"))
    check("Drawing sin guardar: NO ejecuta", "run_code" not in m.cmds(),
          m.cmds())
    check("y explica qué hacer", "save_drawing(path=" in r.get("message", "")
          and r.get("executed") is False, r)

    m = Mock({"list_documents": _doc("Drawing1.dwg", sucio=True),
              "run_code": _ok()})
    r = _con(m, lambda: engine.run_code("return 1;", force=True))
    check("con force=True ejecuta", "run_code" in m.cmds(), m.cmds())
    check("pero avisa del riesgo",
          any("force=True" in w for w in r.get("warnings", [])), r)

    # Si no se puede preguntar al plugin, se asume lo peor.
    m = Mock({"list_documents": autocad_client.AutoCadError("x"),
              "run_code": _ok()})
    _con(m, lambda: engine.run_code("return 1;"))
    check("sin saber el estado del dibujo, tampoco ejecuta sin path",
          "run_code" not in m.cmds(), m.cmds())


def test_dibujo_limpio_sin_path_ejecuta() -> None:
    _limpio()
    m = Mock({"list_documents": _doc("Drawing1.dwg", sucio=False),
              "run_code": _ok()})
    _con(m, lambda: engine.run_code("return 1;"))
    check("sin nada que perder no se niega", "run_code" in m.cmds(), m.cmds())


def test_compile_only_no_toca_nada() -> None:
    _limpio()
    m = Mock({"run_code": _ok(created=[])})
    r = _con(m, lambda: engine.run_code("return 1;", compile_only=True))
    check("compile_only no consulta ni guarda",
          m.cmds() == ["run_code"], m.cmds())
    check("y viaja compile_only=True",
          m.params("run_code").get("compile_only") is True, m.llamadas)
    check("no cuenta como dibujo", session.ops_since_save() == 0,
          session.ops_since_save())
    check("ni se marca como ejecutado", r.get("executed") is False, r)


def test_created_va_a_space_y_cuenta() -> None:
    _limpio()
    creados = [{"handle": "2A3", "type": "Solid3d", "layer": "3D-MUROS",
                "bbox": [1, 2, 0, 5, 7, 2.5]},
               {"handle": "2A4", "type": "Region", "layer": "0",
                "bbox": None}]
    m = Mock({"list_documents": _doc(_archivo_dwg(), sucio=False),
              "run_code": _ok(created=creados)})
    _con(m, lambda: engine.run_code("return 1;"))
    huellas = [h for h in space.FOOTPRINTS if h["what"] == "run_code"]
    check("cada bbox de created queda en space (en planta)",
          huellas == [{"x0": 1, "y0": 2, "x1": 5, "y1": 7,
                       "what": "run_code"}], huellas)
    check("cuenta como UNA operación de dibujo",
          session.ops_since_save() == 1, session.ops_since_save())


def test_abortado_no_deja_rastro() -> None:
    _limpio()
    crudo = _ok(created=[{"handle": "2A3", "type": "Line", "layer": "0",
                          "bbox": [0, 0, 0, 1, 1, 0]}])
    crudo.update(exception={"type": "Autodesk.AutoCAD.Runtime.Exception",
                            "message": "eNotOpenForWrite", "line": 4},
                 aborted=True)
    m = Mock({"list_documents": _doc(_archivo_dwg(), sucio=False),
              "run_code": crudo})
    r = _con(m, lambda: engine.run_code("return 1;"))
    check("lo abortado no se registra en space", space.FOOTPRINTS == [],
          space.FOOTPRINTS)
    check("ni cuenta como dibujo", session.ops_since_save() == 0,
          session.ops_since_save())
    msg = r.get("message", "")
    check("el mensaje dice tipo, línea y que el dibujo quedó intacto",
          "eNotOpenForWrite" in msg and "línea 4" in msg
          and "abortó" in msg, msg)


def test_mensaje_de_compilacion_y_bloqueo() -> None:
    _limpio()
    crudo = _ok()
    crudo.update(compiled=False, errors=[
        {"line": 3, "column": 5, "message": "CS0103: 'x' no existe",
         "severity": "error"},
        {"line": 1, "column": 1, "message": "variable sin usar",
         "severity": "warning"}])
    m = Mock({"run_code": crudo})
    r = _con(m, lambda: engine.run_code("x;", compile_only=True))
    msg = r.get("message", "")
    check("error de compilación con línea:columna",
          "No compiló" in msg and "línea 3:5" in msg and "CS0103" in msg, msg)
    check("los warnings no se mezclan con los errores",
          "sin usar" not in msg, msg)

    crudo = _ok()
    crudo.update(compiled=False, blocked=[
        {"line": 2, "column": 9, "symbol": "System.IO.File.Delete",
         "reason": "toca el disco"}])
    m = Mock({"list_documents": _doc(_archivo_dwg(), sucio=False),
              "run_code": crudo})
    r = _con(m, lambda: engine.run_code("System.IO.File.Delete(\"a\");"))
    msg = r.get("message", "")
    check("bloqueo con símbolo y motivo",
          "System.IO.File.Delete" in msg and "toca el disco" in msg
          and "línea 2:9" in msg, msg)
    check("un bloqueo no cuenta como ejecutado",
          r.get("executed") is False and session.ops_since_save() == 0, r)


def test_rechazo_del_plugin_por_contrasena() -> None:
    _limpio()
    m = Mock({"list_documents": _doc(_archivo_dwg(), sucio=False),
              "run_code": autocad_client.AutoCadError(
                  "run_code: la contraseña no coincide")})
    r = _con(m, lambda: engine.run_code("return 1;"))
    check("contraseña rechazada -> apagado, sin excepción",
          r.get("disabled") is True and "activar" in r.get("message", ""), r)

    m = Mock({"list_documents": _doc(_archivo_dwg(), sucio=False),
              "run_code": autocad_client.AutoCadError("eWasErased")})
    try:
        _con(m, lambda: engine.run_code("return 1;"))
        check("otros errores del plugin se propagan", False, "no lanzó")
    except autocad_client.AutoCadError as exc:
        check("otros errores del plugin se propagan",
              "eWasErased" in str(exc), exc)


def test_session_no_cuenta_dos_veces() -> None:
    session.reset()
    session.after_call("run_code", {}, _ok())
    check("after_call deja el conteo de run_code a engine",
          session.ops_since_save() == 0, session.ops_since_save())
    check("run_code nunca se reintenta solo",
          session.retry_safe("run_code") is False)
    check("las demás siguen igual", session.retry_safe("list_layers")
          and not session.retry_safe("create_line"))


def test_describe_api_no_usa_lo_bloqueado() -> None:
    codigo = engine.codigo_describe("Solid3d", "Extrude")
    check("no usa Type.GetType", "Type.GetType" not in codigo
          and "GetType(\"" not in codigo)
    check("no usa Assembly.Load", "Assembly.Load" not in codigo
          and ".Load(" not in codigo)
    check("recorre los assemblies ya cargados",
          "AppDomain.CurrentDomain.GetAssemblies()" in codigo
          and "GetTypes()" in codigo)
    check("el filtro va en minúsculas", '"extrude"' in codigo)
    check("sin interpolación de C# 6 ni ?. (compila en C# 5)",
          '$"' not in codigo and "?." not in codigo)
    for malo in ('Solid3d"; System.IO.File.Delete("x', "a b", "../x", ""):
        try:
            engine.codigo_describe(malo)
            check(f"type_name {malo!r} rechazado", False, "no lanzó")
        except ValueError:
            check(f"type_name {malo!r} rechazado", True)
    try:
        engine.codigo_describe("Solid3d", 'x"+y')
        check("filter con comillas rechazado", False, "no lanzó")
    except ValueError:
        check("filter con comillas rechazado", True)


_SALIDA = "\n".join([
    "T|Autodesk.AutoCAD.DatabaseServices.Solid3d|acdbmgd, Version=24.1",
    "S|Autodesk.AutoCAD.DatabaseServices.Solid3d|"
    "Autodesk.AutoCAD.DatabaseServices.Entity|class",
    "C|Solid3d|Solid3d()",
    "P|Solid3d|Solid3dMassProperties MassProperties { get; }",
    "P|Entity|string Layer { get; set; }",
    "M|Solid3d|void Extrude(Region region, double height, double taperAngle)",
    "M|Solid3d|void CreateBox(double xLen, double yLen, double zLen)",
    "M|DBObject|void Erase()",
    "M|DBObject|void Erase()",
]) + "\n"


def test_describe_api_interpreta() -> None:
    _limpio()
    acceso.guardar_clave(CLAVE)
    m = Mock({"run_code": _ok()})
    m.respuestas["run_code"] = dict(_ok(), result=_SALIDA)
    r = _con(m, lambda: engine.describe_api("Solid3d"))
    check("describe_api no consulta ni guarda (es solo lectura)",
          m.cmds() == ["run_code"], m.cmds())
    check("ni cuenta como dibujo", session.ops_since_save() == 0)
    check("encuentra el tipo", r.get("found") is True and r.get("type")
          == "Autodesk.AutoCAD.DatabaseServices.Solid3d", r)
    check("assembly sin la versión", r.get("assembly") == "acdbmgd", r)
    metodos = r.get("methods", [])
    check("lo propio primero, lo heredado marcado",
          metodos[0].startswith("void Extrude")
          and metodos[-1] == "void Erase()  — de DBObject", metodos)
    check("sin duplicados", len(metodos) == 3, metodos)
    check("propiedades con tipo y get/set",
          "Solid3dMassProperties MassProperties { get; }"
          in r.get("properties", []), r.get("properties"))


def test_describe_api_varios_y_recorte() -> None:
    varios = ("T|Autodesk.AutoCAD.DatabaseServices.Region|acdbmgd\n"
              "T|System.Drawing.Region|System.Drawing\n")
    r = engine.interpretar_describe("Region", "", varios)
    check("varios tipos sin elegido -> lista para repetir",
          r.get("found") is False and len(r.get("candidates", [])) == 2, r)
    r = engine.interpretar_describe("Nada", "", "")
    check("tipo inexistente lo dice", r.get("found") is False
          and "No hay" in r.get("message", ""), r)

    muchas = ("S|X.Grande||class\n"
              + "".join(f"M|Grande|void M{i}()\n" for i in range(200)))
    r = engine.interpretar_describe("Grande", "", muchas)
    check("recorta a 150 y avisa",
          len(r.get("methods", [])) == engine.MAX_MIEMBROS
          and r.get("truncated") and r.get("total") == 200
          and "filter" in r.get("warning", ""), r.get("warning"))


def test_describe_api_apagado() -> None:
    _limpio()
    acceso._borrar_clave()
    m = Mock({"run_code": _ok()})
    r = _con(m, lambda: engine.describe_api("Solid3d"))
    check("describe_api apagado no llama al plugin y lo dice",
          m.llamadas == [] and r.get("found") is False
          and "activar" in r.get("message", ""), r)


def test_api_guide() -> None:
    indice = engine.api_guide()
    for tema in ("3d", "seleccion", "capas-y-estilos", "errores-comunes"):
        check(f"el índice lista '{tema}'", f"- {tema}:" in indice, indice)
    texto = engine.api_guide("3d")
    check("un tema devuelve la guía entera",
          "Solid3d" in texto and "CreateBox" in texto, texto[:80])
    check("sin distinguir mayúsculas", engine.api_guide("3D") == texto)
    for malo in ("no-existe", "../CLAUDE", "..\\server"):
        try:
            engine.api_guide(malo)
            check(f"tema {malo!r} rechazado", False, "no lanzó")
        except ValueError as exc:
            check(f"tema {malo!r} rechazado con la lista",
                  "errores-comunes" in str(exc), exc)


def test_guias_cortas() -> None:
    for nombre in os.listdir(engine.GUIAS_DIR):
        with open(os.path.join(engine.GUIAS_DIR, nombre),
                  encoding="utf-8") as fh:
            lineas = fh.read().splitlines()
        check(f"guía {nombre} corta (<= 130 líneas)", len(lineas) <= 130,
              len(lineas))
        texto = "\n".join(lineas)
        check(f"guía {nombre} sin ed.Command en un ejemplo",
              "ed.Command(" not in texto.replace("`ed.Command`", ""))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    try:
        for fn in [test_apagado_sin_clave,
                   test_manda_la_contrasena,
                   test_autoguardado_con_path_de_la_sesion,
                   test_autoguardado_con_el_archivo_del_documento,
                   test_niega_sin_path_salvo_force,
                   test_dibujo_limpio_sin_path_ejecuta,
                   test_compile_only_no_toca_nada,
                   test_created_va_a_space_y_cuenta,
                   test_abortado_no_deja_rastro,
                   test_mensaje_de_compilacion_y_bloqueo,
                   test_rechazo_del_plugin_por_contrasena,
                   test_session_no_cuenta_dos_veces,
                   test_describe_api_no_usa_lo_bloqueado,
                   test_describe_api_interpreta,
                   test_describe_api_varios_y_recorte,
                   test_describe_api_apagado,
                   test_api_guide,
                   test_guias_cortas]:
            print(fn.__name__)
            fn()
    finally:
        session.reset()
        space.clear_footprints()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: run_code no corre sin la clave del usuario, guarda antes y "
          "deja rastro solo de lo que de verdad cambió.")
    return 0


if __name__ == "__main__":
    codigo = main()
    try:
        _TMP.cleanup()
    except OSError:
        pass   # el blindaje (icacls) puede trabar el borrado: es un temporal
    sys.exit(codigo)
