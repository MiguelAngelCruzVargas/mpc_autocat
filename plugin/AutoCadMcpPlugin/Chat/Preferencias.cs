using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>
    /// Los ajustes del panel (proveedor, modelo, especialidad, permisos, tope...) en preferencias.json: el mismo archivo y la
    /// misma lista blanca que usa la interfaz web de Python (agent/credenciales.py), así las dos ven lo mismo. Antes el
    /// panel los guardaba pidiéndoselo al servidor Python; ahora se escriben aquí, en C#.
    /// </summary>
    internal static class Preferencias
    {
        // Solo estas claves se guardan: una lista blanca evita escribir cualquier cosa en el disco del usuario.
        private static readonly HashSet<string> Validas = new HashSet<string>
        {
            "proveedor", "modelo", "perfil", "temperatura", "conReglas", "configurado", "autoPlano", "modelos",
            "precios", "topeUSD", "presets", "modoPermisos",
        };

        internal static string Archivo => Path.Combine(Credenciales.Directorio, "preferencias.json");

        public static JsonObject Leer()
        {
            try
            {
                if (!File.Exists(Archivo)) return new JsonObject();
                return JsonNode.Parse(File.ReadAllText(Archivo, Encoding.UTF8)) as JsonObject ?? new JsonObject();
            }
            catch (Exception) { return new JsonObject(); }
        }

        /// <summary>Guarda UNA preferencia. Falla en silencio: no poder guardar no debe romper la sesión en curso.</summary>
        public static void Guardar(string clave, object valor)
        {
            if (!Validas.Contains(clave)) return;
            try
            {
                var datos = Leer();
                datos[clave] = JsonSerializer.SerializeToNode(valor);
                Directory.CreateDirectory(Credenciales.Directorio);
                File.WriteAllText(Archivo, datos.ToJsonString(new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }), new UTF8Encoding(false));
            }
            catch (Exception) { }
        }
    }
}
