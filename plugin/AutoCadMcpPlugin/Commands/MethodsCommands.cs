using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Métodos de instancia de los objetos del dibujo, por reflexión: la otra
    /// mitad de la API (las propiedades están en PropertiesCommands). Curve
    /// tiene GetOffsetCurves, GetSplitCurves, GetClosestPointTo, IntersectWith,
    /// GetPointAtParameter, Extend, TransformBy, Explode...: cientos de
    /// operaciones geométricas que resuelve AutoCAD y que no hay que
    /// reescribir.
    ///
    /// Qué se permite (y qué no). Lista BLANCA de forma, lista negra de
    /// nombres: solo métodos PÚBLICOS DE INSTANCIA declarados por la API de
    /// AutoCAD (nunca los de System.Object), no genéricos, cuyos parámetros
    /// sean de tipos simples (números, texto, booleanos, puntos, vectores,
    /// escalas, enumeraciones) o un objeto del dibujo dado por su handle; sin
    /// parámetros que parezcan rutas o direcciones; sin los del ciclo de vida
    /// del objeto (Dispose, Close, Open, UpgradeOpen, SwapIdWith...) ni los que
    /// guardan, exportan, cargan o ejecutan. No se llama a nada estático.
    ///
    /// Lo que devuelve un método y no pertenece al dibujo todavía (las curvas
    /// de GetOffsetCurves, los pedazos de GetSplitCurves) se descarta, salvo
    /// que se pida add_results_to_space: entonces se agregan al espacio activo y
    /// se devuelven sus handles. Todo en UNA transacción.
    /// </summary>
    public static class MethodsCommands
    {
        private const int MaxResultados = 500;

        /// <summary>Ciclo de vida del objeto y cosas que no son operaciones del dibujo.</summary>
        private static readonly HashSet<string> Prohibidos = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Dispose", "Close", "Cancel", "Open", "UpgradeOpen", "DowngradeOpen", "DowngradeToNotify",
            "SwapIdWith", "SwapReferences", "HandOverTo", "DeepClone", "WblockClone", "AssertReadEnabled",
            "AssertWriteEnabled", "AssertNotifyEnabled", "CloseAndDiscard", "CloseAndSave",
            "SetXmlStream", "GetXmlStream", "SaveAs", "Save", "ReleaseFromProxy"
        };

        /// <summary>Operaciones que guardan, exportan, cargan o ejecutan.</summary>
        private static readonly Regex NombresPeligrosos = new Regex(
            @"^(Save|Export|DxfOut|DxfIn|DwgOut|Plot|Publish|Load|Unload|Download|Upload|Execute|Invoke|StartProcess|Shell|Detach|Attach|Reload|Print)\w*$",
            RegexOptions.IgnoreCase | RegexOptions.Compiled);

        /// <summary>Parámetros que parecen rutas o direcciones.</summary>
        private static readonly Regex ParametrosPeligrosos = new Regex(
            @"(file|path|url|uri|folder|directory|dir$|command|script|assembly)",
            RegexOptions.IgnoreCase | RegexOptions.Compiled);

        /// <summary>Prefijos que indican que el método solo lee.</summary>
        private static readonly Regex Lectura = new Regex(
            @"^(Get|Is|Has|Can|Contains|Compare|Find|Intersect|Closest|Distance|Length|Equals|Check|Test|Hit|Compute|Calculate|Measure|To(?!ggle))",
            RegexOptions.Compiled);

        // ------------------------------------------------------------ reflexión

        private static bool EsObjetoDibujo(Type t)
        {
            return typeof(DBObject).IsAssignableFrom(t);
        }

        /// <summary>Tipo de entrada permitido.</summary>
        private static bool ParametroSoportado(Type t)
        {
            t = Nullable.GetUnderlyingType(t) ?? t;
            return PropertiesCommands.Soportado(t) || EsObjetoDibujo(t);
        }

        /// <summary>Parámetros que NO se piden: el marcador gráfico (IntPtr, se pasa 0) y las
        /// colecciones vacías donde el método deja su resultado (IntersectWith, por ejemplo,
        /// recibe un Point3dCollection para llenarlo). Se crean solas y se devuelven en 'out'.</summary>
        private static bool EsImplicito(ParameterInfo p)
        {
            var t = p.ParameterType.IsByRef ? p.ParameterType.GetElementType() : p.ParameterType;
            return t == typeof(IntPtr) || (!p.IsOut && EsColeccionSalida(t));
        }

        private static bool EsEntrada(ParameterInfo p)
        {
            return !p.IsOut && !EsImplicito(p);
        }

        /// <summary>Colecciones que el método recibe (no 'out'): GetSplitCurves(puntos) las usa de
        /// ENTRADA y IntersectWith(...) de SALIDA. La reflexión no distingue los dos casos, así
        /// que se aceptan como argumentos EXTRA opcionales al final: sin ellos viajan vacías
        /// (salida); con ellos se llenan con lo que se mandó (entrada) y vuelven igual en 'out'.</summary>
        private static int ColeccionesImplicitas(MethodInfo m)
        {
            return m.GetParameters().Count(p => !p.IsOut && p.ParameterType != typeof(IntPtr) && EsImplicito(p));
        }

        private static object ColeccionDesde(Type t, JsonNode n, string nombre)
        {
            var a = n as JsonArray;
            if (a == null) throw new ArgumentException(nombre + " tiene que ser una lista.");
            if (t == typeof(Point3dCollection))
            {
                var c = new Point3dCollection();
                foreach (var x in a) c.Add((Point3d)PropertiesCommands.DeJson(typeof(Point3d), x, nombre));
                return c;
            }
            if (t == typeof(Point2dCollection))
            {
                var c = new Point2dCollection();
                foreach (var x in a) c.Add((Point2d)PropertiesCommands.DeJson(typeof(Point2d), x, nombre));
                return c;
            }
            if (t == typeof(DoubleCollection))
            {
                var c = new DoubleCollection();
                foreach (var x in a) c.Add((double)PropertiesCommands.DeJson(typeof(double), x, nombre));
                return c;
            }
            if (t == typeof(ObjectIdCollection))
                throw new ArgumentException(nombre + ": no se aceptan colecciones de handles como entrada.");
            throw new ArgumentException(nombre + ": colección no soportada.");
        }

        private static bool EsColeccionSalida(Type t)
        {
            return t == typeof(DBObjectCollection) || t == typeof(Point3dCollection)
                || t == typeof(DoubleCollection) || t == typeof(ObjectIdCollection)
                || t == typeof(Point2dCollection);
        }

        private static bool SalidaSoportada(Type t)
        {
            t = Nullable.GetUnderlyingType(t) ?? t;
            if (t == typeof(void)) return true;
            if (t.IsByRef) t = t.GetElementType();
            return PropertiesCommands.Soportado(t) || EsColeccionSalida(t) || EsObjetoDibujo(t);
        }

        private static bool Permitido(MethodInfo m)
        {
            if (m.IsSpecialName || m.IsGenericMethod || m.IsStatic) return false;
            var ns = m.DeclaringType?.Namespace ?? "";
            if (!ns.StartsWith("Autodesk.AutoCAD", StringComparison.Ordinal)) return false;
            if (Prohibidos.Contains(m.Name) || NombresPeligrosos.IsMatch(m.Name)) return false;
            foreach (var p in m.GetParameters())
            {
                var t = p.ParameterType.IsByRef ? p.ParameterType.GetElementType() : p.ParameterType;
                if (ParametrosPeligrosos.IsMatch(p.Name ?? "")) return false;
                if (EsImplicito(p) && !p.ParameterType.IsByRef) continue;
                if (p.IsOut)
                {
                    if (!SalidaSoportada(t)) return false;
                }
                else if (p.ParameterType.IsByRef) return false;       // ref: no se maneja
                else if (!ParametroSoportado(t)) return false;
            }
            return SalidaSoportada(m.ReturnType);
        }

        private static MethodInfo[] Metodos(Type t)
        {
            return t.GetMethods(BindingFlags.Public | BindingFlags.Instance)
                .Where(Permitido)
                .OrderBy(m => m.Name, StringComparer.Ordinal)
                .ThenBy(m => m.GetParameters().Length)
                .ToArray();
        }

        private static bool EsDeLectura(MethodInfo m)
        {
            return Lectura.IsMatch(m.Name);
        }

        private static string NombreTipo(Type t)
        {
            if (t.IsByRef) t = t.GetElementType();
            t = Nullable.GetUnderlyingType(t) ?? t;
            return t.Name;
        }

        // ------------------------------------------------------------ listar

        /// <summary>params: handle | type (clase de DatabaseServices), [filter] (texto en el nombre).</summary>
        public static JsonObject List(Document doc, JsonObject pars)
        {
            Type t;
            string tipoPedido = pars["type"]?.GetValue<string>();
            if (pars["handle"] != null)
            {
                var id = HandleHelper.GetObjectId(doc.Database, pars["handle"].GetValue<string>());
                using (var tr = doc.Database.TransactionManager.StartTransaction())
                {
                    t = tr.GetObject(id, OpenMode.ForRead).GetType();
                    tr.Commit();
                }
            }
            else if (!string.IsNullOrWhiteSpace(tipoPedido))
            {
                t = typeof(Entity).Assembly.GetType("Autodesk.AutoCAD.DatabaseServices." + tipoPedido, false, true);
                if (t == null)
                    throw new ArgumentException("No existe la clase '" + tipoPedido + "' en DatabaseServices.");
            }
            else
                throw new ArgumentException("Falta 'handle' o 'type'.");

            string filtro = pars["filter"]?.GetValue<string>();
            var todos = t.GetMethods(BindingFlags.Public | BindingFlags.Instance).Where(m => !m.IsSpecialName).ToArray();
            var lista = new JsonArray();
            foreach (var m in Metodos(t))
            {
                if (!string.IsNullOrEmpty(filtro) && m.Name.IndexOf(filtro, StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                var ps = new JsonArray();
                foreach (var p in m.GetParameters())
                {
                    var pt = p.ParameterType.IsByRef ? p.ParameterType.GetElementType() : p.ParameterType;
                    if (pt == typeof(IntPtr)) continue;            // se pasa 0 solo
                    var po = new JsonObject { ["name"] = p.Name, ["type"] = NombreTipo(pt), ["out"] = p.IsOut || EsImplicito(p) };
                    var tn = Nullable.GetUnderlyingType(pt) ?? pt;
                    if (tn.IsEnum) po["values"] = new JsonArray(Enum.GetNames(tn).Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                    if (EsObjetoDibujo(tn)) po["type"] = NombreTipo(pt) + " (handle)";
                    ps.Add(po);
                }
                lista.Add(new JsonObject
                {
                    ["name"] = m.Name,
                    ["parameters"] = ps,
                    ["returns"] = NombreTipo(m.ReturnType),
                    ["mode"] = EsDeLectura(m) ? "read" : "write",
                    ["declaredIn"] = m.DeclaringType?.Name,
                });
            }
            return new JsonObject
            {
                ["type"] = t.Name,
                ["supported"] = lista.Count,
                ["totalPublicMethods"] = todos.Length,
                ["methods"] = lista,
                ["note"] = "Solo aparecen los métodos con parámetros simples, sin rutas ni ciclo de vida. 'mode' dice si se abre en lectura o en escritura."
            };
        }

        // ------------------------------------------------------------ invocar

        private static object Salida(Type t)
        {
            if (t.IsValueType) return Activator.CreateInstance(t);
            return Activator.CreateInstance(t);
        }

        private static JsonNode Valor(object v, List<Entity> nuevas, Document doc)
        {
            if (v == null) return null;
            if (v is Point3dCollection p3)
                return new JsonArray(p3.Cast<Point3d>().Take(MaxResultados).Select(p => (JsonNode)new JsonArray(p.X, p.Y, p.Z)).ToArray());
            if (v is Point2dCollection p2)
                return new JsonArray(p2.Cast<Point2d>().Take(MaxResultados).Select(p => (JsonNode)new JsonArray(p.X, p.Y)).ToArray());
            if (v is DoubleCollection dc)
                return new JsonArray(dc.Cast<double>().Take(MaxResultados).Select(d => (JsonNode)JsonValue.Create(d)).ToArray());
            if (v is ObjectIdCollection oc)
                return new JsonArray(oc.Cast<ObjectId>().Take(MaxResultados).Select(i => (JsonNode)JsonValue.Create(i.Handle.ToString())).ToArray());
            if (v is DBObjectCollection col)
            {
                foreach (DBObject o in col)
                {
                    if (o is Entity e && nuevas.Count < MaxResultados) nuevas.Add(e);
                    else o.Dispose();
                }
                return JsonValue.Create("objetos: " + col.Count);
            }
            if (v is Entity ent && !ent.ObjectId.IsValid) { nuevas.Add(ent); return JsonValue.Create("entidad nueva (" + ent.GetType().Name + ")"); }
            if (v is DBObject dbo) return JsonValue.Create(dbo.ObjectId.IsValid ? dbo.ObjectId.Handle.ToString() : dbo.GetType().Name);
            return PropertiesCommands.AJson(v);
        }

        /// <summary>params: handle, method, [args], [add_results_to_space], [mode: read|write].</summary>
        public static JsonObject Call(Document doc, JsonObject pars)
        {
            string handle = pars["handle"]?.GetValue<string>();
            string nombre = pars["method"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(handle)) throw new ArgumentException("Falta 'handle'.");
            if (string.IsNullOrWhiteSpace(nombre)) throw new ArgumentException("Falta 'method'.");
            var args = pars["args"] as JsonArray ?? new JsonArray();
            bool agregar = pars["add_results_to_space"]?.GetValue<bool>() ?? false;
            string modoPedido = pars["mode"]?.GetValue<string>();
            if (modoPedido != null && modoPedido != "read" && modoPedido != "write")
                throw new ArgumentException("'mode' es 'read' o 'write'.");

            var db = doc.Database;
            var id = HandleHelper.GetObjectId(db, handle);
            var salida = new JsonObject();
            var nuevas = new List<Entity>();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var objeto0 = tr.GetObject(id, OpenMode.ForRead);
                    var tipo = objeto0.GetType();
                    var candidatos = Metodos(tipo)
                        .Where(m => m.Name.Equals(nombre, StringComparison.OrdinalIgnoreCase)
                                    && args.Count >= m.GetParameters().Count(EsEntrada)
                                && args.Count <= m.GetParameters().Count(EsEntrada) + ColeccionesImplicitas(m))
                        .ToArray();
                    if (candidatos.Length == 0)
                    {
                        bool existe = tipo.GetMethods(BindingFlags.Public | BindingFlags.Instance)
                            .Any(m => m.Name.Equals(nombre, StringComparison.OrdinalIgnoreCase));
                        throw new ArgumentException(existe
                            ? "El método '" + nombre + "' de " + tipo.Name + " no se admite con " + args.Count +
                              " argumento(s): o no existe esa sobrecarga, o usa tipos que esta capa no maneja, o está prohibido. Mirá list_object_methods."
                            : "El tipo " + tipo.Name + " no tiene un método '" + nombre + "'. Mirá list_object_methods.");
                    }

                    // Se elige la primera sobrecarga cuyos argumentos convierten bien.
                    MethodInfo elegido = null; object[] valores = null; string ultimoError = null;
                    Dictionary<int, ObjectId> objetosArg = null;
                    foreach (var m in candidatos)
                    {
                        try
                        {
                            var ps = m.GetParameters();
                            var v = new object[ps.Length];
                            int k = 0;
                            int entradas = ps.Count(EsEntrada);
                            int extra = entradas;       // desde acá los argumentos son colecciones de entrada
                            var ids = new Dictionary<int, ObjectId>();
                            for (int i = 0; i < ps.Length; i++)
                            {
                                var pt = ps[i].ParameterType.IsByRef ? ps[i].ParameterType.GetElementType() : ps[i].ParameterType;
                                if (pt == typeof(IntPtr)) { v[i] = IntPtr.Zero; continue; }
                                if (ps[i].IsOut) { v[i] = Salida(pt); continue; }
                                if (EsImplicito(ps[i]))
                                {
                                    v[i] = extra < args.Count
                                        ? ColeccionDesde(pt, args[extra++], ps[i].Name)
                                        : Salida(pt);
                                    continue;
                                }
                                var arg = args[k++];
                                if (EsObjetoDibujo(pt))
                                {
                                    var oid = HandleHelper.GetObjectId(db, arg.GetValue<string>());
                                    var o = tr.GetObject(oid, OpenMode.ForRead);
                                    if (!pt.IsAssignableFrom(o.GetType()))
                                        throw new ArgumentException(ps[i].Name + " tiene que ser un " + pt.Name + ", y el handle es un " + o.GetType().Name + ".");
                                    v[i] = o;
                                    ids[i] = oid;
                                }
                                else v[i] = PropertiesCommands.DeJson(pt, arg, ps[i].Name);
                            }
                            elegido = m; valores = v; objetosArg = ids; break;
                        }
                        catch (SysException ex) when (ex is ArgumentException || ex is InvalidOperationException || ex is FormatException || ex is InvalidCastException)
                        { ultimoError = ex.Message; }
                    }
                    if (elegido == null)
                        throw new ArgumentException("Los argumentos no sirven para ninguna sobrecarga de '" + nombre + "': " + ultimoError);

                    bool escribe = modoPedido != null ? modoPedido == "write" : !EsDeLectura(elegido);
                    var objeto = escribe ? tr.GetObject(id, OpenMode.ForWrite) : objeto0;
                    // Los objetos que van como ARGUMENTO se abren en escritura si el método escribe:
                    // BooleanOperation consume al otro sólido, ImprintEntity lo modifica... Pasarlo
                    // abierto en lectura NO lanza una excepción: AutoCAD se cae (probado en vivo).
                    if (escribe)
                        foreach (var kv in objetosArg)
                            valores[kv.Key] = tr.GetObject(kv.Value, OpenMode.ForWrite);

                    object resultado;
                    try { resultado = elegido.Invoke(objeto, valores); }
                    catch (TargetInvocationException ex) { throw ex.InnerException ?? ex; }

                    var o2 = new JsonObject { ["type"] = tipo.Name, ["method"] = elegido.Name, ["mode"] = escribe ? "write" : "read" };
                    o2["result"] = elegido.ReturnType == typeof(void) ? null : Valor(resultado, nuevas, doc);
                    var outs = new JsonObject();
                    var pinfo = elegido.GetParameters();
                    for (int i = 0; i < pinfo.Length; i++)
                        if (pinfo[i].IsOut || (EsImplicito(pinfo[i]) && !(valores[i] is IntPtr)))
                            outs[pinfo[i].Name] = Valor(valores[i], nuevas, doc);
                    if (outs.Count > 0) o2["out"] = outs;

                    // Lo nuevo que devolvió el método: al dibujo o a la basura.
                    var creadas = new JsonArray();
                    if (nuevas.Count > 0)
                    {
                        if (agregar)
                        {
                            var btr = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
                            foreach (var e in nuevas)
                            {
                                btr.AppendEntity(e);
                                tr.AddNewlyCreatedDBObject(e, true);
                                creadas.Add(new JsonObject { ["handle"] = e.Handle.ToString(), ["type"] = e.GetType().Name, ["layer"] = e.Layer });
                            }
                            escribe = true;
                        }
                        else
                        {
                            foreach (var e in nuevas) { creadas.Add(new JsonObject { ["type"] = e.GetType().Name }); e.Dispose(); }
                            o2["discarded"] = nuevas.Count;
                            o2["note"] = "El método devolvió " + nuevas.Count + " objeto(s) nuevo(s) que NO se agregaron al dibujo; pedí add_results_to_space=true para dejarlos.";
                        }
                    }
                    if (agregar) o2["created"] = creadas;
                    o2["written"] = escribe;

                    // Una lectura no deja rastro en el deshacer: se aborta.
                    if (escribe) tr.Commit(); else tr.Abort();
                    return o2;
                }
                catch (SysException ex)
                {
                    tr.Abort();
                    foreach (var e in nuevas) { try { e.Dispose(); } catch (SysException) { } }
                    if (ex is AcException ae)
                        throw new InvalidOperationException(
                            "AutoCAD rechazó la llamada (" + ae.ErrorStatus + "): " + ae.Message + ". No se modificó nada.");
                    throw;
                }
            }
        }
    }
}
