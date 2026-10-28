"""Las herramientas «bajo demanda» (agent/descubrir.py + loop.py): sin AutoCAD, sin red, sin gastar.

Uso:  python -m agent.test_descubrir
"""
from __future__ import annotations

import asyncio
import json
import sys

from . import descubrir
from .loop import conversar
from .providers import ErrorProveedor

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


def catalogo_falso(n: int) -> list[dict]:
    return [{"type": "function", "function": {"name": f"tool_{i}", "description": f"descripción {i}",
                                              "parameters": {"type": "object", "properties": {"x": {"type": "number"}}}}}
            for i in range(n)] + [
        {"type": "function", "function": {"name": "create_walls", "description": "muros",
                                          "parameters": {"type": "object", "properties": {"thickness": {"type": "number"}}}}},
        {"type": "function", "function": {"name": "run_code", "description": "c#", "parameters": {"type": "object", "properties": {}}}},
    ]


class ConexionFalsa:
    def __init__(self, n=300):
        self._cat = catalogo_falso(n)
        self.ejecutadas: list[tuple[str, dict]] = []

    def catalogo(self, incluir=None, limite_descripcion=0):
        return self._cat

    async def ejecutar(self, nombre, argumentos):
        self.ejecutadas.append((nombre, argumentos))
        if nombre == "list_tool_categories":
            return ('{"categorias": ["dibujo", "p_3d"]}', False)
        return ('{"handle": "A1"}', False)


class ProveedorLimitado:
    """Como Groq: rechaza el pedido ENTERO si trae más de `maximo` herramientas."""

    def __init__(self, guion, maximo=128):
        self.guion, self.maximo, self.modelo, self.formato = guion, maximo, "falso", "openai"
        self.pedidos: list[int] = []         # cuántas herramientas llegaron en cada pedido
        self.recibido: list[list[dict]] = []

    def completar(self, mensajes, tools):
        self.pedidos.append(len(tools))
        if len(tools) > self.maximo:
            raise ErrorProveedor(f'El modelo respondió 400: {{"error":{{"message":"\'tools\' : maximum number of items is {self.maximo}"}}}}')
        self.recibido.append([dict(m) for m in mensajes])
        return self.guion[min(len(self.recibido) - 1, len(self.guion) - 1)]


def llamada(id_, herramienta, /, **args):
    return {"id": id_, "type": "function", "function": {"name": herramienta, "arguments": json.dumps(args)}}


def guion_ejecutar():
    return [
        {"role": "assistant", "content": None, "tool_calls": [llamada("a", "buscar_herramientas", flujo="casa")]},
        {"role": "assistant", "content": None, "tool_calls": [llamada("b", "describir_herramienta", nombre="create_walls")]},
        {"role": "assistant", "content": None, "tool_calls": [llamada("c", "ejecutar_herramienta", nombre="create_walls", argumentos={"thickness": 0.15})]},
        {"role": "assistant", "content": "Listo, el muro quedó dibujado."},
    ]


def correr(prov, con, tools, **kw):
    eventos: list[tuple[str, dict]] = []
    mensajes = [{"role": "system", "content": "SISTEMA"}, {"role": "user", "content": "dibuja un muro"}]
    asyncio.run(conversar(con, prov, mensajes, tools, lambda t, d: eventos.append((t, d)), **kw))
    return eventos, mensajes


def main() -> int:
    print("test_limite_conocido")
    con, prov = ConexionFalsa(), ProveedorLimitado(guion_ejecutar())
    ev, msgs = correr(prov, con, con.catalogo(), limite_tools=descubrir.LIMITES["groq"])
    check("con más herramientas que el límite del proveedor, manda solo las 3 de descubrimiento", prov.pedidos[0] == 3, str(prov.pedidos))
    check("y avisa por qué, con una nota (no un error)", any(t == "nota" and "128" in d["texto"] for t, d in ev) and not any(t == "aviso" for t, _ in ev), str(ev[:2]))
    check("el sistema explica cómo usar las tres", "buscar_herramientas" in msgs[0]["content"] and msgs[0]["content"].startswith("SISTEMA"))
    check("buscar_herramientas consulta el mapa de categorías", ("list_tool_categories", {"workflow": "casa"}) in con.ejecutadas, str(con.ejecutadas))
    check("ejecutar_herramienta corre la herramienta REAL con sus argumentos", ("create_walls", {"thickness": 0.15}) in con.ejecutadas)
    tools_ev = [d for t, d in ev if t == "tool"]
    check("en pantalla se ve la herramienta real, no el intermediario",
          {"nombre": "create_walls", "args": {"thickness": 0.15}} in tools_ev, str(tools_ev))
    res = [d for t, d in ev if t == "resultado" and d["nombre"] == "describir_herramienta"]
    check("describir_herramienta da sus parámetros exactos", res and "thickness" in res[0]["texto"], str(res))
    check("termina con el texto del modelo", [d["texto"] for t, d in ev if t == "texto"][-1].startswith("Listo"))

    print("test_el_proveedor_se_queja")
    con, prov = ConexionFalsa(), ProveedorLimitado(guion_ejecutar())
    ev, _ = correr(prov, con, con.catalogo())          # sin límite conocido: lo descubre por el error
    check("sin límite conocido, el primer pedido se rechaza y el reintento va con 3", prov.pedidos[:2] == [302, 3], str(prov.pedidos))
    check("lo cuenta como nota, no como error", any(t == "nota" for t, _ in ev) and not any(t == "aviso" for t, _ in ev))
    check("y el trabajo se hace igual", ("create_walls", {"thickness": 0.15}) in con.ejecutadas)

    print("test_si_cabe_no_cambia")
    con, prov = ConexionFalsa(50), ProveedorLimitado([{"role": "assistant", "content": "Hola."}])
    ev, _ = correr(prov, con, con.catalogo(), limite_tools=128)
    check("con 52 herramientas y límite 128 se mandan todas", prov.pedidos == [52], str(prov.pedidos))
    check("sin notas ni avisos", not any(t in ("nota", "aviso") for t, _ in ev))

    print("test_bajo_demanda_por_eleccion")
    con, prov = ConexionFalsa(), ProveedorLimitado([{"role": "assistant", "content": "Hola."}], maximo=10_000)
    ev, _ = correr(prov, con, con.catalogo(), bajo_demanda=True)
    check("el perfil «descubrir» va bajo demanda aunque el proveedor aceptaría todas", prov.pedidos == [3], str(prov.pedidos))

    print("test_pide_la_herramienta_real_directo")
    from .providers import ToolInvalida

    class ProveedorQueSePasa(ProveedorLimitado):
        """Como Groq: si el modelo pide una tool que no está en la lista que se mandó, rechaza todo con un 400."""
        def completar(self, mensajes, tools):
            self.pedidos.append(len(tools))
            ultimo = mensajes[-1].get("content", "") if mensajes else ""
            if len(self.pedidos) == 1:
                raise ToolInvalida("pidió una tool que no está", "create_walls")
            self.ultimo_mensaje = ultimo
            return {"role": "assistant", "content": "Entendido."}
    con, prov = ConexionFalsa(), ProveedorQueSePasa([])
    ev, _ = correr(prov, con, con.catalogo(), limite_tools=128)
    check("si pide una herramienta real por su nombre, se le explica cómo usar ejecutar_herramienta",
          "ejecutar_herramienta" in getattr(prov, "ultimo_mensaje", "") and "create_walls" in prov.ultimo_mensaje, str(getattr(prov, "ultimo_mensaje", "")))
    check("y no sale como un error rojo", not any(t == "aviso" for t, _ in ev), str(ev))

    print("test_errores_que_vuelven_al_modelo")
    d = descubrir.Descubridor(ConexionFalsa())
    txt, err = asyncio.run(d.atender("ejecutar_herramienta", {"nombre": "run_code", "argumentos": {}}))
    check("run_code no se ejecuta", err and "no está disponible" in txt)
    txt, err = asyncio.run(d.atender("ejecutar_herramienta", {"nombre": "no_existe"}))
    check("una herramienta que no existe se dice y se sugiere buscar", err and "buscar_herramientas" in txt)
    txt, err = asyncio.run(d.atender("describir_herramienta", {"nombre": "no_existe"}))
    check("describir una inexistente también", err)
    txt, err = asyncio.run(d.atender("ejecutar_herramienta", {"__json_invalido__": '{"nombre": "x'}))
    check("un JSON roto vuelve como error en vez de ejecutarse a medias", err and "JSON" in txt)
    n, a = d.visible("ejecutar_herramienta", {"nombre": "x", "argumentos": '{"k": 1}'})
    check("los argumentos que el modelo manda como TEXTO se leen igual", (n, a) == ("x", {"k": 1}))
    check("las tres herramientas son las únicas con ese nombre", descubrir.NOMBRES == {"buscar_herramientas", "describir_herramienta", "ejecutar_herramienta"})

    print("test_el_perfil_descubrir")
    from .cli import PERFILES
    check("existe el perfil «descubrir» (todas, bajo demanda)", PERFILES.get("descubrir") == [])

    if FALLAS:
        print("\n%d FALLAS:" % len(FALLAS))
        for f in FALLAS:
            print(" -", f)
        return 1
    print("\nOK: cuando las herramientas no caben, el agente las descubre bajo demanda.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
