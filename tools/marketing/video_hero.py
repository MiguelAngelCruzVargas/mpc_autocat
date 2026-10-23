import os
import subprocess

from PIL import Image

SRC = r"C:\Users\MQerKAcademy\Desktop\progrmas_de_python\autocad-ia\pruebas\demo_casa\videos\casa_dos_niveles_bruto.mp4"
L = r"C:\Users\MQerKAcademy\Desktop\Sistemas\SISTEMA_ASISTENCIA_GENERAL\landing"
SALIDA = os.path.join(L, "assets", "video", "architech-demo.mp4")
POSTER = os.path.join(L, "assets", "img", "architech", "hero-video-poster.webp")
W, H = 960, 600     # la pantalla del laptop del hero es 16:10

# (inicio, duracion, velocidad): resultado primero (3D), luego el proceso
SEGS = [(322, 9, 3.0), (10, 90, 6.0), (180, 30, 6.0), (280, 30, 6.0), (313, 66, 6.0)]

entradas, filtros, partes = [], [], []
total = 0.0
for i, (ini, dur, vel) in enumerate(SEGS):
    entradas += ["-ss", str(ini), "-t", str(dur), "-i", SRC]
    filtros.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{vel},fps=24,scale=-2:{H}[s{i}]")
    partes.append(f"[s{i}]")
    total += dur / vel
filtros.append("".join(partes) + f"concat=n={len(SEGS)}:v=1:a=0,pad={W}:{H}:(ow-iw)/2:0:color=0x0B1220,format=yuv420p[v]")
cmd = ["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(filtros), "-map", "[v]",
       "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-r", "24", "-an", "-movflags", "+faststart", SALIDA]
r = subprocess.run(cmd, capture_output=True, text=True)
print("ffmpeg:", r.returncode, r.stderr[-400:])
print("duracion %.1f s, %d KB" % (total, os.path.getsize(SALIDA) // 1024))

png = os.path.join(os.environ["TEMP"], "poster_hero.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.2", "-i", SALIDA, "-frames:v", "1", png], check=True)
Image.open(png).convert("RGB").save(POSTER, "WEBP", quality=80, method=6)
print("poster", os.path.getsize(POSTER) // 1024, "KB")
