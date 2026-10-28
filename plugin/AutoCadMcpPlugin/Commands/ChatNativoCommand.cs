using System;
using System.Windows.Forms;
using System.Windows.Forms.Integration;
using Autodesk.AutoCAD.Runtime;
using AutoCadMcpPlugin.Chat;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Comando MCPCHAT: el chat como panel NATIVO de AutoCAD (WPF dentro de un PaletteSet), no una página web.
    /// El navegador embebido de AutoCAD 2022 es Chromium 77; un panel nativo no depende de eso, sigue el tema de
    /// AutoCAD y ve el dibujo y la selección. El cerebro sigue en el servidor Python (ChatCliente).
    /// La versión en página web queda como MCPCHATWEB.
    /// </summary>
    public class McpChatNativoCommands
    {
        [CommandMethod("MCPCHAT")]
        public void AbrirChat()
        {
            ChatNativo.Mostrar();
        }
    }

    internal static class ChatNativo
    {
        private static readonly Guid IdPanel = new Guid("0b6a5c1e-52f4-4d6e-8e0a-7c3f2a9d1b55");
        private static object _paleta;
        private static ChatPanel _panel;

        public static void Mostrar()
        {
            try
            {
                if (_paleta == null)
                {
                    // PaletteSet vive en acmgd.dll; se maneja por reflexión para que el mismo código compile en net48,
                    // net8 y net10 sin depender de cómo cada paquete de referencia expone la clase.
                    var asm = typeof(Autodesk.AutoCAD.ApplicationServices.Application).Assembly;
                    var tPaleta = asm.GetType("Autodesk.AutoCAD.Windows.PaletteSet", true);
                    var ps = Activator.CreateInstance(tPaleta, new object[] { "Asistente AutoCAD", IdPanel });

                    _panel = new ChatPanel(new ContextoCad(), ServidorChat.AsegurarAsync);
                    var anfitrion = new ElementHost { Dock = DockStyle.Fill, Child = _panel };

                    var add = tPaleta.GetMethod("Add", new[] { typeof(string), typeof(Control) });
                    if (add == null) throw new MissingMethodException("PaletteSet.Add(string, Control) no existe en esta versión.");
                    add.Invoke(ps, new object[] { "Chat", anfitrion });
                    tPaleta.GetProperty("MinimumSize")?.SetValue(ps, new System.Drawing.Size(300, 420));
                    tPaleta.GetProperty("Size")?.SetValue(ps, new System.Drawing.Size(420, 720));
                    _paleta = ps;
                    tPaleta.GetProperty("Visible").SetValue(ps, true);
                    AcoplarDerecha(asm, tPaleta, ps);
                }
                else
                {
                    _paleta.GetType().GetProperty("Visible").SetValue(_paleta, true);
                }
            }
            catch (System.Exception ex)
            {
                Decir("[MCPCHAT] No pude abrir el panel nativo (" + ex.GetBaseException().Message + "). Prueba MCPCHATWEB.");
            }
        }

        // El acople va DESPUÉS de mostrar el panel y con el acople permitido: antes de eso AutoCAD lo ignora.
        private static void AcoplarDerecha(System.Reflection.Assembly asm, Type tPaleta, object ps)
        {
            try
            {
                var tDock = asm.GetType("Autodesk.AutoCAD.Windows.DockSides");
                if (tDock == null) return;
                tPaleta.GetProperty("DockEnabled")?.SetValue(ps, Enum.Parse(tDock, "Left, Right"));
                tPaleta.GetProperty("Dock")?.SetValue(ps, Enum.Parse(tDock, "Right"));
            }
            catch { /* flotante también sirve */ }
        }

        private static void Decir(string texto)
        {
            try
            {
                var doc = Autodesk.AutoCAD.ApplicationServices.Application.DocumentManager.MdiActiveDocument;
                if (doc != null) doc.Editor.WriteMessage("\n" + texto + "\n");
            }
            catch { }
        }
    }
}
