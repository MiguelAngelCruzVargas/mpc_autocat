"""Graba la ventana de AutoCAD mientras el MCP trabaja: el PEDIDO arriba y
el PASO que va haciendo abajo, que se actualiza en vivo.

Es para el material de demostración (videos cortos de 20-30 s y fotos):
quien lo ve tiene que entender qué se pidió y qué está pasando sin que
nadie se lo explique.

    from grabar_demo import Grabacion, foto_ventana
    with Grabacion(r"...\\videos\\electrica.mp4",
                   "Hazme la instalación eléctrica de la planta alta") as g:
        g.paso("Dibujando muros, puertas y ventanas")
        ...

Captura SOLO la ventana de AutoCAD con PrintWindow, aunque esté tapada por
otras: la primera versión grababa la región de la pantalla y salió la
terminal de quien estaba trabajando encima. No trae nada al frente ni toca
el foco. Necesita ffmpeg en el PATH y pywin32.

Para que se vea dibujar (y no aparecer todo al final), el cliente tiene que
estar en modo ver dibujar: autocad_client.ver_dibujar(True), plugin 1.9.1+.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

import win32gui
import win32ui

try:                                    # coordenadas físicas, no escaladas
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:                       # noqa: BLE001
    pass

FUENTE = "C\\:/Windows/Fonts/arial.ttf"
FUENTE_B = "C\\:/Windows/Fonts/arialbd.ttf"
FONDO = "0x1b2129"
ANCHO = 1600                            # ancho del video de salida
PW_RENDERFULLCONTENT = 2


def ventana(texto: str = "Autodesk AutoCAD") -> tuple[int, str]:
    """La primera ventana visible cuyo título contiene 'texto' (AutoCAD por
    defecto; 'Excel' para grabar el catálogo de conceptos)."""
    hallados: list[tuple[int, str]] = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if texto in t:
                hallados.append((h, t))
    win32gui.EnumWindows(cb, None)
    if not hallados:
        raise RuntimeError(f"No encuentro una ventana abierta con '{texto}' en el título.")
    return hallados[0]


def ventana_autocad() -> tuple[int, str]:
    return ventana("Autodesk AutoCAD")


def _visible_al_fondo(h: int) -> bool:
    """Una ventana minimizada no se pinta y PrintWindow devuelve negro. Si
    lo está, se restaura SIN activarla y al FONDO de todas, para no tapar
    lo que el usuario tiene adelante. Devuelve si estaba minimizada."""
    if not win32gui.IsIconic(h):
        return False
    SW_SHOWNOACTIVATE, HWND_BOTTOM = 4, 1
    SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10
    ctypes.windll.user32.ShowWindow(h, SW_SHOWNOACTIVATE)
    ctypes.windll.user32.SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0,
                                      SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(1.5)                     # que termine de pintarse
    return True


def _volver_a_minimizar(h: int) -> None:
    SW_SHOWMINNOACTIVE = 7
    ctypes.windll.user32.ShowWindow(h, SW_SHOWMINNOACTIVE)


class _Captura:
    """Cuadros de la ventana (BGRA) con PrintWindow, sin traerla al frente."""

    def __init__(self, h: int, ancho: int = ANCHO):
        self.h = h
        x0, y0, x1, y1 = win32gui.GetWindowRect(h)
        self.W, self.HH = x1 - x0, y1 - y0
        # Se reduce AL CAPTURAR: a tamaño completo eran 12 MB por cuadro y
        # ffmpeg no llegaba a codificarlos -- se perdían cuadros y el video
        # salía acelerado sin decirlo (149 s reales quedaron en 29 s).
        self.w = min(ancho, self.W) // 2 * 2
        self.hh = int(self.HH * self.w / self.W) // 2 * 2
        self.wdc = win32gui.GetWindowDC(h)
        self.mdc = win32ui.CreateDCFromHandle(self.wdc)
        self.sdc = self.mdc.CreateCompatibleDC()
        self.bmp = win32ui.CreateBitmap()
        self.bmp.CreateCompatibleBitmap(self.mdc, self.W, self.HH)
        self.sdc.SelectObject(self.bmp)
        self.cdc = self.mdc.CreateCompatibleDC()
        self.chico = win32ui.CreateBitmap()
        self.chico.CreateCompatibleBitmap(self.mdc, self.w, self.hh)
        self.cdc.SelectObject(self.chico)
        win32gui.SetStretchBltMode(self.cdc.GetSafeHdc(), 4)       # HALFTONE

    def cuadro(self) -> bytes:
        ctypes.windll.user32.PrintWindow(self.h, self.sdc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        self.cdc.StretchBlt((0, 0), (self.w, self.hh), self.sdc, (0, 0), (self.W, self.HH),
                            0x00CC0020)                            # SRCCOPY
        return self.chico.GetBitmapBits(True)

    def cerrar(self) -> None:
        try:
            win32gui.DeleteObject(self.chico.GetHandle())
            self.cdc.DeleteDC()
            win32gui.DeleteObject(self.bmp.GetHandle())
            self.sdc.DeleteDC()
            self.mdc.DeleteDC()
            win32gui.ReleaseDC(self.h, self.wdc)
        except Exception:               # noqa: BLE001
            pass


def _ruta_filtro(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:")


def _escribir(path: str, texto: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(texto)
    # Atómico, para que ffmpeg nunca lea a medias. Pero en Windows no se
    # puede reemplazar un archivo que ffmpeg tiene abierto justo en ese
    # instante (PermissionError: cortó una grabación entera): se reintenta.
    for _ in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.02)
    with open(path, "w", encoding="utf-8") as f:   # último recurso
        f.write(texto)
    try:
        os.remove(tmp)
    except OSError:
        pass


def _filtro_bandas(f_pedido: str, f_paso: Optional[str]) -> str:
    alto_banda, alto_pie = 64, (52 if f_paso else 0)
    vf = (f"scale={ANCHO}:-2,"
          f"pad=iw:ih+{alto_banda + alto_pie}:0:{alto_banda}:color={FONDO},"
          f"drawtext=fontfile='{FUENTE_B}':textfile='{_ruta_filtro(f_pedido)}':"
          f"reload=1:expansion=none:fontcolor=white:fontsize=28:x=24:y=({alto_banda}-th)/2")
    if f_paso:
        vf += (f",drawtext=fontfile='{FUENTE}':textfile='{_ruta_filtro(f_paso)}':"
               f"reload=1:expansion=none:fontcolor=0xffb347:fontsize=24:x=24:y=h-{alto_pie}+(({alto_pie}-th)/2)")
    return vf


class Grabacion:
    def __init__(self, salida: str, pedido: str, fps: int = 8,
                 max_segundos: float = 900.0, titulo: str = "PEDIDO",
                 de: str = "Autodesk AutoCAD"):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("Falta ffmpeg en el PATH.")
        self.salida = os.path.abspath(salida)
        os.makedirs(os.path.dirname(self.salida), exist_ok=True)
        base = os.path.splitext(self.salida)[0]
        self.f_pedido, self.f_paso = base + ".pedido.txt", base + ".paso.txt"
        _escribir(self.f_pedido, f"{titulo}:  {pedido}")
        _escribir(self.f_paso, " ")
        self.fps, self.max_segundos = fps, max_segundos
        self._parar = threading.Event()
        self.duracion = 0.0
        self.cuadros = 0
        self.de = de

    def paso(self, texto: str) -> None:
        _escribir(self.f_paso, f"»  {texto}")

    def _bucle(self) -> None:
        """Mantiene SIEMPRE cuadros escritos = segundos transcurridos x fps:
        si la captura o ffmpeg se atrasan (AutoCAD ocupado con un 3D con
        texturas), repite el último cuadro hasta alcanzar el reloj. Así el
        video dura exactamente lo que duró la toma."""
        datos = None
        try:
            while time.time() - self.t0 < self.max_segundos:
                if self._parar.is_set():
                    objetivo = int(round((self.t_fin - self.t0) * self.fps))
                    while datos is not None and self.cuadros < objetivo:
                        self.proc.stdin.write(datos)
                        self.cuadros += 1
                    break
                datos = self.cap.cuadro()
                self.proc.stdin.write(datos)
                self.cuadros += 1
                objetivo = int((time.time() - self.t0) * self.fps)
                while self.cuadros < objetivo and not self._parar.is_set():
                    self.proc.stdin.write(datos)
                    self.cuadros += 1
                espera = self.cuadros / self.fps - (time.time() - self.t0)
                if espera > 0:
                    time.sleep(espera)
        except (BrokenPipeError, OSError):
            pass

    def __enter__(self) -> "Grabacion":
        h, _ = ventana(self.de)
        self.h, self.estaba_min = h, _visible_al_fondo(h)
        self.cap = _Captura(h)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
               "-s", f"{self.cap.w}x{self.cap.hh}", "-framerate", str(self.fps), "-i", "-",
               "-vf", _filtro_bandas(self.f_pedido, self.f_paso), "-r", "30",
               # ultrafast: con AutoCAD rindiendo un 3D con texturas, veryfast
               # no llegaba a codificar en tiempo real.
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", self.salida]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.t0 = time.time()
        self.hilo = threading.Thread(target=self._bucle, daemon=True)
        self.hilo.start()
        time.sleep(1.0)                 # un segundo de "antes"
        return self

    def __exit__(self, *exc) -> None:
        time.sleep(2.5)                 # que se vea el resultado terminado
        self.t_fin = time.time()
        self._parar.set()
        self.hilo.join(timeout=600)     # escribe los cuadros que falten
        self.duracion = round(self.t_fin - self.t0, 1)
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        err = self.proc.stderr.read() if self.proc.stderr else b""
        self.proc.wait(timeout=180)
        self.cap.cerrar()
        if self.estaba_min:
            _volver_a_minimizar(self.h)
        for f in (self.f_pedido, self.f_paso):
            try:
                os.remove(f)
            except OSError:
                pass
        if not os.path.exists(self.salida):
            raise RuntimeError(f"ffmpeg no dejó el video: {err.decode(errors='replace')}")
        # El video tiene que durar lo que duró de verdad: si faltan cuadros
        # se vería acelerado sin decirlo, y eso no se entrega.
        grabado = self.cuadros / self.fps
        self.desfase = round(self.duracion - grabado, 1)
        if abs(self.desfase) > max(2.0, 0.03 * self.duracion):
            raise RuntimeError(f"El video dura {grabado:.1f} s y la grabación {self.duracion:.1f} s: "
                               "se perdieron cuadros, no es tiempo real.")


def foto_ventana(salida: str, pedido: Optional[str] = None,
                 de: str = "Autodesk AutoCAD") -> str:
    """Una foto de la ventana de AutoCAD tal como se ve (con la interfaz),
    con el pedido arriba si se pasa. No la trae al frente."""
    h, _ = ventana(de)
    estaba_min = _visible_al_fondo(h)
    cap = _Captura(h)
    try:
        datos = cap.cuadro()
    finally:
        cap.cerrar()
        if estaba_min:
            _volver_a_minimizar(h)
    salida = os.path.abspath(salida)
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    vf = f"scale={ANCHO}:-2"
    tmp = None
    if pedido:
        tmp = os.path.splitext(salida)[0] + ".pedido.txt"
        _escribir(tmp, f"PEDIDO:  {pedido}")
        vf = _filtro_bandas(tmp, None)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
                    "-s", f"{cap.w}x{cap.hh}", "-i", "-", "-frames:v", "1", "-vf", vf, salida],
                   input=datos, check=True)
    if tmp:
        os.remove(tmp)
    return salida
