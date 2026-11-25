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

            // AutoCAD 2022 tira NullReferenceException en su PROPIO
            // CommandEditor (set_IsBusy, via el evento Idle) al abrir y
            // cerrar documentos rapido por API -- el plugin ni aparece en el
            // stack -- y el dialogo de "Unhandled exception" que muestra
            // congela el socket hasta que un humano clickea Continue: paso
            // de verdad, tres veces, corriendo test_live.py. Dos defensas:
            // el handler (por si la excepcion viene por la ruta WinForms
            // normal) y el watchdog (para el caso real: AutoCAD crea el
            // dialogo directo y el handler no lo ve -- ver DialogWatchdog).
            System.Windows.Forms.Application.ThreadException += OnUiThreadException;
            DialogWatchdog.Start();

            int port = 8765;
            var envPort = Environment.GetEnvironmentVariable("ACAD_MCP_PORT");
            if (!string.IsNullOrEmpty(envPort) && int.TryParse(envPort, out var parsed))
                port = parsed;

            try
            {
                MainThreadQueue.EnsureHooked();
                _server = new TcpServer(port);
                _server.Start();
                PublishPort(_server.Port);

                if (_server.Port != port)
                {
                    Log($"[MCP] El puerto {port} estaba ocupado por otro programa. " +
                        $"Plugin cargado escuchando en 127.0.0.1:{_server.Port}");
                }
                else
                {
                    Log($"[MCP] Plugin cargado. Escuchando en 127.0.0.1:{_server.Port}");
                }
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
            ProgramarChatAutomatico();
        }

        public void Terminate()
        {
            DialogWatchdog.Stop();
            System.Windows.Forms.Application.ThreadException -= OnUiThreadException;
            Application.DocumentManager.DocumentActivated -= OnDocumentActivated;
            _server?.Stop();
            try { if (File.Exists(PortFilePath)) File.Delete(PortFilePath); } catch { }
            try { if (File.Exists(TokenFilePath)) File.Delete(TokenFilePath); } catch { }
        }

        /// <summary>
        /// Token de acceso al puerto (TcpServer.Token), junto al archivo "port". %LOCALAPPDATA% ya es solo del
        /// usuario; además, en net48, se le quitan los permisos heredados y queda solo para el usuario actual.
        /// </summary>
        internal static string TokenFilePath => Path.Combine(Path.GetDirectoryName(PortFilePath), "token");

        private static void PublishToken()
        {
            try
            {
                File.WriteAllText(TokenFilePath, TcpServer.Token);
#if NETFRAMEWORK
                try
                {
                    var sec = new System.Security.AccessControl.FileSecurity();
                    sec.SetAccessRuleProtection(true, false);
                    sec.AddAccessRule(new System.Security.AccessControl.FileSystemAccessRule(
                        System.Security.Principal.WindowsIdentity.GetCurrent().User,
                        System.Security.AccessControl.FileSystemRights.FullControl,
                        System.Security.AccessControl.AccessControlType.Allow));
                    File.SetAccessControl(TokenFilePath, sec);
                }
                catch (System.Exception) { }
#endif
            }
            catch (System.Exception ex)
            {
                Log("[MCP] No se pudo anotar el token de acceso (" + ex.Message + "): el servidor MCP no podrá conectarse.");
            }
        }

        private static void OnUiThreadException(object sender,
            System.Threading.ThreadExceptionEventArgs e)
        {
            // Equivalente a clickear "Continue" en el dialogo que esto
            // reemplaza: se ignora y la aplicacion sigue. Solo se anota.
            try
            {
                Log("[MCP] Excepcion no manejada en el hilo de UI (ignorada, " +
                    "como haria el boton Continue): " + e.Exception.Message);
            }
            catch { }
        }

        /// <summary>
        /// Archivo donde queda anotado el puerto real, para que el cliente lo
        /// encuentre sin configurar nada aunque no sea el puerto por defecto.
        /// </summary>
        internal static string PortFilePath
        {
            get
            {
                var dir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "AutoCadMcp");
                return Path.Combine(dir, "port");
            }
        }

        private static void PublishPort(int port)
        {
            try
            {
                var dir = Path.GetDirectoryName(PortFilePath);
                if (!Directory.Exists(dir))
                    Directory.CreateDirectory(dir);
                PublishToken();   // antes que el puerto: quien lea el puerto ya encuentra el token
                File.WriteAllText(PortFilePath, port.ToString());
            }
            catch (System.Exception)
            {
                // Que no se pueda anotar el puerto no justifica no arrancar:
                // con el puerto por defecto el cliente lo encuentra igual.
            }
        }

        // ---- el chat se abre solo al arrancar AutoCAD (sin teclear MCPCHAT cada vez)

        private static DateTime _chatDesde;

        /// <summary>
        /// Abre el panel del chat unos segundos después de que AutoCAD esté ocioso con un dibujo abierto. Se apaga creando
        /// el archivo %LOCALAPPDATA%\AutoCadMcp\sin_chat_automatico (o cerrando el panel: AutoCAD recuerda que se cerró
        /// solo en esa sesión; el comando MCPCHAT lo vuelve a mostrar).
        /// </summary>
        private static void ProgramarChatAutomatico()
        {
            try
            {
                var marca = Path.Combine(Path.GetDirectoryName(PortFilePath), "sin_chat_automatico");
                if (File.Exists(marca)) return;
                Application.Idle += AbrirChatCuandoEsteListo;
            }
            catch (System.Exception) { }
        }

        private static void AbrirChatCuandoEsteListo(object sender, EventArgs e)
        {
            try
            {
                if (Application.DocumentManager.MdiActiveDocument == null) return;
                if (_chatDesde == default(DateTime)) { _chatDesde = DateTime.UtcNow; return; }
                if ((DateTime.UtcNow - _chatDesde).TotalSeconds < 4) return;     // deja que AutoCAD termine de cargar
                Application.Idle -= AbrirChatCuandoEsteListo;
                Commands.ChatNativo.Mostrar();
            }
            catch (System.Exception)
            {
                Application.Idle -= AbrirChatCuandoEsteListo;
            }
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
