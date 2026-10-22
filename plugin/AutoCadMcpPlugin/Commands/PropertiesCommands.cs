using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Propiedades de CUALQUIER objeto del dibujo (líneas, polilíneas, textos,
    /// cotas, achurados, bloques, sólidos 3D, capas, estilos...), por reflexión
    /// sobre la API de AutoCAD.
    ///
    /// Por qué así. La API de objetos tiene miles de propiedades: unas 3.700
    /// escribibles contando lo heredado por cada una de las ~70 clases de
    /// entidad (código descompilado de 2022 y 2027). Escribir una tool por
    /// propiedad es inviable, y escribir un comando C# por cada una obligaba a
    /// recompilar y reiniciar AutoCAD. La reflexión las descubre en tiempo de
    /// ejecución en la versión REAL instalada, así que lo que no existe en una
    /// versión simplemente no aparece (2022 y 2027 no tienen que coincidir).
    ///
    /// Qué NO es. No ejecuta métodos ni llama a nada estático: solo lee y
    /// escribe PROPIEDADES públicas de instancia de objetos del dibujo, de tipo
    /// simple (números, texto, booleanos, puntos, vectores, escalas, colores,
    /// enumeraciones). Lo escribible se valida entero antes de tocar nada y
    /// se aplica en UNA transacción: si algo falla, no queda nada a medias.
    /// </summary>
    public static class PropertiesCommands
    {
        private const int MaxObjetos = 500;
        private const int MaxPropiedades = 60;

        /// <summary>Propiedades que son del objeto de infraestructura y no del
        /// dibujo; no se leen en el modo «todas» y no se escriben nunca.</summary>
        private static readonly HashSet<string> Infraestructura = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase)
        {
            "Database", "ExtensionDictionary", "UnmanagedObject", "AutoDelete", "IsDisposed",
            "IsAProxy", "IsReadEnabled", "IsWriteEnabled", "IsNotifying", "IsModified",
            "IsNewObject", "IsTransactionResident", "IsUndoing", "IsCancelling", "IsEraseStatusToggled",
            "IsPersistent", "IsModifiedGraphics", "IsModifiedXData", "IsReallyClosing", "IsObjectIdsInFlux",
            "DrawStream", "Bounds", "BlockId", "OwnerId", "MergeStyle", "ObjectBirthVersion",
            "ClassID", "ObjectId", "Id", "ForceAnnoAllVisible"
        };

        private static readonly Dictionary<Type, PropertyInfo[]> Cache = new Dictionary<Type, PropertyInfo[]>();

        // ------------------------------------------------------------ reflexión

        internal static bool EsNumero(Type t)
        {
            return t == typeof(int) || t == typeof(short) || t == typeof(long) || t == typeof(double)
                || t == typeof(float) || t == typeof(byte) || t == typeof(uint) || t == typeof(ushort);
        }

        /// <summary>Tipos que se saben llevar y traer a JSON.</summary>
        internal static bool Soportado(Type t)
        {
            t = Nullable.GetUnderlyingType(t) ?? t;
            return t == typeof(string) || t == typeof(bool) || EsNumero(t) || t.IsEnum
                || t == typeof(Point3d) || t == typeof(Point2d) || t == typeof(Vector3d) || t == typeof(Vector2d)
                || t == typeof(Scale3d) || t == typeof(Color) || t == typeof(Extents3d) || t == typeof(ObjectId)
                || t == typeof(Matrix3d) || t == typeof(Plane);
        }

        /// <summary>Estructuras de la API con campos simples de solo lectura (Solid3dMassProperties:
        /// volumen, centroide, momentos de inercia...): se LEEN como un objeto {campo: valor}.
        /// No se escriben ni se pasan como argumento.</summary>
        internal static bool EsPlano(Type t)
        {
            t = Nullable.GetUnderlyingType(t) ?? t;
            if (!t.IsValueType || t.IsEnum || t.IsPrimitive || Soportado(t)) return false;
            var ns = t.Namespace ?? "";
            return ns.StartsWith("Autodesk.AutoCAD", StringComparison.Ordinal) && PropsPlanas(t).Length > 0;
        }

        private static PropertyInfo[] PropsPlanas(Type t)
        {
            return t.GetProperties(BindingFlags.Public | BindingFlags.Instance)
                .Where(p => p.GetIndexParameters().Length == 0 && p.GetMethod != null && p.GetMethod.IsPublic
                            && Soportado(p.PropertyType))
                .OrderBy(p => p.Name, StringComparer.Ordinal).ToArray();
        }

        private static bool EsEscribibleTipo(Type t)
        {
            t = Nullable.GetUnderlyingType(t) ?? t;
            return Soportado(t) && t != typeof(Extents3d) && t != typeof(ObjectId);
        }

        private static PropertyInfo[] Propiedades(Type t)
        {
            lock (Cache)
            {
                if (Cache.TryGetValue(t, out var ya)) return ya;
                var lista = t.GetProperties(BindingFlags.Public | BindingFlags.Instance)
                    .Where(p => p.GetIndexParameters().Length == 0)
                    .Where(p => !Infraestructura.Contains(p.Name))
                    .Where(p => Soportado(p.PropertyType) || EsPlano(p.PropertyType))
                    .Where(p => p.GetMethod != null && p.GetMethod.IsPublic)
                    .OrderBy(p => p.Name, StringComparer.Ordinal)
                    .ToArray();
                Cache[t] = lista;
                return lista;
            }
        }

        private static PropertyInfo Buscar(Type t, string nombre)
        {
            var p = Propiedades(t).FirstOrDefault(x => x.Name.Equals(nombre, StringComparison.OrdinalIgnoreCase));
            if (p == null)
            {
                // Hay propiedades que existen pero no se soportan: decirlo, no
                // simular que no existen.
                var cruda = t.GetProperty(nombre, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
                if (cruda != null)
                    throw new ArgumentException(
                        "La propiedad '" + cruda.Name + "' de " + t.Name + " es de tipo " + cruda.PropertyType.Name +
                        ", que esta capa no maneja (solo números, texto, booleanos, puntos, vectores, escalas, colores y enumeraciones).");
                throw new ArgumentException(
                    "El tipo " + t.Name + " no tiene la propiedad '" + nombre + "'. Mirá list_object_properties.");
            }
            return p;
        }

        private static bool Escribible(PropertyInfo p)
        {
            return p.SetMethod != null && p.SetMethod.IsPublic && EsEscribibleTipo(p.PropertyType);
        }

        // ------------------------------------------------------------ valores <-> JSON

        internal static JsonNode AJson(object v)
        {
            if (v == null) return null;
            switch (v)
            {
                case string s: return JsonValue.Create(s);
                case bool b: return JsonValue.Create(b);
                case double d: return double.IsNaN(d) || double.IsInfinity(d) ? null : JsonValue.Create(d);
                case float f: return float.IsNaN(f) || float.IsInfinity(f) ? null : JsonValue.Create((double)f);
                case short i16: return JsonValue.Create((int)i16);
                case ushort u16: return JsonValue.Create((int)u16);
                case byte u8: return JsonValue.Create((int)u8);
                case int i32: return JsonValue.Create(i32);
                case uint u32: return JsonValue.Create((long)u32);
                case long i64: return JsonValue.Create(i64);
                case Enum e: return JsonValue.Create(e.ToString());
                case Point3d p3: return new JsonArray(p3.X, p3.Y, p3.Z);
                case Point2d p2: return new JsonArray(p2.X, p2.Y);
                case Vector3d v3: return new JsonArray(v3.X, v3.Y, v3.Z);
                case Vector2d v2: return new JsonArray(v2.X, v2.Y);
                case Scale3d sc: return new JsonArray(sc.X, sc.Y, sc.Z);
                case Extents3d ex:
                    return new JsonArray(ex.MinPoint.X, ex.MinPoint.Y, ex.MinPoint.Z,
                                         ex.MaxPoint.X, ex.MaxPoint.Y, ex.MaxPoint.Z);
                case ObjectId oid: return oid.IsNull ? null : JsonValue.Create(oid.Handle.ToString());
                case Matrix3d m3:
                    return new JsonArray(Enumerable.Range(0, 4).Select(f =>
                        (JsonNode)new JsonArray(m3[f, 0], m3[f, 1], m3[f, 2], m3[f, 3])).ToArray());
                case Plane pl:
                    return new JsonObject { ["point"] = AJson(pl.PointOnPlane), ["normal"] = AJson(pl.Normal) };
                case Color c:
                    switch (c.ColorMethod)
                    {
                        case ColorMethod.ByLayer: return JsonValue.Create("ByLayer");
                        case ColorMethod.ByBlock: return JsonValue.Create("ByBlock");
                        case ColorMethod.ByColor: return new JsonArray((int)c.Red, (int)c.Green, (int)c.Blue);
                        default: return JsonValue.Create((int)c.ColorIndex);
                    }
                default:
                    if (EsPlano(v.GetType()))
                    {
                        var o = new JsonObject();
                        foreach (var p in PropsPlanas(v.GetType()))
                        {
                            try { o[p.Name] = AJson(p.GetValue(v)); }
                            catch (SysException) { }
                        }
                        return o;
                    }
                    return JsonValue.Create(Convert.ToString(v));
            }
        }

        private static double Num(JsonNode n, string cual)
        {
            if (n is JsonValue v)
            {
                if (v.TryGetValue<double>(out var d)) return d;
                if (v.TryGetValue<int>(out var i)) return i;
                if (v.TryGetValue<long>(out var l)) return l;
                if (v.TryGetValue<string>(out var s)
                    && double.TryParse(s, System.Globalization.NumberStyles.Float,
                                       System.Globalization.CultureInfo.InvariantCulture, out var ds))
                    return ds;
            }
            throw new ArgumentException(cual + " no es un número.");
        }

        private static double[] Vec(JsonNode n, int minimo, int maximo, string cual)
        {
            var a = n as JsonArray;
            if (a == null || a.Count < minimo || a.Count > maximo)
                throw new ArgumentException(cual + " tiene que ser una lista de " +
                    (minimo == maximo ? minimo.ToString() : minimo + " o " + maximo) + " números.");
            var r = new double[maximo];
            for (int i = 0; i < a.Count; i++)
            {
                r[i] = Num(a[i], cual);
                if (double.IsNaN(r[i]) || double.IsInfinity(r[i]))
                    throw new ArgumentException(cual + " tiene un valor inválido (NaN o infinito).");
            }
            return r;
        }

        internal static object DeJson(Type destino, JsonNode v, string nombre)
        {
            var t = Nullable.GetUnderlyingType(destino) ?? destino;
            if (v == null)
                throw new ArgumentException(nombre + ": el valor no puede ser null.");
            try
            {
                if (t == typeof(string))
                    return v is JsonValue sv && sv.TryGetValue<string>(out var s) ? s : v.ToString();
                if (t == typeof(bool))
                {
                    if (v is JsonValue bv)
                    {
                        if (bv.TryGetValue<bool>(out var b)) return b;
                        if (bv.TryGetValue<string>(out var bs) && bool.TryParse(bs, out var b2)) return b2;
                    }
                    throw new ArgumentException("no es true/false");
                }
                if (EsNumero(t))
                {
                    double d = Num(v, nombre);
                    if (double.IsNaN(d) || double.IsInfinity(d)) throw new ArgumentException("número inválido");
                    if (t == typeof(double)) return d;
                    if (t == typeof(float)) return (float)d;
                    if (d != Math.Floor(d)) throw new ArgumentException("tiene que ser un entero");
                    return Convert.ChangeType(d, t, System.Globalization.CultureInfo.InvariantCulture);
                }
                if (t.IsEnum)
                {
                    if (v is JsonValue ev && ev.TryGetValue<string>(out var es))
                    {
                        if (!Enum.IsDefined(t, es) && !t.IsDefined(typeof(FlagsAttribute), false))
                            throw new ArgumentException("valores válidos: " + string.Join(", ", Enum.GetNames(t)));
                        return Enum.Parse(t, es, true);
                    }
                    long n = (long)Num(v, nombre);
                    if (!t.IsDefined(typeof(FlagsAttribute), false) && !Enum.IsDefined(t, Enum.ToObject(t, n)))
                        throw new ArgumentException("valores válidos: " + string.Join(", ", Enum.GetNames(t)));
                    return Enum.ToObject(t, n);
                }
                if (t == typeof(Point3d)) { var a = Vec(v, 2, 3, nombre); return new Point3d(a[0], a[1], a[2]); }
                if (t == typeof(Point2d)) { var a = Vec(v, 2, 2, nombre); return new Point2d(a[0], a[1]); }
                if (t == typeof(Vector3d)) { var a = Vec(v, 3, 3, nombre); return new Vector3d(a[0], a[1], a[2]); }
                if (t == typeof(Vector2d)) { var a = Vec(v, 2, 2, nombre); return new Vector2d(a[0], a[1]); }
                if (t == typeof(Scale3d)) { var a = Vec(v, 3, 3, nombre); return new Scale3d(a[0], a[1], a[2]); }
                if (t == typeof(Matrix3d))
                {
                    // 4 filas de 4 números, o 16 números seguidos (por filas).
                    var m = v as JsonArray;
                    double[] d;
                    if (m != null && m.Count == 4 && m.All(f => f is JsonArray))
                        d = m.SelectMany(f => Vec(f, 4, 4, nombre)).ToArray();
                    else
                        d = Vec(v, 16, 16, nombre);
                    return new Matrix3d(d);
                }
                if (t == typeof(Plane))
                {
                    var o = v as JsonObject;
                    if (o == null || o["point"] == null || o["normal"] == null)
                        throw new ArgumentException("un plano es {\"point\": [x,y,z], \"normal\": [x,y,z]}");
                    var pt = Vec(o["point"], 3, 3, nombre); var nv = Vec(o["normal"], 3, 3, nombre);
                    var normal = new Vector3d(nv[0], nv[1], nv[2]);
                    if (normal.Length < 1e-12) throw new ArgumentException("la normal del plano no puede ser cero");
                    return new Plane(new Point3d(pt[0], pt[1], pt[2]), normal);
                }
                if (t == typeof(Color))
                {
                    if (v is JsonArray ca)
                    {
                        var a = Vec(ca, 3, 3, nombre);
                        foreach (var x in a)
                            if (x < 0 || x > 255 || x != Math.Floor(x))
                                throw new ArgumentException("RGB: tres enteros de 0 a 255");
                        return Color.FromRgb((byte)a[0], (byte)a[1], (byte)a[2]);
                    }
                    if (v is JsonValue cv && cv.TryGetValue<string>(out var cs))
                    {
                        if (cs.Equals("ByLayer", StringComparison.OrdinalIgnoreCase))
                            return Color.FromColorIndex(ColorMethod.ByLayer, 256);
                        if (cs.Equals("ByBlock", StringComparison.OrdinalIgnoreCase))
                            return Color.FromColorIndex(ColorMethod.ByBlock, 0);
                    }
                    double idx = Num(v, nombre);
                    if (idx < 1 || idx > 255 || idx != Math.Floor(idx))
                        throw new ArgumentException("el color es un índice AutoCAD 1-255, 'ByLayer', 'ByBlock' o [r,g,b]");
                    return Color.FromColorIndex(ColorMethod.ByAci, (short)idx);
                }
            }
            catch (ArgumentException ex)
            {
                throw new ArgumentException(nombre + " (" + destino.Name + "): " + ex.Message);
            }
            catch (SysException ex) when (ex is FormatException || ex is OverflowException || ex is InvalidCastException)
            {
                throw new ArgumentException(nombre + " (" + destino.Name + "): " + ex.Message);
            }
            throw new ArgumentException(nombre + ": tipo " + destino.Name + " no soportado.");
        }

        // ------------------------------------------------------------ objetos

        private static List<ObjectId> Objetos(Document doc, JsonObject pars)
        {
            var ids = new List<ObjectId>();
            var lista = pars["handles"] as JsonArray;
            if (lista == null && pars["handle"] != null)
                lista = new JsonArray(pars["handle"].GetValue<string>());
            if (lista == null || lista.Count == 0)
                throw new ArgumentException("Falta 'handle' o 'handles'.");
            if (lista.Count > MaxObjetos)
                throw new ArgumentException("Máximo " + MaxObjetos + " objetos por llamada (llegaron " + lista.Count + ").");
            foreach (var n in lista)
            {
                var id = HandleHelper.GetObjectId(doc.Database, n.GetValue<string>());
                if (!ids.Contains(id)) ids.Add(id);
            }
            return ids;
        }

        private static string[] Nombres(JsonNode n)
        {
            var a = n as JsonArray;
            if (a == null) return null;
            var r = a.Select(x => x.GetValue<string>()).Where(x => !string.IsNullOrWhiteSpace(x)).ToArray();
            if (r.Length > MaxPropiedades)
                throw new ArgumentException("Máximo " + MaxPropiedades + " propiedades por llamada.");
            return r;
        }

        // ------------------------------------------------------------ comandos

        /// <summary>params: handle | handles, [names] (sin names: todas las soportadas).</summary>
        public static JsonObject Get(Document doc, JsonObject pars)
        {
            var ids = Objetos(doc, pars);
            var nombres = Nombres(pars["names"]);
            var salida = new JsonObject();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                foreach (var id in ids)
                {
                    var obj = tr.GetObject(id, OpenMode.ForRead);
                    var t = obj.GetType();
                    var valores = new JsonObject();
                    var omitidas = new JsonObject();
                    IEnumerable<PropertyInfo> props = nombres == null
                        ? Propiedades(t)
                        : nombres.Select(nm => Buscar(t, nm));
                    foreach (var p in props)
                    {
                        try { valores[p.Name] = AJson(p.GetValue(obj)); }
                        catch (SysException ex)
                        {
                            var real = ex is TargetInvocationException ti && ti.InnerException != null ? ex.InnerException : ex;
                            omitidas[p.Name] = real is AcException ae ? ae.ErrorStatus.ToString() : real.Message;
                        }
                    }
                    var o = new JsonObject { ["type"] = t.Name, ["properties"] = valores };
                    if (omitidas.Count > 0) o["unreadable"] = omitidas;
                    salida[id.Handle.ToString()] = o;
                }
                tr.Commit();
            }
            return new JsonObject { ["objects"] = salida, ["count"] = ids.Count };
        }

        /// <summary>params: handle | handles, properties {nombre: valor}, [dry_run].</summary>
        public static JsonObject Set(Document doc, JsonObject pars)
        {
            var ids = Objetos(doc, pars);
            var pedidas = pars["properties"] as JsonObject;
            if (pedidas == null || pedidas.Count == 0)
                throw new ArgumentException("Falta 'properties': un objeto {nombre: valor}.");
            if (pedidas.Count > MaxPropiedades)
                throw new ArgumentException("Máximo " + MaxPropiedades + " propiedades por llamada.");
            bool simulacro = pars["dry_run"]?.GetValue<bool>() ?? false;

            var cambios = new JsonObject();
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                try
                {
                    // 1) Se valida TODO contra cada objeto antes de escribir: tipo, existencia
                    //    de la propiedad, que sea escribible y que el valor convierta.
                    var plan = new List<Tuple<ObjectId, PropertyInfo, object>>();
                    foreach (var id in ids)
                    {
                        var lectura = tr.GetObject(id, OpenMode.ForRead);
                        var t = lectura.GetType();
                        foreach (var kv in pedidas)
                        {
                            var p = Buscar(t, kv.Key);
                            if (!Escribible(p))
                                throw new ArgumentException(
                                    "La propiedad '" + p.Name + "' de " + t.Name + " es de solo lectura.");
                            plan.Add(Tuple.Create(id, p, DeJson(p.PropertyType, kv.Value, p.Name)));
                        }
                    }
                    // 2) Se escribe todo en la misma transacción.
                    foreach (var porObjeto in plan.GroupBy(x => x.Item1))
                    {
                        var lect = tr.GetObject(porObjeto.Key, OpenMode.ForRead);
                        var antes = new JsonObject();
                        var despues = new JsonObject();
                        DBObject esc = simulacro ? lect : tr.GetObject(porObjeto.Key, OpenMode.ForWrite);
                        foreach (var item in porObjeto)
                        {
                            var p = item.Item2;
                            antes[p.Name] = AJson(p.GetValue(esc));
                            if (!simulacro) p.SetValue(esc, item.Item3);
                            despues[p.Name] = AJson(simulacro ? item.Item3 : p.GetValue(esc));
                        }
                        cambios[porObjeto.Key.Handle.ToString()] = new JsonObject
                        {
                            ["type"] = lect.GetType().Name, ["before"] = antes, ["after"] = despues
                        };
                    }
                    if (simulacro) tr.Abort(); else tr.Commit();
                }
                catch (TargetInvocationException ex)
                {
                    tr.Abort();
                    var real = ex.InnerException ?? ex;
                    throw new InvalidOperationException(
                        "AutoCAD rechazó el cambio" + (real is AcException ae ? " (" + ae.ErrorStatus + ")" : "") + ": " +
                        real.Message + ". No se modificó nada.");
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException(
                        "AutoCAD rechazó el cambio (" + ex.ErrorStatus + "): " + ex.Message +
                        ". Puede ser una capa bloqueada. No se modificó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject
            {
                ["applied"] = !simulacro, ["dryRun"] = simulacro, ["changes"] = cambios, ["count"] = ids.Count
            };
        }

        /// <summary>params: handle | type (nombre de clase, p.ej. "Polyline").</summary>
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

            var props = new JsonArray();
            foreach (var p in Propiedades(t))
            {
                var tp = Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;
                var o = new JsonObject
                {
                    ["name"] = p.Name,
                    ["type"] = tp.Name,
                    ["writable"] = Escribible(p),
                    ["declaredIn"] = p.DeclaringType?.Name,
                };
                if (tp.IsEnum) o["values"] = new JsonArray(Enum.GetNames(tp).Select(x => (JsonNode)JsonValue.Create(x)).ToArray());
                props.Add(o);
            }
            return new JsonObject
            {
                ["type"] = t.Name, ["count"] = props.Count,
                ["writableCount"] = props.Count(x => x["writable"].GetValue<bool>()),
                ["properties"] = props
            };
        }
    }
}
