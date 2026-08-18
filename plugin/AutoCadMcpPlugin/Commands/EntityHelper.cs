using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Propiedades comunes a toda entidad que creamos (capa, grosor, color).
    /// Centralizado acá para que agregar una propiedad nueva no signifique
    /// tocar los 15 comandos de creación uno por uno.
    /// </summary>
    internal static class EntityHelper
    {
        /// <summary>
        /// Los únicos grosores que AutoCAD acepta, en centésimas de mm.
        /// </summary>
        private static readonly int[] GrosoresValidos =
        {
            0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90,
            100, 106, 120, 140, 158, 200, 211
        };

        /// <summary>
        /// Convierte un grosor a LineWeight validando primero.
        ///
        /// Un cast directo de un valor que no está en la enumeración —17, por
        /// ejemplo— no falla al compilar pero deja a AutoCAD en un estado
        /// inconsistente: tira eOutOfRange y de ahí en adelante puede caerse.
        /// Vale mucho más un error claro que un dibujo a medias y el programa
        /// cerrándose.
        /// </summary>
        public static LineWeight ParseLineWeight(int valor)
        {
            // Los negativos son los especiales: ByLayer, ByBlock, Default.
            if (valor == (int)LineWeight.ByLayer
                || valor == (int)LineWeight.ByBlock
                || valor == (int)LineWeight.ByLineWeightDefault)
                return (LineWeight)valor;

            foreach (int v in GrosoresValidos)
                if (v == valor)
                    return (LineWeight)valor;

            throw new ArgumentException(
                $"Grosor de línea inválido: {valor}. AutoCAD solo acepta " +
                $"{string.Join(", ", GrosoresValidos)} (centésimas de mm), " +
                "o -1 ByLayer / -2 ByBlock / -3 por defecto.");
        }

        /// <summary>
        /// Aplica layer / lineweight / colorIndex desde los params del request.
        /// Crea la capa si hace falta. Se llama con la entidad ya construida y
        /// la transacción abierta; sirve tanto antes como después de
        /// AppendEntity.
        /// params leídos: [layer], [lineweight] (centésimas de mm), [colorIndex] (ACI)
        /// </summary>
        public static void ApplyCommon(Database db, Transaction tr, Entity ent, JsonObject pars)
        {
            string layer = pars["layer"]?.GetValue<string>();
            if (!string.IsNullOrEmpty(layer))
            {
                LayerHelper.EnsureLayer(db, tr, layer);
                ent.Layer = layer;
            }

            // Grosor por entidad. Sin esto todo queda ByLayer, y una capa recién
            // creada nace con el grosor por defecto del dibujo (fino).
            if (pars["lineweight"] != null)
                ent.LineWeight = ParseLineWeight(pars["lineweight"].GetValue<int>());

            if (pars["colorIndex"] != null)
                ent.Color = Color.FromColorIndex(ColorMethod.ByAci, (short)pars["colorIndex"].GetValue<int>());
        }
    }
}
