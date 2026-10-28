using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>
    /// Un error que el servidor del chat explicó (código HTTP distinto de 200 con {"error": "..."}).
    /// </summary>
    internal sealed class ChatError : Exception
    {
        public ChatError(string mensaje) : base(mensaje) { }
    }

    /// <summary>
    /// El panel nativo no tiene su propio cerebro: le habla por HTTP local al mismo servidor Python que usa la interfaz
    /// web (agent/web.py): proveedores, claves, herramientas, perfiles, costo y el modo «En vivo». Esta clase es solo
    /// el cliente: JSON de ida y vuelta y la lectura del flujo SSE de /api/chat.
    /// </summary>
    internal sealed class ChatCliente : IDisposable
    {
        private readonly HttpClient _http;

        public string Base { get; }

        public ChatCliente(string url)
        {
            // La URL que anota el servidor trae un ?v=hora para que MCPCHAT recargue páginas; para la API no sirve.
            var corte = url.IndexOf('?');
            Base = (corte >= 0 ? url.Substring(0, corte) : url).TrimEnd('/');
            _http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        }

        public async Task<JsonDocument> GetAsync(string ruta, CancellationToken ct = default)
        {
            using (var r = await _http.GetAsync(Base + ruta, ct).ConfigureAwait(true))
                return await LeerAsync(r).ConfigureAwait(true);
        }

        public async Task<JsonDocument> PostAsync(string ruta, object cuerpo, CancellationToken ct = default)
        {
            using (var contenido = new StringContent(JsonSerializer.Serialize(cuerpo ?? new { }), Encoding.UTF8, "application/json"))
            using (var r = await _http.PostAsync(Base + ruta, contenido, ct).ConfigureAwait(true))
                return await LeerAsync(r).ConfigureAwait(true);
        }

        private static async Task<JsonDocument> LeerAsync(HttpResponseMessage r)
        {
            var texto = await r.Content.ReadAsStringAsync().ConfigureAwait(true);
            JsonDocument doc = null;
            try { doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(texto) ? "{}" : texto); } catch (JsonException) { }
            if (!r.IsSuccessStatusCode)
            {
                string msg = null;
                if (doc != null && doc.RootElement.ValueKind == JsonValueKind.Object &&
                    doc.RootElement.TryGetProperty("error", out var e) && e.ValueKind == JsonValueKind.String)
                    msg = e.GetString();
                throw new ChatError(msg ?? ("El servidor respondió " + (int)r.StatusCode + "."));
            }
            return doc ?? JsonDocument.Parse("{}");
        }

        /// <summary>
        /// Manda un pedido a /api/chat y entrega cada evento del flujo SSE a medida que llega. Los eventos se
        /// entregan en el hilo que llamó (el de la interfaz), así que el panel puede tocar sus controles directo.
        /// </summary>
        public async Task ChatAsync(object cuerpo, Action<JsonElement> alEvento, CancellationToken ct)
        {
            using (var contenido = new StringContent(JsonSerializer.Serialize(cuerpo), Encoding.UTF8, "application/json"))
            using (var pedido = new HttpRequestMessage(HttpMethod.Post, Base + "/api/chat") { Content = contenido })
            using (var r = await _http.SendAsync(pedido, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(true))
            {
                if (!r.IsSuccessStatusCode)
                {
                    using (await LeerAsync(r).ConfigureAwait(true)) { }
                    return;
                }
                // Cancelar cierra la respuesta: la lectura que está esperando una línea termina con una excepción.
                using (ct.Register(() => r.Dispose()))
                using (var flujo = await r.Content.ReadAsStreamAsync().ConfigureAwait(true))
                using (var lector = new StreamReader(flujo, Encoding.UTF8))
                {
                    string linea;
                    try
                    {
                        while ((linea = await lector.ReadLineAsync().ConfigureAwait(true)) != null)
                        {
                            if (!linea.StartsWith("data: ", StringComparison.Ordinal)) continue;
                            JsonDocument ev;
                            try { ev = JsonDocument.Parse(linea.Substring(6)); } catch (JsonException) { continue; }
                            using (ev)
                                alEvento(ev.RootElement);
                        }
                    }
                    catch (ObjectDisposedException) when (ct.IsCancellationRequested) { }
                    catch (IOException) when (ct.IsCancellationRequested) { }
                }
            }
        }

        public void Dispose() => _http.Dispose();
    }

    /// <summary>
    /// Que el servidor del chat esté corriendo (lo arranca el plugin con pythonw si hace falta). Es la misma lógica que
    /// usa el panel web (ChatPalette) pero sin bloquear a AutoCAD: espera con await en vez de con DoEvents.
    /// </summary>
    internal static class ServidorChat
    {
        private static string Estado =>
            Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp");

        /// <summary>La URL del servidor listo, o null (con el motivo en <paramref name="problema"/>).</summary>
        public static async Task<(string url, string problema)> AsegurarAsync()
        {
            var url = LeerUrl();
            if (url != null && await RespondeAsync(url).ConfigureAwait(true)) return (url, null);

            var lanzador = Path.Combine(Estado, "chat_launcher.json");
            if (!File.Exists(lanzador))
                return (null, "Falta registrar el servidor del chat. Corre una vez:  python iniciar_en_autocad.py --registrar");
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
            catch (Exception ex) { return (null, "chat_launcher.json está dañado: " + ex.Message); }
            if (!File.Exists(script))
                return (null, "No encuentro " + script + ". Vuelve a registrar el servidor con  --registrar.");

            var pw = Path.Combine(Path.GetDirectoryName(python) ?? "", "pythonw.exe");   // pythonw: sin ventana de consola
            var exe = File.Exists(pw) ? pw : python;
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
            catch (Exception ex) { return (null, "No pude arrancar Python (" + exe + "): " + ex.Message); }

            var limite = DateTime.UtcNow.AddSeconds(40);
            while (DateTime.UtcNow < limite)
            {
                await Task.Delay(400).ConfigureAwait(true);
                url = LeerUrl();
                if (url != null && await RespondeAsync(url).ConfigureAwait(true)) return (url, null);
            }
            return (null, "El servidor del chat no respondió en 40 s.");
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

        private static async Task<bool> RespondeAsync(string url)
        {
            try
            {
                var corte = url.IndexOf('?');
                var baseUrl = (corte >= 0 ? url.Substring(0, corte) : url).TrimEnd('/');
                using (var http = new HttpClient { Timeout = TimeSpan.FromSeconds(1.5) })
                using (var r = await http.GetAsync(baseUrl + "/api/ping").ConfigureAwait(true))
                    return r.IsSuccessStatusCode;
            }
            catch { return false; }
        }
    }
}
