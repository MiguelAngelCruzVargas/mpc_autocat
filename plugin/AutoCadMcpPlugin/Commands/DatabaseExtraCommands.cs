using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Operaciones nativas de la base de datos que no son «propiedades de un objeto»:
    /// purgar lo que no se usa, fijar el actual, grupos, datos propios de un objeto (XData y
    /// diccionario de extensión), atributos de bloque y escalas de anotación.
    ///
    /// Todo sale de leer la API descompilada (ver Desktop\Autodesk_descompilado) y se apoya en lo
    /// mismo que el resto: validar ENTERO antes de tocar el dibujo y una sola transacción, de modo
    /// que si algo falla no queda nada a medias. Nada acá escribe archivos ni ejecuta código.
    /// </summary>
    public static class DatabaseExtraCommands
    {
        private const int MaxItems = 500;

        // ------------------------------------------------------------ utilidades

        private static string Texto(JsonObject pars, string clave, bool obligatorio = true)
        {
            string v = pars[clave]?.GetValue<string>();
            if (obligatorio && string.IsNullOrWhiteSpace(v))
                throw new ArgumentException("Falta '" + clave + "'.");
            return v;
        }

        private static ObjectId IdDe(Document doc, string handle)
        {
            return HandleHelper.GetObjectId(doc.Database, handle);
        }

        // ============================================================ PURGAR

        private sealed class InfoPurga
        {
            public string Tabla;
            public string[] Protegidos;
            public string Actual;
        }

        /// <summary>Orden en que se purga: lo que otros usan va primero (un bloque puede ser lo único
        /// que mantiene viva una capa).</summary>
        private static readonly string[] OrdenPurga = { "block", "dimstyle", "textstyle", "linetype", "layer", "regapp", "ucs", "view" };

        private static readonly Dictionary<string, InfoPurga> Purgables = new Dictionary<string, InfoPurga>(StringComparer.OrdinalIgnoreCase)
        {
            { "layer",     new InfoPurga { Tabla = "LayerTableId",     Protegidos = new[] { "0", "Defpoints" }, Actual = "Clayer" } },
            { "textstyle", new InfoPurga { Tabla = "TextStyleTableId", Protegidos = new[] { "Standard" },        Actual = "Textstyle" } },
            { "dimstyle",  new InfoPurga { Tabla = "DimStyleTableId",  Protegidos = new[] { "Standard" },        Actual = "Dimstyle" } },
            { "linetype",  new InfoPurga { Tabla = "LinetypeTableId",  Protegidos = new[] { "ByBlock", "ByLayer", "Continuous" }, Actual = "Celtype" } },
            { "block",     new InfoPurga { Tabla = "BlockTableId",     Protegidos = new string[0],               Actual = null } },
            { "regapp",    new InfoPurga { Tabla = "RegAppTableId",    Protegidos = new[] { "ACAD" },            Actual = null } },
            { "ucs",       new InfoPurga { Tabla = "UcsTableId",       Protegidos = new string[0],               Actual = null } },
            { "view",      new InfoPurga { Tabla = "ViewTableId",      Protegidos = new string[0],               Actual = null } },
        };

        /// <summary>params: [kinds] (layer, textstyle, dimstyle, linetype, block, regapp, ucs, view; sin lista, todos),
        /// [dry_run]. Es el PURGE de AutoCAD: borra lo que el dibujo ya no referencia, y repite hasta que
        /// no quede nada purgable (borrar un bloque libera las capas que usaba). dry_run solo informa lo
        /// purgable en la primera pasada (no puede simular la cascada).</summary>
        public static JsonObject Purge(Document doc, JsonObject pars)
        {
            var pedidos = new List<string>();
            if (pars["kinds"] is JsonArray ks && ks.Count > 0)
            {
                foreach (var k in ks)
                {
                    string kk = k.GetValue<string>();
                    if (!Purgables.ContainsKey(kk))
                        throw new ArgumentException("'" + kk + "' no se puede purgar. Válidos: " + string.Join(", ", Purgables.Keys) + ".");
                    pedidos.Add(kk.ToLowerInvariant());
                }
            }
            else pedidos.AddRange(OrdenPurga);
            var orden = OrdenPurga.Where(pedidos.Contains).ToList();
            bool simulacro = pars["dry_run"]?.GetValue<bool>() ?? false;

            var db = doc.Database;
            var salida = new Dictionary<string, List<string>>();
            int pasadas = 0;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    for (int pasada = 1; pasada <= (simulacro ? 1 : 6); pasada++)
                    {
                        bool alguno = false;
                        foreach (var kind in orden)
                        {
                            var info = Purgables[kind];
                            var tablaId = DatabaseObjectsCommands.TablaPublica(db, info.Tabla);
                            var tabla = (SymbolTable)tr.GetObject(tablaId, OpenMode.ForRead);
                            ObjectId actual = ObjectId.Null;
                            if (info.Actual != null)
                            {
                                var pa = typeof(Database).GetProperty(info.Actual, BindingFlags.Public | BindingFlags.Instance);
                                if (pa != null && pa.GetValue(db) is ObjectId a) actual = a;
                            }
                            var candidatos = new ObjectIdCollection();
                            foreach (ObjectId rid in tabla)
                            {
                                if (rid.IsErased || rid == actual) continue;
                                var rec = tr.GetObject(rid, OpenMode.ForRead) as SymbolTableRecord;
                                if (rec == null) continue;
                                string nombre = rec.Name;
                                if (nombre.StartsWith("*") || info.Protegidos.Any(x => x.Equals(nombre, StringComparison.OrdinalIgnoreCase)))
                                    continue;
                                candidatos.Add(rid);
                            }
                            if (candidatos.Count == 0) continue;
                            db.Purge(candidatos);                  // lo que queda en la lista es purgable
                            foreach (ObjectId pid in candidatos)
                            {
                                var rec = (SymbolTableRecord)tr.GetObject(pid, OpenMode.ForRead);
                                string nombre = rec.Name;
                                if (!simulacro)
                                {
                                    var w = tr.GetObject(pid, OpenMode.ForWrite);
                                    w.Erase(true);
                                }
                                if (!salida.ContainsKey(kind)) salida[kind] = new List<string>();
                                salida[kind].Add(nombre);
                                alguno = true;
                            }
                        }
                        pasadas = pasada;
                        if (!alguno) break;
                    }
                    if (simulacro) tr.Abort(); else tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó la purga (" + ex.ErrorStatus + "): " + ex.Message + ". No se purgó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            var detalle = new JsonObject();
            int total = 0;
            foreach (var kv in salida)
            {
                detalle[kv.Key] = new JsonArray(kv.Value.Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                total += kv.Value.Count;
            }
            return new JsonObject
            {
                ["purged"] = !simulacro, ["dryRun"] = simulacro, ["total"] = total, ["byKind"] = detalle, ["passes"] = pasadas,
                ["note"] = simulacro ? "Solo la primera pasada: al purgar de verdad puede salir más (borrar un bloque libera sus capas)." : null
            };
        }

        // ============================================================ ACTUAL

        /// <summary>params: kind (layer|textstyle|dimstyle|linetype), name.</summary>
        public static JsonObject SetCurrent(Document doc, JsonObject pars)
        {
            string kind = Texto(pars, "kind").ToLowerInvariant();
            string nombre = Texto(pars, "name");
            if (!(kind == "layer" || kind == "textstyle" || kind == "dimstyle" || kind == "linetype"))
                throw new ArgumentException("'kind' es layer, textstyle, dimstyle o linetype.");
            var info = Purgables[kind];
            var db = doc.Database;
            string previo;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var tabla = (SymbolTable)tr.GetObject(DatabaseObjectsCommands.TablaPublica(db, info.Tabla), OpenMode.ForRead);
                    if (!tabla.Has(nombre))
                        throw new ArgumentException("No hay un " + kind + " llamado '" + nombre + "'.");
                    ObjectId id = tabla[nombre];
                    var pa = typeof(Database).GetProperty(info.Actual, BindingFlags.Public | BindingFlags.Instance);
                    var viejo = (ObjectId)pa.GetValue(db);
                    previo = viejo.IsNull ? null : ((SymbolTableRecord)tr.GetObject(viejo, OpenMode.ForRead)).Name;
                    pa.SetValue(db, id);
                    if (kind == "dimstyle")
                    {
                        // El estilo actual de cota también carga sus variables en la base de datos.
                        var rec = (DimStyleTableRecord)tr.GetObject(id, OpenMode.ForRead);
                        db.SetDimstyleData(rec);
                    }
                    tr.Commit();
                }
                catch (TargetInvocationException ex)
                {
                    tr.Abort();
                    var real = ex.InnerException ?? ex;
                    throw new InvalidOperationException("AutoCAD no dejó poner '" + nombre + "' como actual" +
                        (real is AcException ae ? " (" + ae.ErrorStatus + ")" : "") + ": " + real.Message);
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no dejó poner '" + nombre + "' como actual (" + ex.ErrorStatus + "): " + ex.Message +
                        ". Una capa congelada no puede ser la actual.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["kind"] = kind, ["name"] = nombre, ["previous"] = previo };
        }

        // ============================================================ GRUPOS

        private static List<ObjectId> IdsEntidades(Document doc, JsonNode n, string cual, int minimo)
        {
            var a = n as JsonArray;
            if (a == null || a.Count < minimo)
                throw new ArgumentException("'" + cual + "' necesita al menos " + minimo + " handle(s).");
            if (a.Count > 2000)
                throw new ArgumentException("Máximo 2000 entidades por grupo.");
            var ids = new List<ObjectId>();
            foreach (var x in a)
            {
                var id = IdDe(doc, x.GetValue<string>());
                using (var tr = doc.Database.TransactionManager.StartTransaction())
                {
                    if (!(tr.GetObject(id, OpenMode.ForRead) is Entity))
                        throw new ArgumentException("'" + x.GetValue<string>() + "' no es una entidad: un grupo solo agrupa entidades.");
                    tr.Commit();
                }
                if (!ids.Contains(id)) ids.Add(id);
            }
            return ids;
        }

        /// <summary>params: name, handles, [description], [selectable].</summary>
        public static JsonObject GroupCreate(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            DatabaseObjectsCommands.ValidarNombre(nombre);
            var ids = IdsEntidades(doc, pars["handles"], "handles", 1);
            string descripcion = pars["description"]?.GetValue<string>() ?? "";
            bool seleccionable = pars["selectable"]?.GetValue<bool>() ?? true;
            var db = doc.Database;
            string handle;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var dic = (DBDictionary)tr.GetObject(db.GroupDictionaryId, OpenMode.ForWrite);
                    if (dic.Contains(nombre))
                        throw new ArgumentException("Ya existe un grupo llamado '" + nombre + "'.");
                    var g = new Group(descripcion, seleccionable);
                    dic.SetAt(nombre, g);
                    tr.AddNewlyCreatedDBObject(g, true);
                    foreach (var id in ids) g.Append(id);
                    handle = g.ObjectId.Handle.ToString();
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el grupo (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["name"] = nombre, ["handle"] = handle, ["entities"] = ids.Count };
        }

        /// <summary>params: name. Borra el grupo (las entidades quedan).</summary>
        public static JsonObject GroupDelete(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var dic = (DBDictionary)tr.GetObject(db.GroupDictionaryId, OpenMode.ForWrite);
                    if (!dic.Contains(nombre))
                        throw new ArgumentException("No hay un grupo llamado '" + nombre + "'.");
                    var g = (Group)tr.GetObject(dic.GetAt(nombre), OpenMode.ForWrite);
                    g.Erase(true);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD se negó a borrar el grupo (" + ex.ErrorStatus + "): " + ex.Message);
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["deleted"] = true, ["name"] = nombre };
        }

        /// <summary>params: name, [add], [remove], [description], [selectable]. Un solo grupo, atómico.</summary>
        public static JsonObject GroupModify(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            var agregar = pars["add"] != null ? IdsEntidades(doc, pars["add"], "add", 1) : new List<ObjectId>();
            var quitar = pars["remove"] != null ? IdsEntidades(doc, pars["remove"], "remove", 1) : new List<ObjectId>();
            string descripcion = pars["description"]?.GetValue<string>();
            bool? seleccionable = pars["selectable"]?.GetValue<bool>();
            if (agregar.Count == 0 && quitar.Count == 0 && descripcion == null && seleccionable == null)
                throw new ArgumentException("No hay nada que cambiar: pasá 'add', 'remove', 'description' o 'selectable'.");
            var db = doc.Database;
            int total;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var dic = (DBDictionary)tr.GetObject(db.GroupDictionaryId, OpenMode.ForRead);
                    if (!dic.Contains(nombre))
                        throw new ArgumentException("No hay un grupo llamado '" + nombre + "'.");
                    var g = (Group)tr.GetObject(dic.GetAt(nombre), OpenMode.ForWrite);
                    foreach (var id in quitar)
                        if (g.GetIndex(id) >= 0) g.Remove(id);
                    foreach (var id in agregar)
                        if (g.GetIndex(id) < 0) g.Append(id);
                    if (descripcion != null) g.Description = descripcion;
                    if (seleccionable.HasValue) g.Selectable = seleccionable.Value;
                    total = g.NumEntities;
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
            return new JsonObject { ["name"] = nombre, ["entities"] = total };
        }

        // ============================================================ XDATA

        private static readonly Dictionary<int, string> TiposXData = new Dictionary<int, string>
        {
            { 1000, "text" }, { 1003, "layer" }, { 1005, "handle" }, { 1010, "point" }, { 1040, "real" },
            { 1041, "distance" }, { 1042, "scale" }, { 1070, "int16" }, { 1071, "int" },
        };

        private static readonly Dictionary<string, int> CodigosXData = TiposXData.ToDictionary(kv => kv.Value, kv => kv.Key);

        private static double Real(JsonNode n, string cual)
        {
            if (n is JsonValue v && v.TryGetValue<double>(out var d) && !double.IsNaN(d) && !double.IsInfinity(d)) return d;
            throw new ArgumentException(cual + " no es un número.");
        }

        private static Point3d Punto(JsonNode n, string cual)
        {
            var a = n as JsonArray;
            if (a == null || a.Count != 3) throw new ArgumentException(cual + " tiene que ser [x, y, z].");
            return new Point3d(Real(a[0], cual), Real(a[1], cual), Real(a[2], cual));
        }

        /// <summary>Un valor JSON a un TypedValue de XData. Sin tipo explícito: texto -> 1000, entero -> 1071,
        /// decimal -> 1040, true/false -> 1070, [x,y,z] -> 1010. Con tipo: {"layer": "MUROS"}, {"int16": 3}...</summary>
        internal static TypedValue ValorXData(JsonNode n)
        {
            if (n is JsonObject o)
            {
                if (o.Count != 1) throw new ArgumentException("Un valor con tipo tiene un solo campo: {\"text\": \"...\"}.");
                var kv = o.First();
                if (!CodigosXData.TryGetValue(kv.Key, out int cod))
                    throw new ArgumentException("Tipo '" + kv.Key + "' desconocido. Válidos: " + string.Join(", ", CodigosXData.Keys) + ".");
                return Convertir(cod, kv.Value);
            }
            if (n is JsonArray) return Convertir(1010, n);
            if (n is JsonValue v)
            {
                if (v.TryGetValue<string>(out _)) return Convertir(1000, n);
                if (v.TryGetValue<bool>(out var b)) return new TypedValue(1070, (short)(b ? 1 : 0));
                if (v.TryGetValue<int>(out _)) return Convertir(1071, n);
                if (v.TryGetValue<double>(out _)) return Convertir(1040, n);
            }
            throw new ArgumentException("Valor no soportado: " + (n?.ToJsonString() ?? "null"));
        }

        private static TypedValue Convertir(int cod, JsonNode n)
        {
            switch (cod)
            {
                case 1000:
                case 1003:
                case 1005:
                    {
                        string s = n is JsonValue v && v.TryGetValue<string>(out var t) ? t : null;
                        if (s == null) throw new ArgumentException("Se esperaba texto.");
                        if (s.Length > 255) throw new ArgumentException("Un texto de XData no puede pasar de 255 caracteres.");
                        if (cod == 1005 && !System.Text.RegularExpressions.Regex.IsMatch(s, "^[0-9A-Fa-f]{1,16}$"))
                            throw new ArgumentException("Un handle es hexadecimal.");
                        return new TypedValue(cod, s);
                    }
                case 1010: return new TypedValue(cod, Punto(n, "point"));
                case 1040:
                case 1041:
                case 1042: return new TypedValue(cod, Real(n, "real"));
                case 1070:
                    {
                        double d = Real(n, "int16");
                        if (d != Math.Floor(d) || d < short.MinValue || d > short.MaxValue) throw new ArgumentException("int16 fuera de rango.");
                        return new TypedValue(cod, (short)d);
                    }
                case 1071:
                    {
                        double d = Real(n, "int");
                        if (d != Math.Floor(d) || d < int.MinValue || d > int.MaxValue) throw new ArgumentException("int fuera de rango.");
                        return new TypedValue(cod, (int)d);
                    }
            }
            throw new ArgumentException("Código " + cod + " no soportado.");
        }

        private static JsonNode DeTypedValue(TypedValue tv, Dictionary<int, string> tipos)
        {
            var o = new JsonObject { ["code"] = tv.TypeCode };
            if (tipos.TryGetValue(tv.TypeCode, out var nombre)) o["type"] = nombre;
            o["value"] = PropertiesCommands.AJson(tv.Value is Handle h ? (object)h.ToString() : tv.Value);
            return o;
        }

        private static void ValidarApp(string app)
        {
            DatabaseObjectsCommands.ValidarNombre(app);
            if (app.Length > 31) throw new ArgumentException("El nombre de aplicación de XData no puede pasar de 31 caracteres.");
            if (app.Equals("ACAD", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("ACAD es una aplicación de AutoCAD: no se escribe.");
        }

        /// <summary>params: handle, [app]. Sin app: todas.</summary>
        public static JsonObject XDataGet(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            string app = Texto(pars, "app", false);
            var salida = new JsonObject();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var obj = tr.GetObject(id, OpenMode.ForRead);
                ResultBuffer rb = null;
                try
                {
                    rb = string.IsNullOrWhiteSpace(app) ? obj.XData : obj.GetXDataForApplication(app);
                    if (rb != null)
                    {
                        string actual = null; JsonArray valores = null;
                        foreach (var tv in rb)
                        {
                            if (tv.TypeCode == 1001)
                            {
                                actual = tv.Value as string;
                                valores = new JsonArray();
                                salida[actual] = valores;
                                continue;
                            }
                            valores?.Add(DeTypedValue(tv, TiposXData));
                        }
                    }
                }
                finally { rb?.Dispose(); }
                tr.Commit();
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["apps"] = salida, ["count"] = salida.Count };
        }

        /// <summary>params: handle, app, values.</summary>
        public static JsonObject XDataSet(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            string app = Texto(pars, "app");
            ValidarApp(app);
            var arr = pars["values"] as JsonArray;
            if (arr == null || arr.Count == 0) throw new ArgumentException("Falta 'values': una lista con al menos un valor.");
            if (arr.Count > 200) throw new ArgumentException("Máximo 200 valores de XData por aplicación.");
            var tvs = new List<TypedValue> { new TypedValue(1001, app) };
            foreach (var n in arr) tvs.Add(ValorXData(n));
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    AsegurarApp(tr, db, app);
                    var obj = tr.GetObject(id, OpenMode.ForWrite);
                    using (var rb = new ResultBuffer(tvs.ToArray()))
                        obj.XData = rb;
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el XData (" + ex.ErrorStatus + "): " + ex.Message +
                        ". Puede ser una capa bloqueada o demasiados datos (el límite es 16 KB por objeto). No se modificó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["app"] = app, ["values"] = arr.Count };
        }

        private static void AsegurarApp(Transaction tr, Database db, string app)
        {
            var rat = (RegAppTable)tr.GetObject(db.RegAppTableId, OpenMode.ForRead);
            if (rat.Has(app)) return;
            rat.UpgradeOpen();
            var rec = new RegAppTableRecord { Name = app };
            rat.Add(rec);
            tr.AddNewlyCreatedDBObject(rec, true);
        }

        /// <summary>params: handle, app.</summary>
        public static JsonObject XDataClear(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            string app = Texto(pars, "app");
            ValidarApp(app);
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                try
                {
                    var obj = tr.GetObject(id, OpenMode.ForWrite);
                    using (var rb = new ResultBuffer(new TypedValue(1001, app)))
                        obj.XData = rb;               // solo el nombre de la app: borra sus datos
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el borrado (" + ex.ErrorStatus + "): " + ex.Message);
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["app"] = app, ["cleared"] = true };
        }

        // ============================================================ DATOS PROPIOS (Xrecord)

        private static readonly Dictionary<int, string> TiposXrecord = new Dictionary<int, string>
        {
            { 1, "text" }, { 10, "point" }, { 40, "real" }, { 70, "int16" }, { 90, "int" }, { 290, "bool" },
        };

        internal static TypedValue ValorXrecord(JsonNode n)
        {
            if (n is JsonObject o)
            {
                if (o.Count != 1) throw new ArgumentException("Un valor con tipo tiene un solo campo.");
                var kv = o.First();
                switch (kv.Key)
                {
                    case "text": return ValorXrecord(JsonValue.Create(kv.Value?.GetValue<string>() ?? throw new ArgumentException("text es un texto.")));
                    case "real": return new TypedValue(40, Real(kv.Value, "real"));
                    case "int": return new TypedValue(90, (int)Real(kv.Value, "int"));
                    case "int16": return new TypedValue(70, (short)Real(kv.Value, "int16"));
                    case "bool": return new TypedValue(290, kv.Value.GetValue<bool>());
                    case "point": return new TypedValue(10, Punto(kv.Value, "point"));
                }
                throw new ArgumentException("Tipo '" + kv.Key + "' desconocido (text, real, int, int16, bool, point).");
            }
            if (n is JsonArray) return new TypedValue(10, Punto(n, "point"));
            if (n is JsonValue v)
            {
                if (v.TryGetValue<string>(out var s))
                {
                    if (s.Length > 4000) throw new ArgumentException("Un texto no puede pasar de 4000 caracteres.");
                    return new TypedValue(1, s);
                }
                if (v.TryGetValue<bool>(out var b)) return new TypedValue(290, b);
                if (v.TryGetValue<int>(out var i)) return new TypedValue(90, i);
                if (v.TryGetValue<double>(out var d) && !double.IsNaN(d) && !double.IsInfinity(d)) return new TypedValue(40, d);
            }
            throw new ArgumentException("Valor no soportado: " + (n?.ToJsonString() ?? "null"));
        }

        private static void ValidarClave(string clave)
        {
            DatabaseObjectsCommands.ValidarNombre(clave);
        }

        /// <summary>params: handle, [key].</summary>
        public static JsonObject CustomGet(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            string clave = Texto(pars, "key", false);
            var salida = new JsonObject();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var obj = tr.GetObject(id, OpenMode.ForRead);
                if (!obj.ExtensionDictionary.IsNull)
                {
                    var dic = (DBDictionary)tr.GetObject(obj.ExtensionDictionary, OpenMode.ForRead);
                    foreach (DBDictionaryEntry e in dic)
                    {
                        if (!string.IsNullOrWhiteSpace(clave) && !clave.Equals(e.Key, StringComparison.OrdinalIgnoreCase)) continue;
                        var xr = tr.GetObject(e.Value, OpenMode.ForRead) as Xrecord;
                        if (xr == null) continue;
                        var valores = new JsonArray();
                        using (var rb = xr.Data)
                            if (rb != null)
                                foreach (var tv in rb) valores.Add(DeTypedValue(tv, TiposXrecord));
                        salida[e.Key] = valores;
                    }
                }
                tr.Commit();
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["data"] = salida, ["count"] = salida.Count };
        }

        /// <summary>params: handle, key, values.</summary>
        public static JsonObject CustomSet(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            string clave = Texto(pars, "key");
            ValidarClave(clave);
            var arr = pars["values"] as JsonArray;
            if (arr == null || arr.Count == 0) throw new ArgumentException("Falta 'values': una lista con al menos un valor.");
            if (arr.Count > 1000) throw new ArgumentException("Máximo 1000 valores por clave.");
            var tvs = arr.Select(ValorXrecord).ToArray();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                try
                {
                    var obj = tr.GetObject(id, OpenMode.ForWrite);
                    if (obj.ExtensionDictionary.IsNull) obj.CreateExtensionDictionary();
                    var dic = (DBDictionary)tr.GetObject(obj.ExtensionDictionary, OpenMode.ForWrite);
                    var xr = new Xrecord();
                    xr.Data = new ResultBuffer(tvs);
                    dic.SetAt(clave, xr);
                    tr.AddNewlyCreatedDBObject(xr, true);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el dato (" + ex.ErrorStatus + "): " + ex.Message + ". No se modificó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["key"] = clave, ["values"] = tvs.Length };
        }

        /// <summary>params: handle, key.</summary>
        public static JsonObject CustomDelete(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            string clave = Texto(pars, "key");
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                try
                {
                    var obj = tr.GetObject(id, OpenMode.ForRead);
                    if (obj.ExtensionDictionary.IsNull)
                        throw new ArgumentException("Ese objeto no tiene datos propios.");
                    var dic = (DBDictionary)tr.GetObject(obj.ExtensionDictionary, OpenMode.ForWrite);
                    if (!dic.Contains(clave))
                        throw new ArgumentException("No hay un dato con la clave '" + clave + "'.");
                    var xr = tr.GetObject(dic.GetAt(clave), OpenMode.ForWrite);
                    xr.Erase(true);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el borrado (" + ex.ErrorStatus + "): " + ex.Message);
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["key"] = clave, ["deleted"] = true };
        }

        // ============================================================ ATRIBUTOS DE BLOQUE

        /// <summary>params: handle de una referencia de bloque.</summary>
        public static JsonObject AttributesGet(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            var items = new JsonArray();
            string bloque;
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                if (br == null) throw new ArgumentException("Ese handle no es una referencia de bloque.");
                var btr = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForRead);
                bloque = btr.Name;
                foreach (ObjectId aid in br.AttributeCollection)
                {
                    var ar = (AttributeReference)tr.GetObject(aid, OpenMode.ForRead);
                    items.Add(new JsonObject
                    {
                        ["tag"] = ar.Tag, ["text"] = ar.TextString, ["handle"] = aid.Handle.ToString(),
                        ["invisible"] = ar.Invisible, ["position"] = PropertiesCommands.AJson(ar.Position),
                    });
                }
                tr.Commit();
            }
            return new JsonObject { ["handle"] = id.Handle.ToString(), ["block"] = bloque, ["attributes"] = items, ["count"] = items.Count };
        }

        /// <summary>params: handle, values {TAG: texto}. Valida todas las etiquetas antes de escribir.</summary>
        public static JsonObject AttributesSet(Document doc, JsonObject pars)
        {
            var id = IdDe(doc, Texto(pars, "handle"));
            var pedidos = pars["values"] as JsonObject;
            if (pedidos == null || pedidos.Count == 0)
                throw new ArgumentException("Falta 'values': un objeto {ETIQUETA: texto}.");
            if (pedidos.Count > 100) throw new ArgumentException("Máximo 100 atributos por llamada.");
            var cambios = new JsonObject();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                try
                {
                    var br = tr.GetObject(id, OpenMode.ForRead) as BlockReference;
                    if (br == null) throw new ArgumentException("Ese handle no es una referencia de bloque.");
                    var porTag = new Dictionary<string, ObjectId>(StringComparer.OrdinalIgnoreCase);
                    foreach (ObjectId aid in br.AttributeCollection)
                    {
                        var ar = (AttributeReference)tr.GetObject(aid, OpenMode.ForRead);
                        porTag[ar.Tag] = aid;
                    }
                    foreach (var kv in pedidos)
                        if (!porTag.ContainsKey(kv.Key))
                            throw new ArgumentException("El bloque no tiene un atributo '" + kv.Key + "'. Tiene: " +
                                (porTag.Count == 0 ? "(ninguno)" : string.Join(", ", porTag.Keys)) + ".");
                    foreach (var kv in pedidos)
                    {
                        string nuevo = kv.Value is JsonValue v && v.TryGetValue<string>(out var s) ? s : kv.Value?.ToJsonString();
                        if (nuevo == null) throw new ArgumentException("El valor de '" + kv.Key + "' no puede ser null.");
                        var ar = (AttributeReference)tr.GetObject(porTag[kv.Key], OpenMode.ForWrite);
                        string antes = ar.TextString;
                        ar.TextString = nuevo;
                        cambios[ar.Tag] = new JsonObject { ["before"] = antes, ["after"] = ar.TextString };
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

        // ============================================================ ESCALAS DE ANOTACIÓN

        private static ObjectContextCollection Escalas(Database db)
        {
            var occ = db.ObjectContextManager.GetContextCollection("ACDB_ANNOTATIONSCALES");
            if (occ == null) throw new InvalidOperationException("Este dibujo no tiene la colección de escalas de anotación.");
            return occ;
        }

        private static JsonObject DeEscala(AnnotationScale s, string actual)
        {
            return new JsonObject
            {
                ["name"] = s.Name, ["paperUnits"] = s.PaperUnits, ["drawingUnits"] = s.DrawingUnits,
                ["scale"] = s.Scale, ["current"] = s.Name == actual
            };
        }

        public static JsonObject ScalesList(Document doc, JsonObject pars)
        {
            var occ = Escalas(doc.Database);
            string actual = occ.CurrentContext?.Name;
            var items = new JsonArray();
            foreach (ObjectContext ctx in occ)
                if (ctx is AnnotationScale s) items.Add(DeEscala(s, actual));
            return new JsonObject { ["scales"] = items, ["count"] = items.Count, ["current"] = actual };
        }

        /// <summary>params: name, paper_units, drawing_units (p.ej. 1 y 50 para 1:50).</summary>
        public static JsonObject ScaleAdd(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            if (nombre.Length > 255) throw new ArgumentException("'name' no puede pasar de 255 caracteres.");
            double papel = Real(pars["paper_units"], "paper_units");
            double dibujo = Real(pars["drawing_units"], "drawing_units");
            if (papel <= 0 || dibujo <= 0) throw new ArgumentException("paper_units y drawing_units tienen que ser > 0.");
            var occ = Escalas(doc.Database);
            if (occ.HasContext(nombre)) throw new ArgumentException("Ya existe una escala llamada '" + nombre + "'.");
            try
            {
                var sc = new AnnotationScale { Name = nombre, PaperUnits = papel, DrawingUnits = dibujo };
                occ.AddContext(sc);
                return new JsonObject { ["added"] = DeEscala(sc, occ.CurrentContext?.Name) };
            }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD rechazó la escala (" + ex.ErrorStatus + "): " + ex.Message);
            }
        }

        /// <summary>params: name.</summary>
        public static JsonObject ScaleSetCurrent(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            var occ = Escalas(doc.Database);
            if (!occ.HasContext(nombre)) throw new ArgumentException("No hay una escala llamada '" + nombre + "'.");
            string previa = occ.CurrentContext?.Name;
            try { occ.CurrentContext = occ.GetContext(nombre); }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD no dejó poner '" + nombre + "' como escala actual (" + ex.ErrorStatus + "): " + ex.Message);
            }
            return new JsonObject { ["current"] = nombre, ["previous"] = previa };
        }

        /// <summary>params: name. No se borra la actual ni la que usan objetos (AutoCAD se niega).</summary>
        public static JsonObject ScaleRemove(Document doc, JsonObject pars)
        {
            string nombre = Texto(pars, "name");
            var occ = Escalas(doc.Database);
            if (!occ.HasContext(nombre)) throw new ArgumentException("No hay una escala llamada '" + nombre + "'.");
            if (occ.CurrentContext?.Name == nombre)
                throw new InvalidOperationException("'" + nombre + "' es la escala ACTUAL: poné otra antes de borrarla.");
            try { occ.RemoveContext(nombre); }
            catch (AcException ex)
            {
                throw new InvalidOperationException("AutoCAD se negó a borrar la escala (" + ex.ErrorStatus + "): " + ex.Message +
                    ". Suele ser que hay objetos anotativos que la usan.");
            }
            return new JsonObject { ["removed"] = nombre };
        }
    }
}
