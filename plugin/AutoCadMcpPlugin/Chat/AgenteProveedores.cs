using System;
using System.Collections.Generic;
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
        /// <summary>Lo que el proveedor dijo que costó (OpenRouter y la IA incluida lo mandan en usage.cost). 0 si no lo dijo.</summary>
        public double CostoReportado;
        public long Total => Entrada + Salida;
        public void AnotarVuelta() { Vueltas++; }

        public void Anotar(JsonNode uso)
        {
            if (!(uso is JsonObject o)) return;
            Entrada += Largo(o, "prompt_tokens") + Largo(o, "input_tokens");
            Salida += Largo(o, "completion_tokens") + Largo(o, "output_tokens");
            try { if (o["cost"] != null) CostoReportado += o["cost"].GetValue<double>(); } catch (Exception) { }
            Vueltas++;
        }

        private static long Largo(JsonObject o, string clave)
        {
            try { return o[clave] == null ? 0 : o[clave].GetValue<long>(); }
            catch (Exception) { return 0; }
        }
    }

    /// <summary>Un modelo al que se le pide la siguiente respuesta de la conversación.</summary>
    /// <summary>Un modelo que además puede ir contando el texto a medida que lo escribe (streaming).</summary>
    internal interface IProveedorConTexto : IProveedorModelo
    {
        /// <summary>Igual que CompletarAsync, pero con <paramref name="alTexto"/> se recibe el texto acumulado cada vez que llega un pedazo.</summary>
        Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct, Action<string> alTexto);
    }

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

        /// <summary>Abre una respuesta en flujo (SSE): el llamador la lee línea a línea y la cierra.</summary>
        public static async Task<HttpResponseMessage> AbrirFlujoAsync(string url, JsonObject cuerpo, Action<HttpRequestMessage> cabeceras, CancellationToken ct)
        {
            var pedido = new HttpRequestMessage(HttpMethod.Post, url) { Content = new StringContent(cuerpo.ToJsonString(), Encoding.UTF8, "application/json") };
            cabeceras?.Invoke(pedido);
            try { return await Http.SendAsync(pedido, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(true); }
            catch (HttpRequestException ex) { throw new ErrorProveedor("No se pudo llamar a " + url + ": " + ex.Message); }
            catch (TaskCanceledException) when (!ct.IsCancellationRequested) { throw new ErrorProveedor("El modelo tardó más de 180 s en contestar (" + url + ")."); }
        }

        /// <summary>Lee un flujo SSE entero entregando cada línea a <paramref name="linea"/>; cancelar cierra la respuesta.</summary>
        public static async Task LeerFlujoAsync(HttpResponseMessage r, Action<string> linea, CancellationToken ct)
        {
            using (ct.Register(() => r.Dispose()))
            using (var flujo = await r.Content.ReadAsStreamAsync().ConfigureAwait(true))
            using (var lector = new System.IO.StreamReader(flujo, Encoding.UTF8))
            {
                try
                {
                    string l;
                    while ((l = await lector.ReadLineAsync().ConfigureAwait(true)) != null) linea(l);
                }
                catch (ObjectDisposedException) when (ct.IsCancellationRequested) { throw new OperationCanceledException(ct); }
                catch (System.IO.IOException) when (ct.IsCancellationRequested) { throw new OperationCanceledException(ct); }
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
            if ((codigo == 401 || codigo == 402 || codigo == 403 || codigo == 429) && mensaje.Length > 0 && mensaje.Length < 400)
                return new ErrorProveedor(mensaje);
            return new ErrorProveedor("El modelo respondió " + codigo + ": " + (texto.Length > 600 ? texto.Substring(0, 600) : texto));
        }
    }

    /// <summary>/chat/completions con tools: el formato de OpenAI, Groq, OpenRouter, DeepSeek, Together y los servidores locales.</summary>
    internal sealed class ProveedorOpenAI : IProveedorConTexto
    {
        private readonly string _url, _clave;
        private readonly double? _temperatura;
        public string Modelo { get; }
        public UsoTokens Uso { get; } = new UsoTokens();

        public ProveedorOpenAI(string url, string clave, string modelo, double? temperatura)
        {
            _url = url.TrimEnd('/'); _clave = clave; Modelo = modelo; _temperatura = temperatura;
        }

        private bool _opcionesFlujo = true;       // «stream_options» pide el uso de tokens al final; algunos servidores locales no lo conocen

        private JsonObject Cuerpo(JsonArray mensajes, JsonArray tools)
        {
            var cuerpo = new JsonObject { ["model"] = Modelo, ["messages"] = mensajes.DeepClone() };
            if (tools != null && tools.Count > 0)
            {
                cuerpo["tools"] = tools.DeepClone();
                cuerpo["tool_choice"] = "auto";
            }
            if (_temperatura.HasValue) cuerpo["temperature"] = _temperatura.Value;
            return cuerpo;
        }

        private void Cabeceras(HttpRequestMessage p)
        {
            if (!string.IsNullOrEmpty(_clave)) p.Headers.TryAddWithoutValidation("Authorization", "Bearer " + _clave);
            p.Headers.TryAddWithoutValidation("X-Title", "AutoCAD MCP");
        }

        public Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct) => CompletarSinFlujoAsync(mensajes, tools, ct);

        public async Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct, Action<string> alTexto)
        {
            if (alTexto == null) return await CompletarSinFlujoAsync(mensajes, tools, ct).ConfigureAwait(true);
            var cuerpo = Cuerpo(mensajes, tools);
            cuerpo["stream"] = true;
            if (_opcionesFlujo) cuerpo["stream_options"] = new JsonObject { ["include_usage"] = true };
            using (var r = await ClienteHttp.AbrirFlujoAsync(_url + "/chat/completions", cuerpo, Cabeceras, ct).ConfigureAwait(true))
            {
                if (!r.IsSuccessStatusCode)
                {
                    var texto = await r.Content.ReadAsStringAsync().ConfigureAwait(true);
                    if (_opcionesFlujo && texto.Contains("stream_options"))
                    {
                        _opcionesFlujo = false;
                        return await CompletarAsync(mensajes, tools, ct, alTexto).ConfigureAwait(true);
                    }
                    throw ClienteHttp.ErrorDeRespuesta((int)r.StatusCode, texto);
                }
                var acu = new AcumuladorOpenAI(alTexto);
                await ClienteHttp.LeerFlujoAsync(r, acu.Linea, ct).ConfigureAwait(true);
                var msg = acu.Resultado();
                if (acu.Uso != null) Uso.Anotar(acu.Uso); else Uso.AnotarVuelta();
                return msg;
            }
        }

        private async Task<JsonObject> CompletarSinFlujoAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct)
        {
            var cuerpo = Cuerpo(mensajes, tools);

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
    internal sealed class ProveedorAnthropic : IProveedorConTexto
    {
        private readonly string _url, _clave;
        private readonly double? _temperatura;
        public string Modelo { get; }
        public UsoTokens Uso { get; } = new UsoTokens();

        public ProveedorAnthropic(string url, string clave, string modelo, double? temperatura)
        {
            _url = url.TrimEnd('/'); _clave = clave; Modelo = modelo; _temperatura = temperatura;
        }

        private JsonObject Cuerpo(JsonArray mensajes, JsonArray tools)
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
            return cuerpo;
        }

        private void Cabeceras(HttpRequestMessage p)
        {
            p.Headers.TryAddWithoutValidation("x-api-key", _clave ?? "");
            p.Headers.TryAddWithoutValidation("anthropic-version", "2023-06-01");
        }

        public Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct) => CompletarSinFlujoAsync(mensajes, tools, ct);

        public async Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct, Action<string> alTexto)
        {
            if (alTexto == null) return await CompletarSinFlujoAsync(mensajes, tools, ct).ConfigureAwait(true);
            var cuerpo = Cuerpo(mensajes, tools);
            cuerpo["stream"] = true;
            using (var r = await ClienteHttp.AbrirFlujoAsync(_url + "/messages", cuerpo, Cabeceras, ct).ConfigureAwait(true))
            {
                if (!r.IsSuccessStatusCode)
                {
                    var texto = await r.Content.ReadAsStringAsync().ConfigureAwait(true);
                    throw new ErrorProveedor("El modelo respondió " + (int)r.StatusCode + ": " + (texto.Length > 600 ? texto.Substring(0, 600) : texto));
                }
                var acu = new AcumuladorAnthropic(alTexto);
                await ClienteHttp.LeerFlujoAsync(r, acu.Linea, ct).ConfigureAwait(true);
                var msg = acu.Resultado();
                Uso.Entrada += acu.Entrada; Uso.Salida += acu.Salida; Uso.AnotarVuelta();
                return msg;
            }
        }

        private async Task<JsonObject> CompletarSinFlujoAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct)
        {
            var cuerpo = Cuerpo(mensajes, tools);

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

        /// <summary>Las partes texto + image_url (OpenAI) a bloques text + image con base64 (Anthropic). Un texto suelto queda igual.</summary>
        internal static JsonNode ContenidoAnthropic(JsonNode contenido)
        {
            if (!(contenido is JsonArray partes)) return contenido?.DeepClone() ?? "";
            var bloques = new JsonArray();
            foreach (var parte in partes)
            {
                var tipo = parte?["type"]?.ToString();
                if (tipo == "text") bloques.Add(new JsonObject { ["type"] = "text", ["text"] = parte["text"]?.ToString() ?? "" });
                else if (tipo == "image_url")
                {
                    var url = parte["image_url"]?["url"]?.ToString() ?? "";
                    var m = System.Text.RegularExpressions.Regex.Match(url, @"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", System.Text.RegularExpressions.RegexOptions.Singleline);
                    if (!m.Success) continue;
                    bloques.Add(new JsonObject
                    {
                        ["type"] = "image",
                        ["source"] = new JsonObject { ["type"] = "base64", ["media_type"] = m.Groups[1].Value, ["data"] = m.Groups[2].Value },
                    });
                }
            }
            return bloques;
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
                        salida.Add(new JsonObject { ["role"] = "user", ["content"] = ContenidoAnthropic(m["content"]) });
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
    /// Arma la respuesta de un modelo OpenAI-compatible que llega en pedazos (SSE): el texto, las llamadas a herramientas
    /// (sus argumentos llegan partidos) y el razonamiento. Se alimenta línea a línea, así se prueba sin red.
    /// Si el servidor ignora «stream» y contesta un JSON entero, también lo entiende.
    /// </summary>
    internal sealed class AcumuladorOpenAI
    {
        private readonly Action<string> _alTexto;
        private readonly StringBuilder _texto = new StringBuilder(), _razon = new StringBuilder();
        private readonly SortedDictionary<int, (string id, StringBuilder nombre, StringBuilder args)> _llamadas = new SortedDictionary<int, (string, StringBuilder, StringBuilder)>();
        private readonly List<string> _crudas = new List<string>();
        private bool _vistoData;
        public JsonNode Uso;

        public AcumuladorOpenAI(Action<string> alTexto) { _alTexto = alTexto; }

        public void Linea(string linea)
        {
            if (linea == null) return;
            if (!linea.StartsWith("data:", StringComparison.Ordinal))
            {
                if (linea.Length > 0 && !_vistoData) _crudas.Add(linea);
                return;
            }
            _vistoData = true;
            var d = linea.Substring(5).Trim();
            if (d.Length == 0 || d == "[DONE]") return;
            JsonNode j;
            try { j = JsonNode.Parse(d); } catch (JsonException) { return; }
            if (j?["error"] != null) throw new ErrorProveedor("El modelo respondió un error: " + (j["error"]["message"]?.ToString() ?? j["error"].ToString()));
            var u = j?["usage"] ?? j?["x_groq"]?["usage"];
            if (u != null) Uso = u.DeepClone();
            var delta = (j?["choices"] as JsonArray)?.FirstOrDefault()?["delta"];
            if (delta == null) return;
            var c = delta["content"]?.ToString();
            if (!string.IsNullOrEmpty(c)) { _texto.Append(c); _alTexto?.Invoke(_texto.ToString()); }
            var r = delta["reasoning_content"]?.ToString();
            if (!string.IsNullOrEmpty(r)) _razon.Append(r);
            if (delta["tool_calls"] is JsonArray tcs)
                foreach (var tc in tcs)
                {
                    int idx = 0;
                    int.TryParse(tc?["index"]?.ToString(), out idx);
                    if (!_llamadas.TryGetValue(idx, out var cur)) cur = (null, new StringBuilder(), new StringBuilder());
                    var id = tc["id"]?.ToString();
                    var fn = tc["function"];
                    cur.nombre.Append(fn?["name"]?.ToString() ?? "");
                    cur.args.Append(fn?["arguments"]?.ToString() ?? "");
                    _llamadas[idx] = (id ?? cur.id, cur.nombre, cur.args);
                }
        }

        public JsonObject Resultado()
        {
            if (!_vistoData && _crudas.Count > 0)
            {
                try
                {
                    var datos = JsonNode.Parse(string.Join("\n", _crudas));
                    Uso = datos?["usage"]?.DeepClone();
                    var m = (datos?["choices"] as JsonArray)?.FirstOrDefault()?["message"];
                    if (m != null) return (JsonObject)m.DeepClone();
                }
                catch (JsonException) { }
                throw new ErrorProveedor("Respuesta que no es un flujo ni un JSON del modelo: " + (_crudas[0].Length > 300 ? _crudas[0].Substring(0, 300) : _crudas[0]));
            }
            var msg = new JsonObject { ["role"] = "assistant", ["content"] = _texto.Length > 0 ? (JsonNode)_texto.ToString() : null };
            if (_razon.Length > 0) msg["reasoning_content"] = _razon.ToString();
            if (_llamadas.Count > 0)
            {
                var arr = new JsonArray();
                foreach (var kv in _llamadas)
                    arr.Add(new JsonObject
                    {
                        ["id"] = kv.Value.id ?? ("call_" + kv.Key), ["type"] = "function",
                        ["function"] = new JsonObject { ["name"] = kv.Value.nombre.ToString(), ["arguments"] = kv.Value.args.Length > 0 ? kv.Value.args.ToString() : "{}" },
                    });
                msg["tool_calls"] = arr;
            }
            return msg;
        }
    }

    /// <summary>Lo mismo para el flujo de Anthropic (eventos message_start, content_block_*, message_delta).</summary>
    internal sealed class AcumuladorAnthropic
    {
        private readonly Action<string> _alTexto;
        private readonly StringBuilder _texto = new StringBuilder();
        private readonly SortedDictionary<int, (string id, string nombre, StringBuilder json)> _herramientas = new SortedDictionary<int, (string, string, StringBuilder)>();
        public long Entrada, Salida;

        public AcumuladorAnthropic(Action<string> alTexto) { _alTexto = alTexto; }

        public void Linea(string linea)
        {
            if (linea == null || !linea.StartsWith("data:", StringComparison.Ordinal)) return;
            var d = linea.Substring(5).Trim();
            if (d.Length == 0) return;
            JsonNode j;
            try { j = JsonNode.Parse(d); } catch (JsonException) { return; }
            switch (j?["type"]?.ToString())
            {
                case "message_start":
                    long.TryParse(j["message"]?["usage"]?["input_tokens"]?.ToString(), out var ent); Entrada += ent;
                    break;
                case "content_block_start":
                {
                    int.TryParse(j["index"]?.ToString(), out var i);
                    var b = j["content_block"];
                    if (b?["type"]?.ToString() == "tool_use") _herramientas[i] = (b["id"]?.ToString(), b["name"]?.ToString(), new StringBuilder());
                    break;
                }
                case "content_block_delta":
                {
                    int.TryParse(j["index"]?.ToString(), out var i);
                    var delta = j["delta"];
                    var tipo = delta?["type"]?.ToString();
                    if (tipo == "text_delta") { _texto.Append(delta["text"]?.ToString()); _alTexto?.Invoke(_texto.ToString()); }
                    else if (tipo == "input_json_delta" && _herramientas.TryGetValue(i, out var h)) h.json.Append(delta["partial_json"]?.ToString());
                    break;
                }
                case "message_delta":
                    long.TryParse(j["usage"]?["output_tokens"]?.ToString(), out var sal); if (sal > 0) Salida = sal;
                    break;
                case "error":
                    throw new ErrorProveedor("El modelo respondió un error: " + (j["error"]?["message"]?.ToString() ?? d));
            }
        }

        public JsonObject Resultado()
        {
            var m = new JsonObject { ["role"] = "assistant", ["content"] = _texto.Length > 0 ? (JsonNode)_texto.ToString() : null };
            if (_herramientas.Count > 0)
            {
                var arr = new JsonArray();
                foreach (var kv in _herramientas)
                    arr.Add(new JsonObject
                    {
                        ["id"] = kv.Value.id, ["type"] = "function",
                        ["function"] = new JsonObject { ["name"] = kv.Value.nombre, ["arguments"] = kv.Value.json.Length > 0 ? kv.Value.json.ToString() : "{}" },
                    });
                m["tool_calls"] = arr;
            }
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

        [DllImport("crypt32.dll", SetLastError = true)]
        private static extern bool CryptProtectData(ref DataBlob entrada, IntPtr descripcion, IntPtr entropia, IntPtr reservado,
            IntPtr prompt, int flags, ref DataBlob salida);

        /// <summary>La carpeta donde viven claves y preferencias (la misma que usa Python). AUTOCAD_IA_CREDENCIALES la desvía en las pruebas.</summary>
        internal static string Directorio
        {
            get
            {
                var desvio = Environment.GetEnvironmentVariable("AUTOCAD_IA_CREDENCIALES");
                if (!string.IsNullOrEmpty(desvio)) return desvio;
                return Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp");
            }
        }

        private static string Archivo => Path.Combine(Directorio, "credenciales.json");

        /// <summary>Guarda la clave de un proveedor cifrada con DPAPI (atada a este usuario de Windows), en el mismo formato que Python.</summary>
        public static string Guardar(string proveedor, string clave)
        {
            if (string.IsNullOrWhiteSpace(proveedor)) throw new ArgumentException("Falta el proveedor.");
            if (string.IsNullOrWhiteSpace(clave)) throw new ArgumentException("La clave está vacía.");
            var cifrado = Cifrar(Encoding.UTF8.GetBytes(clave.Trim()));
            var entrada = cifrado != null
                ? new JsonObject { ["modo"] = "dpapi", ["valor"] = Convert.ToBase64String(cifrado) }
                : new JsonObject { ["modo"] = "plano", ["valor"] = clave.Trim() };
            var raiz = LeerTodo();
            raiz[proveedor] = entrada;
            EscribirTodo(raiz);
            return entrada["modo"].ToString();
        }

        /// <summary>¿Hay una clave GUARDADA (no de entorno) para este proveedor? Para la IA incluida: ¿hay licencia?</summary>
        public static bool TieneGuardada(string proveedor)
        {
            if (proveedor == Proveedores.IdIncluida) return !string.IsNullOrEmpty(LicenciaGuard.TokenGuardado());
            try { return !string.IsNullOrEmpty(Revelar(LeerTodo()[proveedor])); }
            catch (Exception) { return false; }
        }

        public static bool Borrar(string proveedor)
        {
            var raiz = LeerTodo();
            if (!raiz.ContainsKey(proveedor)) return false;
            raiz.Remove(proveedor);
            EscribirTodo(raiz);
            return true;
        }

        private static JsonObject LeerTodo()
        {
            try { return File.Exists(Archivo) ? (JsonNode.Parse(File.ReadAllText(Archivo, Encoding.UTF8)) as JsonObject ?? new JsonObject()) : new JsonObject(); }
            catch (Exception) { return new JsonObject(); }
        }

        private static void EscribirTodo(JsonObject raiz)
        {
            Directory.CreateDirectory(Directorio);
            File.WriteAllText(Archivo, raiz.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
        }

        private static byte[] Cifrar(byte[] datos)
        {
            var entrada = new DataBlob { cbData = datos.Length, pbData = Marshal.AllocHGlobal(datos.Length) };
            var salida = new DataBlob();
            try
            {
                Marshal.Copy(datos, 0, entrada.pbData, datos.Length);
                if (!CryptProtectData(ref entrada, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 0, ref salida)) return null;
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

        public static string Obtener(string proveedor, string variableEntorno)
        {
            if (!string.IsNullOrEmpty(variableEntorno))
            {
                var env = Environment.GetEnvironmentVariable(variableEntorno);
                if (!string.IsNullOrEmpty(env)) return env;
            }
            // La IA incluida no tiene clave propia: va el token firmado de la licencia (nunca la clave de licencia).
            if (proveedor == Proveedores.IdIncluida) return LicenciaGuard.TokenGuardado();
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
