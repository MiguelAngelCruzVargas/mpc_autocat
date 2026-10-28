using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Markup;
using System.Windows.Media;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>Colores del panel. Sigue el tema de AutoCAD (COLORTHEME): oscuro o claro.</summary>
    internal sealed class ChatTema
    {
        public Brush Fondo, Panel, Tarjeta, Borde, Texto, Suave, Acento, AcentoTexto, Ok, Mal, Aviso, Usuario, Codigo;
        public string FondoHex, TarjetaHex, BordeHex, TextoHex, AcentoHex, HoverHex;

        private static Brush B(string hex) { var b = (Brush)new BrushConverter().ConvertFromString(hex); b.Freeze(); return b; }

        public static ChatTema Crear(bool claro)
        {
            return claro
                ? new ChatTema
                {
                    FondoHex = "#F3F4F6", TarjetaHex = "#FFFFFF", BordeHex = "#D1D5DB", TextoHex = "#111827", AcentoHex = "#2563EB", HoverHex = "#E5E7EB",
                    Fondo = B("#F3F4F6"), Panel = B("#FFFFFF"), Tarjeta = B("#FFFFFF"), Borde = B("#D1D5DB"), Texto = B("#111827"),
                    Suave = B("#6B7280"), Acento = B("#2563EB"), AcentoTexto = B("#FFFFFF"), Ok = B("#059669"), Mal = B("#DC2626"),
                    Aviso = B("#B45309"), Usuario = B("#DBEAFE"), Codigo = B("#E5E7EB"),
                }
                : new ChatTema
                {
                    FondoHex = "#10151F", TarjetaHex = "#182131", BordeHex = "#2A3850", TextoHex = "#EEF2F7", AcentoHex = "#3B82F6", HoverHex = "#26334A",
                    Fondo = B("#10151F"), Panel = B("#151C29"), Tarjeta = B("#182131"), Borde = B("#2A3850"), Texto = B("#EEF2F7"),
                    Suave = B("#94A3B8"), Acento = B("#3B82F6"), AcentoTexto = B("#FFFFFF"), Ok = B("#34D399"), Mal = B("#F87171"),
                    Aviso = B("#FBBF24"), Usuario = B("#1E3A5F"), Codigo = B("#0B1019"),
                };
        }

        /// <summary>Un botón plano que SÍ respeta los colores (el de WPF por defecto pinta su propio fondo claro).</summary>
        public Style EstiloBoton()
        {
            var xaml =
                "<Style xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' TargetType='Button'>" +
                "<Setter Property='Background' Value='" + TarjetaHex + "'/>" +
                "<Setter Property='Foreground' Value='" + TextoHex + "'/>" +
                "<Setter Property='BorderBrush' Value='" + BordeHex + "'/>" +
                "<Setter Property='BorderThickness' Value='1'/>" +
                "<Setter Property='Padding' Value='8,3'/>" +
                "<Setter Property='Cursor' Value='Hand'/>" +
                "<Setter Property='Template'><Setter.Value><ControlTemplate TargetType='Button'>" +
                "<Border x:Name='b' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' " +
                "BorderThickness='{TemplateBinding BorderThickness}' CornerRadius='5' Padding='{TemplateBinding Padding}'>" +
                "<ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/></Border>" +
                "<ControlTemplate.Triggers>" +
                "<Trigger Property='IsMouseOver' Value='True'><Setter TargetName='b' Property='Background' Value='" + HoverHex + "'/></Trigger>" +
                "<Trigger Property='IsEnabled' Value='False'><Setter Property='Opacity' Value='0.45'/></Trigger>" +
                "</ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter></Style>";
            return (Style)XamlReader.Parse(xaml);
        }
    }

    internal static class ChatEstilos
    {
        private const string Xmlns = "xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'";

        /// <summary>Barra de desplazamiento fina y del color del tema (la de WPF es gris claro y gruesa).</summary>
        public static Style BarraDesplazamiento(ChatTema t)
        {
            return (Style)XamlReader.Parse(
                "<Style " + Xmlns + " TargetType='ScrollBar'>" +
                "<Setter Property='Width' Value='9'/><Setter Property='MinWidth' Value='9'/><Setter Property='Background' Value='Transparent'/>" +
                "<Setter Property='Template'><Setter.Value><ControlTemplate TargetType='ScrollBar'>" +
                "<Grid Background='Transparent'><Track x:Name='PART_Track' IsDirectionReversed='True'>" +
                "<Track.Thumb><Thumb><Thumb.Template><ControlTemplate TargetType='Thumb'>" +
                "<Border CornerRadius='4' Background='" + t.BordeHex + "' Margin='2,1,2,1'/>" +
                "</ControlTemplate></Thumb.Template></Thumb></Track.Thumb></Track></Grid>" +
                "</ControlTemplate></Setter.Value></Setter></Style>");
        }

        /// <summary>Casilla con el tema: la de WPF es un cuadro blanco que desentona en un panel oscuro.</summary>
        public static Style Casilla(ChatTema t)
        {
            return (Style)XamlReader.Parse(
                "<Style " + Xmlns + " TargetType='CheckBox'>" +
                "<Setter Property='Foreground' Value='" + t.TextoHex + "'/><Setter Property='Cursor' Value='Hand'/>" +
                "<Setter Property='Template'><Setter.Value><ControlTemplate TargetType='CheckBox'>" +
                "<StackPanel Orientation='Horizontal' Background='Transparent'>" +
                "<Border x:Name='caja' Width='14' Height='14' CornerRadius='3' BorderThickness='1' BorderBrush='" + t.BordeHex + "' Background='" + t.TarjetaHex + "' VerticalAlignment='Center'>" +
                "<TextBlock x:Name='marca' Text='✓' FontSize='10' FontWeight='Bold' Foreground='White' HorizontalAlignment='Center' VerticalAlignment='Center' Visibility='Collapsed'/></Border>" +
                "<ContentPresenter Margin='6,0,0,0' VerticalAlignment='Center'/></StackPanel>" +
                "<ControlTemplate.Triggers><Trigger Property='IsChecked' Value='True'>" +
                "<Setter TargetName='caja' Property='Background' Value='" + t.AcentoHex + "'/>" +
                "<Setter TargetName='caja' Property='BorderBrush' Value='" + t.AcentoHex + "'/>" +
                "<Setter TargetName='marca' Property='Visibility' Value='Visible'/></Trigger></ControlTemplate.Triggers>" +
                "</ControlTemplate></Setter.Value></Setter></Style>");
        }
    }

    /// <summary>
    /// Markdown liviano para lo que contesta el modelo: **negrita**, `código`, bloques ``` ```, viñetas y títulos.
    /// No es un renderizador completo a propósito: lo que no reconoce sale como texto.
    /// </summary>
    internal static class ChatMarkdown
    {
        private static readonly Regex Inline = new Regex(@"(\*\*[^*\n]+\*\*|`[^`\n]+`)", RegexOptions.Compiled);

        public static UIElement Render(string md, ChatTema t)
        {
            var pila = new StackPanel();
            var partes = (md ?? "").Replace("\r\n", "\n").Split(new[] { "```" }, StringSplitOptions.None);
            for (int i = 0; i < partes.Length; i++)
            {
                if (i % 2 == 1)
                {
                    var cuerpo = partes[i];
                    var nl = cuerpo.IndexOf('\n');
                    if (nl >= 0 && cuerpo.Substring(0, nl).Trim().Length < 15 && cuerpo.Substring(0, nl).IndexOf(' ') < 0)
                        cuerpo = cuerpo.Substring(nl + 1);
                    pila.Children.Add(new Border
                    {
                        Background = t.Codigo, CornerRadius = new CornerRadius(5), Padding = new Thickness(6), Margin = new Thickness(0, 3, 0, 3),
                        Child = new TextBlock
                        {
                            Text = cuerpo.Trim('\n'), FontFamily = new FontFamily("Consolas"), FontSize = 11.5, Foreground = t.Texto,
                            TextWrapping = TextWrapping.Wrap,
                        },
                    });
                    continue;
                }
                foreach (var linea0 in partes[i].Split('\n'))
                {
                    var linea = linea0.TrimEnd();
                    if (linea.Length == 0) { pila.Children.Add(new Border { Height = 4 }); continue; }
                    double sangria = 0; string marca = null;
                    var m = Regex.Match(linea, @"^\s*([-*•]|\d+[.)])\s+(.*)$");
                    if (m.Success) { marca = Regex.IsMatch(m.Groups[1].Value, @"\d") ? m.Groups[1].Value : "•"; linea = m.Groups[2].Value; sangria = 12; }
                    bool titulo = false;
                    var h = Regex.Match(linea, @"^#{1,4}\s+(.*)$");
                    if (h.Success) { titulo = true; linea = h.Groups[1].Value; }
                    var tb = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = t.Texto, FontSize = 12.5 };
                    if (titulo) tb.FontWeight = FontWeights.SemiBold;
                    Rellenar(tb, linea, t);
                    UIElement fila = tb;
                    if (marca != null)
                    {
                        var g = new Grid { Margin = new Thickness(sangria - 12, 0, 0, 0) };
                        g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
                        g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                        var mk = new TextBlock { Text = marca, Foreground = t.Suave, FontSize = 12.5 };
                        Grid.SetColumn(tb, 1);
                        g.Children.Add(mk); g.Children.Add(tb);
                        fila = g;
                    }
                    pila.Children.Add(fila);
                }
            }
            return pila;
        }

        private static void Rellenar(TextBlock tb, string texto, ChatTema t)
        {
            int pos = 0;
            foreach (Match m in Inline.Matches(texto))
            {
                if (m.Index > pos) tb.Inlines.Add(new Run(texto.Substring(pos, m.Index - pos)));
                var s = m.Value;
                if (s.StartsWith("**", StringComparison.Ordinal))
                    tb.Inlines.Add(new Run(s.Substring(2, s.Length - 4)) { FontWeight = FontWeights.Bold });
                else
                    tb.Inlines.Add(new Run(s.Substring(1, s.Length - 2)) { FontFamily = new FontFamily("Consolas"), Background = t.Codigo });
                pos = m.Index + m.Length;
            }
            if (pos < texto.Length) tb.Inlines.Add(new Run(texto.Substring(pos)));
        }
    }
}
