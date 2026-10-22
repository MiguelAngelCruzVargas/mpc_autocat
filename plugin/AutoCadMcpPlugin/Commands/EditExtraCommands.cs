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
    /// Edición que en AutoCAD son comandos (EXPLODE, BREAK, DIVIDE/MEASURE, BOUNDARY, MATCHPROP) y que acá se
    /// resuelven con la API administrada: cada una en UNA transacción, validada ENTERA antes de tocar el dibujo.
    /// A diferencia de TRIM/EXTEND/FILLET/JOIN (que usan el motor del comando y por eso corren por native_op),
    /// estas no necesitan selección por punto ni vista: la API da la misma geometría directamente.
    /// </summary>
    public static class EditExtraCommands
    {
        private const int MaxHandles = 500;

        private static List<ObjectId> Ids(Document doc, JsonNode n, string cual, int minimo, int maximo = MaxHandles)
        {
            var arr = n as JsonArray;
            if (arr == null || arr.Count < minimo) throw new ArgumentException("'" + cual + "' necesita al menos " + minimo + " handle(s).");
            if (arr.Count > maximo) throw new ArgumentException("'" + cual + "': máximo " + maximo + " handles.");
            var lista = new List<ObjectId>();
            foreach (var x in arr)
            {
                var id = HandleHelper.GetObjectId(doc.Database, x.GetValue<string>());
                if (!lista.Contains(id)) lista.Add(id);
            }
            return lista;
        }

        private static ObjectId Uno(Document doc, JsonNode n, string cual)
        {
            string h = n?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(h)) throw new ArgumentException("Falta '" + cual + "' (un handle).");
            return HandleHelper.GetObjectId(doc.Database, h);
        }

        private static void Liberar(DBObjectCollection partes)
        {
            foreach (DBObject o in partes)
            {
                try { if (!o.IsDisposed) o.Dispose(); } catch (SysException) { }
            }
        }

        // ============================================================ EXPLODE

        /// <summary>params: handles[], [delete_original=true]. Descompone cada entidad en sus partes (polilínea en
        /// segmentos, bloque en sus entidades, cota en líneas y texto...). Todo o nada.</summary>
        public static JsonObject Explode(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var ids = Ids(doc, pars["handles"], "handles", 1);
            bool borrar = pars["delete_original"]?.GetValue<bool>() ?? true;
            var creadas = new JsonArray();
            int explotadas = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var porLiberar = new List<DBObjectCollection>();
                try
                {
                    foreach (var id in ids)
                    {
                        var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                        if (ent == null) throw new ArgumentException("'" + id.Handle + "' no es una entidad de dibujo.");
                        if (ent is BlockReference br)
                        {
                            var def = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForRead);
                            if (def.IsFromExternalReference || def.IsFromOverlayReference)
                                throw new InvalidOperationException("'" + id.Handle + "' es un xref: no se descompone (usá bind_xref primero).");
                        }
                        var partes = new DBObjectCollection();
                        porLiberar.Add(partes);
                        try { ent.Explode(partes); }
                        catch (AcException ex)
                        {
                            throw new InvalidOperationException("'" + id.Handle + "' (" + ent.GetType().Name + ") no se puede descomponer (" + ex.ErrorStatus + ").");
                        }
                        if (partes.Count == 0) throw new InvalidOperationException("'" + id.Handle + "' (" + ent.GetType().Name + ") no produjo partes.");
                        var espacio = (BlockTableRecord)tr.GetObject(ent.BlockId, OpenMode.ForWrite);
                        foreach (DBObject o in partes)
                        {
                            var p = o as Entity;
                            if (p == null) continue;
                            espacio.AppendEntity(p);
                            tr.AddNewlyCreatedDBObject(p, true);
                            creadas.Add(p.Handle.ToString());
                        }
                        explotadas++;
                    }
                    if (borrar)
                    {
                        foreach (var id in ids)
                            tr.GetObject(id, OpenMode.ForWrite).Erase(true);
                    }
                    tr.Commit();
                }
                catch (SysException)
                {
                    tr.Abort();
                    foreach (var c in porLiberar) Liberar(c);
                    throw;
                }
            }
            return new JsonObject { ["exploded"] = explotadas, ["created"] = creadas, ["createdCount"] = creadas.Count, ["originalsDeleted"] = borrar };
        }

        // ============================================================ BREAK

        /// <summary>params: handle (de una curva), points[[x,y],...] donde cortar (se llevan a la curva). Parte la
        /// curva en tantos tramos como cortes (una curva cerrada necesita al menos 2 puntos). Los tramos heredan
        /// capa, color, tipo de línea y grosor; el original se borra.</summary>
        public static JsonObject Break(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var id = Uno(doc, pars["handle"], "handle");
            var pa = pars["points"] as JsonArray;
            if (pa == null || pa.Count == 0) throw new ArgumentException("'points' es una lista de puntos [x, y] donde cortar.");
            if (pa.Count > 200) throw new ArgumentException("Máximo 200 puntos de corte.");
            var creadas = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                DBObjectCollection tramos = null;
                try
                {
                    var curva = tr.GetObject(id, OpenMode.ForRead) as Curve;
                    if (curva == null) throw new ArgumentException("Solo se parte una línea, arco, círculo, polilínea o spline.");
                    var parametros = new List<double>();
                    foreach (var pn in pa)
                    {
                        var a = pn as JsonArray;
                        if (a == null || a.Count < 2 || a.Count > 3) throw new ArgumentException("Cada punto es [x, y] o [x, y, z].");
                        var p = new Point3d(a[0].GetValue<double>(), a[1].GetValue<double>(), a.Count == 3 ? a[2].GetValue<double>() : 0.0);
                        var enCurva = curva.GetClosestPointTo(p, false);
                        parametros.Add(curva.GetParameterAtPoint(enCurva));
                    }
                    parametros.Sort();
                    var dc = new DoubleCollection();
                    foreach (var d in parametros)
                    {
                        if (dc.Count > 0 && Math.Abs(dc[dc.Count - 1] - d) < 1e-9) continue;
                        dc.Add(d);
                    }
                    if (curva.Closed && dc.Count < 2)
                        throw new ArgumentException("Una curva cerrada necesita al menos 2 puntos de corte distintos.");
                    tramos = curva.GetSplitCurves(dc);
                    if (tramos == null || tramos.Count < 2)
                        throw new InvalidOperationException("Los puntos caen en los extremos de la curva: no hay nada que partir.");
                    var espacio = (BlockTableRecord)tr.GetObject(curva.BlockId, OpenMode.ForWrite);
                    foreach (DBObject o in tramos)
                    {
                        var c = (Entity)o;
                        c.SetPropertiesFrom(curva);
                        espacio.AppendEntity(c);
                        tr.AddNewlyCreatedDBObject(c, true);
                        creadas.Add(c.Handle.ToString());
                    }
                    tr.GetObject(id, OpenMode.ForWrite).Erase(true);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (tramos != null) Liberar(tramos);
                    throw new InvalidOperationException("AutoCAD rechazó partir la curva (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    if (tramos != null) Liberar(tramos);
                    throw;
                }
            }
            return new JsonObject { ["created"] = creadas, ["pieces"] = creadas.Count };
        }

        // ============================================================ DIVIDE / MEASURE

        /// <summary>params: handle (curva), count (DIVIDE: en N partes iguales) o distance (MEASURE: cada tanto desde el
        /// inicio), [block] (nombre de un bloque a insertar en cada marca; sin él, puntos), [align=true] (el
        /// bloque gira siguiendo la curva), [layer]. Devuelve los handles de lo creado.</summary>
        public static JsonObject Divide(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var id = Uno(doc, pars["handle"], "handle");
            int? cuenta = pars["count"]?.GetValue<int>();
            double? distancia = pars["distance"]?.GetValue<double>();
            if ((cuenta == null) == (distancia == null)) throw new ArgumentException("Pasá 'count' (dividir en N partes) o 'distance' (marcar cada tanto), uno de los dos.");
            if (cuenta != null && (cuenta < 2 || cuenta > 5000)) throw new ArgumentException("'count' va de 2 a 5000.");
            if (distancia != null && (double.IsNaN(distancia.Value) || double.IsInfinity(distancia.Value) || distancia <= 0))
                throw new ArgumentException("'distance' tiene que ser un número mayor que cero.");
            string bloque = pars["block"]?.GetValue<string>();
            bool alinear = pars["align"]?.GetValue<bool>() ?? true;
            string capa = pars["layer"]?.GetValue<string>();
            var creadas = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var curva = tr.GetObject(id, OpenMode.ForRead) as Curve;
                    if (curva == null) throw new ArgumentException("Solo se divide una línea, arco, círculo, polilínea o spline.");
                    double largo = curva.GetDistanceAtParameter(curva.EndParam) - curva.GetDistanceAtParameter(curva.StartParam);
                    if (largo <= 0) throw new InvalidOperationException("La curva no tiene largo.");
                    var marcas = new List<double>();
                    if (cuenta != null) for (int i = 1; i < cuenta.Value; i++) marcas.Add(largo * i / cuenta.Value);
                    else for (double d = distancia.Value; d < largo - 1e-9; d += distancia.Value) marcas.Add(d);
                    if (marcas.Count == 0) throw new InvalidOperationException("La distancia es mayor que el largo de la curva (" + largo + "): no hay marcas.");
                    if (marcas.Count > 5000) throw new ArgumentException("Saldrían " + marcas.Count + " marcas (máximo 5000): usá una distancia mayor.");

                    ObjectId bloqueId = ObjectId.Null;
                    if (!string.IsNullOrEmpty(bloque))
                    {
                        var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                        if (!bt.Has(bloque)) throw new ArgumentException("No hay un bloque llamado '" + bloque + "'.");
                        bloqueId = bt[bloque];
                    }
                    if (!string.IsNullOrEmpty(capa))
                    {
                        var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                        if (!lt.Has(capa)) throw new ArgumentException("No hay una capa llamada '" + capa + "'.");
                    }
                    var espacio = (BlockTableRecord)tr.GetObject(curva.BlockId, OpenMode.ForWrite);
                    double d0 = curva.GetDistanceAtParameter(curva.StartParam);
                    foreach (var m in marcas)
                    {
                        var p = curva.GetPointAtDist(d0 + m);
                        Entity nueva;
                        if (bloqueId.IsNull) nueva = new DBPoint(p);
                        else
                        {
                            var r = new BlockReference(p, bloqueId);
                            if (alinear)
                            {
                                var t = curva.GetFirstDerivative(p);
                                r.Rotation = Math.Atan2(t.Y, t.X);
                            }
                            nueva = r;
                        }
                        if (!string.IsNullOrEmpty(capa)) nueva.Layer = capa;
                        espacio.AppendEntity(nueva);
                        tr.AddNewlyCreatedDBObject(nueva, true);
                        creadas.Add(nueva.Handle.ToString());
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó dividir (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["created"] = creadas, ["marks"] = creadas.Count, ["kind"] = string.IsNullOrEmpty(bloque) ? "points" : "blocks" };
        }

        // ============================================================ BOUNDARY

        /// <summary>params: point [x, y] dentro del recinto, [islands=true] (detectar islas), [layer]. Traza el contorno
        /// cerrado que rodea ese punto (BOUNDARY) y lo dibuja como polilínea(s) cerrada(s). Trabaja sobre lo que se ve
        /// en la vista actual del espacio activo: si el recinto no está a la vista, falla con aviso.</summary>
        public static JsonObject Boundary(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var pa = pars["point"] as JsonArray;
            if (pa == null || pa.Count < 2 || pa.Count > 3) throw new ArgumentException("'point' es [x, y].");
            var punto = new Point3d(pa[0].GetValue<double>(), pa[1].GetValue<double>(), pa.Count == 3 ? pa[2].GetValue<double>() : 0.0);
            bool islas = pars["islands"]?.GetValue<bool>() ?? true;
            string capa = pars["layer"]?.GetValue<string>();
            DBObjectCollection trazado;
            try { trazado = doc.Editor.TraceBoundary(punto, islas); }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD no encontró un contorno cerrado alrededor de ese punto (" + ex.ErrorStatus +
                    "). Revisá que el recinto esté cerrado y a la vista (zoom_window).");
            }
            if (trazado == null || trazado.Count == 0)
                throw new InvalidOperationException("No se encontró un contorno cerrado alrededor de ese punto.");
            var creadas = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    if (!string.IsNullOrEmpty(capa))
                    {
                        var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                        if (!lt.Has(capa)) throw new ArgumentException("No hay una capa llamada '" + capa + "'.");
                    }
                    var espacio = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
                    foreach (DBObject o in trazado)
                    {
                        var e = o as Entity;
                        if (e == null) continue;
                        if (!string.IsNullOrEmpty(capa)) e.Layer = capa;
                        espacio.AppendEntity(e);
                        tr.AddNewlyCreatedDBObject(e, true);
                        creadas.Add(e.Handle.ToString());
                    }
                    tr.Commit();
                }
                catch (SysException)
                {
                    tr.Abort();
                    Liberar(trazado);
                    throw;
                }
            }
            return new JsonObject { ["created"] = creadas, ["loops"] = creadas.Count };
        }

        // ============================================================ MATCHPROP

        private static readonly string[] PropsIgualar = { "layer", "color", "linetype", "linetype_scale", "lineweight", "transparency" };

        /// <summary>params: source (handle), targets[] (handles), [properties] (layer, color, linetype, linetype_scale,
        /// lineweight, transparency; sin lista, todas con SetPropertiesFrom, que también copia estilo de trazado y
        /// visibilidad).</summary>
        public static JsonObject MatchProperties(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var src = Uno(doc, pars["source"], "source");
            var destinos = Ids(doc, pars["targets"], "targets", 1);
            destinos.Remove(src);
            if (destinos.Count == 0) throw new ArgumentException("'targets' no puede ser solo la entidad de origen.");
            var props = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (pars["properties"] is JsonArray pa && pa.Count > 0)
                foreach (var p in pa)
                {
                    string s = p.GetValue<string>();
                    if (!PropsIgualar.Contains(s, StringComparer.OrdinalIgnoreCase))
                        throw new ArgumentException("Propiedad '" + s + "' desconocida. Válidas: " + string.Join(", ", PropsIgualar) + ".");
                    props.Add(s.ToLowerInvariant());
                }
            int hechos = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var o = tr.GetObject(src, OpenMode.ForRead) as Entity;
                    if (o == null) throw new ArgumentException("El origen no es una entidad de dibujo.");
                    foreach (var id in destinos)
                    {
                        var d = tr.GetObject(id, OpenMode.ForWrite) as Entity;
                        if (d == null) throw new ArgumentException("'" + id.Handle + "' no es una entidad de dibujo.");
                        if (props.Count == 0) d.SetPropertiesFrom(o);
                        else
                        {
                            if (props.Contains("layer")) d.Layer = o.Layer;
                            if (props.Contains("color")) d.Color = o.Color;
                            if (props.Contains("linetype")) d.Linetype = o.Linetype;
                            if (props.Contains("linetype_scale")) d.LinetypeScale = o.LinetypeScale;
                            if (props.Contains("lineweight")) d.LineWeight = o.LineWeight;
                            if (props.Contains("transparency")) d.Transparency = o.Transparency;
                        }
                        hechos++;
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó igualar propiedades (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["matched"] = hechos, ["properties"] = props.Count == 0 ? "all" : string.Join(",", props.OrderBy(x => x)) };
        }
    }
}
