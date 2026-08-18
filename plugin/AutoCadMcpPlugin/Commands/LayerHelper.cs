using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    internal static class LayerHelper
    {
        /// <summary>Crea la capa si no existe (con la transacción ya abierta).</summary>
        public static void EnsureLayer(Database db, Transaction tr, string name)
        {
            var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
            if (lt.Has(name))
                return;

            lt.UpgradeOpen();
            var ltr = new LayerTableRecord { Name = name };
            lt.Add(ltr);
            tr.AddNewlyCreatedDBObject(ltr, true);
        }
    }
}
