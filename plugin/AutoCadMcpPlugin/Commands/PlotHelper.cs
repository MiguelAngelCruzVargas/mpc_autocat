using System;
using System.IO;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.PlottingServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Núcleo compartido de "plotear a archivo": lo usan PlotCommand (PDF de
    /// un layout, export_pdf) y CaptureViewportCommand (PNG del estado
    /// actual, capture_viewport). La coreografía BeginPlot/BeginDocument/
    /// BeginPage de la API de plotting es la misma más allá del driver de
    /// salida (PDF vs PNG) — no tiene sentido duplicarla en cada comando.
    /// </summary>
    internal static class PlotHelper
    {
        /// <summary>
        /// Plotea 'layoutId' al archivo 'path' con el driver 'device'
        /// (p.ej. "DWG To PDF.pc3", "PublishToWeb PNG.pc3"). 'plotType'
        /// decide el área: Layout para una hoja tal cual quedó armada,
        /// Extents para encuadrar a lo que hay dibujado (espacio modelo,
        /// sin layout de por medio).
        /// </summary>
        /// <summary>
        /// Cuanto esperar a que el driver termine de escribir el archivo.
        ///
        /// Era un fijo de 35s, y el techo real lo pone el dispatcher: si
        /// esperamos mas que ACAD_MCP_EXEC_TIMEOUT, la llamada se corta
        /// igual y el plot queda huerfano -- envenenando al SIGUIENTE con
        /// "ya hay un plot en curso". Eso paso de verdad capturando los
        /// layouts de un plano de 19 mil entidades: cada uno tardaba mas de
        /// 90s, el primero fallaba por timeout y arrastraba a los tres que
        /// venian atras, aunque los archivos terminaban escribiendose bien.
        ///
        /// Derivarlo del timeout del dispatcher, en vez de un numero fijo,
        /// hace que subir ACAD_MCP_EXEC_TIMEOUT alcance para planos pesados.
        /// </summary>
        private static int PlotWaitMs()
        {
            var raw = System.Environment.GetEnvironmentVariable("ACAD_MCP_EXEC_TIMEOUT");
            int exec = int.TryParse(raw, out var parsed) && parsed > 0 ? parsed : 60;
            // 20s de margen para la espera previa y el resto del comando.
            int ms = (exec - 20) * 1000;
            return ms < 10000 ? 10000 : ms;
        }

        public static void PlotToFile(Document doc, ObjectId layoutId,
                                      Autodesk.AutoCAD.DatabaseServices.PlotType plotType,
                                      string device, string path)
        {
            if (string.IsNullOrWhiteSpace(path))
                throw new ArgumentException("Falta 'path' — la ruta de salida del archivo.");

            string fullPath = Path.GetFullPath(path);
            string dir = Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                throw new InvalidOperationException($"No existe la carpeta de destino '{dir}'.");

            // El motor de plotting tarda en soltar ProcessPlotState después
            // de que el plot ANTERIOR ya escribió su archivo y devolvió el
            // control (visto en vivo: export_pdf seguido de capture_viewport
            // sin pausa choca acá — medido en vivo, tarda unos 10s en
            // liberarse, así que un margen de 5s no alcanzaba). Darle un
            // margen largo antes de asumir que hay un plot de verdad
            // trabado, en vez de fallar apenas el anterior recién terminó.
            for (int espera = 0; espera < 150 && PlotFactory.ProcessPlotState != ProcessPlotState.NotPlotting; espera++)
            {
                System.Windows.Forms.Application.DoEvents();
                System.Threading.Thread.Sleep(100);
            }
            if (PlotFactory.ProcessPlotState != ProcessPlotState.NotPlotting)
                throw new InvalidOperationException(
                    "Ya hay un plot en curso en este AutoCAD; esperá a que termine antes " +
                    "de pedir otro.");

            var db = doc.Database;
            string layoutName;
            using (var tr0 = db.TransactionManager.StartTransaction())
            {
                layoutName = ((Layout)tr0.GetObject(layoutId, OpenMode.ForRead)).LayoutName;
                tr0.Commit();
            }

            // AutoCAD exige que el layout que se plotea sea el ACTIVO
            // ('eLayoutNotCurrent' si no) — mismo motivo por el que
            // LayoutCommands.CreateViewport hace este mismo cambio-y-restaura.
            var lm = LayoutManager.Current;
            string previousLayout = lm.CurrentLayout;
            bool switched = !string.Equals(previousLayout, layoutName, StringComparison.OrdinalIgnoreCase);
            if (switched)
                lm.CurrentLayout = layoutName;

            try
            {
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var layout = (Layout)tr.GetObject(layoutId, OpenMode.ForRead);

                using (var ps = new PlotSettings(layout.ModelType))
                {
                    ps.CopyFrom(layout);

                    var psv = PlotSettingsValidator.Current;
                    try
                    {
                        psv.SetPlotConfigurationName(ps, device, null);
                    }
                    catch (System.Exception ex)
                    {
                        throw new InvalidOperationException(
                            $"No se pudo usar el dispositivo de impresión '{device}': {ex.Message}");
                    }
                    psv.RefreshLists(ps);
                    psv.SetPlotType(ps, plotType);

                    if (plotType == Autodesk.AutoCAD.DatabaseServices.PlotType.Extents)
                    {
                        // Sin layout que ya traiga la escala resuelta (estamos
                        // encuadrando el espacio modelo tal cual), ajustar a
                        // la hoja es lo único que tiene sentido acá.
                        psv.SetUseStandardScale(ps, true);
                        psv.SetStdScaleType(ps, StdScaleType.ScaleToFit);
                        psv.SetPlotCentered(ps, true);
                        // ps.CopyFrom(layout) trae lo que haya quedado guardado
                        // en el PlotSettings del tab Model (visto en vivo: salía
                        // rotado 90° con un cajón apaisado — el rótulo se leía
                        // de costado — mientras que las cotas y coordenadas del
                        // DWG eran correctas). Para esta foto "tal cual está
                        // dibujado" la rotación tiene que ser siempre 0, no lo
                        // que haya quedado de una sesión anterior.
                        psv.SetPlotRotation(ps, PlotRotation.Degrees000);
                    }

                    using (var pi = new PlotInfo())
                    {
                        pi.Layout = layoutId;
                        pi.OverrideSettings = ps;

                        var piv = new PlotInfoValidator
                        {
                            MediaMatchingPolicy = MatchingPolicy.MatchEnabled
                        };
                        piv.Validate(pi);

                        // CreatePublishEngine() es la ÚNICA fábrica que existe
                        // en la API .NET administrada (CreatePlotEngine() es
                        // de la API C++/ObjectARX, acá no compila) — el nombre
                        // "Publish" es histórico, no significa que el trabajo
                        // quede en una cola aparte.
                        //
                        // Sin PlotProgressDialog a propósito: nada de UI desde
                        // acá, mismo criterio que el resto del plugin (ver
                        // notas de diseño del README sobre no tocar el Editor
                        // fuera del hilo de documento).
                        using (var pe = PlotFactory.CreatePublishEngine())
                        {
                            pe.BeginPlot(null, null);
                            System.Windows.Forms.Application.DoEvents();
                            try
                            {
                                pe.BeginDocument(pi, doc.Name, null, 1, true, fullPath);
                                System.Windows.Forms.Application.DoEvents();
                                try
                                {
                                    var ppi = new PlotPageInfo();
                                    pe.BeginPage(ppi, pi, true, null);
                                    System.Windows.Forms.Application.DoEvents();
                                    pe.BeginGenerateGraphics(null);
                                    pe.EndGenerateGraphics(null);
                                    System.Windows.Forms.Application.DoEvents();
                                    pe.EndPage(null);
                                    System.Windows.Forms.Application.DoEvents();
                                }
                                finally
                                {
                                    pe.EndDocument(null);
                                    System.Windows.Forms.Application.DoEvents();
                                }
                            }
                            finally
                            {
                                pe.EndPlot(null);
                                System.Windows.Forms.Application.DoEvents();
                            }
                        }
                    }
                }

                // Nada del layout se modificó de verdad (PlotSettings vive
                // aparte, en 'ps'); el commit es solo para cerrar la
                // transacción de lectura prolijo.
                tr.Commit();
            }

            // El renderizado real (spool del driver, escritura del archivo)
            // puede seguir después de que EndPlot devuelve el control, y en
            // un dibujo con hatches/mucha geometría puede tardar bastante más
            // que un par de segundos. Esperamos hasta 35s bombeando mensajes
            // mientras tanto, en vez de un timeout corto que reporte "no
            // encontrado" sobre un plot que en realidad iba a terminar bien
            // un rato después. Sumado a los 15s de gracia de más arriba da
            // 50s como mucho, por debajo de ACAD_MCP_EXEC_TIMEOUT (60s) —
            // si sumaran los dos máximos, el dispatcher cortaría la llamada
            // con timeout aunque el plot fuera a terminar bien.
            int maxWaitMs = PlotWaitMs();
            const int stepMs = 100;
            for (int waited = 0; waited < maxWaitMs && !File.Exists(fullPath); waited += stepMs)
            {
                System.Windows.Forms.Application.DoEvents();
                System.Threading.Thread.Sleep(stepMs);
            }

            if (!File.Exists(fullPath))
                throw new InvalidOperationException(
                    $"El plot no escribió '{fullPath}' después de esperar {maxWaitMs / 1000}s. " +
                    $"Si el dispositivo '{device}' está instalado, el dibujo es " +
                    "simplemente pesado: subí ACAD_MCP_EXEC_TIMEOUT (y el " +
                    "ACAD_MCP_TIMEOUT del cliente, que tiene que ser mayor).");
            }
            finally
            {
                // Dejamos la vista como estaba: plotear un layout no debería
                // cambiarle la pestaña activa al usuario.
                if (switched)
                {
                    try { lm.CurrentLayout = previousLayout; } catch { }
                }
            }
        }
    }
}
