using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using AutoCadMcpPlugin.Commands;

namespace AutoCadMcpPlugin
{
    /// <summary>
    /// Tabla de comandos soportados. Agregar un tool nuevo = agregar un case acá
    /// + una clase en Commands/.
    /// </summary>
    public static class Handlers
    {
        public static JsonObject Execute(string cmd, Document doc, JsonObject pars)
        {
            switch (cmd)
            {
                // Geometría
                case "create_line":
                    return CreateLineCommand.Run(doc, pars);
                case "create_polyline":
                    return CreatePolylineCommand.Run(doc, pars);
                case "create_circle":
                    return CreateCircleCommand.Run(doc, pars);
                case "create_arc":
                    return CreateArcCommand.Run(doc, pars);

                // Anotación
                case "create_text":
                    return CreateTextCommand.Run(doc, pars);
                case "create_mtext":
                    return CreateMTextCommand.Run(doc, pars);
                case "create_dimension":
                    return CreateDimensionCommand.Run(doc, pars);
                case "create_leader":
                    return CreateLeaderCommand.Run(doc, pars);
                case "create_hatch":
                    return CreateHatchCommand.Run(doc, pars);

                // Bloques / símbolos / imágenes
                case "insert_block":
                    return InsertBlockCommand.Run(doc, pars);
                case "define_block":
                    return DefineBlockCommand.Run(doc, pars);
                case "attach_image":
                    return AttachImageCommand.Run(doc, pars);

                // Capas (simbología / normas)
                case "set_layer":
                    return SetLayerCommand.Run(doc, pars);
                case "list_layers":
                    return ListLayersCommand.Run(doc, pars);

                // Edición
                case "move_entity":
                    return MoveEntityCommand.Run(doc, pars);
                case "copy_entity":
                    return CopyEntityCommand.Run(doc, pars);
                case "rotate_entity":
                    return RotateEntityCommand.Run(doc, pars);
                case "scale_entity":
                    return ScaleEntityCommand.Run(doc, pars);
                case "delete_entity":
                    return DeleteEntityCommand.Run(doc, pars);
                case "offset_entity":
                    return OffsetEntityCommand.Run(doc, pars);

                // Consulta
                case "list_entities":
                    return ListEntitiesCommand.Run(doc, pars);
                case "get_entity":
                    return GetEntityCommand.Run(doc, pars);
                case "calculate_area":
                    return CalculateAreaCommand.Run(doc, pars);
                case "get_drawing_info":
                    return GetDrawingInfoCommand.Run(doc, pars);

                // Vista / visualizacion
                case "set_display_options":
                    return SetDisplayOptionsCommand.Run(doc, pars);
                case "zoom_extents":
                    return ZoomExtentsCommand.Run(doc, pars);

                default:
                    throw new NotSupportedException($"Comando no soportado: '{cmd}'");
            }
        }
    }
}
