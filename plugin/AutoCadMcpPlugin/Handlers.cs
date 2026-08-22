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
                case "list_hatch_patterns":
                    return ListHatchPatternsCommand.Run(doc, pars);

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
                case "move_entities":
                    return MoveEntitiesCommand.Run(doc, pars);
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
                case "mirror_entity":
                    return MirrorEntityCommand.Run(doc, pars);
                case "array_entity":
                    return ArrayEntityCommand.Run(doc, pars);
                case "find_replace_text":
                    return FindReplaceTextCommand.Run(doc, pars);

                // Referencias externas (xrefs)
                case "attach_xref":
                    return XrefCommands.Attach(doc, pars);
                case "list_xrefs":
                    return XrefCommands.List(doc, pars);
                case "detach_xref":
                    return XrefCommands.Detach(doc, pars);
                case "reload_xref":
                    return XrefCommands.Reload(doc, pars);

                // Consulta
                case "list_entities":
                    return ListEntitiesCommand.Run(doc, pars);
                case "get_entity":
                    return GetEntityCommand.Run(doc, pars);
                case "calculate_area":
                    return CalculateAreaCommand.Run(doc, pars);
                case "get_drawing_info":
                    return GetDrawingInfoCommand.Run(doc, pars);

                // Curvas libres
                case "create_spline":
                    return CreateSplineCommand.Run(doc, pars);

                // Layouts / espacio papel
                case "create_layout":
                    return LayoutCommands.Create(doc, pars);
                case "list_layouts":
                    return LayoutCommands.List(doc, pars);
                case "set_current_layout":
                    return LayoutCommands.SetCurrent(doc, pars);
                case "create_viewport":
                    return LayoutCommands.CreateViewport(doc, pars);

                // Estilos con nombre
                case "set_text_style":
                    return StyleCommands.SetTextStyle(doc, pars);
                case "set_dim_style":
                    return StyleCommands.SetDimStyle(doc, pars);
                case "list_styles":
                    return StyleCommands.ListStyles(doc, pars);

                // Cotas que no son la alineada
                case "create_dimension_rotated":
                    return DimensionCommands.Rotated(doc, pars);
                case "create_dimension_radial":
                    return DimensionCommands.Radial(doc, pars);
                case "create_dimension_diametric":
                    return DimensionCommands.Diametric(doc, pars);
                case "create_dimension_angular":
                    return DimensionCommands.Angular(doc, pars);
                case "create_dimension_arc_length":
                    return DimensionCommands.ArcLength(doc, pars);

                // Seleccion y borrado por zona
                case "select_entities":
                    return SelectCommands.Select(doc, pars);
                case "delete_entities":
                    return SelectCommands.DeleteMany(doc, pars);

                // Limpieza de geometria
                case "union_regions":
                    return UnionRegionsCommand.Run(doc, pars);

                // Medicion
                case "get_extents":
                    return GetExtentsCommand.Run(doc, pars);
                case "measure_text":
                    return MeasureTextCommand.Run(doc, pars);

                // Limpieza
                case "delete_layout":
                    return PurgeCommands.DeleteLayout(doc, pars);
                case "purge_block":
                    return PurgeCommands.PurgeBlock(doc, pars);

                // Guardado / exportacion
                case "save_drawing":
                    return SaveCommands.Save(doc, pars);
                case "export_block":
                    return SaveCommands.ExportBlock(doc, pars);
                case "export_pdf":
                    return PlotCommand.Run(doc, pars);
                case "capture_viewport":
                    return CaptureViewportCommand.Run(doc, pars);

                // Documentos abiertos
                case "list_documents":
                    return DocumentCommands.List(doc, pars);
                case "set_active_document":
                    return DocumentCommands.SetActive(doc, pars);
                case "open_document":
                    return DocumentCommands.Open(doc, pars);
                case "new_document":
                    return DocumentCommands.New(doc, pars);
                case "close_document":
                    return DocumentCommands.Close(doc, pars);
                case "ping":
                    return DocumentCommands.Ping(doc, pars);

                // Vista / visualizacion
                case "set_display_options":
                    return SetDisplayOptionsCommand.Run(doc, pars);
                case "zoom_extents":
                    return ZoomExtentsCommand.Run(doc, pars);
                case "undo":
                    return UndoCommand.Run(doc, pars);

                default:
                    throw new NotSupportedException($"Comando no soportado: '{cmd}'");
            }
        }
    }
}
