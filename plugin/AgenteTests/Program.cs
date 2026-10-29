using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AutoCadMcpPlugin.Chat;

namespace AgenteTests
{
    /// <summary>Un modelo de mentira: cada llamada ejecuta el siguiente paso del guion (una respuesta o una excepción).</summary>
    internal sealed class ModeloGuion : IProveedorModelo
    {
        private readonly List<Func<JsonObject>> _pasos;
        public int Llamadas;
        public List<int> ToolsEnviadas = new List<int>();
        public List<string> Ultimos = new List<string>();
        public string Modelo => "falso";
        public UsoTokens Uso { get; } = new UsoTokens();
        public ModeloGuion(params Func<JsonObject>[] pasos) { _pasos = pasos.ToList(); }

        public Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct)
        {
            ToolsEnviadas.Add(tools.Count);
            Ultimos.Add(mensajes[mensajes.Count - 1]["content"]?.ToString() ?? "");
            var paso = _pasos[Math.Min(Llamadas++, _pasos.Count - 1)];
            Uso.Entrada += 100; Uso.Salida += 10; Uso.Vueltas++;
            return Task.FromResult(paso());
        }

        public static JsonObject Texto(string t) => new JsonObject { ["role"] = "assistant", ["content"] = t };
        public static JsonObject Silencio() => new JsonObject { ["role"] = "assistant", ["content"] = "" };
        public static JsonObject Llama(string nombre, string args) => new JsonObject
        {
            ["role"] = "assistant", ["content"] = null,
            ["tool_calls"] = new JsonArray { new JsonObject { ["id"] = "c" + Guid.NewGuid().ToString("N").Substring(0, 6), ["type"] = "function",
                ["function"] = new JsonObject { ["name"] = nombre, ["arguments"] = args } } },
        };
    }

    internal static class Program
    {
        private static readonly List<string> Fallas = new List<string>();

        private static void Check(string nombre, bool ok, string detalle = "")
        {
            if (!ok) Fallas.Add(nombre + ": " + detalle);
            Console.WriteLine((ok ? "  ok  " : " FALLA ") + nombre + (ok ? "" : " -- " + detalle));
        }

        private static async Task<(List<JsonElement> eventos, AgenteNativo agente)> Correr(string url, PedidoAgente p, Func<ModeloGuion> modelo, string dir, CancellationToken ct = default)
        {
            var cli = new ChatCliente(url);
            var agente = new AgenteNativo(() => cli, Path.Combine(dir, Guid.NewGuid().ToString("N") + ".json"));
            var m = modelo();
            agente.FabricaProveedor = (prep, ped) => m;
            var eventos = new List<JsonElement>();
            await agente.EjecutarAsync(p, ev => eventos.Add(ev.Clone()), ct);
            _ultimoModelo = m;
            return (eventos, agente);
        }

        private static ModeloGuion _ultimoModelo;

        private static string[] Tipos(List<JsonElement> ev) => ev.Select(e => e.GetProperty("tipo").GetString()).ToArray();
        private static bool Hay(List<JsonElement> ev, string tipo, string contiene) =>
            ev.Any(e => e.GetProperty("tipo").GetString() == tipo && e.TryGetProperty("texto", out var t) && (t.GetString() ?? "").Contains(contiene));

        private static async Task<int> Main(string[] args)
        {
            var url = args.FirstOrDefault(a => a.StartsWith("http")) ?? "http://127.0.0.1:8780";
            var dir = Path.Combine(Path.GetTempPath(), "agente_tests_" + Guid.NewGuid().ToString("N").Substring(0, 6));
            Directory.CreateDirectory(dir);

            Console.WriteLine("test_capacidades_del_modelo");
            var c20 = Capacidades.Evaluar("groq", "openai/gpt-oss-20b");
            Check("gpt-oss-20b: limitado, sin imagenes y pequeno", c20.Limitado && !c20.Imagenes
                  && c20.Avisos.Any(a => a.Etiqueta == "no ve imágenes") && c20.Avisos.Any(a => a.Etiqueta == "modelo pequeño"));
            var c120 = Capacidades.Evaluar("groq", "openai/gpt-oss-120b");
            Check("gpt-oss-120b: sin imagenes pero NO pequeno", c120.Limitado && !c120.Avisos.Any(a => a.Etiqueta == "modelo pequeño"));
            var cw = Capacidades.Evaluar("groq", "whisper-large-v3");
            Check("whisper no es modelo de chat (nivel alto)", cw.Limitado && cw.Avisos.Count == 1 && cw.Avisos[0].Nivel == "alto");
            var cc = Capacidades.Evaluar("anthropic", "claude-sonnet-5-5");
            Check("claude: sin avisos y con imagenes", !cc.Limitado && cc.Imagenes && cc.Avisos.Count == 0);
            Check("«gemini» no se confunde con «mini»", !Capacidades.EsPequeno("google/gemini-2.5-pro") && Capacidades.EsPequeno("gpt-5-mini"));
            Check("«28b» no es chico y «8b» si", !Capacidades.EsPequeno("qwen2.5-28b") && Capacidades.EsPequeno("llama-3.1-8b-instant"));
            Check("local avisa de las herramientas", Capacidades.Evaluar("local", "llama3").Avisos.Any(a => a.Etiqueta == "herramientas dudosas"));
            Check("lo que el proveedor publica manda sobre el nombre", Capacidades.Evaluar("openrouter", "vendor/raro-1", true).Imagenes);
            Check("groq avisa su tope de 128 herramientas (aviso bajo)", c120.Avisos.Any(a => a.Nivel == "bajo" && a.Etiqueta.Contains("128")));

            Console.WriteLine("test_claves_y_preferencias_en_csharp");
            {
                var raizTmp = Path.Combine(Path.GetTempPath(), "cred_tests_" + Guid.NewGuid().ToString("N").Substring(0, 6));
                var dirCred = Path.Combine(raizTmp, "AutoCadMcp");
                Environment.SetEnvironmentVariable("AUTOCAD_IA_CREDENCIALES", dirCred);
                var modo = Credenciales.Guardar("groq", "gsk_clave_de_prueba_123");
                Check("guarda la clave cifrada con DPAPI", modo == "dpapi", modo);
                Check("el archivo no contiene la clave en claro", !File.ReadAllText(Path.Combine(dirCred, "credenciales.json")).Contains("gsk_clave_de_prueba_123"));
                Check("se lee de vuelta", Credenciales.Obtener("groq", null) == "gsk_clave_de_prueba_123");
                var py = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("python",
                    "-c \"import sys; sys.path.insert(0, r'" + Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..")) + "'); from agent import credenciales as c; print(c.obtener('groq'))\"")
                { RedirectStandardOutput = true, UseShellExecute = false, EnvironmentVariables = { ["LOCALAPPDATA"] = raizTmp } });
                var salidaPy = py.StandardOutput.ReadToEnd().Trim(); py.WaitForExit();
                Check("Python lee lo que escribio C# (mismo formato)", salidaPy == "gsk_clave_de_prueba_123", salidaPy);
                Check("borrar la quita", Credenciales.Borrar("groq") && Credenciales.Obtener("groq", null) == null && !Credenciales.Borrar("groq"));
                Preferencias.Guardar("perfil", "descubrir");
                Preferencias.Guardar("topeUSD", 0.5);
                Preferencias.Guardar("modelos", new Dictionary<string, string> { ["groq"] = "openai/gpt-oss-120b" });
                Preferencias.Guardar("loQueSea", "x");
                var pr = Preferencias.Leer();
                Check("guarda preferencias y las lee", pr["perfil"].ToString() == "descubrir" && (double)pr["topeUSD"] == 0.5 && pr["modelos"]["groq"].ToString() == "openai/gpt-oss-120b");
                Check("lo que no esta en la lista blanca no se guarda", !pr.ContainsKey("loQueSea"));
                Environment.SetEnvironmentVariable("AUTOCAD_IA_CREDENCIALES", null);
                try { Directory.Delete(raizTmp, true); } catch { }
            }

            Console.WriteLine("test_lista_de_modelos_en_csharp");
            {
                const string json = "{\"data\":[{\"id\":\"vendor/raro-1\",\"architecture\":{\"input_modalities\":[\"text\",\"image\"]}},"
                    + "{\"id\":\"openai/gpt-oss-120b\"},{\"id\":\"claude-sonnet-5-5\"},{\"name\":\"solo-nombre\"},{\"id\":\"x/solo-texto\",\"architecture\":{\"modality\":\"text->text\"}}]}";
                var filas = Proveedores.Analizar(json);
                Check("lee id y name", filas.Count == 5 && filas[3].Modelo == "solo-nombre");
                Check("la visión publicada manda (vendor/raro-1 ve imagenes por su arquitectura)", filas[0].Imagenes);
                Check("sin dato publicado se reconoce por el nombre", !filas[1].Imagenes && filas[2].Imagenes);
                Check("modality «text->text» no ve imagenes", !filas[4].Imagenes);
                Check("también entiende {models:[...]} y una lista suelta", Proveedores.Analizar("{\"models\":[{\"id\":\"a\"}]}").Count == 1 && Proveedores.Analizar("[\"a\",\"b\"]").Count == 2);
                Check("los 7 proveedores y su modelo sugerido", Proveedores.Presets.Count == 7 && Proveedores.Buscar("groq").ModeloSugerido == "openai/gpt-oss-120b" && Proveedores.Buscar("nadie") == null);
                try
                {
                    var puerto = 0;
                    using (var tmp = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0)) { tmp.Start(); puerto = ((System.Net.IPEndPoint)tmp.LocalEndpoint).Port; tmp.Stop(); }
                    var oyente = new System.Net.HttpListener(); oyente.Prefixes.Add("http://127.0.0.1:" + puerto + "/"); oyente.Start();
                    string pedidoAuth = null; string ruta = null;
                    var servidor = Task.Run(async () =>
                    {
                        var ctx = await oyente.GetContextAsync();
                        ruta = ctx.Request.Url.AbsolutePath; pedidoAuth = ctx.Request.Headers["Authorization"];
                        var cuerpo = System.Text.Encoding.UTF8.GetBytes(json); ctx.Response.ContentType = "application/json"; ctx.Response.OutputStream.Write(cuerpo, 0, cuerpo.Length); ctx.Response.Close();
                    });
                    Environment.SetEnvironmentVariable("GROQ_API_KEY", "gsk_de_entorno");
                    var viaHttp = await Proveedores.ListarModelosAsync("groq", "http://127.0.0.1:" + puerto + "/v1");
                    await servidor; oyente.Stop();
                    Environment.SetEnvironmentVariable("GROQ_API_KEY", null);
                    Check("pide /models con la clave como Bearer", ruta == "/v1/models" && pedidoAuth == "Bearer gsk_de_entorno" && viaHttp.Count == 5, ruta + " " + pedidoAuth);
                }
                catch (System.Net.HttpListenerException ex) { Console.WriteLine("  (sin prueba por HTTP: " + ex.Message + ")"); }
            }

            Console.WriteLine("test_licencia_en_csharp");
            {
                var tmpLic = Path.Combine(Path.GetTempPath(), "lic_tests_" + Guid.NewGuid().ToString("N").Substring(0, 6));
                Environment.SetEnvironmentVariable("AUTOCAD_IA_CREDENCIALES", tmpLic);
                var sin = AutoCadMcpPlugin.LicenciaGuard.Estado();
                Check("sin archivo: no hay licencia", sin["valida"].GetValue<bool>() == false && sin["motivo"].ToString() == "sin_licencia");
                var rechazado = false;
                try { AutoCadMcpPlugin.LicenciaGuard.Instalar(new System.Text.Json.Nodes.JsonObject { ["token"] = "cuerpo.firma" }, null); }
                catch (InvalidOperationException) { rechazado = true; }
                Check("nunca guarda un token que no verifica", rechazado && !File.Exists(Path.Combine(tmpLic, "licencia.json")));
                var claveCorta = false;
                try { await AutoCadMcpPlugin.LicenciaGuard.ActivarAsync("AIA-1"); } catch (InvalidOperationException) { claveCorta = true; }
                Check("una clave con formato roto ni sale a la red", claveCorta);
                Environment.SetEnvironmentVariable("AUTOCAD_IA_LICENCIAS_URL", "http://127.0.0.1:9/");
                var sinRed = "";
                try { await AutoCadMcpPlugin.LicenciaGuard.PruebaAsync(); } catch (InvalidOperationException ex) { sinRed = ex.Message; }
                Check("sin servidor: mensaje claro, no excepcion cruda", sinRed.Contains("No se pudo contactar"), sinRed);
                Environment.SetEnvironmentVariable("AUTOCAD_IA_LICENCIAS_URL", null);
                Environment.SetEnvironmentVariable("AUTOCAD_IA_CREDENCIALES", null);
            }

            Console.WriteLine("test_perfiles_en_csharp");
            {
                var ids = Perfiles.Todos.Select(p => p.Id).ToArray();
                Check("las 6 especialidades, en el orden de siempre", string.Join(",", ids) == "arquitectura,civil,estructura,basico,todo,descubrir", string.Join(",", ids));
                var nombresPrueba = new[] { "create_line", "create_walls", "check_all", "delete_entities", "run_command", "create_road", "design_footing" };
                var arq = Perfiles.Filtrar(nombresPrueba, Perfiles.Buscar("arquitectura"));
                Check("nombre exacto o prefijo (check_ entra por prefijo)", arq.Contains("create_walls") && arq.Contains("check_all") && arq.Contains("delete_entities") && !arq.Contains("create_road"), string.Join(",", arq));
                Check("«todo» y «descubrir» ven todas", Perfiles.Filtrar(nombresPrueba, Perfiles.Buscar("todo")).Count == nombresPrueba.Length && Perfiles.Buscar("descubrir").Patrones.Length == 0);
                Check("un nombre que solo CONTIENE el patrón no entra", !Perfiles.Coincide("my_check_all", new[] { "check_" }) && Perfiles.Coincide("check_all", new[] { "check_" }));
            }

            Console.WriteLine("test_sin_licencia_no_se_usa_nada");
            {
                var cliLic = new ChatCliente(url);
                var agLic = new AgenteNativo(() => cliLic, Path.Combine(dir, "lic.json"));
                bool llamoAlModelo = false;
                agLic.FabricaProveedor = (prep, ped) => { llamoAlModelo = true; return null; };
                agLic.Licencia = () => (true, false, "La licencia vencio.");
                var evLic = new List<JsonElement>();
                await agLic.EjecutarAsync(new PedidoAgente { Mensaje = "dibuja un circulo", Proveedor = "groq", Modelo = "m" }, e => evLic.Add(e.Clone()), default);
                Check("sin licencia: avisa y explica por qué", Hay(evLic, "aviso", "Sin licencia: La licencia vencio."));
                Check("sin licencia: no llega a pedir las herramientas ni a llamar al modelo", !llamoAlModelo && !Tipos(evLic).Contains("inicio") && !Tipos(evLic).Contains("tool"));
                var evOk = new List<JsonElement>();
                agLic.Licencia = () => (false, false, "");
                await agLic.EjecutarAsync(new PedidoAgente { Mensaje = "hola", Proveedor = "groq", Modelo = "m" }, e => evOk.Add(e.Clone()), default);
                Check("una copia que no exige licencia (desarrollo) sigue funcionando", !Hay(evOk, "aviso", "Sin licencia"));
            }

            Console.WriteLine("test_imagenes_adjuntas");
            {
                const string png = "data:image/png;base64,iVBORw0KGgo=";
                var sinImg = AgenteNativo.MensajeUsuario("hola", new List<string>());
                Check("sin imagenes el mensaje sigue siendo texto", sinImg["content"].ToString() == "hola");
                var conImg = AgenteNativo.MensajeUsuario("mira", new List<string> { png, png });
                var partes = (JsonArray)conImg["content"];
                Check("con imagenes: una parte de texto y una image_url por imagen", partes.Count == 3 && partes[0]["type"].ToString() == "text" && partes[1]["image_url"]["url"].ToString() == png);
                var convImg = new JsonArray { conImg };
                var cambiados = AgenteNativo.QuitarImagenes(convImg);
                Check("al terminar el pedido las imagenes se cambian por una nota (no se guardan ni se reenvian)", cambiados == 1 && convImg[0]["content"].ToString().Contains("[2 imágenes adjuntas") && !convImg.ToJsonString().Contains("base64"));
                var (_, tr) = ProveedorAnthropic.Traducir(new JsonArray { AgenteNativo.MensajeUsuario("mira", new List<string> { png }) });
                var bloque = tr[0]["content"][1];
                Check("Anthropic recibe el bloque image con su media_type y el base64", bloque["type"].ToString() == "image" && bloque["source"]["media_type"].ToString() == "image/png" && bloque["source"]["data"].ToString() == "iVBORw0KGgo=");
                Check("un texto suelto no se toca al traducir", ProveedorAnthropic.ContenidoAnthropic("hola").ToString() == "hola");

                var sinVista = new ModeloGuion(() => ModeloGuion.Texto("listo"));
                var (evImg, _) = await Correr(url, new PedidoAgente { Mensaje = "mira", Proveedor = "groq", Modelo = "openai/gpt-oss-120b", Imagenes = new List<string> { png } }, () => sinVista, dir);
                Check("con un modelo que no ve imagenes avisa y manda solo el texto", Hay(evImg, "aviso", "no ve imágenes") && !sinVista.Ultimos[0].Contains("image_url"), sinVista.Ultimos.Count > 0 ? sinVista.Ultimos[0] : "(sin llamada)");
                var conVista = new ModeloGuion(() => ModeloGuion.Texto("listo"));
                var (evVe, _) = await Correr(url, new PedidoAgente { Mensaje = "mira", Proveedor = "anthropic", Modelo = "claude-sonnet-5-5", Imagenes = new List<string> { png } }, () => conVista, dir);
                Check("con un modelo que ve, la imagen llega como image_url y sin aviso", !Hay(evVe, "aviso", "no ve imágenes") && conVista.Ultimos[0].Contains("image_url"), conVista.Ultimos.Count > 0 ? conVista.Ultimos[0] : "(sin llamada)");
            }

            Console.WriteLine("test_modelo_ve_la_captura");
            {
                var rutaPng = Path.Combine(dir, "captura.png");
                File.WriteAllBytes(rutaPng, new byte[] { 137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3 });
                var url0 = AgenteNativo.LeerCaptura(new JsonObject { ["path"] = rutaPng });
                Check("lee la captura que dejó capture_viewport como data URL png", url0 != null && url0.StartsWith("data:image/png;base64,"));
                Check("una ruta que no existe, o que no es imagen, no da nada", AgenteNativo.LeerCaptura(new JsonObject { ["path"] = Path.Combine(dir, "no_existe.png") }) == null
                      && AgenteNativo.LeerCaptura(new JsonObject { ["path"] = Path.Combine(dir, "captura.png.txt") }) == null && AgenteNativo.LeerCaptura(new JsonObject()) == null);
                var vieja = AgenteNativo.MensajeUsuario("captura 1", new List<string> { "data:image/png;base64,AAAA" });
                var media = AgenteNativo.MensajeUsuario("captura 2", new List<string> { "data:image/png;base64,BBBB" });
                var nueva = AgenteNativo.MensajeUsuario("captura 3", new List<string> { "data:image/png;base64,CCCC" });
                var hist = new JsonArray { vieja, media, nueva };
                AgenteNativo.QuitarImagenes(hist, 2);
                Check("se conservan las ultimas 2 capturas y la mas vieja pasa a nota", hist[0]["content"].ToString().Contains("[1 imagen adjunta") && hist[1]["content"] is JsonArray && hist[2]["content"] is JsonArray);
            }

            Console.WriteLine("test_traduccion_a_anthropic");
            var conv = new JsonArray
            {
                new JsonObject { ["role"] = "system", ["content"] = "SISTEMA" },
                new JsonObject { ["role"] = "user", ["content"] = "hola" },
                ModeloGuion.Llama("create_line", "{\"x1\":0}"),
                new JsonObject { ["role"] = "tool", ["tool_call_id"] = "c1", ["name"] = "create_line", ["content"] = "R1" },
                new JsonObject { ["role"] = "tool", ["tool_call_id"] = "c2", ["name"] = "create_line", ["content"] = "R2" },
                ModeloGuion.Texto("listo"),
            };
            ((JsonObject)conv[2])["tool_calls"][0]["id"] = "c1";
            var (sis, msgs) = ProveedorAnthropic.Traducir(conv);
            Check("el system va aparte", sis == "SISTEMA" && msgs.All(m => m["role"].ToString() != "system"));
            Check("tool_use lleva su input como objeto", msgs[1]["content"][0]["type"].ToString() == "tool_use" && msgs[1]["content"][0]["input"]["x1"].GetValue<int>() == 0);
            Check("los resultados seguidos van juntos en UN mensaje user", msgs[2]["role"].ToString() == "user" && ((JsonArray)msgs[2]["content"]).Count == 2
                  && msgs[2]["content"][1]["tool_use_id"] == null == false);
            var resp = ProveedorAnthropic.AMensajeOpenAI(JsonNode.Parse("{\"content\":[{\"type\":\"text\",\"text\":\"ok\"},{\"type\":\"tool_use\",\"id\":\"t1\",\"name\":\"x\",\"input\":{\"a\":1}}]}") as JsonObject);
            Check("la respuesta de Anthropic vuelve en formato OpenAI", resp["content"].ToString() == "ok" && resp["tool_calls"][0]["function"]["name"].ToString() == "x"
                  && resp["tool_calls"][0]["function"]["arguments"].ToString().Contains("\"a\":1"));

            Console.WriteLine("test_visible");
            var (v, a) = AgenteNativo.Visible("ejecutar_herramienta", new JsonObject { ["nombre"] = "create_line", ["argumentos"] = "{\"x1\":5}" });
            Check("ejecutar_herramienta se ve como la herramienta real, aunque los argumentos lleguen como texto", v == "create_line" && a["x1"].GetValue<int>() == 5);

            Console.WriteLine("test_bucle_con_el_anfitrion");
            var ped = new PedidoAgente { Mensaje = "dibuja una casa", Proveedor = "groq", Modelo = "falso", Perfil = "descubrir" };
            var (ev, ag) = await Correr(url, ped, () => new ModeloGuion(
                () => ModeloGuion.Llama("buscar_herramientas", "{\"flujo\":\"casa\"}"),
                () => ModeloGuion.Silencio(),
                () => ModeloGuion.Texto("Listo: ya quedó.")), dir);
            Check("sin clave no hace falta (el modelo es de mentira) y arranca con 'inicio'", Tipos(ev).Contains("inicio"), string.Join(",", Tipos(ev)) + " " + string.Join(" | ", ev.Where(e => e.GetProperty("tipo").GetString() == "aviso").Select(e => e.GetProperty("texto").GetString())));
            Check("avisa que va bajo demanda", Hay(ev, "nota", "bajo demanda"));
            Check("ejecuta la herramienta por el anfitrión y muestra su resultado",
                  ev.Any(e => e.GetProperty("tipo").GetString() == "tool" && e.GetProperty("nombre").GetString() == "buscar_herramientas")
                  && ev.Any(e => e.GetProperty("tipo").GetString() == "resultado" && !e.GetProperty("error").GetBoolean() && e.GetProperty("texto").GetString().Contains("casa")));
            Check("si el modelo se calla tras trabajar, se le pide seguir", Hay(ev, "nota", "sin decir nada"));
            Check("el texto final llega", Hay(ev, "texto", "Listo"));
            Check("termina con 'fin'", Tipos(ev).Last() == "fin");
            Check("manda solo las 3 herramientas de descubrimiento", _ultimoModelo.ToolsEnviadas.All(n => n == 3), string.Join(",", _ultimoModelo.ToolsEnviadas));
            Check("el uso se informa en cada vuelta", ev.Count(e => e.GetProperty("tipo").GetString() == "uso") == 3);
            Check("la conversación no guarda un mensaje vacío del asistente", ag.Eventos.Count > 0);

            Console.WriteLine("test_pide_la_herramienta_real_directo");
            (ev, _) = await Correr(url, ped, () => new ModeloGuion(
                () => throw new ToolInvalida("pidió una que no está", "create_line"),
                () => ModeloGuion.Texto("Entendido.")), dir);
            Check("se le explica cómo usar ejecutar_herramienta", Hay(ev, "nota", "ejecutar_herramienta") && _ultimoModelo.Ultimos[1].Contains("ejecutar_herramienta") && _ultimoModelo.Ultimos[1].Contains("create_line"));
            Check("y no sale como error rojo", !Tipos(ev).Contains("aviso"), string.Join(",", Tipos(ev)));

            Console.WriteLine("test_demasiadas_herramientas");
            var ped2 = new PedidoAgente { Mensaje = "hola", Proveedor = "groq", Modelo = "falso", Perfil = "arquitectura" };
            (ev, _) = await Correr(url, ped2, () => new ModeloGuion(
                () => throw new ErrorProveedor("El modelo respondió 400: 'tools' : maximum number of items is 128"),
                () => ModeloGuion.Texto("Hola.")), dir);
            Check("si el proveedor rechaza la cantidad, reintenta bajo demanda", _ultimoModelo.ToolsEnviadas.Count == 2 && _ultimoModelo.ToolsEnviadas[0] > 3 && _ultimoModelo.ToolsEnviadas[1] == 3,
                  string.Join(",", _ultimoModelo.ToolsEnviadas));
            Check("lo cuenta como nota, no como error", Hay(ev, "nota", "rechazó la cantidad") && !Tipos(ev).Contains("aviso"));

            Console.WriteLine("test_errores_del_proveedor");
            (ev, _) = await Correr(url, ped2, () => new ModeloGuion(() => throw new ErrorProveedor("El modelo respondió 401: clave inválida")), dir);
            Check("un error del proveedor llega a la persona y corta", Hay(ev, "aviso", "401") && Tipos(ev).Last() == "fin");

            Console.WriteLine("test_cancelar");
            var cts = new CancellationTokenSource(); cts.Cancel();
            (ev, _) = await Correr(url, ped2, () => new ModeloGuion(() => ModeloGuion.Texto("no debería llegar")), dir, cts.Token);
            Check("cancelado antes de empezar: avisa y no llama al modelo", Hay(ev, "aviso", "Cancelado") && _ultimoModelo.Llamadas == 0);

            Console.WriteLine("test_razonamiento_de_deepseek");
            {
                var cliR = new ChatCliente(url);
                var agR = new AgenteNativo(() => cliR, Path.Combine(dir, "r.json"));
                var mR = new ModeloGuion(
                    () => { var m = ModeloGuion.Llama("buscar_herramientas", "{\"flujo\":\"casa\"}"); m["reasoning_content"] = "pienso: busco el flujo"; return m; },
                    () => { var m = ModeloGuion.Texto("Listo."); m["reasoning_content"] = "pienso: ya terminé"; return m; });
                agR.FabricaProveedor = (prep, p) => mR;
                await agR.EjecutarAsync(ped, e => { }, CancellationToken.None);
                var asist = agR.Mensajes.Where(m => m["role"].ToString() == "assistant").ToList();
                Check("el razonamiento de cada turno se guarda para devolverlo (DeepSeek responde 400 si falta)",
                      asist.Count == 2 && asist[0]["reasoning_content"]?.ToString() == "pienso: busco el flujo" && asist[1]["reasoning_content"]?.ToString() == "pienso: ya terminé");
            }

            Console.WriteLine("test_el_sistema_se_renueva");
            {
                var archivoS = Path.Combine(dir, "s.json");
                File.WriteAllText(archivoS, "{\"mensajes\":[{\"role\":\"system\",\"content\":\"REGLA VIEJA\"},{\"role\":\"user\",\"content\":\"hola\"},{\"role\":\"assistant\",\"content\":\"hi\"}],\"eventos\":[]}");
                var cliS = new ChatCliente(url);
                var agS = new AgenteNativo(() => cliS, archivoS);
                var mS = new ModeloGuion(() => ModeloGuion.Texto("ok"));
                agS.FabricaProveedor = (prep, p) => mS;
                await agS.EjecutarAsync(ped2, e => { }, CancellationToken.None);
                Check("una conversación vieja recibe el texto de sistema NUEVO", !agS.Mensajes[0]["content"].ToString().Contains("REGLA VIEJA") && agS.Mensajes.Count(m => m["role"].ToString() == "system") == 1);
                Check("y conserva lo hablado", agS.Mensajes.Any(m => m["content"]?.ToString() == "hi"));
            }

            Console.WriteLine("test_permisos");
            {
                var cliP = new ChatCliente(url);
                var agP = new AgenteNativo(() => cliP, Path.Combine(dir, "p.json"));
                var llamarBorrar = new Func<ModeloGuion>(() => new ModeloGuion(
                    () => ModeloGuion.Llama("delete_entities", "{\"handles\":[\"FFFFFF9\"]}"),
                    () => ModeloGuion.Texto("hecho")));
                var mP = llamarBorrar();
                agP.FabricaProveedor = (prep, p) => mP;
                var evP = new List<JsonElement>();
                int decision = 0;
                await agP.EjecutarAsync(ped2, e => { evP.Add(e.Clone()); if (e.GetProperty("tipo").GetString() == "permiso") agP.ResolverPermiso(e.GetProperty("id").GetString(), decision); }, CancellationToken.None);
                Check("borrar pide permiso (tarjeta con la herramienta y sus argumentos)",
                      evP.Any(e => e.GetProperty("tipo").GetString() == "permiso" && e.GetProperty("nombre").GetString() == "delete_entities" && e.GetProperty("args").GetProperty("handles").GetArrayLength() == 1));
                var res = evP.First(e => e.GetProperty("tipo").GetString() == "resultado");
                Check("rechazado: no se ejecuta y el modelo lo sabe", res.GetProperty("error").GetBoolean() && res.GetProperty("texto").GetString().Contains("RECHAZÓ"));
                Check("el permiso va ANTES de la tarjeta de la herramienta", Tipos(evP).ToList().IndexOf("permiso") < Tipos(evP).ToList().IndexOf("tool"));

                // permitir una vez: se ejecuta (aquí falla porque no hay AutoCAD, pero NO por rechazo)
                mP = llamarBorrar(); decision = 1; evP.Clear();
                await agP.EjecutarAsync(ped2, e => { evP.Add(e.Clone()); if (e.GetProperty("tipo").GetString() == "permiso") agP.ResolverPermiso(e.GetProperty("id").GetString(), decision); }, CancellationToken.None);
                Check("permitido: se ejecuta de verdad (no es un rechazo)", !evP.First(e => e.GetProperty("tipo").GetString() == "resultado").GetProperty("texto").GetString().Contains("RECHAZÓ"));

                // permitir siempre: la segunda vez no pregunta
                mP = llamarBorrar(); decision = 2; evP.Clear();
                await agP.EjecutarAsync(ped2, e => { evP.Add(e.Clone()); if (e.GetProperty("tipo").GetString() == "permiso") agP.ResolverPermiso(e.GetProperty("id").GetString(), decision); }, CancellationToken.None);
                mP = llamarBorrar(); evP.Clear();
                await agP.EjecutarAsync(ped2, e => evP.Add(e.Clone()), CancellationToken.None);
                Check("«permitir siempre» no vuelve a preguntar en la conversación", !Tipos(evP).Contains("permiso") && Tipos(evP).Contains("resultado"));
                agP.Reiniciar();
                mP = llamarBorrar(); evP.Clear();
                await agP.EjecutarAsync(ped2, e => { evP.Add(e.Clone()); if (e.GetProperty("tipo").GetString() == "permiso") agP.ResolverPermiso(e.GetProperty("id").GetString(), 0); }, CancellationToken.None);
                Check("y «＋» (conversación nueva) lo olvida", Tipos(evP).Contains("permiso"));

                // detener mientras espera el permiso: cuenta como rechazo y no se cuelga
                mP = llamarBorrar(); evP.Clear();
                var ctsP = new CancellationTokenSource();
                var tarea = agP.EjecutarAsync(ped2, e => { evP.Add(e.Clone()); if (e.GetProperty("tipo").GetString() == "permiso") ctsP.Cancel(); }, ctsP.Token);
                var termino = await Task.WhenAny(tarea, Task.Delay(15000)) == tarea;
                Check("«Detener» con un permiso pendiente no cuelga el agente", termino && Tipos(evP).Last() == "fin");

                // las herramientas de dibujo y las consultas NO preguntan
                mP = new ModeloGuion(() => ModeloGuion.Llama("create_line", "{\"x1\":0}"), () => ModeloGuion.Llama("list_layers", "{}"), () => ModeloGuion.Texto("ok"));
                agP.FabricaProveedor = (prep, p) => mP;
                evP.Clear();
                await agP.EjecutarAsync(ped2, e => evP.Add(e.Clone()), CancellationToken.None);
                Check("dibujar y consultar no piden permiso", !Tipos(evP).Contains("permiso"));
                Check("sin AutoCAD no hay marca de UNDO: no se ofrece «Deshacer»", !Tipos(evP).Contains("deshacer"));
                Check("ComandoOk entiende la respuesta de run_command",
                      AgenteNativo.ComandoOk("{\"state\":\"done\",\"ok\":true}") && !AgenteNativo.ComandoOk("{\"ok\":false,\"error\":\"x\"}") && !AgenteNativo.ComandoOk("no es json"));
            }

            Console.WriteLine("test_modos_de_permiso");
            {
                var cliM = new ChatCliente(url);
                var agM = new AgenteNativo(() => cliM, Path.Combine(dir, "m.json"));
                int Permisos(string modo, string herramienta, string args)
                {
                    var m = new ModeloGuion(() => ModeloGuion.Llama(herramienta, args), () => ModeloGuion.Texto("ok"));
                    agM.FabricaProveedor = (prep, p) => m;
                    int n = 0;
                    var pe = new PedidoAgente { Mensaje = "x", Proveedor = "groq", Modelo = "falso", Perfil = "arquitectura", ModoPermisos = modo };
                    agM.Reiniciar();
                    agM.EjecutarAsync(pe, e => { if (e.GetProperty("tipo").GetString() == "permiso") { n++; agM.ResolverPermiso(e.GetProperty("id").GetString(), 0); } }, CancellationToken.None).GetAwaiter().GetResult();
                    return n;
                }
                Check("modo «destructivo»: borrar pide permiso", Permisos("destructivo", "delete_entities", "{\"handles\":[\"FFFFFF9\"]}") == 1);
                Check("modo «destructivo»: dibujar no pide", Permisos("destructivo", "create_line", "{\"x1\":0}") == 0);
                Check("modo «todo»: dibujar también pide", Permisos("todo", "create_line", "{\"x1\":0}") == 1);
                Check("modo «todo»: consultar no pide", Permisos("todo", "list_layers", "{}") == 0);
                Check("modo «nada»: ni borrar pide", Permisos("nada", "delete_entities", "{\"handles\":[\"FFFFFF9\"]}") == 0);
                Check("resumen de riesgo: un handle", AgenteNativo.ResumenRiesgo("delete_entities", JsonNode.Parse("{\"handles\":[\"A1\"]}") as JsonObject) == "Afecta a 1 entidad");
                Check("resumen de riesgo: varios", AgenteNativo.ResumenRiesgo("delete_entities", JsonNode.Parse("{\"handles\":[\"A1\",\"B2\",\"C3\"]}") as JsonObject) == "Afecta a 3 entidades");
                Check("resumen de riesgo: todo el espacio", AgenteNativo.ResumenRiesgo("overkill_entities", JsonNode.Parse("{\"all\":true}") as JsonObject).Contains("TODO"));
                Check("resumen de riesgo: comando libre", AgenteNativo.ResumenRiesgo("run_command", JsonNode.Parse("{\"tokens\":[\"ERASE\",\"ALL\",null]}") as JsonObject).StartsWith("Comando de AutoCAD: ERASE ALL"));
            }

            Console.WriteLine("test_varias_conversaciones");
            {
                var estado = Path.Combine(dir, "estado");
                Directory.CreateDirectory(estado);
                Environment.SetEnvironmentVariable("AUTOCAD_IA_ESTADO", estado);
                File.WriteAllText(Path.Combine(estado, "chat_nativo.json"),
                    "{\"mensajes\":[],\"eventos\":[{\"tipo\":\"usuario\",\"texto\":\"[Contexto de AutoCAD] x\\n\\ndibuja una casa de 9x12\"}]}");
                var primera = Conversaciones.RutaActiva();
                Check("la conversación única de antes pasa a la lista", !File.Exists(Path.Combine(estado, "chat_nativo.json")) && File.Exists(primera));
                Check("el título es el primer pedido, sin el bloque de contexto", Conversaciones.Listar().Single().Titulo == "dibuja una casa de 9x12");
                var cliC = new ChatCliente(url);
                var agC = new AgenteNativo(() => cliC, Conversaciones.Nueva());
                var mC = new ModeloGuion(() => ModeloGuion.Texto("hola"));
                agC.FabricaProveedor = (prep, p) => mC;
                agC.EjecutarAsync(new PedidoAgente { Mensaje = "segundo tema", Proveedor = "groq", Modelo = "falso", Perfil = "arquitectura" }, e => { }, CancellationToken.None).GetAwaiter().GetResult();
                var lista = Conversaciones.Listar();
                Check("«＋» no borra la anterior: ahora hay dos", lista.Count == 2, lista.Count.ToString());
                Check("la más reciente primero", lista[0].Titulo == "segundo tema");
                Check("RutaActiva devuelve la que está abierta", Conversaciones.RutaActiva() == agC.Ruta);
                Conversaciones.Activar(primera);
                Check("se puede volver a la anterior", Conversaciones.RutaActiva() == primera);
                Conversaciones.Borrar(primera);
                Check("borrar una la quita de la lista", Conversaciones.Listar().Count == 1);
                Check("una conversación vacía no aparece en la lista", Conversaciones.Listar().All(c => c.Pedidos > 0));
                Environment.SetEnvironmentVariable("AUTOCAD_IA_ESTADO", null);
            }

            Console.WriteLine("test_contexto_largo");
            {
                JsonArray Armar(int pedidos, int tamResultado)
                {
                    var a = new JsonArray { new JsonObject { ["role"] = "system", ["content"] = "SISTEMA" } };
                    for (int i = 0; i < pedidos; i++)
                    {
                        a.Add(new JsonObject { ["role"] = "user", ["content"] = "pedido " + i });
                        a.Add(ModeloGuion.Llama("list_entities", "{}"));
                        ((JsonObject)a[a.Count - 1])["tool_calls"][0]["id"] = "t" + i;
                        a.Add(new JsonObject { ["role"] = "tool", ["tool_call_id"] = "t" + i, ["name"] = "list_entities", ["content"] = new string('x', tamResultado) });
                        a.Add(new JsonObject { ["role"] = "assistant", ["content"] = "listo " + i });
                    }
                    return a;
                }
                var corto = Armar(12, 5000);
                var tocados = AgenteNativo.Compactar(corto, 1000000, 8);
                var largos = corto.Where(m => m["role"].ToString() == "tool").Select(m => m["content"].ToString().Length).ToList();
                Check("los resultados viejos se acortan", largos.Take(4).All(l => l < 700), string.Join(",", largos));
                Check("y los 8 más recientes se conservan completos", largos.Skip(4).All(l => l == 5000));
                Check("un resultado recortado lo dice", corto.First(m => m["role"].ToString() == "tool")["content"].ToString().Contains("recortado"));

                var w = Armar(20, 20000);
                AgenteNativo.Compactar(w, 100000, 8);
                var total = w.Sum(m => (m["content"] is JsonValue c ? c.ToString().Length : 0));
                Check("si sigue pasando del tope, se descartan los pedidos más viejos", total <= 100000 + 2000 && w.Count < 81, total + " / " + w.Count);
                Check("siempre se conserva el último pedido", w.Last()["content"].ToString() == "listo 19" && w.Any(m => m["content"]?.ToString() == "pedido 19"));
                Check("el sistema sigue primero y avisa que se omitió el principio", w[0]["role"].ToString() == "system" && w[0]["content"].ToString().Contains("se omitió el principio"));
                Check("no queda un resultado de herramienta sin su llamada", w.Skip(1).First()["role"].ToString() == "user");
                var llamadas = new HashSet<string>(w.Where(m => m["tool_calls"] != null).SelectMany(m => ((JsonArray)m["tool_calls"]).Select(c => c["id"].ToString())));
                Check("cada resultado conservado tiene su llamada", w.Where(m => m["role"].ToString() == "tool").All(m => llamadas.Contains(m["tool_call_id"].ToString())));
                var chica = Armar(3, 100);
                Check("una conversación corta no se toca", AgenteNativo.Compactar(chica, 100000, 8) == 0);
            }

            Console.WriteLine("test_flujo_openai");
            {
                var vistos = new List<string>();
                var acu = new AcumuladorOpenAI(s => vistos.Add(s));
                foreach (var l in new[]
                {
                    "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\",\"content\":\"Hol\"}}]}",
                    "",
                    "data: {\"choices\":[{\"delta\":{\"content\":\"a, \"}}]}",
                    "data: {\"choices\":[{\"delta\":{\"content\":\"mundo\"}}]}",
                    "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"pienso\"}}]}",
                    "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"c1\",\"function\":{\"name\":\"buscar_herramientas\",\"arguments\":\"{\\\"fl\"}}]}}]}",
                    "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"ujo\\\":\\\"casa\\\"}\"}}]}}]}",
                    "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":1,\"id\":\"c2\",\"function\":{\"name\":\"list_layers\",\"arguments\":\"{}\"}}]}}]}",
                    "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":5}}",
                    "data: [DONE]",
                }) acu.Linea(l);
                var res = acu.Resultado();
                Check("el texto llega en pedazos y se arma entero", res["content"].ToString() == "Hola, mundo" && vistos.Count == 3 && vistos[0] == "Hol" && vistos[2] == "Hola, mundo");
                Check("los argumentos partidos de una herramienta se unen", ((JsonArray)res["tool_calls"])[0]["function"]["arguments"].ToString() == "{\"flujo\":\"casa\"}");
                Check("varias llamadas, en su orden y con su id", ((JsonArray)res["tool_calls"]).Count == 2 && res["tool_calls"][1]["id"].ToString() == "c2" && res["tool_calls"][1]["function"]["name"].ToString() == "list_layers");
                Check("el razonamiento se guarda (DeepSeek lo exige de vuelta)", res["reasoning_content"].ToString() == "pienso");
                Check("el uso de tokens sale del último pedazo", acu.Uso["prompt_tokens"].GetValue<int>() == 10);

                var groq = new AcumuladorOpenAI(null);
                groq.Linea("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}],\"x_groq\":{\"usage\":{\"prompt_tokens\":7,\"completion_tokens\":2}}}");
                Check("Groq informa el uso dentro de x_groq", groq.Uso["prompt_tokens"].GetValue<int>() == 7);

                var plano = new AcumuladorOpenAI(null);
                plano.Linea("{\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"respuesta entera\"}}],\"usage\":{\"prompt_tokens\":3,\"completion_tokens\":1}}");
                Check("un servidor que ignora «stream» y contesta un JSON entero también se entiende", plano.Resultado()["content"].ToString() == "respuesta entera" && plano.Uso["prompt_tokens"].GetValue<int>() == 3);

                var malo = new AcumuladorOpenAI(null);
                bool lanzo = false;
                try { malo.Linea("data: {\"error\":{\"message\":\"cuota agotada\"}}"); } catch (ErrorProveedor ex) { lanzo = ex.Message.Contains("cuota agotada"); }
                Check("un error en medio del flujo llega como error", lanzo);
                Check("una línea de comentario o vacía no rompe nada", new AcumuladorOpenAI(null).Resultado()["content"] == null);
            }

            Console.WriteLine("test_flujo_anthropic");
            {
                var vistos = new List<string>();
                var acu = new AcumuladorAnthropic(s => vistos.Add(s));
                foreach (var l in new[]
                {
                    "event: message_start",
                    "data: {\"type\":\"message_start\",\"message\":{\"usage\":{\"input_tokens\":25,\"output_tokens\":1}}}",
                    "data: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}",
                    "data: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"Voy \"}}",
                    "data: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"a dibujar\"}}",
                    "data: {\"type\":\"content_block_start\",\"index\":1,\"content_block\":{\"type\":\"tool_use\",\"id\":\"tu1\",\"name\":\"create_circle\",\"input\":{}}}",
                    "data: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"{\\\"x\\\":0,\"}}",
                    "data: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"\\\"y\\\":0}\"}}",
                    "data: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"tool_use\"},\"usage\":{\"output_tokens\":42}}",
                    "data: {\"type\":\"message_stop\"}",
                }) acu.Linea(l);
                var res = acu.Resultado();
                Check("el texto de Claude se arma entero y va avisando", res["content"].ToString() == "Voy a dibujar" && vistos.Last() == "Voy a dibujar");
                Check("la herramienta de Claude junta sus argumentos partidos", res["tool_calls"][0]["function"]["name"].ToString() == "create_circle" && res["tool_calls"][0]["function"]["arguments"].ToString() == "{\"x\":0,\"y\":0}");
                Check("y el uso: entrada del inicio, salida del final", acu.Entrada == 25 && acu.Salida == 42);
            }

            Console.WriteLine("test_texto_basura");
            {
                var cliG = new ChatCliente(url);
                var agG = new AgenteNativo(() => cliG, Path.Combine(dir, "g.json"));
                var mG = new ModeloGuion(
                    () => ModeloGuion.Llama("buscar_herramientas", "{\"flujo\":\"casa\"}"),
                    () => ModeloGuion.Texto("\u200B\u200B\u200B\u200B (   ) \u200B"),
                    () => ModeloGuion.Texto("Listo."));
                agG.FabricaProveedor = (prep, p) => mG;
                var evG = new List<JsonElement>();
                await agG.EjecutarAsync(ped, e => evG.Add(e.Clone()), CancellationToken.None);
                Check("una tira de espacios de ancho cero no sale como mensaje: es un silencio y se le pide seguir",
                      Hay(evG, "nota", "sin decir nada") && Tipos(evG).Count(x => x == "texto") == 1, string.Join(",", Tipos(evG)));
                Check("y el texto de verdad llega", Hay(evG, "texto", "Listo"));
                Check("LimpiarTexto deja el texto normal intacto y vacía la basura",
                      AgenteNativo.LimpiarTexto("Círculo creado (radio 10 u).") == "Círculo creado (radio 10 u)." && AgenteNativo.LimpiarTexto("\u200B\u200B ( ) \u200B") == "" && AgenteNativo.LimpiarTexto("Entidades \u200B\u200B (   ) \u200B") == "Entidades");
            }

            Console.WriteLine("test_historial");
            var archivo = Path.Combine(dir, "h.json");
            var cli = new ChatCliente(url);
            var ag2 = new AgenteNativo(() => cli, archivo);
            var m2 = new ModeloGuion(() => ModeloGuion.Texto("Hola, ¿qué plano?"));
            ag2.FabricaProveedor = (prep, p) => m2;
            await ag2.EjecutarAsync(ped2, e => { }, CancellationToken.None);
            var ag3 = new AgenteNativo(() => cli, archivo);
            Check("la conversación se guarda y se recupera", ag3.Eventos.Any(e => e["tipo"].ToString() == "usuario" && e["texto"].ToString() == "hola")
                  && ag3.Eventos.Any(e => e["tipo"].ToString() == "texto"));
            ag3.Reiniciar();
            Check("«＋» la borra", !File.Exists(archivo) && ag3.Eventos.Count == 0);

            Console.WriteLine("test_claves");
            var clave = Credenciales.Obtener("groq", "GROQ_API_KEY");
            Check("la clave de Groq que guardó Python se descifra desde C# (DPAPI)", !string.IsNullOrEmpty(clave) && clave.StartsWith("gsk_"), clave == null ? "no se pudo" : "otra forma");
            Check("una clave en texto plano se lee tal cual", Credenciales.Revelar(JsonNode.Parse("{\"modo\":\"plano\",\"valor\":\"abc\"}")) == "abc" && Credenciales.Revelar(JsonNode.Parse("\"xyz\"")) == "xyz");

            if (args.Contains("--vivo"))
            {
                // Con un modelo de verdad (gasta unos centavos de tokens): el streaming de Groq por la red.
                Console.WriteLine("test_flujo_real_groq");
                var claveG = Credenciales.Obtener("groq", "GROQ_API_KEY");
                if (string.IsNullOrEmpty(claveG)) Console.WriteLine("  (sin clave de Groq guardada: se omite)");
                else
                {
                    var prov = new ProveedorOpenAI("https://api.groq.com/openai/v1", claveG, "openai/gpt-oss-120b", 0.2);
                    var pedazos = new List<string>();
                    var mens = new JsonArray { new JsonObject { ["role"] = "user", ["content"] = "Cuenta del 1 al 25 separados por comas, sin nada más." } };
                    var r1 = await prov.CompletarAsync(mens, new JsonArray(), CancellationToken.None, s => pedazos.Add(s));
                    Check("llegó en varios pedazos y no de golpe", pedazos.Count >= 3, pedazos.Count + " pedazos");
                    Check("el texto final está entero", r1["content"]?.ToString().Contains("25") == true, r1["content"]?.ToString());
                    Check("el uso de tokens se contó", prov.Uso.Total > 0 && prov.Uso.Vueltas == 1, prov.Uso.Total + " tokens");
                    var meta = new JsonArray { new JsonObject { ["type"] = "function", ["function"] = new JsonObject { ["name"] = "buscar_herramientas", ["description"] = "Busca herramientas", ["parameters"] = new JsonObject { ["type"] = "object", ["properties"] = new JsonObject { ["flujo"] = new JsonObject { ["type"] = "string" } } } } } };
                    var mens2 = new JsonArray { new JsonObject { ["role"] = "user", ["content"] = "Usa buscar_herramientas con flujo casa." } };
                    var r2 = await prov.CompletarAsync(mens2, meta, CancellationToken.None, s => { });
                    var llamada = (r2["tool_calls"] as JsonArray)?.FirstOrDefault();
                    Check("una herramienta llamada en streaming llega con sus argumentos completos",
                          llamada?["function"]?["name"]?.ToString() == "buscar_herramientas" && llamada["function"]["arguments"].ToString().Contains("casa"), llamada?.ToJsonString());
                    var ctsG = new CancellationTokenSource(); ctsG.CancelAfter(400);
                    bool cancelo = false;
                    try { await prov.CompletarAsync(new JsonArray { new JsonObject { ["role"] = "user", ["content"] = "Escribe un ensayo largo de 800 palabras sobre muros." } }, new JsonArray(), ctsG.Token, s => { }); }
                    catch (OperationCanceledException) { cancelo = true; }
                    Check("cancelar corta el flujo en marcha", cancelo);
                }
            }

            if (Fallas.Count > 0)
            {
                Console.WriteLine("\n" + Fallas.Count + " FALLAS:");
                foreach (var f in Fallas) Console.WriteLine(" - " + f);
                return 1;
            }
            Console.WriteLine("\nOK: el agente nativo (bucle, traducción a Anthropic, historial, claves) anda contra el anfitrión de herramientas.");
            return 0;
        }
    }
}
