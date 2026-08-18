using System;
using System.IO;
using System.Reflection;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Runtime;

[assembly: ExtensionApplication(typeof(AutoCadMcpPlugin.PluginEntry))]

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Punto de entrada del plugin. AutoCAD llama Initialize() al cargar el DLL
    /// (vía NETLOAD manual, o automático si se registra en el App Bundle),
    /// y Terminate() al descargarlo o cerrar AutoCAD.
    /// </summary>
    public class PluginEntry : IExtensionApplication
    {
        private static TcpServer _server;

        public void Initialize()
        {
            // AutoCAD (acad.exe) resuelve ensamblados desde su propia carpeta,
            // no desde la del plugin. Las dependencias que trajimos por NuGet
            // (System.Text.Json y las suyas: System.Runtime.CompilerServices.
            // Unsafe, System.Buffers, System.Memory, etc.) viven al lado del
            // DLL del plugin, así que hay que buscarlas ahí a mano o el primer
            // uso de System.Text.Json tira una excepción no controlada que
            // crashea AutoCAD entero.
            AppDomain.CurrentDomain.AssemblyResolve += ResolvePluginDependency;

            int port = 8765;
            var envPort = Environment.GetEnvironmentVariable("ACAD_MCP_PORT");
            if (!string.IsNullOrEmpty(envPort) && int.TryParse(envPort, out var parsed))
                port = parsed;

            try
            {
                MainThreadQueue.EnsureHooked();
                _server = new TcpServer(port);
                _server.Start();
                Log($"[MCP] Plugin cargado. Escuchando en 127.0.0.1:{port}");
            }
            catch (System.Exception ex)
            {
                Log($"[MCP] ERROR al iniciar el servidor: {ex.Message}");
            }

            // LWDISPLAY viene apagado de fábrica y se guarda POR DIBUJO: sin
            // esto, todo lo que dibujemos se ve a 1 píxel por más que la capa
            // tenga 0.50mm, y abrir otro DWG lo vuelve a apagar. Por eso se
            // aplica al documento actual y a cada uno que se active después.
            EnableLineweightDisplay();
            Application.DocumentManager.DocumentActivated += OnDocumentActivated;
        }

        public void Terminate()
        {
            Application.DocumentManager.DocumentActivated -= OnDocumentActivated;
            _server?.Stop();
        }

        private static void OnDocumentActivated(object sender, DocumentCollectionEventArgs e)
        {
            EnableLineweightDisplay();
        }

        private static void EnableLineweightDisplay()
        {
            try
            {
                if (Application.DocumentManager.MdiActiveDocument == null)
                    return;
                Application.SetSystemVariable("LWDISPLAY", (short)1);
            }
            catch (System.Exception)
            {
                // Que no se vean los grosores no justifica romper la carga del
                // plugin; set_display_options queda para activarlo a mano.
            }
        }

        private static Assembly ResolvePluginDependency(object sender, ResolveEventArgs args)
        {
            var name = new AssemblyName(args.Name).Name;
            var pluginDir = Path.GetDirectoryName(typeof(PluginEntry).Assembly.Location);
            var candidate = Path.Combine(pluginDir, name + ".dll");
            return File.Exists(candidate) ? Assembly.LoadFrom(candidate) : null;
        }

        private static void Log(string message)
        {
            var doc = Application.DocumentManager.MdiActiveDocument;
            doc?.Editor.WriteMessage("\n" + message + "\n");
        }
    }
}
