using System;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Fusiona contornos cerrados en uno solo (unión booleana).
    ///
    /// Es lo que limpia los encuentros de muros. Cada tramo se dibuja como un
    /// contorno cerrado propio, así que donde dos muros se cruzan quedan las
    /// líneas de ambos atravesando la unión: se ve un cajón en el cruce en vez
    /// de una T o una esquina limpia. Uniendo las regiones, esas líneas
    /// interiores desaparecen y queda el perímetro real de la mampostería.
    /// params: handles ([...] de polilíneas CERRADAS), [deleteSources=true]
    /// </summary>
    public static class UnionRegionsCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var handleArray = pars["handles"].AsArray();
            bool borrarOrigen = pars["deleteSources"] == null
                || pars["deleteSources"].GetValue<bool>();

            if (handleArray.Count < 2)
                throw new ArgumentException(
                    "Para unir hacen falta al menos 2 contornos cerrados.");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var curvas = new DBObjectCollection();
                var originales = new System.Collections.Generic.List<Entity>();
                string capa = null;
                int grosor = 0;

                foreach (var h in handleArray)
                {
                    string handleStr = h.GetValue<string>();
                    var ent = (Entity)tr.GetObject(
                        HandleHelper.GetObjectId(db, handleStr), OpenMode.ForWrite);

                    var pl = ent as Polyline;
                    if (pl == null || !pl.Closed)
                        throw new InvalidOperationException(
                            $"'{handleStr}' no es una polilínea cerrada; la unión " +
                            "solo trabaja con contornos cerrados.");

                    if (capa == null)
                    {
                        capa = pl.Layer;
                        grosor = (int)pl.LineWeight;
                    }
                    curvas.Add(pl);
                    originales.Add(ent);
                }

                DBObjectCollection regiones;
                try
                {
                    regiones = Region.CreateFromCurves(curvas);
                }
                catch (System.Exception ex)
                {
                    throw new InvalidOperationException(
                        "No se pudieron convertir los contornos a región: " +
                        ex.Message);
                }

                if (regiones.Count == 0)
                    throw new InvalidOperationException(
                        "Ningún contorno pudo convertirse en región.");

                var resultado = (Region)regiones[0];
                int unidas = 1;
                var sueltas = new System.Collections.Generic.List<Region>();
                for (int i = 1; i < regiones.Count; i++)
                {
                    var otra = (Region)regiones[i];
                    bool unida = false;
                    try
                    {
                        resultado.BooleanOperation(BooleanOperationType.BoolUnite, otra);
                        unida = true;
                        unidas++;
                    }
                    catch (System.Exception)
                    {
                        // Esa región NO quedó dentro del resultado. Antes se
                        // descartaba y el contorno original se borraba igual:
                        // el tramo de muro desaparecía del dibujo sin aviso.
                        // Tampoco sirve conservar los originales: lo que SÍ se
                        // unió quedaría dos veces (Region + polilínea encima),
                        // y CreateFromCurves no mapea curva -> región 1 a 1
                        // como para conservar solo los que fallaron. Va al
                        // dibujo como región suelta.
                        sueltas.Add(otra);
                    }
                    finally
                    {
                        if (unida)
                            otra.Dispose();
                    }
                }

                var btr = SpaceHelper.Current(db, tr);

                var salidaSueltas = new JsonArray();
                foreach (var r in new[] { resultado }.Concat(sueltas))
                {
                    if (capa != null)
                        r.Layer = capa;
                    r.LineWeight = EntityHelper.ParseLineWeight(grosor);
                    btr.AppendEntity(r);
                    tr.AddNewlyCreatedDBObject(r, true);
                    if (r != resultado)
                        salidaSueltas.Add(r.Handle.ToString());
                }

                if (borrarOrigen)
                    foreach (var e in originales)
                        e.Erase();

                var salida = new JsonObject
                {
                    ["handle"] = resultado.Handle.ToString(),
                    ["merged"] = unidas,
                    ["area"] = resultado.Area,
                    ["perimeter"] = resultado.Perimeter,
                    ["sourcesDeleted"] = borrarOrigen
                };
                if (sueltas.Count > 0)
                {
                    salida["failed"] = sueltas.Count;
                    salida["looseHandles"] = salidaSueltas;
                    salida["warning"] =
                        $"{sueltas.Count} región(es) no se pudieron unir: quedaron " +
                        "como regiones sueltas (en 'looseHandles') para no perder " +
                        "ningún tramo. Revisá ese encuentro.";
                }
                tr.Commit();
                return salida;
            }
        }
    }
}
