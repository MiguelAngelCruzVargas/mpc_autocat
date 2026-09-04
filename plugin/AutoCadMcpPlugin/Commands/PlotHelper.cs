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
        /// <summary>
        /// Tamano del archivo, o -1 si no existe o esta bloqueado por el
        /// driver mientras escribe. Nunca tira: solo dice "todavia no".
        /// </summary>
        private static long TamanoDe(string path)
        {
            try
            {
                var fi = new FileInfo(path);
                return fi.Exists ? fi.Length : -1;
            }
            catch (System.Exception)
            {
                return -1;
            }
        }

        private static int PlotWaitMs()
        {
            var raw = System.Environment.GetEnvironmentVariable("ACAD_MCP_EXEC_TIMEOUT");
            int exec = int.TryParse(raw, out var parsed) && parsed > 0 ? parsed : 60;
            // 20s de margen para la espera previa y el resto del comando.
            int ms = (exec - 20) * 1000;
            return ms < 10000 ? 10000 : ms;
        }

        /// <summary>
        /// Plotea 'layoutId' al archivo 'path' con el driver 'device'
        /// (p.ej. "DWG To PDF.pc3", "PublishToWeb PNG.pc3"). 'plotType'
        /// decide el área: Layout para una hoja tal cual quedó armada,
        /// Extents para encuadrar a lo que hay dibujado (espacio modelo,
        /// sin layout de por medio).
        /// </summary>
        public static void PlotToFile(Document doc, ObjectId layoutId,
                                      Autodesk.AutoCAD.DatabaseServices.PlotType plotType,
                                      string device, string path,
                                      Extents2d? window = null)
        {
            if (string.IsNullOrWhiteSpace(path))
                throw new ArgumentException("Falta 'path' — la ruta de salida del archivo.");

            string fullPath = Path.GetFullPath(path);
            string dir = Path.GetDirectoryName(fullPath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                throw new InvalidOperationException($"No existe la carpeta de destino '{dir}'.");

            // Un comando de línea de comandos en curso (un ZOOM encolado por
            // SendStringToExecute, un REGEN largo) hace que arrancar el plot
            // tire eInvalidInput -- visto en vivo: zoom_extents seguido de
            // capture_viewport fallaba y el reintento a ciegas pasaba. Se le
            // da un margen a que termine, en vez de fallar y hacer gastar el
            // reintento al cliente.
            for (int espera = 0; espera < 100 && !string.IsNullOrEmpty(doc.CommandInProgress); espera++)
            {
                System.Windows.Forms.Application.DoEvents();
                System.Threading.Thread.Sleep(100);
            }

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

            // BACKGROUNDPLOT: con el valor de fábrica (2 = publicar en segundo
            // plano) el PublishEngine le pasa el trabajo a OTRO acad.exe que
            // AutoCAD lanza como proceso hijo. Medido en vivo: ese hijo vive
            // ~40 s por captura, y mientras vive ProcessPlotState no vuelve
            // a NotPlotting -- el siguiente plot se queda en la espera de
            // arriba y todo lo demás (zoom_extents, get_extents) se encola
            // detrás. Una captura pasaba de 7 s a 40-80 s en cuanto había
            // dos seguidas. En primer plano (0) el mismo proceso renderiza,
            // termina, y el estado se libera al instante. Se restaura al
            // salir: es una preferencia del usuario, no de este plugin.
            object backgroundPlotAnterior = null;
            try
            {
                backgroundPlotAnterior = Application.GetSystemVariable("BACKGROUNDPLOT");
                Application.SetSystemVariable("BACKGROUNDPLOT", (short)0);
            }
            catch (System.Exception)
            {
                backgroundPlotAnterior = null;   // se plotea igual, como antes
            }

            try
            {
            PlotToFileCore(doc, layoutId, plotType, device, fullPath, window);
            }
            finally
            {
                if (backgroundPlotAnterior != null)
                {
                    try { Application.SetSystemVariable("BACKGROUNDPLOT", backgroundPlotAnterior); }
                    catch (System.Exception) { /* no vale la pena fallar el plot por esto */ }
                }
            }
        }

        private static void PlotToFileCore(Document doc, ObjectId layoutId,
                                           Autodesk.AutoCAD.DatabaseServices.PlotType plotType,
                                           string device, string fullPath,
                                           Extents2d? window)
        {
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
                    // La ventana se fija ANTES del tipo: SetPlotWindowArea
                    // no tiene efecto si el tipo todavia no es Window.
                    if (window.HasValue)
                        psv.SetPlotWindowArea(ps, window.Value);
                    psv.SetPlotType(ps, plotType);

                    if (window.HasValue)
                    {
                        psv.SetUseStandardScale(ps, true);
                        psv.SetStdScaleType(ps, StdScaleType.ScaleToFit);
                        psv.SetPlotCentered(ps, true);
                        psv.SetPlotRotation(ps, PlotRotation.Degrees000);
                    }

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
            // Que el archivo EXISTA no quiere decir que este terminado: el
            // driver lo crea vacio y sigue escribiendo. Esperar solo por
            // File.Exists devolvia "ok" sobre un PDF/PNG de 0 bytes, y el
            // plot seguia corriendo -- envenenando al siguiente comando con
            // "ya hay un plot en curso". Se vio en test_live: export_pdf y
            // capture_viewport decian que si y no habia archivo.
            //
            // La condicion real es tamano > 0 y ESTABLE: tres lecturas
            // seguidas iguales (300 ms sin crecer).
            int maxWaitMs = PlotWaitMs();
            const int stepMs = 100;
            const int lecturasEstables = 3;
            long ultimo = -1;
            int estables = 0;
            int waited = 0;
            for (; waited < maxWaitMs; waited += stepMs)
            {
                System.Windows.Forms.Application.DoEvents();
                System.Threading.Thread.Sleep(stepMs);

                long tamano = TamanoDe(fullPath);
                if (tamano <= 0)
                {
                    ultimo = -1;
                    estables = 0;
                    continue;
                }
                if (tamano == ultimo)
                {
                    if (++estables >= lecturasEstables)
                        break;
                }
                else
                {
                    ultimo = tamano;
                    estables = 0;
                }
            }

            long final = TamanoDe(fullPath);
            if (final <= 0)
                throw new InvalidOperationException(
                    $"El plot no escribió '{fullPath}' después de esperar {maxWaitMs / 1000}s " +
                    $"(el archivo {(File.Exists(fullPath) ? "quedó en 0 bytes" : "no existe")}). " +
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
