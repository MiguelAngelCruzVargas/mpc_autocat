using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using AcException = Autodesk.AutoCAD.Runtime.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Renombrar y copiar layouts (láminas) con el LayoutManager nativo. Copiar una lámina conserva sus
    /// viewports, su configuración de impresión y lo que dibujaste en el papel: es la forma de armar una
    /// serie (A-01, A-02...) a partir de una lámina ya resuelta.
    /// </summary>
    public static class LayoutManageCommands
    {
        private static string NombreLayout(JsonObject pars, string clave)
        {
            string v = pars[clave]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(v)) throw new ArgumentException("Falta '" + clave + "'.");
            if (v != v.Trim()) throw new ArgumentException("'" + clave + "' no puede empezar ni terminar con espacios.");
            if (v.Length > 255) throw new ArgumentException("'" + clave + "' no puede pasar de 255 caracteres.");
            foreach (char c in "<>/\\\":;?*|,=`")
                if (v.IndexOf(c) >= 0) throw new ArgumentException("'" + clave + "' no puede llevar el carácter '" + c + "'.");
            return v;
        }

        /// <summary>params: name, new_name. No se renombra «Model».</summary>
        public static JsonObject Rename(Document doc, JsonObject pars)
        {
            string viejo = NombreLayout(pars, "name");
            string nuevo = NombreLayout(pars, "new_name");
            if (viejo.Equals("Model", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("El espacio modelo (Model) no se renombra.");
            if (nuevo.Equals("Model", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("'Model' está reservado para el espacio modelo.");
            var lm = LayoutManager.Current;
            if (lm.GetLayoutId(viejo).IsNull) throw new ArgumentException("No hay un layout llamado '" + viejo + "'.");
            if (!lm.GetLayoutId(nuevo).IsNull && !viejo.Equals(nuevo, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Ya hay un layout llamado '" + nuevo + "'.");
            try { lm.RenameLayout(viejo, nuevo); }
            catch (AcException ex) { throw new InvalidOperationException("AutoCAD rechazó renombrar (" + ex.ErrorStatus + "): " + ex.Message + "."); }
            return new JsonObject { ["name"] = nuevo, ["previous"] = viejo };
        }

        /// <summary>params: name (el de origen), new_name.</summary>
        public static JsonObject Copy(Document doc, JsonObject pars)
        {
            string origen = NombreLayout(pars, "name");
            string nuevo = NombreLayout(pars, "new_name");
            if (nuevo.Equals("Model", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("'Model' está reservado para el espacio modelo.");
            var lm = LayoutManager.Current;
            if (lm.GetLayoutId(origen).IsNull) throw new ArgumentException("No hay un layout llamado '" + origen + "'.");
            if (!lm.GetLayoutId(nuevo).IsNull) throw new InvalidOperationException("Ya hay un layout llamado '" + nuevo + "'.");
            try { lm.CopyLayout(origen, nuevo); }
            catch (AcException ex) { throw new InvalidOperationException("AutoCAD rechazó copiar (" + ex.ErrorStatus + "): " + ex.Message + "."); }
            var id = lm.GetLayoutId(nuevo);
            return new JsonObject { ["name"] = nuevo, ["copiedFrom"] = origen, ["handle"] = id.IsNull ? null : id.Handle.ToString() };
        }
    }
}
