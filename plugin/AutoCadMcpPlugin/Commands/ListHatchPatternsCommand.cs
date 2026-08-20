using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Lista los patrones de achurado disponibles de VERDAD en el acad.pat /
    /// acadiso.pat de esta instalación, en vez de adivinar nombres como
    /// "AR-RROOF" y esperar a que no tire error. Un patrón con nombre
    /// equivocado no avisa: create_hatch tira una excepción recién al querer
    /// dibujar, y para ese momento ya se gastó la llamada.
    /// </summary>
    public static class ListHatchPatternsCommand
    {
        /// <summary>params: [filter] (substring, sin importar mayúsculas)</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string filtro = pars["filter"] != null ? pars["filter"].GetValue<string>() : null;

            var db = doc.Database;
            var vistos = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var patrones = new JsonArray();
            var archivos = new JsonArray();

            foreach (var nombreArchivo in new[] { "acad.pat", "acadiso.pat" })
            {
                string ruta;
                try
                {
                    ruta = HostApplicationServices.Current.FindFile(
                        nombreArchivo, db, FindFileHint.Default);
                }
                catch (System.Exception)
                {
                    continue;
                }
                if (string.IsNullOrEmpty(ruta) || !File.Exists(ruta))
                    continue;

                archivos.Add(ruta);
                foreach (var linea in File.ReadLines(ruta))
                {
                    if (linea.Length == 0 || linea[0] != '*')
                        continue;
                    // "*NOMBRE,descripcion" o solo "*NOMBRE"
                    string resto = linea.Substring(1);
                    int coma = resto.IndexOf(',');
                    string nombre = (coma >= 0 ? resto.Substring(0, coma) : resto).Trim();
                    string descripcion = coma >= 0 ? resto.Substring(coma + 1).Trim() : "";
                    if (nombre.Length == 0 || !vistos.Add(nombre))
                        continue;
                    if (filtro != null &&
                        nombre.IndexOf(filtro, StringComparison.OrdinalIgnoreCase) < 0 &&
                        descripcion.IndexOf(filtro, StringComparison.OrdinalIgnoreCase) < 0)
                        continue;

                    patrones.Add(new JsonObject
                    {
                        ["name"] = nombre,
                        ["description"] = descripcion,
                    });
                }
            }

            return new JsonObject
            {
                ["patterns"] = patrones,
                ["count"] = patrones.Count,
                ["files"] = archivos,
            };
        }
    }
}
