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
        /// <summary>
        /// Tamaño de la hoja TAL COMO SE VE en el layout: con el plot rotado
        /// 90 grados el papel del dispositivo (A0 841x1189, el único A0 que
        /// trae DWG To PDF) queda apaisado, 1189x841, y las coordenadas del
        /// espacio papel siguen a lo que se ve.
        /// </summary>
        public static (double w, double h) HojaEfectiva(PlotSettings l)
        {
            var s = l.PlotPaperSize;
            bool girada = l.PlotRotation == PlotRotation.Degrees090
                || l.PlotRotation == PlotRotation.Degrees270;
            return girada ? (s.Y, s.X) : (s.X, s.Y);
        }

        /// <summary>params: name, [plotConfig], [paperSize], [orientation]
        /// orientation: 'horizontal' o 'vertical'. Si el papel del dispositivo
        /// viene en la otra orientación (A0 en DWG To PDF solo existe vertical)
        /// se rota el plot 90 grados en vez de cambiar de papel.</summary>
        public static JsonObject Create(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            string plotConfig = pars["plotConfig"]?.GetValue<string>();
            string paperSize = pars["paperSize"]?.GetValue<string>();
            string orientation = pars["orientation"]?.GetValue<string>();

            var lm = LayoutManager.Current;
            if (!lm.GetLayoutId(name).IsNull)
                throw new InvalidOperationException($"Ya existe un layout llamado '{name}'.");

            ObjectId layoutId = lm.CreateLayout(name);

            var db = doc.Database;
            var result = new JsonObject { ["name"] = name };

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var layout = (Layout)tr.GetObject(layoutId, OpenMode.ForWrite);

                if (!string.IsNullOrEmpty(plotConfig) || !string.IsNullOrEmpty(paperSize)
                    || !string.IsNullOrEmpty(orientation))
                    ApplyPlotSettings(layout, plotConfig, paperSize, orientation);

                var (w, h) = HojaEfectiva(layout);
                result["paperWidth"] = w;
                result["paperHeight"] = h;
                result["plotRotation"] = layout.PlotRotation.ToString();
                // 'A3' matchea tanto el horizontal como el vertical: hay que
                // devolver cual quedo, o quien ubica el viewport lo hace a ciegas.
                result["paperName"] = layout.CanonicalMediaName;
                result["orientation"] = w >= h ? "horizontal" : "vertical";
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
        private static void ApplyPlotSettings(Layout layout, string plotConfig, string paperSize,
                                              string orientation = null)
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
                    // Primero el nombre ENTERO: "A0" no puede ser parte de
                    // "2A0" (1189x1682), que en la lista viene antes y era el
                    // que se elegía -- una lámina pedida en A0 salió del doble
                    // (visto en un edificio). Contener el texto queda de
                    // respaldo, para nombres como "ARCH D".
                    var entero = new System.Text.RegularExpressions.Regex(
                        "(?<![A-Za-z0-9])" + System.Text.RegularExpressions.Regex.Escape(paperSize) +
                        "(?![A-Za-z0-9])", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                    string match = null;
                    foreach (string m in media)
                    {
                        if (entero.IsMatch(m))
                        {
                            match = m;
                            break;
                        }
                    }
                    if (match == null)
                    {
                        foreach (string m in media)
                        {
                            if (m.IndexOf(paperSize, StringComparison.OrdinalIgnoreCase) >= 0)
                            {
                                match = m;
                                break;
                            }
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

                // Rotación explícita: CreateLayout hereda la de la plantilla
                // (90°, visto en vivo) y la hoja salía acostada respecto de la
                // orientación que esta misma tool devuelve.
                // Solo se gira si se pidió una orientación que el papel no tiene.
                var rot = PlotRotation.Degrees000;
                if (!string.IsNullOrEmpty(orientation))
                {
                    psv.RefreshLists(ps);
                    bool papelHoriz = ps.PlotPaperSize.X >= ps.PlotPaperSize.Y;
                    string o = orientation.ToLowerInvariant();
                    bool quiereHoriz = o == "horizontal" || o == "landscape" || o == "apaisado";
                    if (papelHoriz != quiereHoriz)
                        rot = PlotRotation.Degrees090;
                }
                psv.SetPlotRotation(ps, rot);

                layout.CopyFrom(ps);
            }
        }

        private const string CAPA_VIEWPORTS = "MCP-VIEWPORTS";

        /// <summary>La capa de los marcos de viewport: gris y SIN imprimir.
        /// Si ya existe se respeta tal cual (alguien la configuró).</summary>
        private static ObjectId CapaViewports(Database db, Transaction tr)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(CAPA_VIEWPORTS))
                return lt[CAPA_VIEWPORTS];
            lt.UpgradeOpen();
            var capa = new LayerTableRecord
            {
                Name = CAPA_VIEWPORTS,
                IsPlottable = false,
                Color = Autodesk.AutoCAD.Colors.Color.FromColorIndex(
                    Autodesk.AutoCAD.Colors.ColorMethod.ByAci, 8)
            };
            ObjectId id = lt.Add(capa);
            tr.AddNewlyCreatedDBObject(capa, true);
            return id;
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
                        ["paperWidth"] = HojaEfectiva(layout).w,
                        ["paperHeight"] = HojaEfectiva(layout).h,
                        ["mediaWidth"] = layout.PlotPaperSize.X,
                        ["mediaHeight"] = layout.PlotPaperSize.Y,
                        ["isModel"] = layout.ModelType,
                        ["plotRotation"] = layout.PlotRotation.ToString(),
                        ["mediaName"] = layout.CanonicalMediaName
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

                    // Un viewport que no entra en la hoja se crea igual y se
                    // dibuja cruzando el borde: mejor frenarlo acá, porque en
                    // pantalla parece que "algo salió descuadrado" y no queda
                    // claro que el problema es el tamaño pedido.
                    CheckFitsInPaper(layout, cx, cy, w, h);

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
                    // El marco del viewport es una ayuda de pantalla: en una
                    // lámina no se imprime. Impreso cortaba los títulos de vista
                    // que caían sobre el borde (visto en vivo: "ISOMETRICO SO"
                    // tachado por la línea del marco).
                    vp.LayerId = CapaViewports(db, tr);

                    var result = new JsonObject
                    {
                        ["handle"] = vp.Handle.ToString(),
                        ["layout"] = layoutName,
                        ["customScale"] = vp.CustomScale,
                        ["number"] = vp.Number,
                        ["paperWidth"] = HojaEfectiva(layout).w,
                        ["paperHeight"] = HojaEfectiva(layout).h
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

        /// <summary>
        /// El viewport se ubica en milímetros de papel con el origen abajo a la
        /// izquierda de la hoja. Si la ventana pedida se sale, el error dice
        /// cuánto mide la hoja y por dónde se pasa, que es lo que hace falta
        /// para corregirlo.
        /// </summary>
        private static void CheckFitsInPaper(Layout layout, double cx, double cy,
                                             double w, double h)
        {
            var (pw, ph) = HojaEfectiva(layout);
            if (pw <= 0 || ph <= 0)
                return;   // sin dispositivo de impresión no hay hoja que validar

            double left = cx - w / 2.0;
            double right = cx + w / 2.0;
            double bottom = cy - h / 2.0;
            double top = cy + h / 2.0;
            const double tol = 0.51;   // medio milímetro de gracia

            if (left < -tol || bottom < -tol || right > pw + tol || top > ph + tol)
            {
                string orientation = pw >= ph ? "horizontal" : "vertical";
                throw new InvalidOperationException(
                    $"El viewport ({w:0.#}x{h:0.#}mm centrado en {cx:0.#},{cy:0.#}) " +
                    $"ocupa de {left:0.#},{bottom:0.#} a {right:0.#},{top:0.#} y no " +
                    $"entra en la hoja de {pw:0.#}x{ph:0.#}mm ({orientation}). " +
                    $"Achicalo, movelo, o creá el layout con un papel más grande " +
                    $"o en la otra orientación.");
            }
        }
    }
}
