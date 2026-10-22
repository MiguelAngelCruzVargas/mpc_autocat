using System;
using System.IO;
using System.Text.Json.Nodes;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Deja a la vista QUÉ comando estaba ejecutando el plugin. Un error fatal de AutoCAD («INTERNAL ERROR:
    /// eNotOpenForWrite» y se cierra) no se puede atrapar desde adentro, y después de la caída nadie sabe cuál
    /// de cientos de comandos fue. Con esto, el comando que quedó en estado «corriendo» cuando AutoCAD ya no está
    /// es el culpable: el servidor MCP lo lee (ojos.py) y se lo dice a quien pregunta.
    ///
    /// Un solo archivo chico que se SOBREESCRIBE (no crece): %LOCALAPPDATA%\AutoCadMcp\ultimo_comando.json.
    /// No guarda el contenido de run_code ni nada con pinta de clave; los parámetros se recortan. Si no se puede
    /// escribir, se ignora: la bitácora nunca puede romper un comando.
    /// </summary>
    internal static class Bitacora
    {
        private static readonly string Ruta = Path.Combine(
            Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(), "AutoCadMcp", "ultimo_comando.json");

        private static string Recortar(string cmd, JsonObject pars)
        {
            if (pars == null) return "{}";
            if (cmd == "run_code") return "{…}";                       // el código no se registra
            try
            {
                string t = pars.ToJsonString();
                return t.Length <= 300 ? t : t.Substring(0, 300) + "…";
            }
            catch (Exception) { return "{…}"; }
        }

        private static void Escribir(string cmd, string parametros, string estado, DateTime inicio, string error)
        {
            try
            {
                var o = new JsonObject
                {
                    ["cmd"] = cmd, ["params"] = parametros, ["estado"] = estado,
                    ["inicio"] = inicio.ToString("yyyy-MM-dd HH:mm:ss.fff"),
                    ["ahora"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff"),
                    ["pid"] = System.Diagnostics.Process.GetCurrentProcess().Id,
                };
                if (error != null) o["error"] = error.Length <= 300 ? error : error.Substring(0, 300) + "…";
                Directory.CreateDirectory(Path.GetDirectoryName(Ruta));
                File.WriteAllText(Ruta, o.ToJsonString());
            }
            catch (Exception) { /* la bitácora nunca rompe un comando */ }
        }

        /// <summary>Corre un comando dejando constancia: «corriendo» antes, «ok» o «error» después.</summary>
        public static JsonObject Ejecutar(string cmd, Func<JsonObject> ejecutar, JsonObject pars)
        {
            if (cmd == "ping") return ejecutar();                      // el latido no ensucia la bitácora
            var inicio = DateTime.Now;
            string p = Recortar(cmd, pars);
            Escribir(cmd, p, "corriendo", inicio, null);
            try
            {
                var r = ejecutar();
                Escribir(cmd, p, "ok", inicio, null);
                return r;
            }
            catch (Exception ex)
            {
                Escribir(cmd, p, "error", inicio, ex.Message);
                throw;
            }
        }
    }
}
