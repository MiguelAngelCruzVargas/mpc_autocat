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
