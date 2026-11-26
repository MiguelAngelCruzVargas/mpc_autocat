using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace AutoCadMcpPlugin.Chat
{
    internal sealed class PresetProveedor
    {
        public string Id, Url, Variable, ModeloSugerido;
    }

    internal sealed class ModeloFila
    {
        public string Modelo, Estado = "";
        public bool Imagenes;
    }

    /// <summary>
    /// Los proveedores de IA que el panel conoce (URL, de qué variable sale la clave, modelo sugerido) y la lista de modelos
    /// de cada uno. Es la misma tabla que tiene Python en agent/providers.py (PRESETS); el panel la usa directo, sin pasar por
    /// el servidor. Si cambia un modelo sugerido (un proveedor retira el suyo), se cambia en los dos sitios.
    /// </summary>
    internal static class Proveedores
    {
        /// <summary>«IA incluida en mi plan»: el servidor de licencias de Vigentra hace de intermediario (licencias/servidor/ia.py).
        /// No pide clave: se autentica con el token de la licencia. Va primero porque es la opción para quien no tiene cuenta
        /// con un proveedor; quien prefiera su propia clave elige cualquiera de los demás.</summary>
        public const string IdIncluida = "vigentra";

        // La incluida primero; el resto ordenados por id, como los devuelve el servidor.
        public static readonly IReadOnlyList<PresetProveedor> Presets = new List<PresetProveedor>
        {
            new PresetProveedor { Id = IdIncluida,   Url = LicenciaGuard.UrlIaIncluida(),     Variable = "VIGENTRA_IA_TOKEN",  ModeloSugerido = "incluido" },
            new PresetProveedor { Id = "anthropic",  Url = "https://api.anthropic.com/v1",    Variable = "ANTHROPIC_API_KEY",  ModeloSugerido = "claude-sonnet-5-5" },
            new PresetProveedor { Id = "deepseek",   Url = "https://api.deepseek.com/v1",     Variable = "DEEPSEEK_API_KEY",   ModeloSugerido = "deepseek-flash" },
            new PresetProveedor { Id = "groq",       Url = "https://api.groq.com/openai/v1",  Variable = "GROQ_API_KEY",       ModeloSugerido = "openai/gpt-oss-120b" },
            new PresetProveedor { Id = "local",      Url = "http://localhost:1234/v1",        Variable = "LOCAL_API_KEY",      ModeloSugerido = "local-model" },
            new PresetProveedor { Id = "openai",     Url = "https://api.openai.com/v1",       Variable = "OPENAI_API_KEY",     ModeloSugerido = "gpt-6.1-sol" },
            new PresetProveedor { Id = "openrouter", Url = "https://openrouter.ai/api/v1",    Variable = "OPENROUTER_API_KEY", ModeloSugerido = "anthropic/claude-sonnet-5.5" },
            new PresetProveedor { Id = "together",   Url = "https://api.together.xyz/v1",     Variable = "TOGETHER_API_KEY",   ModeloSugerido = "Qwen/Qwen2.5-72B-Instruct-Turbo" },
        };

        public static PresetProveedor Buscar(string id) => Presets.FirstOrDefault(p => p.Id == id);

        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };

        /// <summary>Qué modelos ofrece el proveedor. <paramref name="urlBase"/> solo se usa en las pruebas.</summary>
        public static async Task<List<ModeloFila>> ListarModelosAsync(string proveedor, string urlBase = null, CancellationToken ct = default)
        {
            var preset = Buscar(proveedor);
            var baseUrl = (urlBase ?? preset?.Url ?? "").TrimEnd('/');
            if (baseUrl.Length == 0) throw new InvalidOperationException("Proveedor desconocido: " + proveedor);
            var clave = Credenciales.Obtener(proveedor, preset?.Variable);

            using (var req = new HttpRequestMessage(HttpMethod.Get, baseUrl + "/models"))
            {
                if (proveedor == "anthropic")
                {
                    req.Headers.TryAddWithoutValidation("x-api-key", clave ?? "");
                    req.Headers.TryAddWithoutValidation("anthropic-version", "2023-06-01");
                }
                else if (!string.IsNullOrEmpty(clave)) req.Headers.TryAddWithoutValidation("Authorization", "Bearer " + clave);

                HttpResponseMessage resp;
                try { resp = await Http.SendAsync(req, ct).ConfigureAwait(false); }
                catch (HttpRequestException ex) { throw new InvalidOperationException("No se pudo listar modelos: " + ex.Message); }
                using (resp)
                {
                    var texto = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
                    if ((int)resp.StatusCode >= 400)
                        throw new InvalidOperationException("El proveedor respondió " + (int)resp.StatusCode + ": " + (texto.Length > 300 ? texto.Substring(0, 300) : texto));
                    return Analizar(texto);
                }
            }
        }

        /// <summary>Cuánto crédito de la IA incluida le queda este mes, dicho para la persona. Nunca lanza.</summary>
        public static async Task<string> SaldoIncluidaAsync(string urlBase = null, CancellationToken ct = default)
        {
            var token = Credenciales.Obtener(IdIncluida, "VIGENTRA_IA_TOKEN");
            if (string.IsNullOrEmpty(token)) return "La IA incluida necesita una licencia activa o la prueba gratis.";
            try
            {
                using (var req = new HttpRequestMessage(HttpMethod.Get, (urlBase ?? LicenciaGuard.UrlIaIncluida()).TrimEnd('/') + "/saldo"))
                {
                    req.Headers.TryAddWithoutValidation("Authorization", "Bearer " + token);
                    using (var resp = await Http.SendAsync(req, ct).ConfigureAwait(false))
                    {
                        var texto = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
                        if ((int)resp.StatusCode == 404)
                            return "La IA incluida todavía no está disponible. Por ahora elige un proveedor y usa tu propia clave.";
                        using (var doc = JsonDocument.Parse(texto))
                        {
                            var r = doc.RootElement;
                            if ((int)resp.StatusCode >= 400)
                                return r.TryGetProperty("error", out var e) && e.TryGetProperty("message", out var msg) ? msg.GetString() : "No pude consultar tu crédito.";
                            double Num(string k) => r.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : 0;
                            var inv = System.Globalization.CultureInfo.InvariantCulture;
                            var restante = Num("restante_usd");
                            var texto2 = "Incluida en tu plan: no necesitas clave. Te quedan US$" + restante.ToString("0.00", inv)
                                         + " de crédito este mes (de US$" + Num("credito_del_plan_usd").ToString("0.00", inv) + ")";
                            if (Num("extra_usd") > 0) texto2 += " más US$" + Num("extra_usd").ToString("0.00", inv) + " de paquetes";
                            return restante > 0 ? texto2 + "."
                                : "Se acabó el crédito incluido de este mes. Usa tu propia clave (elige otro proveedor) o pide un paquete; se renueva el día 1.";
                        }
                    }
                }
            }
            catch (Exception) { return "Incluida en tu plan: no necesitas clave. (No pude consultar tu crédito ahora.)"; }
        }

        /// <summary>De la respuesta de /models («data» u «models»), las filas. Lo que el proveedor publica de visión manda sobre el nombre.</summary>
        internal static List<ModeloFila> Analizar(string json)
        {
            var filas = new List<ModeloFila>();
            using (var doc = JsonDocument.Parse(json))
            {
                var raiz = doc.RootElement;
                JsonElement lista;
                if (raiz.ValueKind == JsonValueKind.Object && raiz.TryGetProperty("data", out lista) && lista.ValueKind == JsonValueKind.Array) { }
                else if (raiz.ValueKind == JsonValueKind.Object && raiz.TryGetProperty("models", out lista) && lista.ValueKind == JsonValueKind.Array) { }
                else if (raiz.ValueKind == JsonValueKind.Array) lista = raiz;
                else return filas;
                foreach (var m in lista.EnumerateArray())
                {
                    string nombre = null;
                    if (m.ValueKind == JsonValueKind.Object)
                    {
                        if (m.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String) nombre = id.GetString();
                        else if (m.TryGetProperty("name", out var nm) && nm.ValueKind == JsonValueKind.String) nombre = nm.GetString();
                    }
                    else if (m.ValueKind == JsonValueKind.String) nombre = m.GetString();
                    if (string.IsNullOrEmpty(nombre)) continue;
                    var publicado = m.ValueKind == JsonValueKind.Object ? VisionPublicada(m) : null;
                    filas.Add(new ModeloFila { Modelo = nombre, Imagenes = publicado ?? Capacidades.SoportaImagenes(nombre) });
                }
            }
            return filas;
        }

        // OpenRouter publica las modalidades de entrada de cada modelo (architecture.input_modalities).
        private static bool? VisionPublicada(JsonElement m)
        {
            if (!m.TryGetProperty("architecture", out var arq) || arq.ValueKind != JsonValueKind.Object) return null;
            if (arq.TryGetProperty("input_modalities", out var ent) && ent.ValueKind == JsonValueKind.Array)
                return ent.EnumerateArray().Any(x => x.ValueKind == JsonValueKind.String && x.GetString() == "image");
            if (arq.TryGetProperty("modality", out var mod) && mod.ValueKind == JsonValueKind.String && mod.GetString().Length > 0)
                return mod.GetString().Split(new[] { "->" }, StringSplitOptions.None)[0].Contains("image");
            return null;
        }
    }
}
