using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Application;
using AcDoc = Autodesk.AutoCAD.ApplicationServices.Document;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>
    /// Lo que el panel nativo sabe de AutoCAD sin pasar por el servidor: el dibujo activo, lo que hay seleccionado y el
    /// tema de colores. Es la parte «activa» de la integración: el chat ve lo que la persona está tocando.
    /// </summary>
    internal sealed class ContextoCad : IContextoCad
    {
        public event Action Cambio;
        private readonly HashSet<AcDoc> _docs = new HashSet<AcDoc>();

        public ContextoCad()
        {
            try
            {
                var dm = AcApp.DocumentManager;
                foreach (AcDoc d in dm) Enganchar(d);
                dm.DocumentCreated += (s, e) => { Enganchar(e.Document); Avisar(); };
                dm.DocumentActivated += (s, e) => Avisar();
                dm.DocumentToBeDestroyed += (s, e) => { Soltar(e.Document); Avisar(); };
            }
            catch { /* sin documentos todavía: el panel se ve igual */ }
        }

        private void Enganchar(AcDoc d)
        {
            if (d != null && _docs.Add(d)) d.ImpliedSelectionChanged += SeleccionCambio;
        }

        private void Soltar(AcDoc d)
        {
            if (d != null && _docs.Remove(d)) d.ImpliedSelectionChanged -= SeleccionCambio;
        }

        private void SeleccionCambio(object sender, EventArgs e) => Avisar();

        private void Avisar() { try { Cambio?.Invoke(); } catch { } }

        public string VersionAutoCad
        {
            get
            {
                try { return "AutoCAD " + AcApp.Version.Major + "." + AcApp.Version.Minor + " (" + AcApp.Version + ")"; }
                catch { return "desconocida"; }
            }
        }

        public string NombreDibujo
        {
            get
            {
                try
                {
                    var d = AcApp.DocumentManager.MdiActiveDocument;
                    return d == null ? "" : Path.GetFileName(d.Name);
                }
                catch { return ""; }
            }
        }

        public int Seleccionados
        {
            get
            {
                try
                {
                    var d = AcApp.DocumentManager.MdiActiveDocument;
                    if (d == null) return 0;
                    var r = d.Editor.SelectImplied();
                    return r.Status == PromptStatus.OK ? r.Value.Count : 0;
                }
                catch { return 0; }
            }
        }

        public string DescribirSeleccion(int max)
        {
            try
            {
                var d = AcApp.DocumentManager.MdiActiveDocument;
                var r = d.Editor.SelectImplied();
                if (r.Status != PromptStatus.OK) return null;
                var ids = r.Value.GetObjectIds();
                var sb = new StringBuilder();
                sb.Append("[Contexto de AutoCAD] Dibujo activo: ").Append(Path.GetFileName(d.Name)).Append(". ");
                sb.Append("La persona tiene seleccionadas ").Append(ids.Length).Append(" entidad(es)");
                if (ids.Length > max) sb.Append(" (se listan las primeras ").Append(max).Append(')');
                sb.AppendLine(". Si dice «esto», «lo seleccionado» o «estos», se refiere a:");
                int n = 0;
                using (var tr = d.TransactionManager.StartOpenCloseTransaction())
                {
                    foreach (var id in ids)
                    {
                        if (n++ >= max) break;
                        try
                        {
                            var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                            if (ent == null) continue;
                            sb.Append("- ").Append(ent.GetType().Name).Append(" handle=").Append(ent.Handle.ToString())
                              .Append(" capa=").AppendLine(ent.Layer);
                        }
                        catch { /* una entidad que no se deja leer no tumba el resto */ }
                    }
                }
                return sb.ToString().TrimEnd();
            }
            catch { return null; }
        }

        public bool TemaClaro
        {
            get
            {
                try { return Convert.ToInt32(AcApp.GetSystemVariable("COLORTHEME")) == 1; }
                catch { return false; }
            }
        }
    }
}
