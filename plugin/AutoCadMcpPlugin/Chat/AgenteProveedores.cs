using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>Falla al hablar con la API del modelo.</summary>
    internal class ErrorProveedor : Exception
    {
        public ErrorProveedor(string mensaje) : base(mensaje) { }
    }

    /// <summary>
    /// El modelo pidió una herramienta que no estaba en el catálogo que se le mandó. Groq y otros rechazan el pedido ENTERO
    /// con un 400 en vez de devolver la llamada: es un error del MODELO, y vuelve a él para que lo corrija.
    /// </summary>
    internal sealed class ToolInvalida : ErrorProveedor
    {
        public string Tool { get; }
        public ToolInvalida(string mensaje, string tool) : base(mensaje) { Tool = tool; }
    }

    /// <summary>Tokens gastados, tal como los informa el proveedor (no se estiman).</summary>
    internal sealed class UsoTokens
    {
        public long Entrada, Salida;
        public int Vueltas;
        public long Total => Entrada + Salida;

        public void Anotar(JsonNode uso)
        {
            if (!(uso is JsonObject o)) return;
            Entrada += Largo(o, "prompt_tokens") + Largo(o, "input_tokens");
            Salida += Largo(o, "completion_tokens") + Largo(o, "output_tokens");
            Vueltas++;
        }

        private static long Largo(JsonObject o, string clave)
        {
            try { return o[clave] == null ? 0 : o[clave].GetValue<long>(); }
            catch (Exception) { return 0; }
        }
    }

    /// <summary>Un modelo al que se le pide la siguiente respuesta de la conversación.</summary>
    internal interface IProveedorModelo
    {
        string Modelo { get; }
        UsoTokens Uso { get; }

        /// <summary>
        /// La conversación va SIEMPRE en el formato de OpenAI (role system/user/assistant/tool, tool_calls); cada proveedor la
        /// traduce a lo suyo. Devuelve el mensaje del asistente en ese mismo formato: content (texto o null) y tool_calls.
        /// </summary>
        Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct);
    }

    internal static class ClienteHttp
    {
        public static readonly HttpClient Http = Crear();

        private static HttpClient Crear()
        {
#if NETFRAMEWORK
            // AutoCAD 2022 corre en .NET Framework: sin esto algunas instalaciones negocian un TLS que los proveedores rechazan.
            System.Net.ServicePointManager.SecurityProtocol |= System.Net.SecurityProtocolType.Tls12;
#endif
            return new HttpClient { Timeout = TimeSpan.FromSeconds(180) };
        }

        public static async Task<(int codigo, string texto)> PostAsync(string url, JsonObject cuerpo,
            Action<HttpRequestMessage> cabeceras, CancellationToken ct)
        {
            using (var pedido = new HttpRequestMessage(HttpMethod.Post, url))
            {
                pedido.Content = new StringContent(cuerpo.ToJsonString(), Encoding.UTF8, "application/json");
                cabeceras?.Invoke(pedido);
                try
                {
                    using (var r = await Http.SendAsync(pedido, ct).ConfigureAwait(true))
                    {
                        var texto = await r.Content.ReadAsStringAsync().ConfigureAwait(true);
                        return ((int)r.StatusCode, texto);
                    }
                }
                catch (HttpRequestException ex) { throw new ErrorProveedor("No se pudo llamar a " + url + ": " + ex.Message); }
                catch (TaskCanceledException) when (!ct.IsCancellationRequested)
                {
                    throw new ErrorProveedor("El modelo tardó más de 180 s en contestar (" + url + ").");
                }
            }
        }

        /// <summary>El 400 que corresponda: una herramienta inexistente se distingue del resto.</summary>
        public static ErrorProveedor ErrorDeRespuesta(int codigo, string texto)
        {
            string mensaje = "", clave = "";
            try
            {
                var e = JsonNode.Parse(texto)?["error"];
                mensaje = e?["message"]?.ToString() ?? "";
                clave = e?["code"]?.ToString() ?? "";
            }
            catch (Exception) { }
            if (clave == "tool_use_failed" || mensaje.Contains("not in request.tools"))
            {
                var m = Regex.Match(mensaje, "tool '([^']+)'");
                var nombre = m.Success ? m.Groups[1].Value : "";
                return new ToolInvalida("El modelo pidió la tool '" + (nombre.Length > 0 ? nombre : "?") + "', que no está en el perfil elegido.", nombre);
            }
            return new ErrorProveedor("El modelo respondió " + codigo + ": " + (texto.Length > 600 ? texto.Substring(0, 600) : texto));
        }
    }

    /// <summary>/chat/completions con tools: el formato de OpenAI, Groq, OpenRouter, DeepSeek, Together y los servidores locales.</summary>
    internal sealed class ProveedorOpenAI : IProveedorModelo
    {
        private readonly string _url, _clave;
        private readonly double? _temperatura;
        public string Modelo { get; }
        public UsoTokens Uso { get; } = new UsoTokens();

        public ProveedorOpenAI(string url, string clave, string modelo, double? temperatura)
        {
            _url = url.TrimEnd('/'); _clave = clave; Modelo = modelo; _temperatura = temperatura;
        }

        public async Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct)
        {
            var cuerpo = new JsonObject { ["model"] = Modelo, ["messages"] = mensajes.DeepClone() };
            if (tools != null && tools.Count > 0)
            {
                cuerpo["tools"] = tools.DeepClone();
                cuerpo["tool_choice"] = "auto";
            }
            if (_temperatura.HasValue) cuerpo["temperature"] = _temperatura.Value;

            var (codigo, texto) = await ClienteHttp.PostAsync(_url + "/chat/completions", cuerpo, p =>
            {
                if (!string.IsNullOrEmpty(_clave))
                    p.Headers.TryAddWithoutValidation("Authorization", "Bearer " + _clave);
                p.Headers.TryAddWithoutValidation("X-Title", "AutoCAD MCP");
            }, ct).ConfigureAwait(true);
            if (codigo >= 400) throw ClienteHttp.ErrorDeRespuesta(codigo, texto);

            JsonNode datos;
            try { datos = JsonNode.Parse(texto); }
            catch (JsonException) { throw new ErrorProveedor("Respuesta que no es JSON: " + (texto.Length > 300 ? texto.Substring(0, 300) : texto)); }
            var choices = datos?["choices"] as JsonArray;
            if (choices == null || choices.Count == 0)
                throw new ErrorProveedor("Respuesta sin 'choices': " + (texto.Length > 400 ? texto.Substring(0, 400) : texto));
            Uso.Anotar(datos["usage"]);
            return (JsonObject)choices[0]["message"].DeepClone();
        }
    }

    /// <summary>/messages de Anthropic: otro formato de tools; la conversación se traduce al vuelo.</summary>
    internal sealed class ProveedorAnthropic : IProveedorModelo
    {
        private readonly string _url, _clave;
        private readonly double? _temperatura;
        public string Modelo { get; }
        public UsoTokens Uso { get; } = new UsoTokens();

        public ProveedorAnthropic(string url, string clave, string modelo, double? temperatura)
        {
            _url = url.TrimEnd('/'); _clave = clave; Modelo = modelo; _temperatura = temperatura;
        }

        public async Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct)
        {
            var (sistema, conversacion) = Traducir(mensajes);
            var cuerpo = new JsonObject { ["model"] = Modelo, ["max_tokens"] = 8192, ["messages"] = conversacion };
            if (sistema.Length > 0) cuerpo["system"] = sistema;
            if (tools != null && tools.Count > 0)
            {
                var ts = new JsonArray();
                foreach (var t in tools)
                {
                    var f = t["function"];
                    ts.Add(new JsonObject
                    {
                        ["name"] = f["name"]?.ToString(),
                        ["description"] = f["description"]?.ToString() ?? "",
                        ["input_schema"] = f["parameters"]?.DeepClone() ?? new JsonObject { ["type"] = "object" },
                    });
                }
                cuerpo["tools"] = ts;
            }
            if (_temperatura.HasValue) cuerpo["temperature"] = Math.Min(1.0, _temperatura.Value);

            var (codigo, texto) = await ClienteHttp.PostAsync(_url + "/messages", cuerpo, p =>
            {
                p.Headers.TryAddWithoutValidation("x-api-key", _clave ?? "");
                p.Headers.TryAddWithoutValidation("anthropic-version", "2023-06-01");
            }, ct).ConfigureAwait(true);
            if (codigo >= 400) throw new ErrorProveedor("El modelo respondió " + codigo + ": " + (texto.Length > 600 ? texto.Substring(0, 600) : texto));

            JsonNode datos;
            try { datos = JsonNode.Parse(texto); }
            catch (JsonException) { throw new ErrorProveedor("Respuesta que no es JSON: " + (texto.Length > 300 ? texto.Substring(0, 300) : texto)); }
            Uso.Anotar(datos?["usage"]);
            return AMensajeOpenAI(datos as JsonObject);
        }

        /// <summary>Del formato de la conversación (OpenAI) al de Anthropic: system aparte, tool_use y tool_result en bloques.</summary>
        internal static (string sistema, JsonArray conversacion) Traducir(JsonArray mensajes)
        {
            var sistema = new StringBuilder();
            var salida = new JsonArray();
            JsonArray resultados = null;       // tool_result consecutivos van juntos en UN mensaje 'user'
            foreach (var n in mensajes)
            {
                var m = (JsonObject)n;
                var rol = m["role"]?.ToString();
                if (rol != "tool") resultados = null;
                switch (rol)
                {
                    case "system":
                        if (sistema.Length > 0) sistema.Append("\n\n");
                        sistema.Append(m["content"]?.ToString());
                        break;
                    case "user":
                        salida.Add(new JsonObject { ["role"] = "user", ["content"] = m["content"]?.DeepClone() ?? "" });
                        break;
                    case "assistant":
                    {
                        var bloques = new JsonArray();
                        var txt = m["content"]?.ToString();
                        if (!string.IsNullOrEmpty(txt)) bloques.Add(new JsonObject { ["type"] = "text", ["text"] = txt });
                        if (m["tool_calls"] is JsonArray llamadas)
                            foreach (var c in llamadas)
                            {
                                JsonNode entrada = null;
                                try { entrada = JsonNode.Parse(c["function"]?["arguments"]?.ToString() ?? "{}"); } catch (JsonException) { }
                                bloques.Add(new JsonObject
                                {
                                    ["type"] = "tool_use", ["id"] = c["id"]?.ToString(), ["name"] = c["function"]?["name"]?.ToString(),
                                    ["input"] = entrada is JsonObject ? entrada : new JsonObject(),
                                });
                            }
                        if (bloques.Count == 0) bloques.Add(new JsonObject { ["type"] = "text", ["text"] = "(sin texto)" });
                        salida.Add(new JsonObject { ["role"] = "assistant", ["content"] = bloques });
                        break;
                    }
                    case "tool":
                        if (resultados == null)
                        {
                            resultados = new JsonArray();
                            salida.Add(new JsonObject { ["role"] = "user", ["content"] = resultados });
                        }
                        resultados.Add(new JsonObject { ["type"] = "tool_result", ["tool_use_id"] = m["tool_call_id"]?.ToString(), ["content"] = m["content"]?.ToString() ?? "" });
                        break;
                }
            }
            return (sistema.ToString(), salida);
        }

        /// <summary>De la respuesta de Anthropic (bloques) al mensaje del asistente en formato OpenAI.</summary>
        internal static JsonObject AMensajeOpenAI(JsonObject datos)
        {
            var texto = new StringBuilder();
            var llamadas = new JsonArray();
            if (datos?["content"] is JsonArray bloques)
                foreach (var b in bloques)
                {
                    var tipo = b["type"]?.ToString();
                    if (tipo == "text") { if (texto.Length > 0) texto.Append("\n"); texto.Append(b["text"]?.ToString()); }
                    else if (tipo == "tool_use")
                        llamadas.Add(new JsonObject
                        {
                            ["id"] = b["id"]?.ToString(), ["type"] = "function",
                            ["function"] = new JsonObject { ["name"] = b["name"]?.ToString(), ["arguments"] = (b["input"] ?? new JsonObject()).ToJsonString() },
                        });
                }
            var m = new JsonObject { ["role"] = "assistant", ["content"] = texto.Length > 0 ? texto.ToString() : null };
            if (llamadas.Count > 0) m["tool_calls"] = llamadas;
            return m;
        }
    }

    /// <summary>
    /// Las claves que guardó el servidor Python (credenciales.json): cifradas con DPAPI, atadas a este usuario de Windows. Se
    /// leen aquí mismo para que el agente nativo hable con el proveedor sin pasar la clave por ninguna otra parte.
    /// Orden: variable de entorno del proveedor, y luego lo guardado.
    /// </summary>
    internal static class Credenciales
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct DataBlob { public int cbData; public IntPtr pbData; }

        [DllImport("crypt32.dll", SetLastError = true)]
        private static extern bool CryptUnprotectData(ref DataBlob entrada, IntPtr descripcion, IntPtr entropia, IntPtr reservado,
            IntPtr prompt, int flags, ref DataBlob salida);

        [DllImport("kernel32.dll")]
        private static extern IntPtr LocalFree(IntPtr memoria);

        private static string Archivo =>
            Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp", "credenciales.json");

        public static string Obtener(string proveedor, string variableEntorno)
        {
            if (!string.IsNullOrEmpty(variableEntorno))
            {
                var env = Environment.GetEnvironmentVariable(variableEntorno);
                if (!string.IsNullOrEmpty(env)) return env;
            }
            try
            {
                if (!File.Exists(Archivo)) return null;
                var raiz = JsonNode.Parse(File.ReadAllText(Archivo, Encoding.UTF8)) as JsonObject;
                return Revelar(raiz?[proveedor]);
            }
            catch (Exception) { return null; }
        }

        internal static string Revelar(JsonNode entrada)
        {
            if (entrada == null) return null;
            if (entrada is JsonValue v && v.TryGetValue<string>(out var viejo)) return viejo;     // formato viejo, sin envoltorio
            if (!(entrada is JsonObject o)) return null;
            var modo = o["modo"]?.ToString();
            var valor = o["valor"]?.ToString();
            if (modo == "dpapi")
            {
                var claro = Descifrar(Convert.FromBase64String(valor ?? ""));
                return claro == null ? null : Encoding.UTF8.GetString(claro);
            }
            return valor;
        }

        private static byte[] Descifrar(byte[] datos)
        {
            var entrada = new DataBlob { cbData = datos.Length, pbData = Marshal.AllocHGlobal(datos.Length) };
            var salida = new DataBlob();
            try
            {
                Marshal.Copy(datos, 0, entrada.pbData, datos.Length);
                if (!CryptUnprotectData(ref entrada, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 0, ref salida)) return null;
                var bytes = new byte[salida.cbData];
                Marshal.Copy(salida.pbData, bytes, 0, salida.cbData);
                return bytes;
            }
            finally
            {
                Marshal.FreeHGlobal(entrada.pbData);
                if (salida.pbData != IntPtr.Zero) LocalFree(salida.pbData);
            }
        }
    }
}
