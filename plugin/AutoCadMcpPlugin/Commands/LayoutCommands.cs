using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Layouts (espacio papel) y viewports: lo que convierte un dibujo en una
    /// lámina imprimible de verdad, con la escala controlada por el viewport en
    /// vez de dibujando el marco a mano en el espacio modelo.
    ///
    /// Coordenadas: dentro de un layout se trabaja en MILÍMETROS DE PAPEL, con
    /// el origen en la esquina inferior izquierda de la hoja.
    /// </summary>
    public static class LayoutCommands
    {
        /// <summary>params: name, [plotConfig], [paperSize]</summary>
        public static JsonObject Create(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            string plotConfig = pars["plotConfig"]?.GetValue<string>();
            string paperSize = pars["paperSize"]?.GetValue<string>();

            var lm = LayoutManager.Current;
            if (!lm.GetLayoutId(name).IsNull)
                throw new InvalidOperationException($"Ya existe un layout llamado '{name}'.");

            ObjectId layoutId = lm.CreateLayout(name);

            var db = doc.Database;
            var result = new JsonObject { ["name"] = name };

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var layout = (Layout)tr.GetObject(layoutId, OpenMode.ForWrite);

                if (!string.IsNullOrEmpty(plotConfig) || !string.IsNullOrEmpty(paperSize))
                    ApplyPlotSettings(layout, plotConfig, paperSize);

                result["paperWidth"] = layout.PlotPaperSize.X;
                result["paperHeight"] = layout.PlotPaperSize.Y;
                result["tabOrder"] = layout.TabOrder;
                tr.Commit();
            }

            return result;
        }

        /// <summary>
        /// El tamaño de papel depende del dispositivo de impresión configurado:
        /// los nombres válidos salen de la lista del propio plotter, por eso el
        /// error incluye las opciones disponibles en vez de un "no se pudo".
        /// </summary>
        private static void ApplyPlotSettings(Layout layout, string plotConfig, string paperSize)
        {
            var psv = PlotSettingsValidator.Current;
            using (var ps = new PlotSettings(layout.ModelType))
            {
                ps.CopyFrom(layout);

                string device = string.IsNullOrEmpty(plotConfig) ? "DWG To PDF.pc3" : plotConfig;
                try
                {
                    psv.SetPlotConfigurationName(ps, device, null);
                }
                catch (System.Exception ex)
                {
                    throw new InvalidOperationException(
                        $"No se pudo usar el dispositivo de impresión '{device}': {ex.Message}");
                }

                if (!string.IsNullOrEmpty(paperSize))
                {
                    psv.RefreshLists(ps);
                    var media = psv.GetCanonicalMediaNameList(ps);
                    string match = null;
                    foreach (string m in media)
                    {
                        if (m.IndexOf(paperSize, StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            match = m;
                            break;
                        }
                    }
                    if (match == null)
                    {
                        var sample = new JsonArray();
                        int i = 0;
                        foreach (string m in media)
                        {
                            if (i++ >= 12) break;
                            sample.Add(m);
                        }
                        throw new InvalidOperationException(
                            $"El dispositivo '{device}' no tiene un papel que contenga " +
                            $"'{paperSize}'. Algunos disponibles: {sample.ToJsonString()}");
                    }
                    psv.SetCanonicalMediaName(ps, match);
                }

                layout.CopyFrom(ps);
            }
        }

        /// <summary>params: (ninguno)</summary>
        public static JsonObject List(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var arr = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var dict = (DBDictionary)tr.GetObject(db.LayoutDictionaryId, OpenMode.ForRead);
                foreach (DBDictionaryEntry entry in dict)
                {
                    var layout = (Layout)tr.GetObject(entry.Value, OpenMode.ForRead);
                    arr.Add(new JsonObject
                    {
                        ["name"] = layout.LayoutName,
                        ["tabOrder"] = layout.TabOrder,
                        ["paperWidth"] = layout.PlotPaperSize.X,
                        ["paperHeight"] = layout.PlotPaperSize.Y,
                        ["isModel"] = layout.ModelType
                    });
                }
                tr.Commit();
            }

            return new JsonObject
            {
                ["layouts"] = arr,
                ["current"] = LayoutManager.Current.CurrentLayout
            };
        }

        /// <summary>params: name</summary>
        public static JsonObject SetCurrent(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var lm = LayoutManager.Current;
            if (lm.GetLayoutId(name).IsNull)
                throw new InvalidOperationException($"No existe un layout llamado '{name}'.");

            lm.CurrentLayout = name;
            return new JsonObject { ["current"] = lm.CurrentLayout };
        }

        /// <summary>
        /// Viewport: la ventana del layout que muestra una zona del espacio
        /// modelo a una escala dada.
        /// params: layout, centerX, centerY, width, height (mm de papel),
        ///         viewCenterX, viewCenterY (punto del modelo que queda al
        ///         centro), scaleDenominator (50 para 1:50), [locked=true]
        /// </summary>
        public static JsonObject CreateViewport(Document doc, JsonObject pars)
        {
            string layoutName = pars["layout"].GetValue<string>();
            double cx = pars["centerX"].GetValue<double>();
            double cy = pars["centerY"].GetValue<double>();
            double w = pars["width"].GetValue<double>();
            double h = pars["height"].GetValue<double>();
            double viewCx = pars["viewCenterX"] != null ? pars["viewCenterX"].GetValue<double>() : 0.0;
            double viewCy = pars["viewCenterY"] != null ? pars["viewCenterY"].GetValue<double>() : 0.0;
            double scaleDen = pars["scaleDenominator"] != null
                ? pars["scaleDenominator"].GetValue<double>() : 1.0;
            bool locked = pars["locked"] == null || pars["locked"].GetValue<bool>();
            double unitsPerMm = pars["modelUnitsPerMm"] != null
                ? pars["modelUnitsPerMm"].GetValue<double>() : 1.0;

            if (scaleDen <= 0)
                throw new ArgumentException("scaleDenominator tiene que ser > 0 (1:50 -> 50).");

            var db = doc.Database;
            var lm = LayoutManager.Current;
            ObjectId layoutId = lm.GetLayoutId(layoutName);
            if (layoutId.IsNull)
                throw new InvalidOperationException($"No existe un layout llamado '{layoutName}'.");

            // Un viewport solo se puede prender con su layout activo; si no,
            // queda creado pero apagado y no muestra nada.
            string previous = lm.CurrentLayout;
            lm.CurrentLayout = layoutName;

            try
            {
                using (var tr = db.TransactionManager.StartTransaction())
                {
                    var layout = (Layout)tr.GetObject(layoutId, OpenMode.ForRead);
                    var btr = (BlockTableRecord)tr.GetObject(
                        layout.BlockTableRecordId, OpenMode.ForWrite);

                    var vp = new Viewport();
                    btr.AppendEntity(vp);
                    tr.AddNewlyCreatedDBObject(vp, true);

                    vp.CenterPoint = new Point3d(cx, cy, 0);
                    vp.Width = w;
                    vp.Height = h;
                    vp.ViewCenter = new Point2d(viewCx, viewCy);

                    // CustomScale = mm de papel por unidad de modelo. Dibujando
                    // en metros a 1:50, 1 unidad son 1000mm reales -> 1000/50.
                    vp.CustomScale = unitsPerMm / scaleDen;
                    vp.On = true;
                    if (locked)
                        vp.Locked = true;

                    var result = new JsonObject
                    {
                        ["handle"] = vp.Handle.ToString(),
                        ["layout"] = layoutName,
                        ["customScale"] = vp.CustomScale,
                        ["number"] = vp.Number
                    };

                    tr.Commit();
                    return result;
                }
            }
            finally
            {
                // Dejamos la vista como estaba: crear un viewport no debería
                // cambiarle la pestaña al usuario.
                try { lm.CurrentLayout = previous; } catch { }
            }
        }
    }
}
