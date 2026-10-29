using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using AutoCadMcpPlugin.Chat;

namespace BancoModelos
{
    /// <summary>Un modelo que contesta «listo» sin hacer nada: para probar el banco sin AutoCAD ni gastar (--simulado).</summary>
    internal sealed class ModeloMudo : IProveedorModelo
    {
        public string Modelo => "simulado";
        public UsoTokens Uso { get; } = new UsoTokens();
        public Task<JsonObject> CompletarAsync(JsonArray mensajes, JsonArray tools, CancellationToken ct)
        {
            Uso.Entrada += 100; Uso.Salida += 5; Uso.Vueltas++;
            return Task.FromResult(new JsonObject { ["role"] = "assistant", ["content"] = "Listo." });
        }
    }

    internal sealed class Contexto
    {
        public ChatCliente Host;
        public string Carpeta;
        public string Modelo;                 // para nombrar archivos de salida
        public string DibujoPrueba;           // el dibujo NUEVO que creó el banco: lo único que se borra

        /// <summary>Se niega a modificar nada si el dibujo activo no es el de prueba que creó el banco: nunca se toca un plano ajeno.</summary>
        public async Task<bool> EnDibujoDePrueba()
        {
            if (DibujoPrueba == null) return false;
            var (t, err) = await Tool("get_drawing_info").ConfigureAwait(false);
            if (err) return false;
            try { return JsonNode.Parse(t)?["fileName"]?.ToString() == DibujoPrueba; } catch (Exception) { return false; }
        }

        /// <summary>Limpia el dibujo de prueba (ERASE ALL) y solo ahí.</summary>
        public async Task Limpiar()
        {
            if (!await EnDibujoDePrueba().ConfigureAwait(false)) throw new InvalidOperationException("el dibujo activo no es el de prueba del banco: no borro nada");
            await Comando("ERASE", "ALL", null).ConfigureAwait(false);
        }

        public async Task Crear(string tool, JsonObject args)
        {
            if (!await EnDibujoDePrueba().ConfigureAwait(false)) throw new InvalidOperationException("el dibujo activo no es el de prueba del banco: no dibujo nada");
            await Tool(tool, args).ConfigureAwait(false);
        }
        public async Task<(string texto, bool error)> Tool(string nombre, JsonObject args = null)
        {
            try
            {
                using (var doc = await Host.PostAsync("/api/h/ejecutar", new { nombre, args = JsonSerializer.Deserialize<object>((args ?? new JsonObject()).ToJsonString()), meta = false }).ConfigureAwait(false))
                {
                    var r = doc.RootElement;
                    return (r.TryGetProperty("texto", out var t) && t.ValueKind == JsonValueKind.String ? t.GetString() : "", r.TryGetProperty("error", out var e) && e.ValueKind == JsonValueKind.True);
                }
            }
            catch (Exception ex) { return ("ERROR: " + ex.Message, true); }
        }

        public Task<(string texto, bool error)> Comando(params object[] tokens) =>
            Tool("run_command", new JsonObject { ["tokens"] = new JsonArray(tokens.Select(t => t == null ? null : JsonValue.Create(t)).ToArray()) });

        public async Task<int> Entidades()
        {
            var (t, err) = await Tool("get_drawing_info").ConfigureAwait(false);
            if (err) return -1;
            try { return JsonNode.Parse(t)?["entityCount"]?.GetValue<int>() ?? -1; } catch (Exception) { return -1; }
        }

        /// <summary>Cuántas entidades de un tipo hay: lee «count» o la primera lista que traiga el resultado.</summary>
        public async Task<int> Contar(string tipo)
        {
            var (t, err) = await Tool("list_entities", new JsonObject { ["entity_type"] = tipo, ["limit"] = 500 }).ConfigureAwait(false);
            if (err) return -1;
            try
            {
                var raiz = JsonNode.Parse(t) as JsonObject;
                if (raiz == null) return -1;
                if (raiz["count"] != null) return raiz["count"].GetValue<int>();
                foreach (var kv in raiz) if (kv.Value is JsonArray a) return a.Count;
                return 0;
            }
            catch (Exception) { return -1; }
        }
    }

    internal sealed class Caso
    {
        public string Id, Titulo, Pedido;
        public Func<Contexto, Task> Preparar = c => Task.CompletedTask;
        public Func<Contexto, Task<(bool ok, string detalle)>> Verificar;
        public Func<Contexto, string> PedidoPara;       // si el pedido necesita una ruta propia de cada modelo
    }

    internal sealed class Resultado
    {
        public string Modelo, Caso;
        public bool Ok; public string Detalle = "";
        public double Segundos; public int Herramientas, Errores, Vueltas, Tokens; public double Costo;
        public string Final = "";
    }

    internal static class Program
    {
        private static string Arg(string[] a, string n, string def = null) { var i = Array.IndexOf(a, n); return i >= 0 && i + 1 < a.Length ? a[i + 1] : def; }

        private static List<Caso> Casos() => new List<Caso>
        {
            new Caso
            {
                Id = "circulo", Titulo = "Un círculo",
                Pedido = "Dibuja un círculo de radio 5 con centro en el punto 0,0.",
                Preparar = async c => { await c.Limpiar(); },
                Verificar = async c => { var n = await c.Contar("Circle"); return (n >= 1, n < 0 ? "no pude contar círculos" : n + " círculo(s)"); },
            },
            new Caso
            {
                Id = "casa", Titulo = "Casa de 9 x 12 m",
                Pedido = "Dibuja la planta arquitectónica de una casa de 9 x 12 metros con dos recámaras y un baño: muros, puertas y ventanas.",
                Preparar = async c => { await c.Limpiar(); },
                Verificar = async c => { var n = await c.Entidades(); return (n >= 30, n < 0 ? "no pude contar entidades" : n + " entidades (se piden 30 o más)"); },
            },
            new Caso
            {
                Id = "borrar", Titulo = "Borrar líneas",
                Pedido = "Borra todas las líneas del dibujo.",
                Preparar = async c =>
                {
                    await c.Limpiar();
                    for (int i = 0; i < 3; i++)
                        await c.Crear("create_line", new JsonObject { ["x1"] = 0, ["y1"] = i * 10, ["x2"] = 20, ["y2"] = i * 10 });
                },
                Verificar = async c => { var n = await c.Contar("Line"); return (n == 0, n < 0 ? "no pude contar líneas" : n + " línea(s) quedaron"); },
            },
            new Caso
            {
                Id = "pdf", Titulo = "Exportar a PDF",
                Preparar = async c => { await c.Limpiar(); await c.Crear("create_circle", new JsonObject { ["x"] = 0, ["y"] = 0, ["radius"] = 5 }); },
                PedidoPara = c => "Exporta el dibujo a PDF y guárdalo exactamente en " + Ruta(c).Replace('\\', '/') + ".",
                Verificar = async c =>
                {
                    var f = new FileInfo(Ruta(c));
                    await Task.CompletedTask;
                    return (f.Exists && f.Length > 1000, f.Exists ? f.Length + " bytes" : "no existe " + f.FullName);
                },
            },
        };

        private static string Ruta(Contexto c) => Path.Combine(c.Carpeta, "banco_" + new string(c.Modelo.Where(char.IsLetterOrDigit).ToArray()) + ".pdf");

        private static async Task<int> Main(string[] args)
        {
            var url = Arg(args, "--url", "http://127.0.0.1:8780");
            var modelos = Arg(args, "--modelos", "groq:openai/gpt-oss-120b").Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries).Select(s => s.Trim()).ToList();
            var ids = Arg(args, "--casos", "circulo,casa,borrar,pdf").Split(',').Select(s => s.Trim()).ToList();
            var perfil = Arg(args, "--perfil", "descubrir");
            var topeUsd = double.Parse(Arg(args, "--tope", "0.50"), System.Globalization.CultureInfo.InvariantCulture);
            var simulado = args.Contains("--simulado");
            var vivo = args.Contains("--vivo");
            var carpeta = Arg(args, "--carpeta", Path.Combine(Path.GetTempPath(), "banco_modelos_" + DateTime.Now.ToString("yyyyMMdd_HHmmss")));
            var salida = Arg(args, "--salida", Path.Combine(carpeta, "informe.md"));
            Directory.CreateDirectory(carpeta);

            var casos = Casos().Where(c => ids.Contains(c.Id)).ToList();
            Console.WriteLine("Banco de pruebas: " + modelos.Count + " modelo(s) x " + casos.Count + " caso(s)  ->  " + salida);
            if (!vivo && !simulado)
            {
                Console.WriteLine("\nModo de vista previa: no se ejecuta nada. Con --vivo crea un dibujo NUEVO en AutoCAD y trabaja solo ahí (nunca toca el que tengas abierto; lo cierra sin guardar al terminar) y gasta de la cuenta de cada modelo (tope por caso: US$" + topeUsd + ").");
                foreach (var m in modelos) foreach (var c in casos) Console.WriteLine("  - " + m + "  ·  " + c.Titulo);
                return 0;
            }

            var host = new ChatCliente(url);
            var resultados = new List<Resultado>();
            string dibujoPrueba = null;
            if (vivo && !simulado)
            {
                // Un dibujo NUEVO y propio: es lo único que el banco dibuja y borra. Nunca el que la persona tenga abierto.
                var previo = new Contexto { Host = host };
                var (txtN, errN) = await previo.Tool("new_document");
                var (txtI, errI) = await previo.Tool("get_drawing_info");
                if (errN || errI) { Console.WriteLine("No pude crear el dibujo de prueba (¿está AutoCAD abierto y el servidor conectado?): " + (errN ? txtN : txtI)); return 1; }
                dibujoPrueba = JsonNode.Parse(txtI)?["fileName"]?.ToString();
                Console.WriteLine("Dibujo de prueba: " + dibujoPrueba);
            }
            foreach (var par in modelos)
            {
                var corte = par.IndexOf(':');
                var proveedor = corte > 0 ? par.Substring(0, corte) : "groq";
                var modelo = corte > 0 ? par.Substring(corte + 1) : par;
                foreach (var caso in casos)
                {
                    var ctx = new Contexto { Host = host, Carpeta = carpeta, Modelo = modelo, DibujoPrueba = dibujoPrueba };
                    var r = new Resultado { Modelo = modelo, Caso = caso.Titulo };
                    Console.Write("  " + modelo + "  ·  " + caso.Titulo + " ... ");
                    var reloj = Stopwatch.StartNew();
                    try
                    {
                        if (!simulado) await caso.Preparar(ctx);          // en simulado no se modifica nada
                        var agente = new AgenteNativo(() => host, Path.Combine(carpeta, Guid.NewGuid().ToString("N") + ".json"));
                        agente.Licencia = () => (false, true, "");
                        if (simulado) agente.FabricaProveedor = (prep, ped) => new ModeloMudo();
                        var pedido = new PedidoAgente
                        {
                            Mensaje = caso.PedidoPara != null ? caso.PedidoPara(ctx) : caso.Pedido, Proveedor = proveedor, Modelo = modelo, Perfil = perfil,
                            ModoPermisos = "nada", Vueltas = 25, TopeUSD = topeUsd, ConReglas = true,
                        };
                        using (var cts = new CancellationTokenSource(TimeSpan.FromMinutes(5)))
                        {
                            await agente.EjecutarAsync(pedido, ev =>
                            {
                                var tipo = ev.TryGetProperty("tipo", out var t) ? t.GetString() : "";
                                if (tipo == "tool") r.Herramientas++;
                                else if (tipo == "resultado" && ev.TryGetProperty("error", out var e) && e.ValueKind == JsonValueKind.True) r.Errores++;
                                else if (tipo == "texto") r.Final = ev.GetProperty("texto").GetString();
                                else if (tipo == "aviso") r.Detalle = (r.Detalle.Length > 0 ? r.Detalle + " | " : "") + ev.GetProperty("texto").GetString();
                                else if (tipo == "uso")
                                {
                                    if (ev.TryGetProperty("total", out var tot) && tot.ValueKind == JsonValueKind.Number) r.Tokens = tot.GetInt32();
                                    if (ev.TryGetProperty("vueltas", out var v) && v.ValueKind == JsonValueKind.Number) r.Vueltas = v.GetInt32();
                                    if (ev.TryGetProperty("costoUSD", out var cu) && cu.ValueKind == JsonValueKind.Number) r.Costo = cu.GetDouble();
                                }
                            }, cts.Token);
                        }
                        var (ok, detalle) = await caso.Verificar(ctx);
                        r.Ok = ok; r.Detalle = (detalle + (r.Detalle.Length > 0 ? " | " + r.Detalle : "")).Trim();
                    }
                    catch (Exception ex) { r.Ok = false; r.Detalle = "se cortó: " + ex.Message; }
                    r.Segundos = reloj.Elapsed.TotalSeconds;
                    Console.WriteLine((r.Ok ? "OK" : "FALLA") + "  (" + r.Segundos.ToString("0") + " s, " + r.Herramientas + " herramientas, " + r.Tokens + " tokens)");
                    resultados.Add(r);
                }
            }

            File.WriteAllText(salida, Informe(resultados, casos, modelos, simulado), new UTF8Encoding(false));
            Console.WriteLine("\nInforme: " + salida);
            if (dibujoPrueba != null)
            {
                // se cierra el dibujo de prueba SIN guardar (es descartable); solo si sigue siendo el activo
                var fin = new Contexto { Host = host, DibujoPrueba = dibujoPrueba };
                if (await fin.EnDibujoDePrueba()) await fin.Tool("close_document", new JsonObject { ["discard_unsaved"] = true });
            }
            return 0;
        }

        private static string Informe(List<Resultado> rs, List<Caso> casos, List<string> modelos, bool simulado)
        {
            var sb = new StringBuilder();
            sb.AppendLine("# Banco de pruebas de modelos" + (simulado ? " (SIMULADO: modelo de mentira, no mide nada real)" : ""));
            sb.AppendLine().AppendLine(DateTime.Now.ToString("yyyy-MM-dd HH:mm") + " · los mismos pedidos, el mismo agente, un AutoCAD de verdad.").AppendLine();
            sb.AppendLine("| Modelo | " + string.Join(" | ", casos.Select(c => c.Titulo)) + " | Aciertos | Tokens | Costo |");
            sb.AppendLine("|---|" + string.Concat(casos.Select(c => "---|")) + "---|---|---|");
            foreach (var m in modelos)
            {
                var nombre = m.Contains(':') ? m.Substring(m.IndexOf(':') + 1) : m;
                var suyos = rs.Where(r => r.Modelo == nombre).ToList();
                var celdas = casos.Select(c => { var r = suyos.FirstOrDefault(x => x.Caso == c.Titulo); return r == null ? "-" : (r.Ok ? "✔" : "✘") + " " + r.Segundos.ToString("0") + " s · " + r.Herramientas + " herr."; });
                sb.AppendLine("| " + nombre + " | " + string.Join(" | ", celdas) + " | " + suyos.Count(r => r.Ok) + "/" + suyos.Count + " | " + suyos.Sum(r => r.Tokens).ToString("N0") + " | US$" + suyos.Sum(r => r.Costo).ToString("0.000", System.Globalization.CultureInfo.InvariantCulture) + " |");
            }
            sb.AppendLine().AppendLine("## Detalle").AppendLine();
            foreach (var r in rs)
            {
                sb.AppendLine("- **" + r.Modelo + " · " + r.Caso + "**: " + (r.Ok ? "logrado" : "NO logrado") + " — " + r.Detalle + (r.Errores > 0 ? " · " + r.Errores + " herramienta(s) con error" : ""));
                if (!string.IsNullOrWhiteSpace(r.Final)) sb.AppendLine("  - dijo al final: " + r.Final.Replace("\n", " ").Substring(0, Math.Min(240, r.Final.Replace("\n", " ").Length)));
            }
            return sb.ToString();
        }
    }
}
