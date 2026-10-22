using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Referencias externas (xrefs): coordinar varias disciplinas (arquitectura,
    /// estructura, instalaciones) como archivos separados VINCULADOS, en vez de
    /// copiar geometría de un DWG a otro con insert_block. La diferencia real:
    /// un xref se recarga cuando el archivo de origen cambia, sin volver a
    /// insertar nada a mano; un bloque importado queda congelado en el momento
    /// en que se insertó.
    /// </summary>
    public static class XrefCommands
    {
        /// <summary>params: path, name, x, y, [z=0], [scale=1], [rotationDeg=0], [layer]</summary>
        public static JsonObject Attach(Document doc, JsonObject pars)
        {
            string path = pars["path"].GetValue<string>();
            string name = pars["name"].GetValue<string>();
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double scale = pars["scale"] != null ? pars["scale"].GetValue<double>() : 1.0;
            double rotationDeg = pars["rotationDeg"] != null ? pars["rotationDeg"].GetValue<double>() : 0.0;

            if (!File.Exists(path))
                throw new FileNotFoundException($"No se encontró el archivo: {path}");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                if (bt.Has(name))
                    throw new InvalidOperationException(
                        $"Ya existe un bloque o xref llamado '{name}' en este dibujo.");

                ObjectId xrefId = db.AttachXref(path, name);

                var btrModel = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
                var br = new BlockReference(new Point3d(x, y, z), xrefId)
                {
                    ScaleFactors = new Scale3d(scale),
                    Rotation = rotationDeg * Math.PI / 180.0
                };
                EntityHelper.ApplyCommon(db, tr, br, pars);
                btrModel.AppendEntity(br);
                tr.AddNewlyCreatedDBObject(br, true);

                tr.Commit();
                return new JsonObject { ["handle"] = br.Handle.ToString(), ["name"] = name, ["path"] = path };
            }
        }

        /// <summary>params: (ninguno)</summary>
        public static JsonObject List(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var arr = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                foreach (ObjectId id in bt)
                {
                    var btr = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                    if (!btr.IsFromExternalReference) continue;
                    arr.Add(new JsonObject
                    {
                        ["name"] = btr.Name,
                        ["path"] = btr.PathName,
                        ["status"] = btr.XrefStatus.ToString(),
                        ["unloaded"] = btr.IsUnloaded,
                    });
                }
                tr.Commit();
            }
            return new JsonObject { ["xrefs"] = arr };
        }

        /// <summary>params: name</summary>
        public static JsonObject Detach(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                if (!bt.Has(name))
                    throw new InvalidOperationException($"No existe un xref llamado '{name}'.");
                var btrId = bt[name];
                var btr = (BlockTableRecord)tr.GetObject(btrId, OpenMode.ForRead);
                if (!btr.IsFromExternalReference)
                    throw new InvalidOperationException($"'{name}' no es un xref, es un bloque normal.");

                db.DetachXref(btrId);
                tr.Commit();
                return new JsonObject { ["status"] = "detached", ["name"] = name };
            }
        }

        /// <summary>params: [name] (si se omite, recarga todos los xrefs)</summary>
        public static JsonObject Reload(Document doc, JsonObject pars)
        {
            string name = pars.ContainsKey("name") ? pars["name"]?.GetValue<string>() : null;
            var db = doc.Database;
            var ids = new ObjectIdCollection();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                if (!string.IsNullOrEmpty(name))
                {
                    if (!bt.Has(name))
                        throw new InvalidOperationException($"No existe un xref llamado '{name}'.");
                    ids.Add(bt[name]);
                }
                else
                {
                    foreach (ObjectId id in bt)
                    {
                        var btr = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                        if (btr.IsFromExternalReference)
                            ids.Add(id);
                    }
                }
                tr.Commit();
            }

            db.ReloadXrefs(ids);
            return new JsonObject { ["reloaded"] = ids.Count };
        }

        private static ObjectIdCollection XrefsResueltos(Database db, JsonObject pars, bool soloResueltos, out List<string> nombres)
        {
            var ids = new ObjectIdCollection();
            nombres = new List<string>();
            var pedidos = new List<string>();
            if (pars["names"] is JsonArray na)
                foreach (var n in na) pedidos.Add(n.GetValue<string>());
            else if (pars["name"] != null) pedidos.Add(pars["name"].GetValue<string>());
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                foreach (var n in pedidos)
                {
                    if (!bt.Has(n)) throw new InvalidOperationException("No existe un xref llamado '" + n + "'.");
                    var btr = (BlockTableRecord)tr.GetObject(bt[n], OpenMode.ForRead);
                    if (!btr.IsFromExternalReference) throw new InvalidOperationException("'" + n + "' no es un xref, es un bloque normal.");
                    if (soloResueltos && btr.XrefStatus != XrefStatus.Resolved)
                        throw new InvalidOperationException("El xref '" + n + "' está en estado " + btr.XrefStatus + ": solo se puede unir uno resuelto (con su archivo cargado).");
                    ids.Add(bt[n]);
                    nombres.Add(btr.Name);
                }
                if (pedidos.Count == 0)
                {
                    foreach (ObjectId id in bt)
                    {
                        var btr = (BlockTableRecord)tr.GetObject(id, OpenMode.ForRead);
                        if (!btr.IsFromExternalReference) continue;
                        if (btr.XrefStatus != XrefStatus.Resolved) continue;      // sin names: solo los que están cargados
                        ids.Add(id);
                        nombres.Add(btr.Name);
                    }
                }
                tr.Commit();
            }
            return ids;
        }

        /// <summary>params: [name | names] (sin ninguno, todos los resueltos), [insert=true]. Une el xref al dibujo
        /// (BIND): deja de depender del archivo externo. insert=true (opción Insertar) sus capas, estilos y bloques
        /// se mezclan con los del dibujo sin prefijo; insert=false (opción Unir) llevan el prefijo «xref$0$»
        /// para no chocar con los propios. Es irreversible salvo con undo: avisar antes de entregar.</summary>
        public static JsonObject Bind(Document doc, JsonObject pars)
        {
            bool insertar = pars["insert"]?.GetValue<bool>() ?? true;
            var db = doc.Database;
            var ids = XrefsResueltos(db, pars, true, out var nombres);
            if (ids.Count == 0) throw new InvalidOperationException("No hay xrefs resueltos para unir.");
            try { db.BindXrefs(ids, insertar); }
            catch (Autodesk.AutoCAD.Runtime.Exception ex)
            {
                throw new InvalidOperationException("AutoCAD rechazó unir los xrefs (" + ex.ErrorStatus + "): " + ex.Message + ".");
            }
            return new JsonObject
            {
                ["bound"] = new JsonArray(nombres.Select(n => (JsonNode)n).ToArray()),
                ["mode"] = insertar ? "insert" : "bind"
            };
        }

        /// <summary>params: [name | names] (sin ninguno, todos). Descarga el xref de memoria sin quitarlo del dibujo
        /// (se vuelve a cargar con reload_xref).</summary>
        public static JsonObject Unload(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var ids = XrefsResueltos(db, pars, false, out var nombres);
            if (ids.Count == 0) throw new InvalidOperationException("No hay xrefs para descargar.");
            try { db.UnloadXrefs(ids); }
            catch (Autodesk.AutoCAD.Runtime.Exception ex)
            {
                throw new InvalidOperationException("AutoCAD rechazó descargar los xrefs (" + ex.ErrorStatus + "): " + ex.Message + ".");
            }
            return new JsonObject { ["unloaded"] = new JsonArray(nombres.Select(n => (JsonNode)n).ToArray()) };
        }
    }
}
