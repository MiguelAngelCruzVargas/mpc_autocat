using System;
using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Varios dibujos abiertos a la vez. Todos los demás comandos trabajan
    /// sobre el documento ACTIVO, así que con esto se elige sobre cuál, sin
    /// tener que ir a la ventana de AutoCAD a cambiar de pestaña.
    /// </summary>
    public static class DocumentCommands
    {
        /// <summary>params: (ninguno)</summary>
        public static JsonObject List(Document doc, JsonObject pars)
        {
            var arr = new JsonArray();
            var dm = Application.DocumentManager;
            var active = dm.MdiActiveDocument;

            foreach (Document d in dm)
            {
                bool isActive = ReferenceEquals(d, active);
                var entry = new JsonObject
                {
                    ["name"] = Path.GetFileName(d.Name),
                    ["fullPath"] = d.Name,
                    ["isActive"] = isActive,
                    ["isReadOnly"] = d.IsReadOnly
                };
                // DBMOD (0 = sin cambios sin guardar) es una variable del
                // dibujo ACTIVO: para los demas no hay forma barata de saberlo.
                if (isActive)
                    entry["hasUnsavedChanges"] =
                        Convert.ToInt32(Application.GetSystemVariable("DBMOD")) != 0;
                arr.Add(entry);
            }

            return new JsonObject { ["documents"] = arr, ["count"] = arr.Count };
        }

        /// <summary>
        /// params: name (nombre de archivo o ruta; alcanza con que coincida el
        /// final, así se puede pasar "Drawing1.dwg" sin la ruta completa)
        /// </summary>
        public static JsonObject SetActive(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var dm = Application.DocumentManager;

            Document target = null;
            foreach (Document d in dm)
            {
                if (string.Equals(Path.GetFileName(d.Name), name, StringComparison.OrdinalIgnoreCase)
                    || d.Name.EndsWith(name, StringComparison.OrdinalIgnoreCase))
                {
                    target = d;
                    break;
                }
            }

            if (target == null)
            {
                var abiertos = new JsonArray();
                foreach (Document d in dm)
                    abiertos.Add(Path.GetFileName(d.Name));
                throw new InvalidOperationException(
                    $"No hay ningún dibujo abierto que coincida con '{name}'. " +
                    $"Abiertos: {abiertos.ToJsonString()}");
            }

            if (ReferenceEquals(target, dm.MdiActiveDocument))
                return new JsonObject { ["active"] = Path.GetFileName(target.Name),
                                        ["changed"] = false };

            dm.MdiActiveDocument = target;
            return new JsonObject
            {
                ["active"] = Path.GetFileName(target.Name),
                ["changed"] = true
            };
        }

        /// <summary>
        /// Abre un DWG del disco y lo deja activo.
        ///
        /// Hasta que existió esto, todo el MCP asumía que alguien ya había
        /// abierto el dibujo a mano en AutoCAD: se podía guardar, plotear y
        /// exportar, pero no abrir. Corregir un plano entregado obligaba a ir
        /// a la ventana de AutoCAD.
        ///
        /// OJO: corre SIN el lock del documento (ver CommandDispatcher).
        /// Abrir un dibujo teniendo tomado el lock de otro tira eLockViolation.
        ///
        /// params: path (ruta al .dwg), readOnly (opcional, false por defecto)
        /// </summary>
        public static JsonObject Open(Document doc, JsonObject pars)
        {
            string path = pars["path"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(path))
                throw new ArgumentException("Falta 'path': la ruta del .dwg a abrir.");

            path = Path.GetFullPath(path);
            if (!File.Exists(path))
                throw new FileNotFoundException(
                    $"No existe el archivo '{path}'. Pasá la ruta completa al .dwg.");

            bool readOnly = pars["readOnly"]?.GetValue<bool>() ?? false;
            var dm = Application.DocumentManager;

            // Si ya está abierto, AutoCAD no lo abre dos veces: se activa el
            // que hay. Reabrirlo perdería los cambios sin guardar.
            foreach (Document d in dm)
            {
                if (string.Equals(Path.GetFullPath(d.Name), path,
                                  StringComparison.OrdinalIgnoreCase))
                {
                    if (!ReferenceEquals(d, dm.MdiActiveDocument))
                        dm.MdiActiveDocument = d;
                    return new JsonObject
                    {
                        ["active"] = Path.GetFileName(d.Name),
                        ["fullPath"] = d.Name,
                        ["alreadyOpen"] = true,
                        ["isReadOnly"] = d.IsReadOnly
                    };
                }
            }

            Document abierto = dm.Open(path, readOnly);
            if (abierto == null)
                throw new InvalidOperationException(
                    $"AutoCAD no pudo abrir '{path}'. ¿Está en uso por otro programa?");

            dm.MdiActiveDocument = abierto;
            return new JsonObject
            {
                ["active"] = Path.GetFileName(abierto.Name),
                ["fullPath"] = abierto.Name,
                ["alreadyOpen"] = false,
                ["isReadOnly"] = abierto.IsReadOnly
            };
        }

        /// <summary>
        /// Dibujo nuevo a partir de una plantilla, y lo deja activo.
        ///
        /// Igual que Open: corre SIN el lock del documento.
        ///
        /// params: template (opcional, .dwt; por defecto la de AutoCAD)
        /// </summary>
        public static JsonObject New(Document doc, JsonObject pars)
        {
            string template = pars["template"]?.GetValue<string>();
            if (!string.IsNullOrWhiteSpace(template))
            {
                template = Path.GetFullPath(template);
                if (!File.Exists(template))
                    throw new FileNotFoundException(
                        $"No existe la plantilla '{template}'.");
            }
            else
            {
                // "" = la plantilla por defecto de AutoCAD (la de QNEW).
                template = "";
            }

            var dm = Application.DocumentManager;
            Document nuevo = dm.Add(template);
            if (nuevo == null)
                throw new InvalidOperationException(
                    "AutoCAD no pudo crear el dibujo nuevo.");

            dm.MdiActiveDocument = nuevo;
            return new JsonObject
            {
                ["active"] = Path.GetFileName(nuevo.Name),
                ["fullPath"] = nuevo.Name,
                ["template"] = string.IsNullOrEmpty(template) ? "(default)" : template
            };
        }

        /// <summary>
        /// Chequeo de salud: confirma que el plugin responde y sobre qué dibujo
        /// está parado. El cliente abre una conexión nueva por llamada, así que
        /// esto es lo que hace las veces de "reconectar".
        /// params: (ninguno)
        /// </summary>
        public static JsonObject Ping(Document doc, JsonObject pars)
        {
            return new JsonObject
            {
                ["ok"] = true,
                ["activeDocument"] = Path.GetFileName(doc.Name),
                ["openDocuments"] = CountDocuments(),
                ["pluginVersion"] = PluginInfo.Version
            };
        }

        private static int CountDocuments()
        {
            int n = 0;
            foreach (Document unused in Application.DocumentManager)
                n++;
            return n;
        }
    }

    /// <summary>
    /// Versión del plugin. Sirve para que el cliente sepa si el DLL cargado en
    /// AutoCAD es el mismo que el código con el que está hablando, sin tener
    /// que adivinar por qué un comando "no existe".
    /// </summary>
    public static class PluginInfo
    {
        public const string Version = "0.4.0";
    }
}
