"""Enlaces con parametros de campana (utm) para cada corte y cada red social.

    python tools/marketing/enlaces_utm.py [carpeta_de_salida]

Escribe enlaces_utm.md. Cada enlace lleva utm_source (la red), utm_medium (video_organico), utm_campaign (la tanda) y
utm_content (el corte): asi Google Analytics, Meta y la tabla de compras del servidor saben que video trajo cada visita
y cada venta (`python licencias/admin.py estadisticas`). En anuncios de pago cambia utm_medium a `anuncio_pago`.
"""
import os
import re
import sys
import unicodedata
from urllib.parse import urlencode

SITIO = "https://vigentra.mx"
CAMPANA = "cortes_2026_10"
REDES = ["instagram", "tiktok", "youtube", "facebook"]

# (gancho, destino): la casa lleva a la pagina del proyecto; lo tecnico, al producto; el ultimo, a la galeria
CORTES = {
    1: ("Casa de dos niveles en 7 minutos", "/proyecto-casa-dos-niveles"),
    2: ("Planta baja en menos de un minuto", "/proyecto-casa-dos-niveles"),
    3: ("Segunda planta y escalera", "/proyecto-casa-dos-niveles"),
    4: ("Fachada y corte a escala", "/proyecto-casa-dos-niveles"),
    5: ("Instalacion electrica NOM-001-SEDE", "/vigentra-architech"),
    6: ("Agua y drenaje con diametros", "/vigentra-architech"),
    7: ("Cuadro de volumenes de obra", "/vigentra-architech"),
    8: ("Asi se veria tu casa", "/proyecto-casa-dos-niveles"),
    9: ("Recorrido 3D interior", "/proyecto-casa-dos-niveles"),
    10: ("No solo casas", "/proyectos"),
}


def slug(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def enlace(destino: str, red: str, contenido: str, medio: str = "video_organico", campana: str = CAMPANA) -> str:
    return SITIO + destino + "?" + urlencode({"utm_source": red, "utm_medium": medio, "utm_campaign": campana, "utm_content": contenido})


def main() -> None:
    salida = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(salida, exist_ok=True)
    lineas = ["# Enlaces con parámetros por video y red", "",
              "Pégalos en la descripción (YouTube, Facebook) o en el enlace de la biografía (Instagram, TikTok). "
              "Cada uno identifica el video y la red, para medir qué trae pruebas y ventas.", "",
              "| Corte | Destino | " + " | ".join(r.capitalize() for r in REDES) + " |",
              "|---|---|" + "|".join("---" for _ in REDES) + "|"]
    for n, (gancho, destino) in CORTES.items():
        cont = f"corte_{n:02d}_{slug(gancho)}"
        fila = [f"{n:02d} · {gancho}", destino] + [f"`{enlace(destino, r, cont)}`" for r in REDES]
        lineas.append("| " + " | ".join(fila) + " |")
    lineas += ["", "## Enlace único de la biografía (Instagram y TikTok solo permiten uno)", ""]
    for r in ("instagram", "tiktok"):
        lineas.append(f"- {r.capitalize()}: `{enlace('/vigentra-architech', r, 'bio')}`")
    lineas += ["", "## Para anuncios de pago", "",
               "Cambia `utm_medium=video_organico` por `utm_medium=anuncio_pago` y pon el nombre del anuncio en `utm_content`.", ""]
    with open(os.path.join(salida, "enlaces_utm.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    print("enlaces_utm.md escrito en", os.path.abspath(salida))


if __name__ == "__main__":
    main()
