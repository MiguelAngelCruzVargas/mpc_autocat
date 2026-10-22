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
                case "create_ellipse":
                    return CreateEllipseCommand.Run(doc, pars);
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
                case "fillet_solid_edges":
                    return FilletSolidEdgesCommand.Run(doc, pars);
                case "extrude_profile":
                    return SolidCommands.Extrude(doc, pars);
                case "solid_boolean":
                    return SolidCommands.Boolean(doc, pars);

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

                // Propiedades de cualquier objeto por reflexión (PropertiesCommands)
                case "get_properties":
                    return PropertiesCommands.Get(doc, pars);
                case "set_properties":
                    return PropertiesCommands.Set(doc, pars);
                case "list_children":
                    return PropertiesCommands.Children(doc, pars);
                // Operaciones nativas de la base de datos (DatabaseExtraCommands)
                case "list_plot_options":
                    return LayoutPlotCommands.Options(doc, pars);
                case "configure_layout":
                    return LayoutPlotCommands.Configure(doc, pars);
                case "get_dynamic_block_properties":
                    return LayoutPlotCommands.DynamicGet(doc, pars);
                case "set_dynamic_block_properties":
                    return LayoutPlotCommands.DynamicSet(doc, pars);
                case "purge_database_objects":
                    return DatabaseExtraCommands.Purge(doc, pars);
                case "set_current":
                    return DatabaseExtraCommands.SetCurrent(doc, pars);
                case "create_group":
                    return DatabaseExtraCommands.GroupCreate(doc, pars);
                case "delete_group":
                    return DatabaseExtraCommands.GroupDelete(doc, pars);
                case "modify_group":
                    return DatabaseExtraCommands.GroupModify(doc, pars);
                case "get_xdata":
                    return DatabaseExtraCommands.XDataGet(doc, pars);
                case "set_xdata":
                    return DatabaseExtraCommands.XDataSet(doc, pars);
                case "clear_xdata":
                    return DatabaseExtraCommands.XDataClear(doc, pars);
                case "get_custom_data":
                    return DatabaseExtraCommands.CustomGet(doc, pars);
                case "set_custom_data":
                    return DatabaseExtraCommands.CustomSet(doc, pars);
                case "delete_custom_data":
                    return DatabaseExtraCommands.CustomDelete(doc, pars);
                case "get_block_attributes":
                    return DatabaseExtraCommands.AttributesGet(doc, pars);
                case "set_block_attributes":
                    return DatabaseExtraCommands.AttributesSet(doc, pars);
                case "list_annotation_scales":
                    return DatabaseExtraCommands.ScalesList(doc, pars);
                case "add_annotation_scale":
                    return DatabaseExtraCommands.ScaleAdd(doc, pars);
                case "set_current_annotation_scale":
                    return DatabaseExtraCommands.ScaleSetCurrent(doc, pars);
                case "remove_annotation_scale":
                    return DatabaseExtraCommands.ScaleRemove(doc, pars);
                case "merge_layers":
                    return LayerOpsCommands.Merge(doc, pars);
                case "delete_layer_with_objects":
                    return LayerOpsCommands.DeleteWithObjects(doc, pars);
                case "save_layer_state":
                    return LayerOpsCommands.StateSave(doc, pars);
                case "restore_layer_state":
                    return LayerOpsCommands.StateRestore(doc, pars);
                case "list_layer_states":
                    return LayerOpsCommands.StateList(doc, pars);
                case "delete_layer_state":
                    return LayerOpsCommands.StateDelete(doc, pars);
                case "isolate_layers":
                    return LayerOpsCommands.Isolate(doc, pars);
                case "unisolate_layers":
                    return LayerOpsCommands.Unisolate(doc, pars);
                case "set_viewport_layers":
                    return LayerOpsCommands.ViewportLayers(doc, pars);
                case "export_copy":
                    return SaveCommands.ExportCopy(doc, pars);
                case "stretch_entities":
                    return EditExtra2Commands.Stretch(doc, pars);
                case "lengthen_curve":
                    return EditExtra2Commands.Lengthen(doc, pars);
                case "align_entities":
                    return EditExtra2Commands.Align(doc, pars);
                case "create_wipeout":
                    return EditExtra2Commands.Wipeout(doc, pars);
                case "attach_pdf_underlay":
                    return UnderlayCommands.AttachPdf(doc, pars);
                case "create_surface":
                    return SurfaceCommands.Create(doc, pars);
                case "offset_surface":
                    return SurfaceCommands.Offset(doc, pars);
                case "create_nurb_surface":
                    return SurfaceCommands.NurbsDesdePuntos(doc, pars);
                case "create_mesh_from_faces":
                    return SurfaceCommands.MallaDesdeCaras(doc, pars);
                case "bind_xref":
                    return XrefCommands.Bind(doc, pars);
                case "unload_xref":
                    return XrefCommands.Unload(doc, pars);
                case "get_drawing_properties":
                    return DrawingPropsCommands.Get(doc, pars);
                case "set_drawing_properties":
                    return DrawingPropsCommands.Set(doc, pars);
                case "explode_entities":
                    return EditExtraCommands.Explode(doc, pars);
                case "break_curve":
                    return EditExtraCommands.Break(doc, pars);
                case "divide_curve":
                    return EditExtraCommands.Divide(doc, pars);
                case "create_boundary":
                    return EditExtraCommands.Boundary(doc, pars);
                case "match_properties":
                    return EditExtraCommands.MatchProperties(doc, pars);
                case "extrude_solid":
                    return Solid3dOpsCommands.Extrude(doc, pars);
                case "revolve_solid":
                    return Solid3dOpsCommands.Revolve(doc, pars);
                case "sweep_solid":
                    return Solid3dOpsCommands.Sweep(doc, pars);
                case "loft_solid":
                    return Solid3dOpsCommands.Loft(doc, pars);
                case "rename_layout":
                    return LayoutManageCommands.Rename(doc, pars);
                case "copy_layout":
                    return LayoutManageCommands.Copy(doc, pars);

                case "create_database_object":
                    return DatabaseObjectsCommands.Create(doc, pars);
                case "delete_database_object":
                    return DatabaseObjectsCommands.Delete(doc, pars);
                case "create_object":
                    return PropertiesCommands.Create(doc, pars);
                case "list_properties":
                    return PropertiesCommands.List(doc, pars);

                // Métodos de los objetos por reflexión (MethodsCommands)
                case "list_methods":
                    return MethodsCommands.List(doc, pars);
                case "call_method":
                    return MethodsCommands.Call(doc, pars);

                // Edición con el motor nativo de AutoCAD: TRIM, EXTEND, FILLET, JOIN,
                // OVERKILL (comando fijo por operación; ver NativeOpsCommand)
                case "native_op":
                    return NativeOpsCommand.Run(doc, pars);
                case "native_status":
                    return NativeOpsCommand.Status(doc, pars);

                // Variables de sistema y estado del editor (SystemVariableCommands)
                case "get_system_variables":
                    return SystemVariableCommands.Get(doc, pars);
                case "set_system_variable":
                    return SystemVariableCommands.Set(doc, pars);
                case "get_editor_state":
                    return SystemVariableCommands.EditorState(doc, pars);

                // Varios comandos en un solo viaje
                case "batch":
                    return BatchCommand.Run(doc, pars);

                // Acceso total a la API (apagado salvo que el usuario lo active)
                case "run_code":
                    return RunCodeCommand.Run(doc, pars);

                default:
                    throw new NotSupportedException($"Comando no soportado: '{cmd}'");
            }
        }
    }
}
