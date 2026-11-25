using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Servidor TCP simple en loopback. Protocolo: una línea de texto = un
    /// request JSON, una línea de respuesta = un response JSON. Cada cliente
    /// se atiende en su propio hilo; el trabajo real contra la base de datos
    /// de AutoCAD se marshaliza al hilo de documento dentro de CommandDispatcher.
    /// </summary>
    public class TcpServer
    {
        /// <summary>Cuantos puertos probar despues del pedido, si esta ocupado.</summary>
        private const int PortSearchRange = 20;

        private readonly int _requestedPort;
        private TcpListener _listener;
        private Thread _acceptThread;
        private volatile bool _running;

        public TcpServer(int port)
        {
            _requestedPort = port;
        }

        /// <summary>Puerto en el que quedo escuchando de verdad (0 si no arranco).</summary>
        public int Port { get; private set; }

        /// <summary>
        /// Arranca en el puerto pedido o, si esta ocupado por otro programa, en
        /// el primero libre despues de ese. Pasa seguido: cualquier servicio de
        /// desarrollo (Docker, un dev server) puede haberse quedado con el
        /// 8765, y antes eso dejaba el plugin mudo sin explicacion.
        /// </summary>
        public void Start()
        {
            SocketException last = null;

            for (int offset = 0; offset <= PortSearchRange; offset++)
            {
                int candidate = _requestedPort + offset;
                var listener = new TcpListener(IPAddress.Loopback, candidate);
                try
                {
                    listener.Start();
                    _listener = listener;
                    Port = candidate;
                    _running = true;

                    _acceptThread = new Thread(AcceptLoop)
                    {
                        IsBackground = true,
                        Name = "AutoCadMcp-Accept"
                    };
                    _acceptThread.Start();
                    return;
                }
                catch (SocketException ex)
                {
                    last = ex;
                    try { listener.Stop(); } catch { }
                }
            }

            throw new InvalidOperationException(
                $"No se pudo escuchar en ningun puerto entre {_requestedPort} y " +
                $"{_requestedPort + PortSearchRange}. Ultimo error: {last?.Message}");
        }

        public void Stop()
        {
            _running = false;
            try { _listener?.Stop(); } catch { /* ya cerrado */ }
        }

        private void AcceptLoop()
        {
            while (_running)
            {
                TcpClient client;
                try
                {
                    client = _listener.AcceptTcpClient();
                }
                catch
                {
                    break; // listener detenido
                }

                var clientThread = new Thread(() => SafeHandleClient(client))
                {
                    IsBackground = true,
                    Name = "AutoCadMcp-Client"
                };
                clientThread.Start();
            }
        }

        /// <summary>
        /// CUALQUIER excepción que escape de un hilo de fondo mata el proceso
        /// entero — o sea, se cae AutoCAD con el dibujo del usuario adentro.
        /// El caso normal que la dispara: el cliente Python corta la conexión
        /// (timeout, Claude reiniciando el server) y el ReadLine/WriteLine de
        /// abajo tira IOException. Nada de lo que pase con un cliente puede
        /// escaparse de este método.
        /// </summary>
        private void SafeHandleClient(TcpClient client)
        {
            try
            {
                HandleClient(client);
            }
            catch (Exception ex)
            {
                LogQuietly(ex);
            }
        }

        private void HandleClient(TcpClient client)
        {
            using (client)
            using (var stream = client.GetStream())
            using (var reader = new StreamReader(stream, Encoding.UTF8))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true })
            {
                string line;
                while (_running && (line = reader.ReadLine()) != null)
                {
                    if (string.IsNullOrWhiteSpace(line))
                        continue;

                    // Autenticación: cualquier programa (o una página web con un POST a 127.0.0.1) puede abrir el
                    // puerto. Cada línea tiene que ser un JSON con el "token" que el plugin anotó al arrancar; a la
                    // primera que no lo sea se corta la conexión (eso también mata las cabeceras HTTP colgadas).
                    string motivo = MotivoRechazo(line);
                    if (motivo != null)
                    {
                        if (motivo.Length > 0)
                            try { writer.WriteLine(CommandDispatcher.ErrorResponse(motivo)); } catch (IOException) { }
                        break;
                    }

                    string response = CommandDispatcher.Dispatch(line);

                    try
                    {
                        writer.WriteLine(response);
                    }
                    catch (IOException)
                    {
                        // El cliente ya se fue (típicamente por timeout). El
                        // comando YA se ejecutó sobre el dibujo; no hay nada
                        // que reintentar, solo dejar de escribir.
                        break;
                    }
                }
            }
        }

        // ------------------------------------------------------------ token de acceso

        /// <summary>
        /// Token aleatorio de esta sesión de AutoCAD (32 bytes en hex). PluginEntry lo anota junto al archivo
        /// "port"; el cliente Python lo lee y lo manda en cada pedido.
        /// </summary>
        public static readonly string Token = NuevoToken();

        private static string NuevoToken()
        {
            var b = new byte[32];
            using (var rng = System.Security.Cryptography.RandomNumberGenerator.Create()) rng.GetBytes(b);
            var sb = new StringBuilder(64);
            foreach (var x in b) sb.Append(x.ToString("x2"));
            return sb.ToString();
        }

        private static readonly string[] PrefijosHttp =
        {
            "GET ", "POST ", "PUT ", "HEAD ", "DELETE ", "OPTIONS ", "PATCH ", "CONNECT ", "TRACE ", "HTTP/",
        };

        /// <summary>Comparación en tiempo constante (no revela cuántos caracteres coinciden).</summary>
        internal static bool IgualConstante(string a, string b)
        {
            if (a == null || b == null) return false;
            int dif = a.Length ^ b.Length;
            for (int i = 0; i < b.Length; i++)
                dif |= (i < a.Length ? a[i] : 0) ^ b[i];
            return dif == 0;
        }

        /// <summary>
        /// null si la línea se atiende; "" si se corta sin contestar (no es JSON: HTTP u otra cosa);
        /// un texto si se contesta ese error y se corta (JSON sin token o con uno equivocado).
        /// </summary>
        internal static string MotivoRechazo(string line)
        {
            string t = line.TrimStart();
            foreach (var p in PrefijosHttp)
                if (t.StartsWith(p, StringComparison.OrdinalIgnoreCase)) return "";
            if (!t.StartsWith("{")) return "";
            string token;
            try
            {
                var obj = System.Text.Json.Nodes.JsonNode.Parse(t) as System.Text.Json.Nodes.JsonObject;
                if (obj == null) return "";
                var nodo = obj["token"];
                token = nodo != null && nodo.GetValueKind() == System.Text.Json.JsonValueKind.String ? nodo.GetValue<string>() : null;
            }
            catch (Exception) { return ""; }
            if (!IgualConstante(token, Token))
                return "TOKEN: pedido sin el token de acceso de esta sesión de AutoCAD (o con uno viejo). " +
                       "El cliente lo lee del archivo 'token' junto a 'port' en %LOCALAPPDATA%\\AutoCadMcp: " +
                       "actualiza el servidor MCP o reinicia AutoCAD.";
            return null;
        }

        /// <summary>
        /// Nada de tocar la API de AutoCAD (Editor incluido) desde el hilo del
        /// socket: es justo lo que estamos evitando. Trace no depende del hilo
        /// principal y se ve con DebugView o un debugger enganchado.
        /// </summary>
        private static void LogQuietly(Exception ex)
        {
            try { System.Diagnostics.Trace.WriteLine("[MCP] Conexion terminada con error: " + ex); }
            catch { /* ni siquiera loguear puede tirar hacia arriba desde este hilo */ }
        }
    }
}
