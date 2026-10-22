using System;
using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Calco PDF (PDFATTACH): un PDF como fondo del dibujo, sobre el que se traza. Es lo habitual cuando el cliente
    /// manda su plano como PDF. Se agrega como UnderlayDefinition (en el diccionario ACAD_PDFDEFINITIONS, con la
    /// clave que da UnderlayDefinition.GetDictionaryKey) y una PdfReference que la usa. Precondiciones leídas del
    /// código descompilado (tools/precondiciones.py): UnderlayDefinition y UnderlayReference no tienen constructor
    /// público de datos (se llenan por propiedades antes de agregarlas) y la definición va al diccionario ANTES de
    /// que la referencia apunte a ella.
    /// </summary>
    public static class UnderlayCommands
    {
        /// <summary>params: path (.pdf existente), x, y, [z=0], [page=1], [scale=1], [rotation_deg=0], [layer].
        /// El tamaño real depende del PDF: se informa 'width' y 'height' de la referencia en unidades del dibujo.</summary>
        public static JsonObject AttachPdf(Document doc, JsonObject pars)
        {
            string ruta = pars["path"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(ruta)) throw new ArgumentException("Falta 'path' (el .pdf).");
            ruta = Path.GetFullPath(ruta);
            if (!ruta.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("El archivo tiene que ser un .pdf.");
            if (!File.Exists(ruta)) throw new FileNotFoundException("No existe el archivo: " + ruta);
            int pagina = pars["page"]?.GetValue<int>() ?? 1;
            if (pagina < 1 || pagina > 10000) throw new ArgumentException("'page' va de 1 en adelante.");
            double x = pars["x"].GetValue<double>(), y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double escala = pars["scale"] != null ? pars["scale"].GetValue<double>() : 1.0;
            double rot = pars["rotation_deg"] != null ? pars["rotation_deg"].GetValue<double>() : 0.0;
            foreach (var v in new[] { x, y, z, escala, rot })
                if (double.IsNaN(v) || double.IsInfinity(v)) throw new ArgumentException("Hay un número inválido (NaN o infinito).");
            if (escala <= 0) throw new ArgumentException("'scale' tiene que ser mayor que cero.");
            string capa = pars["layer"]?.GetValue<string>();
            var db = doc.Database;
            string clave = UnderlayDefinition.GetDictionaryKey(typeof(PdfDefinition));
            string nombre = Path.GetFileNameWithoutExtension(ruta) + "_" + pagina;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    if (!string.IsNullOrEmpty(capa))
                    {
                        var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                        if (!lt.Has(capa)) throw new ArgumentException("No hay una capa llamada '" + capa + "'.");
                    }
                    var nod = (DBDictionary)tr.GetObject(db.NamedObjectsDictionaryId, OpenMode.ForRead);
                    DBDictionary dic;
                    if (nod.Contains(clave)) dic = (DBDictionary)tr.GetObject(nod.GetAt(clave), OpenMode.ForWrite);
                    else
                    {
                        nod.UpgradeOpen();
                        dic = new DBDictionary();
                        nod.SetAt(clave, dic);
                        tr.AddNewlyCreatedDBObject(dic, true);
                    }
                    ObjectId defId;
                    string nombreDef = nombre;
                    if (dic.Contains(nombreDef))
                    {
                        defId = dic.GetAt(nombreDef);
                        var existente = (PdfDefinition)tr.GetObject(defId, OpenMode.ForRead);
                        if (!string.Equals(existente.SourceFileName, ruta, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("Ya hay un calco llamado '" + nombreDef + "' que apunta a otro archivo (" + existente.SourceFileName + ").");
                    }
                    else
                    {
                        var def = new PdfDefinition { SourceFileName = ruta, ItemName = pagina.ToString() };
                        defId = dic.SetAt(nombreDef, def);
                        tr.AddNewlyCreatedDBObject(def, true);
                    }
                    var r = new PdfReference { DefinitionId = defId, Position = new Point3d(x, y, z),
                                               ScaleFactors = new Scale3d(escala), Rotation = rot * Math.PI / 180.0 };
                    if (!string.IsNullOrEmpty(capa)) r.Layer = capa;
                    var espacio = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
                    espacio.AppendEntity(r);
                    tr.AddNewlyCreatedDBObject(r, true);
                    var salida = new JsonObject { ["handle"] = r.Handle.ToString(), ["name"] = nombreDef, ["path"] = ruta, ["page"] = pagina };
                    try { salida["width"] = r.Width; salida["height"] = r.Height; } catch (SysException) { }
                    tr.Commit();
                    return salida;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el calco PDF (" + ex.ErrorStatus + "): " + ex.Message + ". No se agregó nada.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }
    }
}
