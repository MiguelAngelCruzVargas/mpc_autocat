using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;

namespace AutoCadMcpPlugin.Chat
{
    internal sealed class ResumenConversacion
    {
        public string Ruta, Titulo;
        public DateTime Fecha;
        public int Pedidos;
    }

    /// <summary>
    /// Las conversaciones guardadas: una carpeta con un archivo por conversación (<c>conversaciones\</c> dentro del directorio de estado),
    /// y cuál está abierta. «＋» ya no borra la anterior: empieza otra, y la lista deja volver a cualquiera. La conversación única de
    /// versiones anteriores (<c>chat_nativo.json</c>) pasa a ser la primera de la lista.
    /// </summary>
    internal static class Conversaciones
    {
        private static string Estado
        {
            get
            {
                var e = Environment.GetEnvironmentVariable("AUTOCAD_IA_ESTADO");
                return string.IsNullOrEmpty(e)
                    ? Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp")
                    : e;
            }
        }

        public static string Carpeta => Path.Combine(Estado, "conversaciones");
        private static string ArchivoActiva => Path.Combine(Estado, "conversacion_activa.txt");

        private static string NuevoId() => DateTime.Now.ToString("yyyyMMdd_HHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0, 4);

        /// <summary>La ruta de la conversación abierta (la crea, vacía, si no hay ninguna).</summary>
        public static string RutaActiva()
        {
            Directory.CreateDirectory(Carpeta);
            try
            {
                var viejo = Path.Combine(Estado, "chat_nativo.json");
                if (File.Exists(viejo) && !Directory.EnumerateFiles(Carpeta, "*.json").Any())
                    File.Move(viejo, Path.Combine(Carpeta, NuevoId() + ".json"));
            }
            catch (Exception) { }
            try
            {
                if (File.Exists(ArchivoActiva))
                {
                    var ruta = Path.Combine(Carpeta, File.ReadAllText(ArchivoActiva).Trim() + ".json");
                    if (File.Exists(ruta)) return ruta;
                }
                var ultima = Directory.EnumerateFiles(Carpeta, "*.json").OrderByDescending(File.GetLastWriteTime).FirstOrDefault();
                if (ultima != null) { Activar(ultima); return ultima; }
            }
            catch (Exception) { }
            return Nueva();
        }

        /// <summary>Una conversación nueva (el archivo se crea al primer mensaje) y pasa a ser la abierta.</summary>
        public static string Nueva()
        {
            Directory.CreateDirectory(Carpeta);
            var ruta = Path.Combine(Carpeta, NuevoId() + ".json");
            Activar(ruta);
            return ruta;
        }

        public static void Activar(string ruta)
        {
            try { File.WriteAllText(ArchivoActiva, Path.GetFileNameWithoutExtension(ruta)); } catch (Exception) { }
        }

        public static void Borrar(string ruta)
        {
            try { if (File.Exists(ruta)) File.Delete(ruta); } catch (Exception) { }
        }

        /// <summary>Las conversaciones con al menos un pedido, la más reciente primero.</summary>
        public static List<ResumenConversacion> Listar()
        {
            var lista = new List<ResumenConversacion>();
            if (!Directory.Exists(Carpeta)) return lista;
            foreach (var ruta in Directory.EnumerateFiles(Carpeta, "*.json"))
            {
                try
                {
                    var raiz = JsonNode.Parse(File.ReadAllText(ruta, Encoding.UTF8)) as JsonObject;
                    var eventos = raiz?["eventos"] as JsonArray;
                    if (eventos == null) continue;
                    var pedidos = eventos.Where(e => e?["tipo"]?.ToString() == "usuario").ToList();
                    if (pedidos.Count == 0) continue;
                    lista.Add(new ResumenConversacion { Ruta = ruta, Titulo = Titulo(pedidos[0]?["texto"]?.ToString()), Fecha = File.GetLastWriteTime(ruta), Pedidos = pedidos.Count });
                }
                catch (Exception) { }
            }
            return lista.OrderByDescending(c => c.Fecha).ToList();
        }

        /// <summary>El primer pedido, sin el bloque «[Contexto de AutoCAD]» y en una línea.</summary>
        internal static string Titulo(string texto)
        {
            texto = texto ?? "";
            if (texto.StartsWith("[Contexto de AutoCAD]", StringComparison.Ordinal))
            {
                var corte = texto.IndexOf("\n\n", StringComparison.Ordinal);
                if (corte > 0) texto = texto.Substring(corte + 2);
            }
            texto = string.Join(" ", texto.Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
            return texto.Length > 60 ? texto.Substring(0, 57) + "…" : (texto.Length == 0 ? "(sin título)" : texto);
        }
    }
}
