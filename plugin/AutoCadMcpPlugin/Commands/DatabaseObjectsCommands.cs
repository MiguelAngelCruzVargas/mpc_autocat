using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Crear y borrar los objetos que NO son entidades: capas, estilos de texto y de cota,
    /// bloques (la definición), aplicaciones registradas y sistemas de coordenadas.
    ///
    /// Se apoya en lo mismo que las propiedades: el registro nuevo se crea por reflexión,
    /// sus propiedades se validan ENTERAS antes de tocar el dibujo (existen, se escriben, el
    /// valor convierte), y todo va en una transacción: si algo falla no se crea nada.
    ///
    /// Qué NO se hace. No se crean ni se borran los objetos del sistema (capa 0 y Defpoints,
    /// el estilo Standard, *Model_Space y los espacios de papel, los bloques anónimos), ni el
    /// que está en uso como actual. Borrar no es purgar: AutoCAD se niega a borrar lo que el
    /// dibujo todavía usa (una capa con objetos, un bloque insertado) y ese rechazo se
    /// informa tal cual, no se esquiva.
    /// </summary>
    public static class DatabaseObjectsCommands
    {
        private sealed class Tipo
        {
            public string Clase;            // nombre de la clase del registro
            public string TablaId;          // propiedad de Database con el id de la tabla
            public string ActualEnDb;       // propiedad de Database con el actual (para no borrarlo)
            public string[] Protegidos;     // nombres que no se tocan
        }

        private static readonly Dictionary<string, Tipo> Tipos = new Dictionary<string, Tipo>(StringComparer.OrdinalIgnoreCase)
        {
            { "layer",     new Tipo { Clase = "LayerTableRecord",      TablaId = "LayerTableId",      ActualEnDb = "Clayer",     Protegidos = new[] { "0", "Defpoints" } } },
            { "textstyle", new Tipo { Clase = "TextStyleTableRecord",  TablaId = "TextStyleTableId",  ActualEnDb = "Textstyle",  Protegidos = new[] { "Standard" } } },
            { "dimstyle",  new Tipo { Clase = "DimStyleTableRecord",   TablaId = "DimStyleTableId",   ActualEnDb = "Dimstyle",   Protegidos = new[] { "Standard" } } },
            { "block",     new Tipo { Clase = "BlockTableRecord",      TablaId = "BlockTableId",      ActualEnDb = null,         Protegidos = new string[0] } },
            { "regapp",    new Tipo { Clase = "RegAppTableRecord",     TablaId = "RegAppTableId",     ActualEnDb = null,         Protegidos = new[] { "ACAD" } } },
            { "ucs",       new Tipo { Clase = "UcsTableRecord",        TablaId = "UcsTableId",        ActualEnDb = null,         Protegidos = new string[0] } },
        };

        private static Tipo Resolver(string kind)
        {
            if (string.IsNullOrWhiteSpace(kind) || !Tipos.TryGetValue(kind, out var t))
                throw new ArgumentException("'kind' desconocido: " + kind + ". Válidos: " + string.Join(", ", Tipos.Keys) + ".");
            return t;
        }

        private static readonly char[] Prohibidos = { '<', '>', '/', '\\', '"', ':', ';', '?', '*', '|', ',', '=', '`' };

        private static void ValidarNombre(string nombre)
        {
            if (string.IsNullOrWhiteSpace(nombre) || nombre != nombre.Trim())
                throw new ArgumentException("'name' no puede estar vacío ni empezar o terminar con espacios.");
            if (nombre.Length > 255)
                throw new ArgumentException("'name' no puede pasar de 255 caracteres.");
            int mal = nombre.IndexOfAny(Prohibidos);
            if (mal >= 0)
                throw new ArgumentException("'name' no puede llevar el carácter '" + nombre[mal] + "' (AutoCAD lo reserva).");
            if (nombre.StartsWith("*"))
                throw new ArgumentException("Los nombres que empiezan con * son de AutoCAD (bloques anónimos y espacios).");
        }

        private static ObjectId Tabla(Database db, Tipo t)
        {
            var p = typeof(Database).GetProperty(t.TablaId, BindingFlags.Public | BindingFlags.Instance);
            if (p == null) throw new InvalidOperationException("Esta versión de AutoCAD no tiene " + t.TablaId + ".");
            return (ObjectId)p.GetValue(db);
        }

        /// <summary>params: kind (layer|textstyle|dimstyle|block|regapp|ucs), name, [properties].</summary>
        public static JsonObject Create(Document doc, JsonObject pars)
        {
            var tipo = Resolver(pars["kind"]?.GetValue<string>());
            string nombre = pars["name"]?.GetValue<string>();
            ValidarNombre(nombre);
            var pedidas = pars["properties"] as JsonObject ?? new JsonObject();
            if (pedidas.Count > 60) throw new ArgumentException("Máximo 60 propiedades por llamada.");
            if (pedidas.Any(kv => kv.Key.Equals("Name", StringComparison.OrdinalIgnoreCase)))
                throw new ArgumentException("El nombre va en 'name', no en 'properties'.");
            if (tipo.Protegidos.Any(x => x.Equals(nombre, StringComparison.OrdinalIgnoreCase)))
                throw new ArgumentException("'" + nombre + "' es un nombre reservado del sistema y ya existe.");

            var t = typeof(Entity).Assembly.GetType("Autodesk.AutoCAD.DatabaseServices." + tipo.Clase, true);
            // Se valida TODO antes de crear.
            var plan = new List<Tuple<PropertyInfo, object>>();
            foreach (var kv in pedidas)
            {
                var p = PropertiesCommands.BuscarPublico(t, kv.Key);
                if (!PropertiesCommands.EscribiblePublico(p))
                    throw new ArgumentException("La propiedad '" + p.Name + "' de " + t.Name + " es de solo lectura.");
                plan.Add(Tuple.Create(p, PropertiesCommands.DeJson(p.PropertyType, kv.Value, p.Name)));
            }

            var db = doc.Database;
            var rec = (SymbolTableRecord)Activator.CreateInstance(t);
            try
            {
                using (var tr = db.TransactionManager.StartTransaction())
                {
                    try
                    {
                        var tabla = (SymbolTable)tr.GetObject(Tabla(db, tipo), OpenMode.ForWrite);
                        if (tabla.Has(nombre))
                            throw new ArgumentException("Ya existe un " + kind(tipo) + " llamado '" + nombre + "'.");
                        rec.Name = nombre;
                        tabla.Add(rec);
                        tr.AddNewlyCreatedDBObject(rec, true);
                        // Las propiedades van DESPUÉS de agregarlo a la tabla: algunas (la descripción de
                        // una capa, por ejemplo) se pierden si el registro todavía no vive en el dibujo.
                        // Si una falla, se aborta la transacción y el registro no queda.
                        foreach (var item in plan)
                            item.Item1.SetValue(rec, item.Item2);
                        tr.Commit();
                    }
                    catch (TargetInvocationException ex)
                    {
                        tr.Abort();
                        var real = ex.InnerException ?? ex;
                        throw new InvalidOperationException(
                            "AutoCAD rechazó la creación" + (real is AcException ae ? " (" + ae.ErrorStatus + ")" : "") + ": " +
                            real.Message + ". No se creó nada.");
                    }
                    catch (AcException ex)
                    {
                        tr.Abort();
                        throw new InvalidOperationException(
                            "AutoCAD rechazó la creación (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                    }
                    catch (SysException)
                    {
                        tr.Abort();
                        throw;
                    }
                }
            }
            catch (SysException)
            {
                if (!rec.ObjectId.IsValid) { try { rec.Dispose(); } catch (SysException) { } }
                throw;
            }
            return new JsonObject
            {
                ["kind"] = pars["kind"].GetValue<string>().ToLowerInvariant(), ["name"] = nombre,
                ["handle"] = rec.ObjectId.Handle.ToString(), ["type"] = t.Name
            };
        }

        private static string kind(Tipo t) { return t.Clase.Replace("TableRecord", ""); }

        /// <summary>params: kind, name | handle.</summary>
        public static JsonObject Delete(Document doc, JsonObject pars)
        {
            var tipo = Resolver(pars["kind"]?.GetValue<string>());
            string nombre = pars["name"]?.GetValue<string>();
            string handle = pars["handle"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(nombre) == string.IsNullOrWhiteSpace(handle))
                throw new ArgumentException("Pasá 'name' o 'handle', uno de los dos.");
            var db = doc.Database;
            string borrado, handleBorrado;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var tabla = (SymbolTable)tr.GetObject(Tabla(db, tipo), OpenMode.ForRead);
                    ObjectId id;
                    if (!string.IsNullOrWhiteSpace(nombre))
                    {
                        if (!tabla.Has(nombre))
                            throw new ArgumentException("No hay un " + kind(tipo) + " llamado '" + nombre + "'.");
                        id = tabla[nombre];
                    }
                    else
                    {
                        id = HandleHelper.GetObjectId(db, handle);
                    }
                    var rec = tr.GetObject(id, OpenMode.ForRead) as SymbolTableRecord;
                    if (rec == null || rec.GetType().Name != tipo.Clase)
                        throw new ArgumentException("Ese handle no es un " + tipo.Clase + ".");
                    borrado = rec.Name;
                    handleBorrado = id.Handle.ToString();
                    if (tipo.Protegidos.Any(x => x.Equals(borrado, StringComparison.OrdinalIgnoreCase)))
                        throw new InvalidOperationException("'" + borrado + "' es un objeto del sistema: no se borra.");
                    if (borrado.StartsWith("*"))
                        throw new InvalidOperationException("'" + borrado + "' es un objeto de AutoCAD (espacio o bloque anónimo): no se borra.");
                    if (tipo.ActualEnDb != null)
                    {
                        var pa = typeof(Database).GetProperty(tipo.ActualEnDb, BindingFlags.Public | BindingFlags.Instance);
                        if (pa != null && pa.GetValue(db) is ObjectId actual && actual == id)
                            throw new InvalidOperationException("'" + borrado + "' es el " + kind(tipo) + " ACTUAL: poné otro como actual antes de borrarlo.");
                    }
                    if (rec is BlockTableRecord btr)
                    {
                        var refs = btr.GetBlockReferenceIds(true, false);
                        if (refs.Count > 0)
                            throw new InvalidOperationException(
                                "El bloque '" + borrado + "' está insertado " + refs.Count + " vez/veces: borrá o explotá esas referencias antes.");
                    }
                    // «En uso» lo decide AutoCAD con la misma prueba de PURGE: lo que el dibujo todavía
                    // referencia no se puede purgar. Erase a secas BORRABA una capa con objetos y los dejaba
                    // apuntando a una capa borrada (probado en vivo).
                    var candidatos = new ObjectIdCollection();
                    candidatos.Add(id);
                    db.Purge(candidatos);
                    if (!candidatos.Contains(id))
                        throw new InvalidOperationException(
                            "'" + borrado + "' está en uso (el dibujo todavía lo referencia: objetos en esa capa, texto o cotas " +
                            "con ese estilo, referencias a ese bloque...). Liberalo antes de borrarlo. No se borró nada.");
                    rec.UpgradeOpen();
                    rec.Erase(true);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException(
                        "AutoCAD se negó a borrarlo (" + ex.ErrorStatus + "): " + ex.Message +
                        ". Suele ser que el dibujo todavía lo usa (una capa con objetos, un estilo en uso). No se borró nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    throw;
                }
            }
            return new JsonObject { ["deleted"] = true, ["kind"] = pars["kind"].GetValue<string>().ToLowerInvariant(),
                                    ["name"] = borrado, ["handle"] = handleBorrado };
        }
    }
}
