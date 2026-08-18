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
        private readonly int _port;
        private TcpListener _listener;
        private Thread _acceptThread;
        private volatile bool _running;

        public TcpServer(int port)
        {
            _port = port;
        }

        public void Start()
        {
            _listener = new TcpListener(IPAddress.Loopback, _port);
            _listener.Start();
            _running = true;

            _acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "AutoCadMcp-Accept" };
            _acceptThread.Start();
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
