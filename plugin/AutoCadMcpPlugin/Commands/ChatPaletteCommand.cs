using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text.Json;
using System.Threading;
using Autodesk.AutoCAD.Runtime;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Comando MCPCHATWEB: el chat como PÁGINA WEB dentro de un panel (la versión nativa es MCPCHAT, ver ChatNativoCommand.cs).
    ///
    /// El panel solo MUESTRA una página: el chat de verdad (el agente, las herramientas, la clave de API) vive en
    /// un proceso de Python (mcp_server/chat_server.py) que habla con el plugin por el mismo socket de siempre.
    /// Este comando se asegura de que ese proceso esté corriendo (lo arranca si hace falta) y pone el panel.
    ///
    /// El panel (PaletteSet, ensamblado acmgd) se maneja por REFLEXION: así el mismo código compila para
    /// net48, net8 y net10 sin depender de cómo cada paquete de referencia expone la clase.
    /// </summary>
    public class McpChatCommands
    {
        [CommandMethod("MCPCHATWEB")]
        public void AbrirChat()
        {
            ChatPalette.Mostrar();
        }
    }

    internal static class ChatPalette
    {
        private static readonly Guid IdPanel = new Guid("6f0f6c1e-3a3b-4a7e-9f6e-1d5c2c9b7a41");
        private static object _paleta;
        private static string _urlMostrada;

        private static string Estado =>
            Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp");

        private static void Decir(string texto)
        {
            try
            {
                var doc = Autodesk.AutoCAD.ApplicationServices.Application.DocumentManager.MdiActiveDocument;
                if (doc != null) doc.Editor.WriteMessage("\n" + texto + "\n");
            }
            catch { /* sin documento no hay donde escribir */ }
        }

        public static void Mostrar()
        {
            var url = AsegurarServidor();
            if (url == null) return;
            try
            {
                if (_paleta == null || _urlMostrada != url)
                {
                    _paleta = CrearPaleta(url);
                    _urlMostrada = url;
                }
                _paleta.GetType().GetProperty("Visible").SetValue(_paleta, true);
            }
            catch (System.Exception ex)
            {
                // sin panel (versión sin navegador embebido, o algo cambió): el chat igual funciona en el navegador
                Decir("[MCPCHAT] No pude abrir el panel (" + ex.GetBaseException().Message + "). Lo abro en el navegador.");
                try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch { /* nada más que hacer */ }
            }
        }

        private static object CrearPaleta(string url)
        {
            // PaletteSet vive en acmgd.dll (el mismo ensamblado que Application), no en AcWindows.dll.
            var asm = typeof(Autodesk.AutoCAD.ApplicationServices.Application).Assembly;
            var tPaleta = asm.GetType("Autodesk.AutoCAD.Windows.PaletteSet", true);
            var ps = Activator.CreateInstance(tPaleta, new object[] { "Asistente AutoCAD", IdPanel });
            var add = tPaleta.GetMethod("Add", new[] { typeof(string), typeof(Uri) });
            if (add == null) throw new MissingMethodException("PaletteSet.Add(string, Uri) no existe en esta versión.");
            add.Invoke(ps, new object[] { "Chat", new Uri(url) });
            tPaleta.GetProperty("MinimumSize")?.SetValue(ps, new System.Drawing.Size(320, 400));
            tPaleta.GetProperty("Size")?.SetValue(ps, new System.Drawing.Size(440, 720));
            var tDock = asm.GetType("Autodesk.AutoCAD.Windows.DockSides");
            if (tDock != null) tPaleta.GetProperty("Dock")?.SetValue(ps, Enum.Parse(tDock, "Right"));
            return ps;
        }

        // ---------------------------------------------------------------------------------- el servidor de chat

        private static bool Responde(string url)
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create(url.TrimEnd('/') + "/api/ping");
                req.Timeout = 1000;
                using (var resp = (HttpWebResponse)req.GetResponse())
                    return resp.StatusCode == HttpStatusCode.OK;
            }
            catch { return false; }
        }

        private static string LeerUrl()
        {
            try
            {
                var f = Path.Combine(Estado, "chat_url.txt");
                return File.Exists(f) ? File.ReadAllText(f).Trim() : null;
            }
            catch { return null; }
        }

        private static string AsegurarServidor()
        {
            var url = LeerUrl();
            if (url != null && Responde(url)) return url;

            var lanzador = Path.Combine(Estado, "chat_launcher.json");
            if (!File.Exists(lanzador))
            {
                Decir("[MCPCHAT] Falta registrar el servidor de chat. Corre una vez:  python mcp_server\\chat_server.py --registrar");
                return null;
            }
            string python, script, cwd;
            try
            {
                using (var doc = JsonDocument.Parse(File.ReadAllText(lanzador)))
                {
                    python = doc.RootElement.GetProperty("python").GetString();
                    script = doc.RootElement.GetProperty("script").GetString();
                    cwd = doc.RootElement.GetProperty("cwd").GetString();
                }
            }
            catch (System.Exception ex)
            {
                Decir("[MCPCHAT] chat_launcher.json está dañado: " + ex.Message);
                return null;
            }
            if (!File.Exists(script))
            {
                Decir("[MCPCHAT] No encuentro " + script + ". Vuelve a registrar el servidor de chat con --registrar.");
                return null;
            }
            // pythonw no abre ventana de consola
            var pw = Path.Combine(Path.GetDirectoryName(python) ?? "", "pythonw.exe");
            var exe = File.Exists(pw) ? pw : python;
            Decir("[MCPCHAT] Arrancando el servidor de chat…");
            try
            {
                Process.Start(new ProcessStartInfo(exe, "\"" + script + "\"")
                {
                    WorkingDirectory = cwd,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                });
            }
            catch (System.Exception ex)
            {
                Decir("[MCPCHAT] No pude arrancar Python (" + exe + "): " + ex.Message);
                return null;
            }
            var limite = DateTime.UtcNow.AddSeconds(30);
            while (DateTime.UtcNow < limite)
            {
                Thread.Sleep(300);
                System.Windows.Forms.Application.DoEvents();
                url = LeerUrl();
                if (url != null && Responde(url)) return url;
            }
            Decir("[MCPCHAT] El servidor de chat no respondió en 30 s. Pruébalo a mano:  python mcp_server\\chat_server.py");
            return null;
        }
    }
}
