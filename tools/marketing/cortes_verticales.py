"""10 cortes verticales 9:16 (1080x1920) del video de la casa, con gancho arriba y subtitulos grabados.

Uso: python cortes_verticales.py [numero ...]    (sin argumentos hace los 10)
Salida: <SALIDA>/corte_XX.mp4, corte_XX.srt y textos_publicacion.md
"""
import os
import shutil
import subprocess
import sys

from PIL import Image

SRC = r"C:\Users\MQerKAcademy\Desktop\progrmas_de_python\autocad-ia\pruebas\demo_casa\videos\casa_dos_niveles_bruto.mp4"
IMG = r"C:\Users\MQerKAcademy\Desktop\Sistemas\SISTEMA_ASISTENCIA_GENERAL\landing\assets\img\proyectos"
SALIDA = r"C:\Users\MQerKAcademy\Desktop\progrmas_de_python\autocad-ia\pruebas\demo_casa\shorts"
TRABAJO = r"C:\Users\MQerKAcademy\AppData\Local\Temp\cortes\trabajo"
FUENTE = r"C:\Windows\Fonts\arialbd.ttf"

W, H = 1080, 1920
VID_Y, VID_H = 470, 1002         # donde va el video dentro del lienzo
CROP_Y, CROP_W, CROP_H = 235, 868, 805   # zona de dibujo de AutoCAD en el bruto (sin cinta ni barras)
FONDO = "0x0B1628"
CTA = "Pruébalo 7 días gratis"
PIE = "Vigentra Architech · vigentra.mx"

# (segmentos [(inicio_s, duracion_s, velocidad)], x_recorte, gancho, [(t0, t1, subtitulo)], hashtags/idea de texto)
CORTES = {
    1: dict(segs=[(322, 12, 3.0), (10, 100, 3.0)], cx=366,
            gancho="Casa de dos niveles:\nplanos, instalaciones\ny 3D en 7 minutos",
            caps=[(322, 334, "Casa de 2 niveles, en 3D"), (10, 30, "1. Muros, puertas y ventanas"),
                  (30, 50, "2. Muebles, nombres y cotas"), (50, 80, "3. Segunda planta y escalera"),
                  (80, 110, "4. Fachada y corte")],
            titulo="Una casa de dos niveles completa en 7 minutos (planos, instalaciones y 3D)"),
    2: dict(segs=[(14, 42, 2.0)], cx=366,
            gancho="Una planta baja\ncompleta en menos\nde un minuto",
            caps=[(14, 26, "Muros, puertas y ventanas"), (26, 40, "Muebles en cada ambiente"),
                  (40, 56, "Nombres, superficies y cotas")],
            titulo="Una planta baja completa en menos de un minuto, dentro de AutoCAD"),
    3: dict(segs=[(50, 35, 1.75)], cx=560,
            gancho="La segunda planta\ny la escalera\nse dibujan solas",
            caps=[(50, 62, "Muros de la planta alta"), (62, 75, "Recámaras, baños y clósets"),
                  (75, 85, "Escalera y hueco en la losa")],
            titulo="La segunda planta y la escalera, dibujadas por la IA"),
    4: dict(segs=[(80, 30, 1.75)], cx=700,
            gancho="Fachada y corte\na escala, sin dibujar\nuna sola línea",
            caps=[(80, 90, "Fachada principal con vanos"), (90, 110, "Corte A-A con niveles y losas")],
            titulo="Fachada y corte a escala sin dibujar una línea"),
    5: dict(segs=[(170, 45, 1.5)], cx=400,
            gancho="Instalación eléctrica\ncon la norma\nNOM-001-SEDE",
            caps=[(170, 180, "Circuitos y tablero"), (180, 200, "Cuadro de circuitos"),
                  (200, 215, "Notas según NOM-001-SEDE")],
            titulo="Instalación eléctrica con la norma NOM-001-SEDE, generada desde la planta"),
    6: dict(segs=[(210, 60, 2.0)], cx=250,
            gancho="Agua y drenaje\ntrazados con\nsus diámetros",
            caps=[(210, 230, "Agua fría y caliente"), (230, 250, "Desagües, registros y pendientes"),
                  (250, 270, "Las 3 instalaciones, en una lámina")],
            titulo="Instalación hidráulica y sanitaria dibujadas con sus diámetros y pendientes"),
    7: dict(segs=[(270, 40, 1.5)], cx=300,
            gancho="El cuadro de volúmenes\nde obra, medido\ndel propio dibujo",
            caps=[(270, 280, "Nueva lámina de cantidades"), (280, 300, "Partidas y totales"),
                  (300, 310, "Medido del propio dibujo")],
            titulo="Cuantificación de obra medida del propio dibujo de AutoCAD"),
    8: dict(segs=[(313, 38, 1.6)], cx=366,
            gancho="Así se vería tu casa\nantes de construirla",
            caps=[(313, 330, "Vista desde la calle"), (330, 340, "Acceso con marquesina"),
                  (340, 351, "Terraza con pérgola")],
            titulo="Así se vería tu casa antes de construirla: modelo 3D desde AutoCAD"),
    9: dict(segs=[(351, 40, 1.33)], cx=366,
            gancho="Entra a la casa:\nescalera, recámara\ny vista sin techo",
            caps=[(351, 361, "Sala y comedor"), (361, 371, "Escalera en U con barandal"),
                  (371, 381, "Recámara principal"), (381, 391, "Vista sin techo")],
            titulo="Recorrido 3D por el interior de una casa dibujada con IA"),
    10: dict(imagenes=[("mixtan/portico-calle.webp", "Pórtico con arco y barda"),
                       ("mixtan/portico-arco.webp", "Arco, frontón y pilastras"),
                       ("mixtan/lamina-02-alzado-y-estructura-del-portico.webp", "Estructura calculada"),
                       ("mixtan/lamina-03-trabe-curva-y-fronton.webp", "Armado de la trabe curva"),
                       ("celular/tres-cuartos.webp", "Un celular modelado"),
                       ("celular/dorso-angulo.webp", "desde sus medidas")],
             gancho="No solo casas:\nun pórtico y\nun celular en 3D",
             titulo="No solo casas: un pórtico calculado y un celular modelados con IA en AutoCAD"),
}

HASHTAGS = "#AutoCAD #Arquitectura #IngenieriaCivil #Planos #IA #Construccion #Mexico #Diseño3D"


def srt_tiempo(s):
    ms = int(round(s * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def escribir(nombre, texto):
    with open(os.path.join(TRABAJO, nombre), "w", encoding="utf-8", newline="") as f:
        f.write(texto)
    return nombre


def mapear(segs, t_src):
    """Tiempo de salida de un instante del video fuente."""
    off = 0.0
    for ini, dur, vel in segs:
        if ini <= t_src <= ini + dur:
            return off + (t_src - ini) / vel
        off += dur / vel
    return off


def construir(n):
    c = CORTES[n]
    tag = "%02d" % n
    entradas, filtros, partes = [], [], []
    if "segs" in c:
        total = 0.0
        for i, (ini, dur, vel) in enumerate(c["segs"]):
            entradas += ["-ss", str(ini), "-t", str(dur), "-i", SRC]
            filtros.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{vel},fps=30,crop={CROP_W}:{CROP_H}:{c['cx']}:{CROP_Y},"
                           f"scale={W}:-2,setsar=1[s{i}]")
            partes.append(f"[s{i}]")
            total += dur / vel
        if len(partes) > 1:
            filtros.append("".join(partes) + f"concat=n={len(partes)}:v=1:a=0[vid]")
        else:
            filtros.append("[s0]null[vid]")
        caps = [(mapear(c["segs"], a), mapear(c["segs"], b), t) for a, b, t in c["caps"]]
    else:
        seg = 4.0
        total = seg * len(c["imagenes"])
        caps = []
        for i, (ruta, texto) in enumerate(c["imagenes"]):
            png = f"img{n}_{i}.png"
            Image.open(os.path.join(IMG, ruta)).convert("RGB").save(os.path.join(TRABAJO, png))
            entradas += ["-i", png]   # un solo cuadro: zoompan genera los d cuadros de la imagen
            filtros.append(f"[{i}:v]scale=2160:1580:force_original_aspect_ratio=increase,crop=2160:1580,"
                           f"zoompan=z='min(zoom+0.0007,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(seg*30)}:s={W}x{VID_H}:fps=30,setsar=1[s{i}]")
            partes.append(f"[s{i}]")
            caps.append((i * seg, (i + 1) * seg, texto))
        filtros.append("".join(partes) + f"concat=n={len(partes)}:v=1:a=0[vid]")

    escribir(f"gancho{tag}.txt", c["gancho"])
    dt = []
    base = f"fontfile=arialbd.ttf"
    dt.append(f"drawtext={base}:text='VIGENTRA ARCHITECH':fontcolor=0x7FB0FF:fontsize=40:x=(w-text_w)/2:y=80")
    for k, linea in enumerate(c["gancho"].split("\n")):
        lf = escribir(f"gancho{tag}_{k}.txt", linea)
        dt.append(f"drawtext={base}:textfile={lf}:fontcolor=white:fontsize=78:x=(w-text_w)/2:y={150 + k * 100}")
    dt.append(f"drawbox=x=(iw-220)/2:y=440:w=220:h=8:color=0x3B82F6:t=fill")
    for k, (a, b, texto) in enumerate(caps):
        f = escribir(f"cap{tag}_{k}.txt", texto)
        dt.append(f"drawtext={base}:textfile={f}:fontcolor=white:fontsize=60:borderw=6:bordercolor=black:"
                  f"x=(w-text_w)/2:y=1500:enable='between(t,{a:.3f},{b - 0.05:.3f})'")
    dt.append(f"drawtext={base}:text='{CTA}':fontcolor=white:fontsize=58:box=1:boxcolor=0x2563EB:boxborderw=26:"
              f"x=(w-text_w)/2:y=1640:enable='gte(t,{total - 3.5:.3f})'")
    dt.append(f"drawtext={base}:text='{PIE}':fontcolor=0x9FB3D1:fontsize=40:x=(w-text_w)/2:y=1790")
    filtros.append(f"color=c={FONDO}:s={W}x{H}:r=30:d={total:.3f}[bg]")
    filtros.append(f"[bg][vid]overlay=0:{VID_Y}:shortest=1,{','.join(dt)},format=yuv420p[out]")

    salida = os.path.join(SALIDA, f"corte_{tag}.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(filtros), "-map", "[out]",
           "-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-r", "30", "-an",
           "-movflags", "+faststart", salida]
    r = subprocess.run(cmd, cwd=TRABAJO, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"corte {tag}: ERROR\n", r.stderr[-1500:])
        return None
    with open(os.path.join(SALIDA, f"corte_{tag}.srt"), "w", encoding="utf-8") as f:
        for k, (a, b, texto) in enumerate(caps, 1):
            f.write(f"{k}\n{srt_tiempo(a)} --> {srt_tiempo(b)}\n{texto}\n\n")
    print(f"corte {tag}: {total:.1f} s -> {salida}")
    return total


def main():
    os.makedirs(SALIDA, exist_ok=True)
    shutil.rmtree(TRABAJO, ignore_errors=True)
    os.makedirs(TRABAJO)
    shutil.copy(FUENTE, os.path.join(TRABAJO, "arialbd.ttf"))
    pedir = [int(a) for a in sys.argv[1:]] or sorted(CORTES)
    resumen = []
    for n in pedir:
        t = construir(n)
        if t:
            resumen.append((n, t))
    with open(os.path.join(SALIDA, "textos_publicacion.md"), "w", encoding="utf-8") as f:
        f.write("# Textos para publicar los cortes\n\nPublicar en Reels, TikTok y YouTube Shorts. Los videos van sin audio: "
                "agrega música o una voz desde la propia aplicación. Cada `.srt` trae los subtítulos por si prefieres subirlos aparte.\n\n")
        for n in sorted(CORTES):
            c = CORTES[n]
            f.write(f"## Corte {n:02d}\n\n**Título:** {c['titulo']}\n\n**Descripción:** {c['titulo']}. Pruébalo 7 días gratis en vigentra.mx.\n\n"
                    f"**Hashtags:** {HASHTAGS}\n\n")


if __name__ == "__main__":
    main()
