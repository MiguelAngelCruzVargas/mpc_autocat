using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Cierra solo el diálogo de "Unhandled exception" que congela el socket.
    ///
    /// El incidente real: AutoCAD 2022 tira NullReferenceException en su
    /// PROPIO CommandEditor (set_IsBusy, evento Idle) al abrir/cerrar
    /// documentos rápido por API — el plugin ni aparece en el stack. AutoCAD
    /// muestra entonces el diálogo WinForms de excepción no manejada, y ese
    /// diálogo modal deja de atender el socket: cada comando muere por
    /// timeout hasta que un humano clickea Continue.
    ///
    /// Se probó interceptarlo con Application.ThreadException y NO alcanzó:
    /// el diálogo volvió a aparecer, lo que indica que AutoCAD lo crea
    /// directo en su propio manejo de excepciones, no por la ruta que ese
    /// evento cubre. Por eso este watchdog: un hilo de fondo (los hilos del
    /// plugin siguen vivos aunque la UI esté en un modal) que busca ese
    /// diálogo puntual y le manda el mismo click de Continue que haría la
    /// persona.
    ///
    /// El filtro es deliberadamente estrecho para no clickear nada ajeno:
    /// ventana visible del propio proceso, clase WinForms
    /// ("WindowsForms10..."), título exacto "AutoCAD" y un botón cuyo texto
    /// es exactamente "&amp;Continue". Los diálogos nativos de AutoCAD
    /// (guardar cambios, plot, etc.) son clase #32770 y no tienen ese botón:
    /// no los toca.
    ///
    /// Cada cierre queda anotado en %LOCALAPPDATA%\AutoCadMcp\dialogos.log
    /// (archivo y no línea de comandos: Editor.WriteMessage no es seguro
    /// desde un hilo de fondo).
    /// </summary>
    internal static class DialogWatchdog
    {
        private delegate bool EnumProc(IntPtr h, IntPtr l);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumProc cb, IntPtr l);

        [DllImport("user32.dll")]
        private static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr l);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr h);

        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern int GetWindowText(IntPtr h, StringBuilder text, int max);

        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern int GetClassName(IntPtr h, StringBuilder text, int max);

        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);

        private const uint BM_CLICK = 0x00F5;

        private static Thread _thread;
        private static volatile bool _stop;

        public static void Start()
        {
            if (_thread != null)
                return;
            _stop = false;
            _thread = new Thread(Loop) { IsBackground = true, Name = "McpDialogWatchdog" };
            _thread.Start();
        }

        public static void Stop()
        {
            _stop = true;
            _thread = null;
        }

        private static void Loop()
        {
            uint pid = (uint)System.Diagnostics.Process.GetCurrentProcess().Id;
            while (!_stop)
            {
                try
                {
                    Sweep(pid);
                }
                catch
                {
                    // El watchdog nunca puede ser él mismo una fuente de
                    // excepciones no manejadas.
                }
                Thread.Sleep(1500);
            }
        }

        private static void Sweep(uint pid)
        {
            IntPtr dialogo = IntPtr.Zero;
            EnumWindows((h, l) =>
            {
                GetWindowThreadProcessId(h, out uint winPid);
                if (winPid != pid || !IsWindowVisible(h))
                    return true;
                var titulo = new StringBuilder(256);
                GetWindowText(h, titulo, 256);
                if (titulo.ToString() != "AutoCAD")
                    return true;
                var clase = new StringBuilder(256);
                GetClassName(h, clase, 256);
                if (!clase.ToString().StartsWith("WindowsForms10", StringComparison.Ordinal))
                    return true;
                dialogo = h;
                return false;
            }, IntPtr.Zero);

            if (dialogo == IntPtr.Zero)
                return;

            IntPtr boton = IntPtr.Zero;
            EnumChildWindows(dialogo, (h, l) =>
            {
                var texto = new StringBuilder(256);
                GetWindowText(h, texto, 256);
                if (texto.ToString() == "&Continue")
                {
                    boton = h;
                    return false;
                }
                return true;
            }, IntPtr.Zero);

            if (boton == IntPtr.Zero)
                return;

            SendMessage(boton, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
            Anotar("Dialogo de excepcion no manejada cerrado solo (click " +
                   "Continue). Es el bug del CommandEditor de AutoCAD al " +
                   "abrir/cerrar documentos por API; el plugin no aparece " +
                   "en el stack.");
        }

        private static void Anotar(string mensaje)
        {
            try
            {
                var dir = Path.GetDirectoryName(PluginEntry.PortFilePath);
                File.AppendAllText(Path.Combine(dir, "dialogos.log"),
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {mensaje}\r\n");
            }
            catch
            {
                // Sin log no se pierde nada esencial: el click ya salió.
            }
        }
    }
}
