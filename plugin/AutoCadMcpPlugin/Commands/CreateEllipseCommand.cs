using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Elipse o arco elíptico con el constructor REAL de la API (center, normal, majorAxis, ratio, start, end).
    /// Una Ellipse construida vacía (new Ellipse()) es NULA (Ellipse.IsNull, visto en el código descompilado) y
    /// agregarla al dibujo es una violación de acceso que cierra AutoCAD: por eso create_object no la admite.
    /// params: cx, cy, [cz=0], major_x, major_y, ratio (0,1], [start_rad=0], [end_rad=2π], [layer], [lineweight], [colorIndex]
    /// </summary>
    public static class CreateEllipseCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            double cx = pars["cx"].GetValue<double>(), cy = pars["cy"].GetValue<double>();
            double cz = pars["cz"] != null ? pars["cz"].GetValue<double>() : 0.0;
            double mx = pars["major_x"].GetValue<double>(), my = pars["major_y"].GetValue<double>();
            double ratio = pars["ratio"].GetValue<double>();
            double ini = pars["start_rad"] != null ? pars["start_rad"].GetValue<double>() : 0.0;
            double fin = pars["end_rad"] != null ? pars["end_rad"].GetValue<double>() : 2 * Math.PI;
            foreach (var v in new[] { cx, cy, cz, mx, my, ratio, ini, fin })
                if (double.IsNaN(v) || double.IsInfinity(v)) throw new ArgumentException("Hay un número inválido (NaN o infinito).");
            if (Math.Abs(mx) < 1e-12 && Math.Abs(my) < 1e-12) throw new ArgumentException("El eje mayor no puede ser un vector nulo.");
            if (ratio <= 0 || ratio > 1) throw new ArgumentException("'ratio' (eje menor / eje mayor) va de 0 (exclusive) a 1.");
            if (ini < 0 || ini > 2 * Math.PI + 1e-9 || fin <= ini || fin > 2 * Math.PI + 1e-9)
                throw new ArgumentException("Los ángulos van de 0 a 2π y el final tiene que ser mayor que el inicio.");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);
                var e = new Ellipse(new Point3d(cx, cy, cz), Vector3d.ZAxis, new Vector3d(mx, my, 0), ratio, ini, fin);
                if (e.IsNull) { e.Dispose(); throw new InvalidOperationException("AutoCAD construyó una elipse nula con esos datos."); }
                EntityHelper.ApplyCommon(db, tr, e, pars);
                btr.AppendEntity(e);
                tr.AddNewlyCreatedDBObject(e, true);
                var salida = new JsonObject
                {
                    ["handle"] = e.Handle.ToString(), ["majorRadius"] = e.MajorRadius, ["minorRadius"] = e.MinorRadius,
                    ["area"] = (ini == 0 && Math.Abs(fin - 2 * Math.PI) < 1e-9) ? Math.PI * e.MajorRadius * e.MinorRadius : (double?)null
                };
                tr.Commit();
                return salida;
            }
        }
    }
}
