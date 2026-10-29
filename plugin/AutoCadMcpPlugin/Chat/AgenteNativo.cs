using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>Lo que la persona pidió y con qué modelo y especialidad.</summary>
    internal sealed class PedidoAgente
    {
        public string Mensaje = "";
        public string Proveedor = "";
        public string Modelo = "";
        public string Perfil = "arquitectura";
        public double? Temperatura;
        public bool ConReglas = true;
        public string Contexto = "";
        public int Vueltas = 40;
        public double TopeUSD;
    }

    /// <summary>
    /// El AGENTE del chat, en C# dentro de AutoCAD: el bucle «modelo → herramientas → modelo», la conversación y los proveedores
    /// (Groq, OpenRouter, OpenAI, DeepSeek, Together, local y Claude) ya no pasan por un servidor aparte. De Python queda solo lo
    /// que sigue siendo suyo —las ~300 herramientas y el texto de sistema con las reglas de dibujo— que se le pide al anfitrión
    /// (agent/web.py: /api/h/preparar y /api/h/ejecutar). Es el mismo bucle que agent/loop.py, con las mismas decisiones:
    ///   - un error de herramienta vuelve al modelo COMO TEXTO (el modelo lee y corrige; no se cae el bucle);
    ///   - tope de vueltas (un modelo chico puede quedarse en un lazo);
    ///   - si el proveedor no acepta tantas herramientas, pasa a «bajo demanda» (3 herramientas de descubrimiento);
    ///   - si el modelo pide una herramienta que no existe, se le explica y sigue;
    ///   - si corta el turno sin decir nada tras trabajar, se le pide seguir o resumir;
    ///   - tras dibujar se ajusta la vista (zoom_extents) para que lo dibujado se vea.
    /// Los eventos que emite son los mismos que ya mostraba el panel (inicio, texto, tool, resultado, uso, aviso, nota, fin).
    /// </summary>
    internal sealed class AgenteNativo
    {
        private readonly Func<ChatCliente> _host;

        /// <summary>Cómo se arma el modelo; las pruebas lo cambian por uno de mentira.</summary>
        internal Func<JsonObject, PedidoAgente, IProveedorModelo> FabricaProveedor = CrearProveedor;
        private readonly string _archivo;
        private JsonArray _mensajes = new JsonArray();
        private JsonArray _eventos = new JsonArray();
        private const int MaxEventos = 600;

        // Permisos y «Deshacer este pedido». Las listas vienen del servidor (agent/permisos.py: una sola fuente).
        private Regex _destructivas = new Regex("$^");
        private Regex _soloLectura = new Regex("^");
        private readonly Dictionary<string, TaskCompletionSource<int>> _permisos = new Dictionary<string, TaskCompletionSource<int>>();
        private readonly HashSet<string> _siempre = new HashSet<string>();     // herramientas que la persona dejó correr sin preguntar, en ESTA conversación
        private bool _hayMarca;                                                  // hay una marca de UNDO puesta por el pedido en curso o el último
        private string _avisoDeshacer = "";

        private static readonly string[] Meta = { "buscar_herramientas", "describir_herramienta", "ejecutar_herramienta" };

        public AgenteNativo(Func<ChatCliente> host, string archivo = null)
        {
            _host = host;
            // AUTOCAD_IA_ESTADO desvía el historial a otra carpeta (las pruebas no tocan el del usuario), igual que en Python.
            var estado = Environment.GetEnvironmentVariable("AUTOCAD_IA_ESTADO");
            if (string.IsNullOrEmpty(estado))
                estado = Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp");
            _archivo = archivo ?? Path.Combine(estado, "chat_nativo.json");
            Cargar();
        }

        /// <summary>La conversación tal como se le manda al modelo (las pruebas la miran).</summary>
        internal JsonArray Mensajes => _mensajes;

        /// <summary>Lo que se vio en pantalla, para reconstruirla al abrir el panel.</summary>
        public IReadOnlyList<JsonNode> Eventos => _eventos.ToList();

        public void Reiniciar()
        {
            _mensajes = new JsonArray();
            _eventos = new JsonArray();
            _siempre.Clear();
            _hayMarca = false;
            _avisoDeshacer = "";
            try { if (File.Exists(_archivo)) File.Delete(_archivo); } catch (Exception) { }
        }

        // ------------------------------------------------------------------------------------------ permisos y deshacer

        /// <summary>La persona contestó una tarjeta de permiso: 0 = rechazar, 1 = permitir, 2 = permitir esa herramienta siempre en esta conversación.</summary>
        public void ResolverPermiso(string id, int decision)
        {
            TaskCompletionSource<int> tcs;
            lock (_permisos) { if (!_permisos.TryGetValue(id ?? "", out tcs)) return; }
            tcs.TrySetResult(decision);
        }

        /// <summary>
        /// Deshace TODO lo que hizo el último pedido: vuelve a la marca de UNDO que se puso antes de su primera herramienta que tocaba el
        /// dibujo (UNDO Back). No cuenta pasos, así que no le importan las lecturas de en medio ni cuántas operaciones fueron.
        /// </summary>
        public async Task<(bool ok, string mensaje)> DeshacerAsync()
        {
            var host = _host();
            if (host == null) return (false, "No hay conexión con el servidor de herramientas.");
            if (!_hayMarca) return (false, "No hay nada que deshacer: ese pedido no cambió el dibujo.");
            var (texto, error) = await EjecutarHerramienta(host, "run_command", Comando("UNDO", "Back"), false).ConfigureAwait(true);
            if (error || !ComandoOk(texto))
                return (false, "AutoCAD no pudo deshacerlo: " + (texto.Length > 200 ? texto.Substring(0, 200) : texto));
            _hayMarca = false;
            _avisoDeshacer = "[La persona deshizo tu último pedido con «Deshacer»: todo lo que dibujaste en él se revirtió. El dibujo está como estaba antes.]";
            Anotar("nota", new JsonObject { ["tipo"] = "nota", ["texto"] = "Pedido deshecho: el dibujo volvió a como estaba antes." });
            Guardar();
            return (true, "Pedido deshecho: el dibujo volvió a como estaba antes.");
        }

        private static JsonObject Comando(params string[] tokens)
        {
            var arr = new JsonArray();
            foreach (var t in tokens) arr.Add(t);
            return new JsonObject { ["tokens"] = arr };
        }

        /// <summary>run_command contesta {"ok": true|false, "state": ...}: un fallo no llega como excepción.</summary>
        internal static bool ComandoOk(string texto)
        {
            try
            {
                var o = JsonNode.Parse(texto) as JsonObject;
                if (o == null) return false;
                if (o["ok"] is JsonValue v && v.TryGetValue<bool>(out var b)) return b;
                return o["state"]?.ToString() != "error";
            }
            catch (Exception) { return false; }
        }

        private async Task<bool> PonerMarca(ChatCliente host)
        {
            var (texto, error) = await EjecutarHerramienta(host, "run_command", Comando("UNDO", "Mark"), false).ConfigureAwait(true);
            return !error && ComandoOk(texto);
        }

        // ------------------------------------------------------------------------------------------ el bucle

        public async Task EjecutarAsync(PedidoAgente p, Action<JsonElement> alPanel, CancellationToken ct)
        {
            void Emitir(string tipo, JsonObject cuerpo)
            {
                cuerpo["tipo"] = tipo;
                Anotar(tipo, cuerpo);
                using (var doc = JsonDocument.Parse(cuerpo.ToJsonString()))
                    alPanel(doc.RootElement);
            }

            try
            {
                Anotar("usuario", new JsonObject { ["tipo"] = "usuario", ["texto"] = p.Mensaje });     // la burbuja del usuario ya la puso el panel
                var host = _host();
                if (host == null) { Emitir("aviso", Obj("texto", "No hay conexión con el servidor de herramientas.")); return; }

                JsonObject prep = await Preparar(host, p, false, ct).ConfigureAwait(true);
                if (prep == null) { Emitir("aviso", Obj("texto", _ultimoError ?? "No pude leer las herramientas.")); return; }
                var proveedor = FabricaProveedor(prep, p);
                if (proveedor == null)
                {
                    Emitir("aviso", Obj("texto", "Falta la clave de '" + p.Proveedor + "': pégala en la configuración y pulsa Guardar."));
                    return;
                }

                var nombres = new HashSet<string>((prep["nombres"] as JsonArray ?? new JsonArray()).Select(x => x.ToString()));
                var tools = (JsonArray)prep["tools"];
                bool meta = prep["bajoDemanda"]?.GetValue<bool>() ?? false;
                var regexDibujo = new Regex(prep["regexDibujo"]?.ToString() ?? "^$");
                var demasiadas = new Regex(prep["patronDemasiadas"]?.ToString() ?? "maximum number of items", RegexOptions.IgnoreCase);
                bool enAutocad = prep["enAutocad"]?.GetValue<bool>() ?? false;
                _destructivas = new Regex(prep["destructivas"]?.ToString() ?? "$^");
                _soloLectura = new Regex(prep["soloLectura"]?.ToString() ?? "^");
                _hayMarca = false;
                bool marcaIntentada = false;
                var precio = prep["precio"] as JsonObject;
                string sistemaMeta = prep["sistemaMeta"]?.ToString() ?? "";

                Emitir("inicio", new JsonObject { ["tools"] = prep["total"]?.GetValue<int>() ?? tools.Count, ["modelo"] = proveedor.Modelo });

                // El texto de sistema se renueva en CADA pedido: una conversación empezada con una versión vieja (con reglas que
                // ya se quitaron) no puede quedarse con ella para siempre.
                if (_mensajes.Count == 0 || _mensajes[0]?["role"]?.ToString() != "system")
                    _mensajes.Insert(0, new JsonObject { ["role"] = "system", ["content"] = prep["sistema"]?.ToString() ?? "" });
                else
                    _mensajes[0]["content"] = prep["sistema"]?.ToString() ?? "";
                _mensajes.Add(new JsonObject { ["role"] = "user", ["content"] = _avisoDeshacer.Length > 0 ? _avisoDeshacer + "\n\n" + p.Mensaje : p.Mensaje });
                _avisoDeshacer = "";
                if (meta) PasarABajoDemanda(sistemaMeta, prep["nota"]?.ToString(), Emitir);

                int invalidas = 0, silencios = 0;
                bool hubieronTools = false, dibujo = false;
                bool tope = false;

                for (int vuelta = 0; vuelta < p.Vueltas; vuelta++)
                {
                    if (tope) break;
                    if (ct.IsCancellationRequested)
                    {
                        Emitir("aviso", Obj("texto", "Cancelado. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir."));
                        break;
                    }

                    JsonObject resp;
                    try { resp = await proveedor.CompletarAsync(_mensajes, tools, ct).ConfigureAwait(true); }
                    catch (OperationCanceledException)
                    {
                        Emitir("aviso", Obj("texto", "Cancelado. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir."));
                        break;
                    }
                    catch (ToolInvalida ex)
                    {
                        invalidas++;
                        if (invalidas > 3)
                        {
                            Emitir("aviso", Obj("texto", ex.Message + " Insistió " + invalidas + " veces con herramientas que no tiene; se corta."));
                            break;
                        }
                        var real = ex.Tool ?? "";
                        if (meta && nombres.Contains(real))
                        {
                            Emitir("nota", Tecnica("El modelo llamó '" + real + "' directo; se le indica que use ejecutar_herramienta."));
                            _mensajes.Add(new JsonObject
                            {
                                ["role"] = "user",
                                ["content"] = "ERROR: '" + real + "' NO se llama directamente: la llamada no se ejecutó. Hazlo así: ejecutar_herramienta con nombre='" + real +
                                              "' y sus parámetros dentro de `argumentos` (un objeto JSON). Si no sabes sus parámetros, antes llama describir_herramienta con nombre='" + real +
                                              "'. Vuelve a intentarlo ahora."
                            });
                            continue;
                        }
                        Emitir("aviso", Obj("texto", ex.Message + " Se le avisa y sigue."));
                        var disponibles = string.Join(", ", tools.Select(t => t["function"]?["name"]?.ToString()));
                        _mensajes.Add(new JsonObject
                        {
                            ["role"] = "user",
                            ["content"] = "ERROR: la tool '" + (string.IsNullOrEmpty(ex.Tool) ? "?" : ex.Tool) + "' no existe en este perfil, así que la llamada NO se ejecutó. Las que tienes son: " +
                                          disponibles + ". Si necesitas una que no está, dilo y sigue con el resto del trabajo."
                        });
                        continue;
                    }
                    catch (ErrorProveedor ex)
                    {
                        if (!meta && demasiadas.IsMatch(ex.Message))
                        {
                            var otra = await Preparar(host, p, true, ct).ConfigureAwait(true);
                            if (otra != null)
                            {
                                tools = (JsonArray)otra["tools"];
                                meta = true;
                                PasarABajoDemanda(sistemaMeta, otra["nota"]?.ToString(), Emitir);
                                continue;
                            }
                        }
                        Emitir("aviso", Obj("texto", ex.Message));
                        break;
                    }
                    invalidas = 0;

                    var uso = new JsonObject
                    {
                        ["entrada"] = proveedor.Uso.Entrada, ["salida"] = proveedor.Uso.Salida,
                        ["total"] = proveedor.Uso.Total, ["vueltas"] = proveedor.Uso.Vueltas,
                    };
                    double? costo = Costo(proveedor.Uso, precio);
                    if (costo.HasValue)
                    {
                        uso["costoUSD"] = Math.Round(costo.Value, 5);
                        if (p.TopeUSD > 0 && costo.Value >= p.TopeUSD && !tope)
                        {
                            tope = true;          // se detiene al terminar esta vuelta
                        }
                    }
                    Emitir("uso", uso);

                    var texto = LimpiarTexto(resp["content"]?.ToString() ?? "");
                    if (texto.Length > 0) Emitir("texto", Obj("texto", texto));

                    var llamadas = LlamadasDe(resp);
                    var asistente = new JsonObject { ["role"] = "assistant", ["content"] = texto.Length > 0 ? (JsonNode)texto : null };
                    if (llamadas.Count > 0) asistente["tool_calls"] = resp["tool_calls"]?.DeepClone();
                    // DeepSeek (modo de razonamiento, el de fábrica en sus modelos V4): con herramientas, el razonamiento de CADA
                    // turno hay que devolverlo en los pedidos siguientes o responde 400. Los que no lo traen no lo notan.
                    if (resp["reasoning_content"] != null) asistente["reasoning_content"] = resp["reasoning_content"].DeepClone();
                    _mensajes.Add(asistente);

                    if (llamadas.Count == 0)
                    {
                        // Un modelo chico a veces corta el turno en seco, sin una palabra, a la mitad del trabajo: la persona se queda
                        // viendo un dibujo a medias y ningún mensaje. Se le pide una vez más seguir o resumir.
                        if (hubieronTools && texto.Length == 0 && silencios < 2)
                        {
                            silencios++;
                            _mensajes.RemoveAt(_mensajes.Count - 1);
                            Emitir("nota", Tecnica("El modelo se detuvo sin decir nada; se le pide que siga o que resuma."));
                            _mensajes.Add(new JsonObject
                            {
                                ["role"] = "user",
                                ["content"] = "Te detuviste sin decir nada. Si el pedido todavía no está terminado, sigue con las herramientas hasta completarlo; si ya terminaste, resume en pocas líneas qué hiciste y qué falta."
                            });
                            continue;
                        }
                        break;
                    }

                    hubieronTools = true;
                    bool cortado = false;
                    foreach (var ll in llamadas)
                    {
                        // Se corta ENTRE herramientas, nunca a mitad de una: abandonar un create_walls a medio camino dejaría el dibujo inconsistente.
                        if (ct.IsCancellationRequested)
                        {
                            Emitir("aviso", Obj("texto", "Cancelado. La herramienta en curso terminó; las que faltaban no se ejecutaron."));
                            cortado = true;
                            break;
                        }
                        string visible = ll.Nombre;
                        JsonObject argsVisibles = ll.Args;
                        if (meta && Meta.Contains(ll.Nombre)) (visible, argsVisibles) = Visible(ll.Nombre, ll.Args);
                        // Lo destructivo (borrar, purgar, cerrar, deshacer, comandos libres) pide permiso CADA vez, con una tarjeta en el
                        // panel (los diálogos emergentes no abren dentro de una paleta de AutoCAD). Dibujar no pregunta: se revierte con «Deshacer».
                        bool rechazada = false;
                        if (_destructivas.IsMatch(visible) && !_siempre.Contains(visible))
                        {
                            var idPermiso = Guid.NewGuid().ToString("N").Substring(0, 8);
                            var tcs = new TaskCompletionSource<int>();
                            lock (_permisos) _permisos[idPermiso] = tcs;
                            Emitir("permiso", new JsonObject { ["id"] = idPermiso, ["nombre"] = visible, ["args"] = argsVisibles.DeepClone() });
                            int decision;
                            using (ct.Register(() => tcs.TrySetResult(0)))
                                decision = await tcs.Task.ConfigureAwait(true);
                            lock (_permisos) _permisos.Remove(idPermiso);
                            if (decision == 2) _siempre.Add(visible);
                            rechazada = decision == 0;
                        }
                        Emitir("tool", new JsonObject { ["nombre"] = visible, ["args"] = argsVisibles.DeepClone() });
                        string salida; bool error;
                        if (rechazada)
                        {
                            salida = "La persona RECHAZÓ esta acción (no se ejecutó). No la repitas ni busques otro camino para lograr lo mismo: pregúntale qué prefiere hacer.";
                            error = true;
                        }
                        else
                        {
                            // Antes de la primera herramienta que toca el dibujo: una marca de UNDO para poder deshacer el pedido entero.
                            if (!marcaIntentada && !_soloLectura.IsMatch(visible))
                            {
                                marcaIntentada = true;
                                _hayMarca = await PonerMarca(host).ConfigureAwait(true);
                            }
                            (salida, error) = await EjecutarHerramienta(host, ll.Nombre, ll.Args, meta).ConfigureAwait(true);
                        }
                        Emitir("resultado", new JsonObject { ["nombre"] = visible, ["texto"] = salida, ["error"] = error });
                        if (!error && regexDibujo.IsMatch(visible)) dibujo = true;
                        _mensajes.Add(new JsonObject { ["role"] = "tool", ["tool_call_id"] = ll.Id, ["name"] = ll.Nombre, ["content"] = salida });
                    }
                    if (cortado) break;
                    if (vuelta == p.Vueltas - 1)
                        Emitir("aviso", Obj("texto", "Se llegó al tope de " + p.Vueltas + " vueltas. Si la tarea era larga, sigue con otra instrucción; si el modelo se quedó en un lazo, revisa qué herramienta repite."));
                }

                if (tope)
                    Emitir("aviso", Obj("texto", "Se alcanzó el tope de US$" + p.TopeUSD.ToString("0.####") + " por pedido: la corrida se detuvo. Lo dibujado se queda; sube el tope si hace falta seguir."));

                if (dibujo && enAutocad)
                {
                    // Dentro de AutoCAD no hay visor: lo que se dibujó tiene que VERSE. Una línea de 5 unidades en una vista de cientos
                    // queda escondida bajo el ícono de ejes y parece que no pasó nada.
                    var (s, e) = await EjecutarHerramienta(host, "zoom_extents", new JsonObject(), false).ConfigureAwait(true);
                    Emitir("nota", Obj("texto", e ? "No pude ajustar la vista: " + (s.Length > 120 ? s.Substring(0, 120) : s) : "Vista ajustada para mostrar lo dibujado."));
                }
                if (_hayMarca) Emitir("deshacer", new JsonObject());
            }
            catch (OperationCanceledException)
            {
                Emitir("aviso", Obj("texto", "Cancelado. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir."));
            }
            catch (Exception ex)
            {
                Emitir("aviso", Obj("texto", "Se cortó la corrida: " + ex.Message));
            }
            finally
            {
                Guardar();
                try { Emitir("fin", new JsonObject()); } catch (Exception) { }
            }
        }

        // ------------------------------------------------------------------------------------------ piezas

        private string _ultimoError;

        private async Task<JsonObject> Preparar(ChatCliente host, PedidoAgente p, bool forzar, CancellationToken ct)
        {
            try
            {
                using (var doc = await host.PostAsync("/api/h/preparar", new
                {
                    perfil = p.Perfil, proveedor = p.Proveedor, modelo = p.Modelo, conReglas = p.ConReglas,
                    contexto = p.Contexto ?? "", forzarBajoDemanda = forzar,
                }, ct).ConfigureAwait(true))
                    return (JsonObject)JsonNode.Parse(doc.RootElement.GetRawText());
            }
            catch (ChatError e) { _ultimoError = e.Message; return null; }
            catch (Exception e) when (!(e is OperationCanceledException)) { _ultimoError = "No pude hablar con el servidor de herramientas: " + e.Message; return null; }
        }

        private static IProveedorModelo CrearProveedor(JsonObject prep, PedidoAgente p)
        {
            var url = prep["url"]?.ToString() ?? "";
            var modelo = string.IsNullOrWhiteSpace(p.Modelo) ? prep["modelo"]?.ToString() ?? "" : p.Modelo.Trim();
            var clave = Credenciales.Obtener(p.Proveedor, prep["env"]?.ToString());
            if (string.IsNullOrEmpty(clave) && url.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) return null;
            if (prep["formato"]?.ToString() == "anthropic") return new ProveedorAnthropic(url, clave, modelo, p.Temperatura);
            return new ProveedorOpenAI(url, clave, modelo, p.Temperatura);
        }

        // Los avisos técnicos del agente (cómo descubre las herramientas, reintentos) no se muestran: ensucian la conversación.
        private static JsonObject Tecnica(string texto) => new JsonObject { ["texto"] = texto, ["tecnica"] = true };

        private void PasarABajoDemanda(string sistemaMeta, string nota, Action<string, JsonObject> emitir)
        {
            if (_mensajes.Count > 0 && _mensajes[0]?["role"]?.ToString() == "system")
            {
                var actual = _mensajes[0]["content"]?.ToString() ?? "";
                if (sistemaMeta.Length > 0 && !actual.Contains(sistemaMeta)) _mensajes[0]["content"] = actual + "\n\n" + sistemaMeta;
            }
            else _mensajes.Insert(0, new JsonObject { ["role"] = "system", ["content"] = sistemaMeta });
            if (!string.IsNullOrEmpty(nota)) emitir("nota", Tecnica(nota));
        }

        private sealed class Llamada { public string Id, Nombre; public JsonObject Args; }

        private static List<Llamada> LlamadasDe(JsonObject resp)
        {
            var salida = new List<Llamada>();
            if (!(resp["tool_calls"] is JsonArray ll)) return salida;
            foreach (var c in ll)
            {
                var fn = c["function"];
                var crudo = fn?["arguments"]?.ToString();
                if (string.IsNullOrWhiteSpace(crudo)) crudo = "{}";
                JsonObject args;
                try { args = JsonNode.Parse(crudo) as JsonObject ?? new JsonObject(); }
                catch (JsonException)
                {
                    // Un modelo chico a veces manda JSON roto: se le devuelve el error como resultado de la herramienta y casi siempre se corrige.
                    args = new JsonObject { ["__json_invalido__"] = crudo };
                }
                salida.Add(new Llamada { Id = c["id"]?.ToString() ?? "", Nombre = fn?["name"]?.ToString() ?? "", Args = args });
            }
            return salida;
        }

        /// <summary>Cómo se muestra la llamada en pantalla: `ejecutar_herramienta` se ve como la herramienta real.</summary>
        internal static (string nombre, JsonObject args) Visible(string nombre, JsonObject args)
        {
            if (nombre != "ejecutar_herramienta") return (nombre, args);
            var real = args["nombre"]?.ToString() ?? "?";
            JsonNode interno = args["argumentos"];
            if (interno is JsonValue v && v.TryGetValue<string>(out var texto))
            {
                try { interno = JsonNode.Parse(texto); } catch (JsonException) { interno = null; }
            }
            return (real, interno as JsonObject ?? new JsonObject());
        }

        private static async Task<(string texto, bool error)> EjecutarHerramienta(ChatCliente host, string nombre, JsonObject args, bool meta)
        {
            try
            {
                // Sin ct: una herramienta que ya empezó termina (cancelar corta ENTRE herramientas).
                using (var doc = await host.PostAsync("/api/h/ejecutar", new { nombre, args = JsonSerializer.Deserialize<object>(args.ToJsonString()), meta }).ConfigureAwait(true))
                {
                    var r = doc.RootElement;
                    var texto = r.TryGetProperty("texto", out var t) && t.ValueKind == JsonValueKind.String ? t.GetString() : "(sin salida)";
                    var error = r.TryGetProperty("error", out var e) && e.ValueKind == JsonValueKind.True;
                    return (texto, error);
                }
            }
            catch (Exception ex) { return ("ERROR al invocar '" + nombre + "': " + ex.Message, true); }
        }

        private static double? Costo(UsoTokens uso, JsonObject precio)
        {
            if (precio == null) return null;
            try
            {
                return (uso.Entrada * precio["entrada"].GetValue<double>() + uso.Salida * precio["salida"].GetValue<double>()) / 1e6;
            }
            catch (Exception) { return null; }
        }

        /// <summary>
        /// Un modelo chico a veces escupe una tira de espacios de ancho cero (U+200B...) y paréntesis: en pantalla es un mensaje
        /// «vacío» con basura. Se quitan; si no queda ninguna letra ni número, es un silencio (y el bucle le pide seguir).
        /// </summary>
        internal static string LimpiarTexto(string t)
        {
            if (string.IsNullOrEmpty(t)) return "";
            t = Regex.Replace(t, "[\u200B-\u200F\u2060-\u2064\uFEFF]", "").Replace('\u202F', ' ');
            t = Regex.Replace(t, @"\(\s*\)", "");                 // paréntesis vacíos que deja la basura
            t = Regex.Replace(t, @"[ \t]{2,}", " ").Trim();
            foreach (var c in t) if (char.IsLetterOrDigit(c)) return t;
            return "";
        }

        private static JsonObject Obj(string clave, string valor) => new JsonObject { [clave] = valor };

        // ------------------------------------------------------------------------------------------ historial

        private void Anotar(string tipo, JsonObject ev)
        {
            if (tipo != "usuario" && tipo != "texto" && tipo != "tool" && tipo != "resultado" && tipo != "aviso" && tipo != "nota") return;
            var copia = (JsonObject)ev.DeepClone();
            // Lo que la pantalla muestra de una herramienta son unos cientos de caracteres: guardar el resultado entero inflaba el archivo.
            if (tipo == "resultado")
            {
                var t = copia["texto"]?.ToString() ?? "";
                copia["texto"] = t.Length > 400 ? t.Substring(0, 400) : t;
            }
            if (tipo == "tool")
            {
                var a = copia["args"]?.ToJsonString() ?? "";
                if (a.Length > 400) copia["args"] = a.Substring(0, 397) + "…";
            }
            _eventos.Add(copia);
            while (_eventos.Count > MaxEventos) _eventos.RemoveAt(0);
        }

        private void Guardar()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_archivo));
                var raiz = new JsonObject { ["mensajes"] = _mensajes.DeepClone(), ["eventos"] = _eventos.DeepClone() };
                var tmp = _archivo + ".tmp";
                File.WriteAllText(tmp, raiz.ToJsonString(), new UTF8Encoding(false));
                if (File.Exists(_archivo)) File.Delete(_archivo);
                File.Move(tmp, _archivo);
            }
            catch (Exception) { /* el historial es una comodidad: no tumba el chat */ }
        }

        private void Cargar()
        {
            try
            {
                if (!File.Exists(_archivo)) return;
                var raiz = JsonNode.Parse(File.ReadAllText(_archivo, Encoding.UTF8)) as JsonObject;
                if (raiz?["mensajes"] is JsonArray m) _mensajes = (JsonArray)m.DeepClone();
                if (raiz?["eventos"] is JsonArray e) _eventos = (JsonArray)e.DeepClone();
            }
            catch (Exception) { }
        }
    }
}
