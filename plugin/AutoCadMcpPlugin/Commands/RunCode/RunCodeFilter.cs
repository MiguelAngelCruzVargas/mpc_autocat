using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

namespace AutoCadMcpPlugin.Commands.RunCode
{
    /// <summary>Un uso rechazado por el filtro, con su ubicación en el código de la IA.</summary>
    internal sealed class Blocked
    {
        public int Line;
        public int Column;
        public string Symbol;
        public string Reason;
    }

    /// <summary>
    /// Qué puede tocar el código de run_code: AutoCAD y lo básico de C#, nada más.
    ///
    /// Es una lista de lo PERMITIDO, no de lo prohibido. Una lista negra
    /// siempre se queda corta: bloquear System.IO no sirve si queda abierto
    /// Expression.Compile, o MethodInfo.Invoke, o el objeto COM de AutoCAD
    /// (AcadApplication), que puede mandar comandos y LISP. Con la lista
    /// blanca, lo que nadie pensó queda afuera solo.
    ///
    /// Se mira el MODELO SEMÁNTICO, no el texto: "System.IO.File", un alias
    /// "using F = System.IO.File;" o un "var" que esconde el tipo resuelven
    /// todos al mismo símbolo, y es el símbolo lo que se juzga.
    ///
    /// Esto ataja también la inyección por contenido: si la IA lee un texto
    /// malicioso (un PDF, un DWG ajeno) que le dicta código, ese código igual
    /// no puede salir de AutoCAD. Con permitir_sistema=true (lo prende el
    /// usuario a mano) el filtro no corre.
    /// </summary>
    internal static class RunCodeFilter
    {
        private const string NamespaceScript = "AutoCadMcpScript";

        private static readonly HashSet<string> NamespacesPermitidos = new HashSet<string>(StringComparer.Ordinal)
        {
            "System",
            "System.Collections",
            "System.Collections.Generic",
            "System.Collections.ObjectModel",
            "System.Collections.Specialized",
            "System.Linq",
            "System.Text",
            "System.Text.RegularExpressions",
            "System.Globalization",
            // Solo lectura: describe_api lista tipos y miembros. Invocar,
            // asignar, cargar o crear instancias está cortado abajo.
            "System.Reflection",
            "Autodesk.AutoCAD.ApplicationServices",
            "Autodesk.AutoCAD.ApplicationServices.Core",
            "Autodesk.AutoCAD.BoundaryRepresentation",
            "Autodesk.AutoCAD.Colors",
            "Autodesk.AutoCAD.DatabaseServices",
            "Autodesk.AutoCAD.DatabaseServices.Filters",
            "Autodesk.AutoCAD.EditorInput",
            "Autodesk.AutoCAD.Geometry",
            "Autodesk.AutoCAD.GraphicsInterface",
            "Autodesk.AutoCAD.GraphicsSystem",
            "Autodesk.AutoCAD.LayerManager",
            "Autodesk.AutoCAD.Runtime",
        };

        /// <summary>Tipos enteros fuera, aunque su namespace esté permitido.</summary>
        private static readonly Dictionary<string, string> TiposProhibidos = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["System.Environment"] = "variables de entorno y salir del proceso",
            ["System.Activator"] = "crear instancias de cualquier tipo por nombre",
            ["System.Runtime.CompilerServices.RuntimeHelpers"] = "acceso al runtime",
            ["Autodesk.AutoCAD.Runtime.SystemObjects"] = "DynamicLinker: cargar DLLs",
            ["Autodesk.AutoCAD.Runtime.DynamicLinker"] = "cargar DLLs",
            ["Autodesk.AutoCAD.Runtime.Interop"] = "puente COM",
            ["Autodesk.AutoCAD.Runtime.ExtensionLoader"] = "cargar módulos",
            ["Autodesk.AutoCAD.Runtime.RegistryKey"] = "registro de Windows",
            ["Autodesk.AutoCAD.Runtime.SynchronizationContext"] = "ejecución diferida, fuera de la transacción",
            ["Autodesk.AutoCAD.ApplicationServices.UserConfigurationManager"] = "escribe el perfil de AutoCAD (registro)",
            ["Autodesk.AutoCAD.ApplicationServices.IConfigurationSection"] = "escribe el perfil de AutoCAD (registro)",
            ["Autodesk.AutoCAD.ApplicationServices.InplaceTextEditor"] = "editor interactivo",
            ["Autodesk.AutoCAD.GraphicsSystem.Configuration"] = "escribe el registro",
            ["Autodesk.AutoCAD.DatabaseServices.DataLink"] = "lee/escribe planillas externas",
            ["Autodesk.AutoCAD.DatabaseServices.DataLinkManager"] = "lee/escribe planillas externas",
        };

        /// <summary>Familias de tipos fuera por prefijo de nombre completo.</summary>
        private static readonly Dictionary<string, string> PrefijosProhibidos = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Autodesk.AutoCAD.EditorInput.LivePreview"] = "vista previa interactiva: ejecuta comandos",
        };

        /// <summary>
        /// Miembros fuera, por el tipo que los DECLARA. La regla de cada uno:
        /// ejecutan algo que el filtro no puede ver (comandos, LISP, COM),
        /// escriben archivos, cierran/abren dibujos con el documento tomado
        /// (AutoCAD se cae) o esperan una respuesta del usuario (el socket se
        /// congela hasta que alguien la dé).
        /// </summary>
        private static readonly Dictionary<string, HashSet<string>> MiembrosProhibidos = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal)
        {
            ["Autodesk.AutoCAD.EditorInput.Editor"] = Set(
                "Command", "CommandAsync", "Drag", "DoPrompt", "StartUserInteraction",
                "GetPoint", "GetDistance", "GetAngle", "GetCorner", "GetString", "GetKeywords",
                "GetInteger", "GetDouble", "GetEntity", "GetNestedEntity", "GetSelection",
                "GetFileNameForOpen", "GetFileNameForSave"),
            ["Autodesk.AutoCAD.ApplicationServices.Document"] = Set(
                "SendStringToExecute", "CloseAndSave", "CloseAndDiscard", "AcadDocument",
                "StartUserInteraction"),
            ["Autodesk.AutoCAD.ApplicationServices.DocumentCollection"] = Set(
                "CloseAll", "Open", "Add", "ExecuteInApplicationContext",
                "ExecuteInCommandContextAsync", "AppContextCloseDocument",
                "AppContextNewDocument", "AppContextOpenDocument"),
            ["Autodesk.AutoCAD.ApplicationServices.Application"] = Set(
                "Quit", "Invoke", "SetSystemVariable", "AcadApplication", "ShowModalDialog",
                "ShowModelessDialog", "ShowAlertDialog", "ShowModalWindow",
                "ShowModelessWindow", "LoadPartialMenu", "LoadMainMenu", "UnloadPartialMenu",
                "LoadJSScript", "InvokeHelp", "InvokeContextHelp", "InvokeHelpForExternal",
                "PostSearchQuery"),
            ["Autodesk.AutoCAD.ApplicationServices.Core.Application"] = Set(
                "Quit", "Invoke", "SetSystemVariable", "AcadApplication", "ShowAlertDialog",
                "LoadJSScript", "InvokeHelp", "InvokeContextHelp", "InvokeHelpForExternal",
                "PostSearchQuery"),
            // Los métodos de extensión se declaran en OTRA clase: doc.CloseAndSave
            // es de DocumentExtension, no de Document. Sin estas dos entradas el
            // banco de pruebas los dejaba pasar.
            ["Autodesk.AutoCAD.ApplicationServices.DocumentExtension"] = Set(
                "CloseAndSave", "CloseAndDiscard"),
            ["Autodesk.AutoCAD.ApplicationServices.DocumentCollectionExtension"] = Set(
                "CloseAll", "Open", "Add"),
            ["Autodesk.AutoCAD.EditorInput.EditorExtension"] = Set("StartUserInteraction"),
            ["Autodesk.AutoCAD.DatabaseServices.Database"] = Set(
                "SaveAs", "Save", "ReadDwgFile", "DxfOut", "DxfOutEx", "DxfIn", "AcadDatabase",
                "CloseInput"),
            ["Autodesk.AutoCAD.DatabaseServices.HostApplicationServices"] = Set("LoadApplication"),
            ["Autodesk.AutoCAD.DatabaseServices.LayerStateManager"] = Set("ExportLayerState"),
            ["Autodesk.AutoCAD.DatabaseServices.RenderGlobal"] = Set("SaveFileName", "SaveEnabled"),
            ["Autodesk.AutoCAD.DatabaseServices.DBObject"] = Set("AcadObject"),
            ["System.Delegate"] = Set("DynamicInvoke", "CreateDelegate"),
            ["System.Type"] = Set("InvokeMember", "GetTypeFromProgID", "GetTypeFromCLSID"),
            ["System.AppDomain"] = null, // tratado aparte: solo CurrentDomain y GetAssemblies
        };

        /// <summary>En System.Reflection se puede mirar, no tocar.</summary>
        private static readonly HashSet<string> ReflexionProhibida = Set(
            "Invoke", "SetValue", "GetValue", "SetValueDirect", "GetValueDirect",
            "CreateDelegate", "CreateInstance", "InvokeMember", "Load", "LoadFrom", "LoadFile",
            "UnsafeLoadFrom", "LoadWithPartialName", "ReflectionOnlyLoad",
            "ReflectionOnlyLoadFrom", "GetManifestResourceStream", "AddEventHandler",
            "RemoveEventHandler", "RaiseEvent");

        private static readonly HashSet<string> AppDomainPermitido = Set("CurrentDomain", "GetAssemblies");

        private static HashSet<string> Set(params string[] nombres) => new HashSet<string>(nombres, StringComparer.Ordinal);

        /// <summary>
        /// Revisa solo lo que cae dentro del código de la IA (userSpan): la
        /// plantilla que lo envuelve es nuestra.
        /// </summary>
        public static List<Blocked> Check(SemanticModel model, SyntaxNode root, TextSpan userSpan)
        {
            var bloqueos = new List<Blocked>();
            var vistos = new HashSet<string>(StringComparer.Ordinal);

            void Bloquear(SyntaxNode nodo, string simbolo, string motivo)
            {
                var pos = nodo.GetLocation().GetMappedLineSpan().StartLinePosition;
                var clave = pos.Line + "|" + simbolo;
                if (!vistos.Add(clave))
                    return;
                bloqueos.Add(new Blocked
                {
                    Line = pos.Line + 1,
                    Column = pos.Character + 1,
                    Symbol = simbolo,
                    Reason = motivo,
                });
            }

            foreach (var nodo in root.DescendantNodes(n => n.FullSpan.IntersectsWith(userSpan)))
            {
                if (!userSpan.Contains(nodo.Span))
                    continue;

                switch (nodo.Kind())
                {
                    case SyntaxKind.UnsafeStatement:
                    case SyntaxKind.FixedStatement:
                    case SyntaxKind.PointerType:
                    case SyntaxKind.StackAllocArrayCreationExpression:
                    case SyntaxKind.ImplicitStackAllocArrayCreationExpression:
                    case SyntaxKind.MakeRefExpression:
                    case SyntaxKind.RefTypeExpression:
                    case SyntaxKind.RefValueExpression:
                    case SyntaxKind.ArgListExpression:
                    case SyntaxKind.FunctionPointerType:
                        Bloquear(nodo, nodo.Kind().ToString(), "código inseguro (punteros/memoria directa)");
                        continue;
                }

                // Una función local 'extern' + [DllImport] llama directo a una
                // DLL de Windows: es la puerta trasera más corta que hay.
                if (nodo is LocalFunctionStatementSyntax local
                    && local.Modifiers.Any(m => m.IsKind(SyntaxKind.ExternKeyword)
                                                || m.IsKind(SyntaxKind.UnsafeKeyword)))
                {
                    Bloquear(nodo, local.Identifier.Text, "función 'extern'/'unsafe': llamada directa a código nativo");
                    continue;
                }

                if (nodo is ExpressionSyntax || nodo is TypeSyntax)
                {
                    var info = model.GetSymbolInfo(nodo);
                    var simbolo = info.Symbol ?? info.CandidateSymbols.FirstOrDefault();
                    var motivo = RevisarSimbolo(simbolo);
                    if (motivo != null)
                        Bloquear(nodo, Nombre(simbolo), motivo);

                    var tipo = model.GetTypeInfo(nodo);
                    foreach (var t in new[] { tipo.Type, tipo.ConvertedType })
                    {
                        motivo = RevisarTipo(t);
                        if (motivo != null)
                            Bloquear(nodo, Nombre(t), motivo);
                    }
                }
                else if (nodo is VariableDeclaratorSyntax || nodo is ParameterSyntax
                         || nodo is LocalFunctionStatementSyntax || nodo is ForEachStatementSyntax
                         || nodo is SingleVariableDesignationSyntax || nodo is CatchDeclarationSyntax)
                {
                    var declarado = model.GetDeclaredSymbol(nodo);
                    var motivo = RevisarSimbolo(declarado);
                    if (motivo != null)
                        Bloquear(nodo, Nombre(declarado), motivo);
                }
            }
            return bloqueos;
        }

        private static string Nombre(ISymbol s) => s?.ToDisplayString() ?? "?";

        private static string RevisarSimbolo(ISymbol s)
        {
            switch (s)
            {
                case null:
                case INamespaceSymbol _:
                case ILabelSymbol _:
                case IRangeVariableSymbol _:
                case IDiscardSymbol _:
                    return null;
                case IAliasSymbol alias:
                    return RevisarSimbolo(alias.Target);
                case ITypeSymbol t:
                    return RevisarTipo(t);
                case ILocalSymbol local:
                    return RevisarTipo(local.Type);
                case IParameterSymbol p:
                    return RevisarTipo(p.Type);
                case IMethodSymbol m:
                    if (m.MethodKind == MethodKind.AnonymousFunction || m.MethodKind == MethodKind.LocalFunction)
                        return RevisarTipo(m.ReturnType);
                    var original = m.ReducedFrom ?? m;
                    return RevisarTipo(original.ContainingType)
                        ?? RevisarMiembro(original.ContainingType, original.Name, original.IsStatic)
                        ?? RevisarTipo(m.ReturnType);
                case IPropertySymbol prop:
                    return RevisarTipo(prop.ContainingType)
                        ?? RevisarMiembro(prop.ContainingType, prop.Name, prop.IsStatic)
                        ?? RevisarTipo(prop.Type);
                case IFieldSymbol campo:
                    return RevisarTipo(campo.ContainingType)
                        ?? RevisarMiembro(campo.ContainingType, campo.Name, campo.IsStatic)
                        ?? RevisarTipo(campo.Type);
                case IEventSymbol ev:
                    return RevisarTipo(ev.ContainingType)
                        ?? RevisarMiembro(ev.ContainingType, ev.Name, ev.IsStatic);
                default:
                    return "construcción no permitida (" + s.Kind + ")";
            }
        }

        private static string RevisarTipo(ITypeSymbol t, int profundidad = 0)
        {
            if (t == null || profundidad > 8)
                return null;
            switch (t.TypeKind)
            {
                case TypeKind.Dynamic:
                    return "'dynamic' esquiva la revisión de tipos";
                case TypeKind.Pointer:
                case TypeKind.FunctionPointer:
                    return "punteros";
                case TypeKind.TypeParameter:
                case TypeKind.Error:
                    return null;
                case TypeKind.Array:
                    return RevisarTipo(((IArrayTypeSymbol)t).ElementType, profundidad + 1);
            }
            if (!(t is INamedTypeSymbol nt))
                return null;
            if (nt.IsAnonymousType)
                return null;

            // El tipo de más afuera manda el namespace (los anidados no tienen).
            var externo = nt;
            while (externo.ContainingType != null)
                externo = externo.ContainingType;
            var ns = externo.ContainingNamespace;
            string nsTexto = ns == null || ns.IsGlobalNamespace ? "" : ns.ToDisplayString();
            string completo = nsTexto.Length == 0 ? externo.MetadataName : nsTexto + "." + externo.MetadataName;
            completo = completo.Split('`')[0];

            if (nsTexto == NamespaceScript)
                return null;
            if (nsTexto.StartsWith("AutoCadMcpPlugin", StringComparison.Ordinal))
            {
                return externo.Name == nameof(ScriptBase)
                    ? null
                    : "interno del plugin";
            }
            if (nsTexto.Length > 0 && !NamespacesPermitidos.Contains(nsTexto))
                return "fuera de lo permitido: solo AutoCAD y lo básico de C# (" + nsTexto + ")";
            if (TiposProhibidos.TryGetValue(completo, out var motivoTipo))
                return motivoTipo;
            foreach (var p in PrefijosProhibidos)
                if (completo.StartsWith(p.Key, StringComparison.Ordinal))
                    return p.Value;

            foreach (var arg in nt.TypeArguments)
            {
                var m = RevisarTipo(arg, profundidad + 1);
                if (m != null)
                    return m;
            }
            return null;
        }

        private static string RevisarMiembro(INamedTypeSymbol tipo, string miembro, bool estatico)
        {
            if (tipo == null)
                return null;
            var def = tipo.OriginalDefinition;
            string ns = def.ContainingNamespace == null || def.ContainingNamespace.IsGlobalNamespace
                ? "" : def.ContainingNamespace.ToDisplayString();
            string completo = (ns.Length == 0 ? def.MetadataName : ns + "." + def.MetadataName).Split('`')[0];

            if (completo == "System.AppDomain")
                return AppDomainPermitido.Contains(miembro)
                    ? null
                    : "AppDomain: solo CurrentDomain y GetAssemblies";
            if (completo == "System.Type" && miembro == "GetType" && estatico)
                return "Type.GetType(string) carga tipos por nombre";
            if (ns == "System.Reflection" && ReflexionProhibida.Contains(miembro))
                return "reflexión que ejecuta o carga código (solo se permite mirar)";
            if (MiembrosProhibidos.TryGetValue(completo, out var prohibidos)
                && prohibidos != null && prohibidos.Contains(miembro))
                return "ejecuta algo fuera del alcance del filtro, toca archivos o espera al usuario";
            return null;
        }
    }
}
