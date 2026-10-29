using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace AutoCadMcpPlugin.Chat
{
    internal sealed class PerfilDef
    {
        public string Id;
        public string[] Patrones;          // vacío = todas las herramientas
    }

    /// <summary>
    /// Las especialidades: qué herramientas ve el modelo según el trabajo (arquitectura, civil, estructura...). Cada una es una
    /// lista de nombres exactos o prefijos («check_», «create_walls») sobre el catálogo de herramientas. La lista sale de
    /// perfiles.json, incrustado en el plugin y generado desde agent/cli.py (tools/generar_perfiles.py); el catálogo, en cambio,
    /// es de Python: aquí solo se filtran sus nombres.
    /// </summary>
    internal static class Perfiles
    {
        private static List<PerfilDef> _todos;

        public static IReadOnlyList<PerfilDef> Todos
        {
            get
            {
                if (_todos != null) return _todos;
                var lista = new List<PerfilDef>();
                using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("perfiles.json"))
                {
                    if (s != null)
                        using (var doc = JsonDocument.Parse(new StreamReader(s).ReadToEnd()))
                            foreach (var p in doc.RootElement.EnumerateArray())
                                lista.Add(new PerfilDef
                                {
                                    Id = p.GetProperty("id").GetString(),
                                    Patrones = p.GetProperty("patrones").EnumerateArray().Select(x => x.GetString()).ToArray(),
                                });
                }
                return _todos = lista;
            }
        }

        public static PerfilDef Buscar(string id) => Todos.FirstOrDefault(p => p.Id == id);

        /// <summary>Igual que ConexionMcp.catalogo(incluir=...) de Python: nombre exacto o prefijo; sin patrones, todas.</summary>
        public static bool Coincide(string nombre, string[] patrones) =>
            patrones == null || patrones.Length == 0 || patrones.Any(p => nombre == p || nombre.StartsWith(p, StringComparison.Ordinal));

        public static List<string> Filtrar(IEnumerable<string> nombres, PerfilDef perfil) =>
            nombres.Where(n => Coincide(n, perfil?.Patrones)).ToList();
    }
}
