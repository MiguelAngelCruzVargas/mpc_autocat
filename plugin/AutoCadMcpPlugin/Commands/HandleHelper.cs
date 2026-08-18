using System;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    internal static class HandleHelper
    {
        /// <summary>Resuelve un handle hex (el que devuelven los create_*) a ObjectId.</summary>
        public static ObjectId GetObjectId(Database db, string handleStr)
        {
            var handle = new Handle(Convert.ToInt64(handleStr, 16));
            var id = db.GetObjectId(false, handle, 0);
            if (id.IsNull || id.IsErased)
                throw new InvalidOperationException($"No existe una entidad con handle '{handleStr}'.");
            return id;
        }
    }
}
