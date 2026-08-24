"""Tests del host de agente. Necesita el servidor MCP (que sí necesita
AutoCAD solo para las tools que dibujan; el catálogo se lee sin él).

Verifica lo que rompe silenciosamente:
  - que los schemas lleguen en una forma que un modelo cualquiera entienda
    (sin los anyOf de Optional, que varios modelos ignoran o rechazan),
  - que los perfiles de tools no nombren tools que no existen,
  - que un error de tool vuelva como TEXTO y no como excepción, que es lo
    que permite al modelo corregir en vez de tumbar la sesión.

Uso:  python -m agent.test_agent
"""
from __future__ import annotations

import asyncio
import sys

from .cli import PERFILES
from .mcp_link import ConexionMcp, _aplanar_schema, _recortar

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre
          + (f" -- {detalle}" if not ok else ""))


def test_aplanar_schema() -> None:
    crudo = {
        "type": "object",
        "properties": {
            "layer": {"anyOf": [{"type": "string"}, {"type": "null"}],
                      "default": None, "title": "Layer"},
            "x": {"type": "number", "title": "X"},
            "puntos": {"type": "array",
                       "items": {"anyOf": [{"type": "number"},
                                           {"type": "null"}]}},
        },
        "required": ["x"],
    }
    limpio = _aplanar_schema(crudo)
    props = limpio["properties"]
    check("el Optional[str] queda como string",
          props["layer"]["type"] == "string", str(props["layer"]))
    # El `default: null` se TIRA. Si se deja, el modelo lo copia y manda
    # null en un campo que ahora dice "string": Groq rechaza la llamada
    # entera con "expected string, but got null" y la tool nunca corre.
    # Paso de verdad con new_document(template=None).
    check("pero el 'default: null' NO sobrevive",
          "default" not in props["layer"], str(props["layer"]))
    check("y el titulo si", props["layer"].get("title") == "Layer",
          str(props["layer"]))
    check("lo que no era anyOf no se toca",
          props["x"]["type"] == "number", str(props["x"]))
    check("tambien aplana adentro de un array",
          props["puntos"]["items"]["type"] == "number",
          str(props["puntos"]))
    check("required sigue igual", limpio["required"] == ["x"],
          str(limpio.get("required")))


def test_recortar() -> None:
    largo = "Primera linea corta.\n\nSegundo parrafo mucho mas largo " * 5
    check("sin limite no recorta", _recortar(largo, 0) == largo, "recorto")
    corto = _recortar(largo, 60)
    check("con limite corta en el primer parrafo",
          corto == "Primera linea corta.", corto)
    check("un texto ya corto no se toca",
          _recortar("hola", 100) == "hola", "lo toco")


async def _con_conexion() -> None:
    async with ConexionMcp() as mcp:
        nombres = {t["name"] for t in mcp.tools}
        check("el servidor expone sus tools", len(nombres) > 100,
              str(len(nombres)))

        # Los perfiles no pueden nombrar tools que no existen: un nombre
        # mal escrito deja al agente sin esa capacidad y en silencio.
        for perfil, patrones in PERFILES.items():
            huerfanos = [pat for pat in patrones
                         if not any(n == pat or n.startswith(pat)
                                    for n in nombres)]
            check(f"el perfil '{perfil}' no nombra tools inexistentes",
                  not huerfanos, str(huerfanos))

        catalogo = mcp.catalogo(incluir=PERFILES["arquitectura"])
        check("el perfil de arquitectura filtra de verdad",
              0 < len(catalogo) < len(mcp.tools),
              f"{len(catalogo)} de {len(mcp.tools)}")

        formato_ok = all(
            t["type"] == "function" and "name" in t["function"]
            and "parameters" in t["function"] for t in catalogo)
        check("el catalogo sale en formato de function calling", formato_ok,
              str(catalogo[:1]))

        sin_anyof = [t["function"]["name"] for t in catalogo
                     if "anyOf" in str(t["function"]["parameters"])]
        check("ningun schema conserva anyOf", not sin_anyof,
              str(sin_anyof[:4]))

        # Ningun parametro tipado puede traer default null: es la
        # combinacion que hace que el modelo mande null y el proveedor
        # rechace la llamada.
        con_default_null = []
        for t in catalogo:
            for nombre, prop in (t["function"]["parameters"]
                                 .get("properties", {}).items()):
                if (isinstance(prop, dict) and "type" in prop
                        and "default" in prop and prop["default"] is None):
                    con_default_null.append(f"{t['function']['name']}.{nombre}")
        check("ningun parametro queda con 'default: null'",
              not con_default_null, str(con_default_null[:4]))

        # Una tool que no existe: el error tiene que volver como texto.
        salida, error = await mcp.ejecutar("tool_que_no_existe", {})
        check("una tool inexistente devuelve error como texto",
              error and isinstance(salida, str), f"{error} {salida[:80]}")

        # Y una que existe pero sin AutoCAD: tambien texto, no excepcion.
        salida, error = await mcp.ejecutar("ping", {})
        check("ping responde algo legible", isinstance(salida, str) and salida,
              salida[:80])


class ProveedorFalso:
    """Devuelve respuestas guionadas, para probar el bucle sin gastar."""

    def __init__(self, guion: list[dict], formato: str = "openai") -> None:
        self.guion = guion
        self.formato = formato
        self.modelo = "falso"
        self.recibido: list[list[dict]] = []

    def completar(self, mensajes, tools):
        # Copia: el bucle sigue mutando la lista despues de esta llamada.
        self.recibido.append([dict(m) for m in mensajes])
        return self.guion[min(len(self.recibido) - 1, len(self.guion) - 1)]


class ConexionFalsa:
    def __init__(self) -> None:
        self.ejecutadas: list[tuple[str, dict]] = []

    async def ejecutar(self, nombre, argumentos):
        self.ejecutadas.append((nombre, argumentos))
        if nombre == "falla":
            return ("ERROR: el hueco se sale del muro, que mide 10", True)
        return ('{"handle": "A1"}', False)


def test_bucle_openai() -> None:
    from .loop import conversar
    guion = [
        {"role": "assistant", "content": "Dibujo el muro.",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "create_walls",
                                      "arguments": '{"thickness": 0.15}'}}]},
        {"role": "assistant", "content": "Listo, el muro quedó dibujado."},
    ]
    prov = ProveedorFalso(guion)
    con = ConexionFalsa()
    eventos: list[tuple[str, dict]] = []
    mensajes = [{"role": "user", "content": "dibujá un muro"}]
    asyncio.run(conversar(con, prov, mensajes, [],
                          lambda t, d: eventos.append((t, d))))

    check("ejecuta la tool que pidio el modelo",
          con.ejecutadas == [("create_walls", {"thickness": 0.15})],
          str(con.ejecutadas))
    check("el resultado vuelve como mensaje 'tool'",
          any(m.get("role") == "tool" and m.get("tool_call_id") == "c1"
              for m in mensajes), str(mensajes[-2:]))
    check("para cuando el modelo deja de pedir tools",
          len(prov.recibido) == 2, str(len(prov.recibido)))
    tipos = [t for t, _ in eventos]
    check("avisa texto, tool y resultado",
          "texto" in tipos and "tool" in tipos and "resultado" in tipos,
          str(tipos))


def test_bucle_anthropic() -> None:
    from .loop import conversar
    guion = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "Dibujo el muro."},
            {"type": "tool_use", "id": "t1", "name": "create_walls",
             "input": {"thickness": 0.15}}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Listo."}]},
    ]
    prov = ProveedorFalso(guion, formato="anthropic")
    con = ConexionFalsa()
    mensajes = [{"role": "user", "content": "dibujá un muro"}]
    asyncio.run(conversar(con, prov, mensajes, []))

    check("tambien ejecuta en formato anthropic",
          con.ejecutadas == [("create_walls", {"thickness": 0.15})],
          str(con.ejecutadas))
    ultimo_user = [m for m in mensajes if m.get("role") == "user"][-1]
    bloques = ultimo_user.get("content")
    check("el resultado va como tool_result en un mensaje user",
          isinstance(bloques, list)
          and bloques[0].get("type") == "tool_result"
          and bloques[0].get("tool_use_id") == "t1", str(bloques))


def test_un_error_de_tool_no_corta_la_sesion() -> None:
    """El servidor escribe errores para que el modelo corrija. Si el bucle
    se cayera, se perderia la sesion por algo recuperable."""
    from .loop import conversar
    guion = [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "falla", "arguments": "{}"}}]},
        {"role": "assistant", "content": "Corrijo la distancia."},
    ]
    prov = ProveedorFalso(guion)
    con = ConexionFalsa()
    mensajes = [{"role": "user", "content": "x"}]
    asyncio.run(conversar(con, prov, mensajes, []))
    resultado = [m for m in mensajes if m.get("role") == "tool"][0]
    check("el error llega al modelo como texto",
          "se sale del muro" in resultado["content"], resultado["content"])
    check("y el bucle sigue", len(prov.recibido) == 2,
          str(len(prov.recibido)))


def test_json_invalido_no_revienta() -> None:
    """Un modelo chico manda JSON roto de vez en cuando."""
    from .loop import conversar
    guion = [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "create_line",
                                      "arguments": "{roto"}}]},
        {"role": "assistant", "content": "ok"},
    ]
    prov = ProveedorFalso(guion)
    con = ConexionFalsa()
    asyncio.run(conversar(con, prov,
                          [{"role": "user", "content": "x"}], []))
    check("el JSON roto no tumba el bucle",
          con.ejecutadas and "__json_invalido__" in con.ejecutadas[0][1],
          str(con.ejecutadas))


def test_tope_de_vueltas() -> None:
    """Sin tope, un modelo en lazo es una factura corriendo sola."""
    from .loop import conversar
    guion = [{"role": "assistant", "content": None,
              "tool_calls": [{"id": "c", "type": "function",
                              "function": {"name": "ping",
                                           "arguments": "{}"}}]}]
    prov = ProveedorFalso(guion)
    con = ConexionFalsa()
    avisos: list[str] = []
    asyncio.run(conversar(con, prov, [{"role": "user", "content": "x"}], [],
                          lambda t, d: avisos.append(d.get("texto", ""))
                          if t == "aviso" else None,
                          vueltas_max=3))
    check("corta en el tope", len(prov.recibido) == 3,
          str(len(prov.recibido)))
    check("y lo dice", any("tope" in a for a in avisos), str(avisos))


def main() -> int:
    for fn in (test_aplanar_schema, test_recortar, test_bucle_openai,
               test_bucle_anthropic, test_un_error_de_tool_no_corta_la_sesion,
               test_json_invalido_no_revienta, test_tope_de_vueltas):
        print(fn.__name__)
        fn()
    print("_con_conexion")
    asyncio.run(_con_conexion())

    if FALLAS:
        print("\n%d FALLAS:" % len(FALLAS))
        for f in FALLAS:
            print(" -", f)
        return 1
    print("\nOK: el host traduce el catalogo y sobrevive a los errores.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
