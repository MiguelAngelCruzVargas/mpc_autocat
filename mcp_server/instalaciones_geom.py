"""Geometría de las instalaciones: dónde conecta cada mueble, cómo se
recorren los muros y cómo se arma una red de tubería ortogonal en árbol.

Sin AutoCAD y sin números de norma: eso vive en instalaciones.py. Acá está
lo que es igual para la hidráulica, la sanitaria y la eléctrica:

- Cada mueble sanitario conecta en el centro de su lado APOYADO en el muro
  (el WC por el tanque, el lavabo por atrás): ahí llegan el agua y sale el
  desagüe, no en el centro del mueble.
- Una red de tubería real no es una línea por mueble desde la fuente: es un
  árbol con troncales compartidas. Se arma como lo haría un proyectista:
  cada salida se une al punto MÁS CERCANO de lo ya tendido, con tramos
  ortogonales (paralelos a los muros). Así cada tramo sabe qué muebles
  alimenta (o drena) aguas abajo, que es lo que define su diámetro.
"""
from __future__ import annotations

import math
from typing import Any, Optional

Punto = tuple[float, float]

# Ancho por defecto de cada mueble (el de furniture.py), para ubicar su
# punto de conexión cuando el item no lo trae.
ANCHO_MUEBLE = {"wc": 0.38, "lavatory": 0.60, "shower": 0.90,
                "kitchen_sink": 0.80, "laundry_sink": 0.70}


def _rotar(px: float, py: float, base: Punto, ang_deg: float) -> Punto:
    a = math.radians(ang_deg)
    dx, dy = px - base[0], py - base[1]
    return (base[0] + dx * math.cos(a) - dy * math.sin(a),
            base[1] + dx * math.sin(a) + dy * math.cos(a))


def conexion(mueble: dict[str, Any]) -> Punto:
    """Punto donde el mueble conecta, en el muro de atrás.

    furniture.py dibuja cada pieza como un rectángulo con su esquina (x, y)
    contra el muro y el lado local y=0 apoyado: el centro de ese lado es la
    conexión."""
    x, y = float(mueble["x"]), float(mueble["y"])
    ancho = float(mueble.get("width") or ANCHO_MUEBLE.get(mueble["type"], 0.5))
    return _rotar(x + ancho / 2.0, y, (x, y), float(mueble.get("rotation_deg", 0.0)))


def recinto_de(p: Punto, rooms: list[dict[str, Any]]) -> Optional[str]:
    """El recinto (por nombre) que contiene el punto, el más chico si hay
    varios (la conexión cae en la frontera entre dos)."""
    adentro = [r for r in rooms
               if r["x0"] - 1e-6 <= p[0] <= r["x1"] + 1e-6
               and r["y0"] - 1e-6 <= p[1] <= r["y1"] + 1e-6]
    if not adentro:
        return None
    return min(adentro, key=lambda r: (r["x1"] - r["x0"]) * (r["y1"] - r["y0"]))["name"]


# ------------------------------------------------------------ red en árbol

class Red:
    """Árbol de tramos ortogonales con raíz en la fuente (o la descarga).

    'nodos' son puntos; cada nodo salvo la raíz tiene un 'padre' hacia la
    raíz. Las salidas (muebles) son hojas con su carga; 'carga_tramo' suma
    lo que hay aguas abajo de cada tramo."""

    def __init__(self, raiz: Punto) -> None:
        self.nodos: list[Punto] = [raiz]
        self.padre: list[Optional[int]] = [None]
        self.carga: list[float] = [0.0]
        self.etiqueta: list[Any] = [None]

    def _tramos(self) -> list[tuple[int, int]]:
        return [(i, p) for i, p in enumerate(self.padre) if p is not None]

    def _mas_cercano(self, q: Punto) -> tuple[Punto, Optional[tuple[int, int]], int]:
        """El punto de la red más cercano a q (distancia manhattan): sobre un
        tramo (y cuál) o un nodo suelto (la raíz sola)."""
        mejor = (math.inf, self.nodos[0], None, 0)
        if len(self.nodos) == 1:
            p = self.nodos[0]
            return p, None, 0
        for i, j in self._tramos():
            a, b = self.nodos[i], self.nodos[j]
            if abs(a[0] - b[0]) < 1e-9:      # tramo vertical
                y = min(max(q[1], min(a[1], b[1])), max(a[1], b[1]))
                c = (a[0], y)
            else:                            # tramo horizontal
                x = min(max(q[0], min(a[0], b[0])), max(a[0], b[0]))
                c = (x, a[1])
            d = abs(q[0] - c[0]) + abs(q[1] - c[1])
            if d < mejor[0] - 1e-9:
                mejor = (d, c, (i, j), 0)
        return mejor[1], mejor[2], mejor[3]

    def _nodo_en(self, c: Punto, tramo: Optional[tuple[int, int]]) -> int:
        """Índice de un nodo en c, partiendo el tramo si c cae en su medio."""
        for k, n in enumerate(self.nodos):
            if math.dist(n, c) < 1e-6:
                return k
        i, j = tramo  # type: ignore[misc]
        self.nodos.append(c)
        self.padre.append(j)
        self.carga.append(0.0)
        self.etiqueta.append(None)
        nuevo = len(self.nodos) - 1
        self.padre[i] = nuevo
        return nuevo

    def conectar(self, q: Punto, carga: float, etiqueta: Any = None,
                 preferir: str = "auto") -> int:
        """Une la salida q al punto más cercano de la red con un tramo en L
        (o recto si están alineados). Devuelve el índice de la hoja."""
        c, tramo, _ = self._mas_cercano(q)
        destino = self._nodo_en(c, tramo) if tramo else 0
        # La esquina de la L: el codo va sobre la línea del tramo al que se
        # llega, así el ramal entra perpendicular y no corre encima de él.
        if abs(q[0] - c[0]) < 1e-9 or abs(q[1] - c[1]) < 1e-9:
            codo = None
        elif tramo and abs(self.nodos[tramo[0]][1] - self.nodos[tramo[1]][1]) < 1e-9:
            codo = (q[0], c[1])          # llega a un tramo horizontal: baja en vertical
        elif tramo:
            codo = (c[0], q[1])          # llega a un tramo vertical: va en horizontal
        else:
            codo = (q[0], c[1]) if preferir != "x" else (c[0], q[1])
        anterior = destino
        if codo and math.dist(codo, c) > 1e-6:
            self.nodos.append(codo)
            self.padre.append(anterior)
            self.carga.append(0.0)
            self.etiqueta.append(None)
            anterior = len(self.nodos) - 1
        self.nodos.append(q)
        self.padre.append(anterior)
        self.carga.append(float(carga))
        self.etiqueta.append(etiqueta)
        return len(self.nodos) - 1

    def carga_tramo(self) -> dict[int, float]:
        """Carga aguas abajo de cada tramo, indexado por su nodo hijo."""
        total = list(self.carga)
        hijos: dict[int, list[int]] = {}
        for i, p in enumerate(self.padre):
            if p is not None:
                hijos.setdefault(p, []).append(i)
        orden: list[int] = []
        pila = [0]
        while pila:
            n = pila.pop()
            orden.append(n)
            pila.extend(hijos.get(n, []))
        for n in reversed(orden):
            p = self.padre[n]
            if p is not None:
                total[p] += total[n]
        return {i: total[i] for i, p in enumerate(self.padre) if p is not None}

    def aguas_abajo(self, nodo: int) -> list[Any]:
        """Las etiquetas de las salidas que cuelgan de ese nodo."""
        hijos: dict[int, list[int]] = {}
        for i, p in enumerate(self.padre):
            if p is not None:
                hijos.setdefault(p, []).append(i)
        salida, pila = [], [nodo]
        while pila:
            n = pila.pop()
            if self.etiqueta[n] is not None:
                salida.append(self.etiqueta[n])
            pila.extend(hijos.get(n, []))
        return salida

    def tramos(self) -> list[dict[str, Any]]:
        cargas = self.carga_tramo()
        return [{"desde": self.nodos[p], "hasta": self.nodos[i], "nodo": i,
                 "carga": cargas[i],
                 "largo": abs(self.nodos[p][0] - self.nodos[i][0])
                 + abs(self.nodos[p][1] - self.nodos[i][1])}
                for i, p in enumerate(self.padre) if p is not None]


def red_en_arbol(raiz: Punto, salidas: list[tuple[Punto, float, Any]]) -> Red:
    """Arma la red uniendo, cada vez, la salida más cercana a lo ya tendido
    (Prim con distancia manhattan). Así las troncales se comparten."""
    red = Red(raiz)
    pendientes = list(salidas)
    while pendientes:
        mejor = None
        for k, (q, carga, et) in enumerate(pendientes):
            c, _t, _ = red._mas_cercano(q)
            d = abs(q[0] - c[0]) + abs(q[1] - c[1])
            if mejor is None or d < mejor[0]:
                mejor = (d, k)
        q, carga, et = pendientes.pop(mejor[1])
        red.conectar(q, carga, et)
    return red


# ------------------------------------------------------- muros de un recinto

def tramos_de_muro(caja: tuple[float, float, float, float],
                   huecos: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    """Los tramos de muro LIBRE de un recinto (caja útil x0,y0,x1,y1), sin
    los vanos de puertas. huecos: [(lado, desde, hasta)] con lado en
    bottom/top (coordenada x) o left/right (coordenada y).

    Cada tramo: {"lado", "a0", "a1", "punto": f(t) -> (x, y), "hacia": ang
    hacia adentro del recinto}."""
    x0, y0, x1, y1 = caja
    lados = {"bottom": (x0, x1, lambda t: (t, y0), 90.0),
             "top": (x0, x1, lambda t: (t, y1), 270.0),
             "left": (y0, y1, lambda t: (x0, t), 0.0),
             "right": (y0, y1, lambda t: (x1, t), 180.0)}
    salida = []
    for lado, (a0, a1, f, hacia) in lados.items():
        cortes = sorted((max(a0, h0), min(a1, h1)) for l, h0, h1 in huecos
                        if l == lado and h1 > a0 and h0 < a1)
        cursor = a0
        for h0, h1 in cortes:
            if h0 - cursor > 1e-6:
                salida.append({"lado": lado, "a0": cursor, "a1": h0,
                               "punto": f, "hacia": hacia})
            cursor = max(cursor, h1)
        if a1 - cursor > 1e-6:
            salida.append({"lado": lado, "a0": cursor, "a1": a1,
                           "punto": f, "hacia": hacia})
    return salida
