using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class SetLayerCommand
    {
        /// <summary>
        /// Crea la capa si no existe y le aplica propiedades (simbología/norma).
        /// params: name, [colorIndex] (ACI 1-255), [linetype] (nombre; si no está
        /// cargada en el dibujo se intenta cargar desde acad.lin),
        /// [lineweightHundredthsMm] (centésimas de mm, p.ej. 30 = 0.30mm; valores
        /// válidos de AutoCAD: 0,5,9,13,15,18,20,25,30,35,40,50,53,60,70,80,90,
        /// 100,106,120,140,158,200,211)
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                LayerHelper.EnsureLayer(db, tr, name);

                var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                var ltr = (LayerTableRecord)tr.GetObject(lt[name], OpenMode.ForWrite);

                if (pars["colorIndex"] != null)
                {
                    short aci = (short)pars["colorIndex"].GetValue<int>();
                    ltr.Color = Color.FromColorIndex(ColorMethod.ByAci, aci);
                }

                if (pars["linetype"] != null)
                {
                    string ltName = pars["linetype"].GetValue<string>();
                    var ltt = (LinetypeTable)tr.GetObject(db.LinetypeTableId, OpenMode.ForRead);
                    if (!ltt.Has(ltName))
                    {
                        try
                        {
                            db.LoadLineTypeFile(ltName, "acad.lin");
                        }
                        catch (System.Exception ex)
                        {
                            throw new InvalidOperationException(
                                $"No se pudo cargar el linetype '{ltName}' desde acad.lin: {ex.Message}");
                        }
                        ltt = (LinetypeTable)tr.GetObject(db.LinetypeTableId, OpenMode.ForRead);
                    }
                    ltr.LinetypeObjectId = ltt[ltName];
                }

                if (pars["lineweightHundredthsMm"] != null)
                {
                    ltr.LineWeight = EntityHelper.ParseLineWeight(
                        pars["lineweightHundredthsMm"].GetValue<int>());
                }

                tr.Commit();
                return new JsonObject { ["status"] = "ok" };
            }
        }
    }
}
