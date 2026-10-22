using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Configuración de impresión de un layout con el VALIDADOR nativo de AutoCAD
    /// (PlotSettingsValidator): dispositivo, papel, escala, rotación, área, tabla de estilos.
    ///
    /// Por qué un comando aparte y no propiedades. El validador es una clase ESTÁTICA con listas
    /// que dependen del dispositivo elegido (qué papeles admite cada impresora), y la reflexión
    /// genérica no maneja estáticos. Las propiedades simples del layout (PlotPlotStyles,
    /// ShowPlotStyles...) siguen siendo de get/set_object_properties sobre su handle.
    ///
    /// Se valida todo antes de escribir y va en una transacción: si algo falla, el layout queda
    /// como estaba. No envía nada a imprimir ni escribe archivos.
    /// </summary>
    public static class LayoutPlotCommands
    {
        private static Layout Buscar(Transaction tr, Database db, string nombre, OpenMode modo)
        {
            var dic = (DBDictionary)tr.GetObject(db.LayoutDictionaryId, OpenMode.ForRead);
            if (!dic.Contains(nombre))
            {
                var nombres = new List<string>();
                foreach (DBDictionaryEntry e in dic) nombres.Add(e.Key);
                throw new ArgumentException("No hay un layout llamado '" + nombre + "'. Hay: " + string.Join(", ", nombres) + ".");
            }
            return (Layout)tr.GetObject(dic.GetAt(nombre), modo);
        }

        private static JsonArray Lista(System.Collections.Specialized.StringCollection c, int max = 500)
        {
            var a = new JsonArray();
            if (c == null) return a;
            foreach (string s in c)
            {
                if (a.Count >= max) break;
                a.Add(JsonValue.Create(s));
            }
            return a;
        }

        private static JsonObject Estado(Layout l)
        {
            var o = new JsonObject
            {
                ["device"] = l.PlotConfigurationName,
                ["media"] = l.CanonicalMediaName,
                ["styleSheet"] = l.CurrentStyleSheet,
                ["plotType"] = l.PlotType.ToString(),
                ["rotation"] = l.PlotRotation.ToString(),
                ["centered"] = l.PlotCentered,
                ["paperUnits"] = l.PlotPaperUnits.ToString(),
                ["useStandardScale"] = l.UseStandardScale,
            };
            try { o["standardScale"] = l.StdScaleType.ToString(); } catch (SysException) { }
            try
            {
                var c = l.CustomPrintScale;
                o["customScale"] = new JsonObject { ["paper"] = c.Numerator, ["drawing"] = c.Denominator };
            }
            catch (SysException) { }
            return o;
        }

        /// <summary>params: [layout] (default el activo). Devuelve lo que ofrece AutoCAD y la configuración actual.</summary>
        public static JsonObject Options(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            string nombre = pars["layout"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(nombre))
                nombre = Convert.ToString(Autodesk.AutoCAD.ApplicationServices.Application.GetSystemVariable("CTAB"));
            var psv = PlotSettingsValidator.Current;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var layout = Buscar(tr, db, nombre, OpenMode.ForRead);
                // RefreshLists MODIFICA el objeto que recibe (necesita escritura): sobre un layout abierto en lectura es una
                // aserción interna fatal de AutoCAD (eNotOpenForWrite en dbobji.cpp), no una excepción. Se trabaja sobre una
                // COPIA suelta (PlotSettings fuera de la base), que el layout nunca ve.
                var r = new JsonObject();
                using (var copia = new PlotSettings(layout.ModelType))
                {
                    copia.CopyFrom(layout);
                    psv.RefreshLists(copia);
                    r["layout"] = nombre;
                    r["devices"] = Lista(psv.GetPlotDeviceList());
                    r["media"] = Lista(psv.GetCanonicalMediaNameList(copia));
                    r["styleSheets"] = Lista(psv.GetPlotStyleSheetList());
                }
                r["plotTypes"] = new JsonArray(Enum.GetNames(typeof(PlotType)).Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                r["rotations"] = new JsonArray(Enum.GetNames(typeof(PlotRotation)).Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                r["paperUnits"] = new JsonArray(Enum.GetNames(typeof(PlotPaperUnit)).Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                r["standardScales"] = new JsonArray(Enum.GetNames(typeof(StdScaleType)).Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                r["current"] = Estado(layout);
                tr.Commit();
                return r;
            }
        }

        private static T Enumeracion<T>(JsonNode n, string cual) where T : struct
        {
            string s = n is JsonValue v && v.TryGetValue<string>(out var t) ? t : null;
            if (s == null || !Enum.IsDefined(typeof(T), s))
                throw new ArgumentException("'" + cual + "' admite: " + string.Join(", ", Enum.GetNames(typeof(T))) + ".");
            return (T)Enum.Parse(typeof(T), s);
        }

        private static string DeLista(System.Collections.Specialized.StringCollection c, string pedido, string cual)
        {
            foreach (string s in c)
                if (s.Equals(pedido, StringComparison.OrdinalIgnoreCase)) return s;
            var ej = new List<string>();
            foreach (string s in c) { if (ej.Count >= 8) break; ej.Add(s); }
            throw new ArgumentException("'" + pedido + "' no está entre los " + cual + " disponibles (por ejemplo: " + string.Join(", ", ej) +
                                        "). Mirá list_plot_options.");
        }

        /// <summary>params: layout, [device], [media], [style_sheet], [plot_type], [rotation], [centered], [paper_units],
        /// [scale] ("fit", un nombre de escala estándar o {"paper": 1, "drawing": 100}), [window] [[x1,y1],[x2,y2]].</summary>
        public static JsonObject Configure(Document doc, JsonObject pars)
        {
            string nombre = pars["layout"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(nombre)) throw new ArgumentException("Falta 'layout'.");
            var campos = new[] { "device", "media", "style_sheet", "plot_type", "rotation", "centered", "paper_units", "scale", "window" };
            if (!campos.Any(c => pars[c] != null))
                throw new ArgumentException("No hay nada que configurar: pasá " + string.Join(", ", campos) + ".");
            var db = doc.Database;
            var psv = PlotSettingsValidator.Current;
            JsonObject antes, despues;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var layout = Buscar(tr, db, nombre, OpenMode.ForWrite);
                    antes = Estado(layout);

                    // 1) dispositivo y papel juntos: el papel depende del dispositivo
                    string dispositivo = layout.PlotConfigurationName, papel = layout.CanonicalMediaName;
                    if (pars["device"] != null)
                        dispositivo = DeLista(psv.GetPlotDeviceList(), pars["device"].GetValue<string>(), "dispositivos");
                    if (pars["device"] != null || pars["media"] != null)
                    {
                        psv.SetPlotConfigurationName(layout, dispositivo, null);
                        psv.RefreshLists(layout);
                        if (pars["media"] != null)
                            papel = DeLista(psv.GetCanonicalMediaNameList(layout), pars["media"].GetValue<string>(), "papeles de ese dispositivo");
                        else if (pars["device"] != null)
                            papel = null;
                        if (papel != null) psv.SetCanonicalMediaName(layout, papel);
                    }
                    if (pars["plot_type"] != null && pars["window"] == null)
                    {
                        if (pars["plot_type"].GetValue<string>() == "Window")
                            throw new ArgumentException("plot_type=Window necesita también 'window' ([[x1,y1],[x2,y2]]): sin el área AutoCAD lo rechaza.");
                        psv.SetPlotType(layout, Enumeracion<PlotType>(pars["plot_type"], "plot_type"));
                    }
                    if (pars["window"] != null)
                    {
                        var w = pars["window"] as JsonArray;
                        if (w == null || w.Count != 2 || !(w[0] is JsonArray a) || !(w[1] is JsonArray b) || a.Count != 2 || b.Count != 2)
                            throw new ArgumentException("'window' es [[x1, y1], [x2, y2]].");
                        double x1 = a[0].GetValue<double>(), y1 = a[1].GetValue<double>(), x2 = b[0].GetValue<double>(), y2 = b[1].GetValue<double>();
                        if (x1 == x2 || y1 == y2) throw new ArgumentException("'window' tiene que tener área.");
                        // El área va ANTES que el tipo: SetPlotType(Window) sin área definida da eInvalidInput.
                        psv.SetPlotWindowArea(layout, new Extents2d(Math.Min(x1, x2), Math.Min(y1, y2), Math.Max(x1, x2), Math.Max(y1, y2)));
                        psv.SetPlotType(layout, PlotType.Window);
                    }
                    if (pars["paper_units"] != null)
                        psv.SetPlotPaperUnits(layout, Enumeracion<PlotPaperUnit>(pars["paper_units"], "paper_units"));
                    if (pars["rotation"] != null)
                        psv.SetPlotRotation(layout, Enumeracion<PlotRotation>(pars["rotation"], "rotation"));
                    if (pars["centered"] != null)
                        psv.SetPlotCentered(layout, pars["centered"].GetValue<bool>());
                    if (pars["scale"] != null)
                    {
                        var sc = pars["scale"];
                        if (sc is JsonObject so)
                        {
                            double papelU = so["paper"]?.GetValue<double>() ?? 0, dibujoU = so["drawing"]?.GetValue<double>() ?? 0;
                            if (papelU <= 0 || dibujoU <= 0 || double.IsNaN(papelU) || double.IsNaN(dibujoU))
                                throw new ArgumentException("'scale' es {\"paper\": n > 0, \"drawing\": n > 0}, p.ej. 1 y 100 para 1:100.");
                            psv.SetUseStandardScale(layout, false);
                            psv.SetCustomPrintScale(layout, new CustomScale(papelU, dibujoU));
                        }
                        else if (sc is JsonValue sv && sv.TryGetValue<string>(out var ss))
                        {
                            psv.SetUseStandardScale(layout, true);
                            if (ss.Equals("fit", StringComparison.OrdinalIgnoreCase)) psv.SetStdScaleType(layout, StdScaleType.ScaleToFit);
                            else psv.SetStdScaleType(layout, Enumeracion<StdScaleType>(sc, "scale"));
                        }
                        else throw new ArgumentException("'scale' es \"fit\", un nombre de escala estándar o {\"paper\": 1, \"drawing\": 100}.");
                    }
                    if (pars["style_sheet"] != null)
                        psv.SetCurrentStyleSheet(layout, DeLista(psv.GetPlotStyleSheetList(), pars["style_sheet"].GetValue<string>(), "tablas de estilos de trazado"));
                    despues = Estado(layout);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó la configuración (" + ex.ErrorStatus + "): " + ex.Message + ". El layout quedó como estaba.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["layout"] = nombre, ["before"] = antes, ["after"] = despues };
        }

        // ============================================================ BLOQUES DINÁMICOS

        private static JsonNode DePropiedad(DynamicBlockReferenceProperty p)
        {
            var o = new JsonObject
            {
                ["name"] = p.PropertyName, ["value"] = PropertiesCommands.AJson(p.Value), ["readOnly"] = p.ReadOnly,
                ["show"] = p.Show, ["typeCode"] = (int)p.PropertyTypeCode,
            };
            try
            {
                var permitidos = p.GetAllowedValues();
                if (permitidos != null && permitidos.Length > 0)
                    o["allowedValues"] = new JsonArray(permitidos.Take(200).Select(x => PropertiesCommands.AJson(x)).ToArray());
            }
            catch (SysException) { }
            try { o["units"] = p.UnitsType.ToString(); } catch (SysException) { }
            return o;
        }

        /// <summary>params: handle de una referencia de bloque dinámico.</summary>
        public static JsonObject DynamicGet(Document doc, JsonObject pars)
        {
            var id = HandleHelper.GetObjectId(doc.Database, pars["handle"]?.GetValue<string>() ?? "");
            var items = new JsonArray();
            string bloque;
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                if (br == null) throw new ArgumentException("Ese handle no es una referencia de bloque.");
                if (!br.IsDynamicBlock) throw new ArgumentException("Ese bloque no es dinámico.");
                var btr = (BlockTableRecord)tr.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead);
                bloque = btr.Name;
                foreach (DynamicBlockReferenceProperty p in br.DynamicBlockReferencePropertyCollection)
                    items.Add(DePropiedad(p));
                tr.Commit();
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["block"] = bloque, ["properties"] = items, ["count"] = items.Count };
        }

        /// <summary>params: handle, values {nombre: valor}. Se validan todos antes de escribir.</summary>
        public static JsonObject DynamicSet(Document doc, JsonObject pars)
        {
            var id = HandleHelper.GetObjectId(doc.Database, pars["handle"]?.GetValue<string>() ?? "");
            var pedidos = pars["values"] as JsonObject;
            if (pedidos == null || pedidos.Count == 0) throw new ArgumentException("Falta 'values': un objeto {propiedad: valor}.");
            if (pedidos.Count > 60) throw new ArgumentException("Máximo 60 propiedades por llamada.");
            var cambios = new JsonObject();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                try
                {
                    var lectura = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (lectura == null) throw new ArgumentException("Ese handle no es una referencia de bloque.");
                    if (!lectura.IsDynamicBlock) throw new ArgumentException("Ese bloque no es dinámico.");
                    var plan = new List<Tuple<string, object>>();
                    foreach (var kv in pedidos)
                    {
                        DynamicBlockReferenceProperty prop = null;
                        foreach (DynamicBlockReferenceProperty p in lectura.DynamicBlockReferencePropertyCollection)
                            if (p.PropertyName.Equals(kv.Key, StringComparison.OrdinalIgnoreCase)) { prop = p; break; }
                        if (prop == null)
                        {
                            var nombres = new List<string>();
                            foreach (DynamicBlockReferenceProperty p in lectura.DynamicBlockReferencePropertyCollection) nombres.Add(p.PropertyName);
                            throw new ArgumentException("El bloque no tiene la propiedad '" + kv.Key + "'. Tiene: " + string.Join(", ", nombres) + ".");
                        }
                        if (prop.ReadOnly) throw new ArgumentException("La propiedad '" + prop.PropertyName + "' es de solo lectura.");
                        if (kv.Value == null) throw new ArgumentException("El valor de '" + kv.Key + "' no puede ser null.");
                        object actual = prop.Value;
                        object nuevo;
                        if (actual is string) nuevo = kv.Value is JsonValue sv && sv.TryGetValue<string>(out var s1) ? s1 : kv.Value.ToString();
                        else if (actual is double) nuevo = kv.Value.GetValue<double>();
                        else if (actual is short) nuevo = Convert.ToInt16(kv.Value.GetValue<double>());
                        else if (actual is int) nuevo = Convert.ToInt32(kv.Value.GetValue<double>());
                        else throw new ArgumentException("La propiedad '" + prop.PropertyName + "' es de un tipo (" + actual?.GetType().Name + ") que no se maneja.");
                        var permitidos = prop.GetAllowedValues();
                        if (permitidos != null && permitidos.Length > 0)
                        {
                            bool esta = permitidos.Any(x => x is double dx && nuevo is double dn
                                ? Math.Abs(dx - dn) < 1e-9
                                : Equals(x, nuevo) || (x is string xs && nuevo is string ns && xs.Equals(ns, StringComparison.OrdinalIgnoreCase)));
                            if (!esta)
                                throw new ArgumentException("'" + prop.PropertyName + "' no admite " + kv.Value.ToJsonString() + ". Permitidos: " +
                                    string.Join(", ", permitidos.Take(30).Select(x => Convert.ToString(x))) + ".");
                        }
                        plan.Add(Tuple.Create(prop.PropertyName, nuevo));
                    }
                    var br = (BlockReference)tr.GetObject(id, OpenMode.ForWrite, false, true);
                    foreach (var item in plan)
                    {
                        foreach (DynamicBlockReferenceProperty p in br.DynamicBlockReferencePropertyCollection)
                        {
                            if (!p.PropertyName.Equals(item.Item1, StringComparison.OrdinalIgnoreCase)) continue;
                            var antes = PropertiesCommands.AJson(p.Value);
                            p.Value = item.Item2;
                            cambios[p.PropertyName] = new JsonObject { ["before"] = antes, ["after"] = PropertiesCommands.AJson(p.Value) };
                            break;
                        }
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el cambio (" + ex.ErrorStatus + "): " + ex.Message + ". No se modificó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["changes"] = cambios, ["count"] = cambios.Count };
        }
    }
}
