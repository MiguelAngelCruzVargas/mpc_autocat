using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Dónde se dibuja: el espacio ACTIVO, no el modelo siempre.
    ///
    /// Con ModelSpace fijo, el cajón y el rótulo terminan dibujados encima del
    /// plano —el marco atraviesa las recámaras— porque no hay forma de mandarlos
    /// al espacio papel. Usando el espacio actual, basta con activar un layout
    /// antes de dibujar el rótulo para que viva donde corresponde.
    /// </summary>
    internal static class SpaceHelper
    {
        /// <summary>El bloque donde van las entidades nuevas, abierto para escritura.</summary>
        public static BlockTableRecord Current(Database db, Transaction tr)
        {
            return (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
        }

        /// <summary>true si el espacio activo es el modelo.</summary>
        public static bool IsModel(Database db)
        {
            return db.CurrentSpaceId == SymbolUtilityServices.GetBlockModelSpaceId(db);
        }
    }
}
