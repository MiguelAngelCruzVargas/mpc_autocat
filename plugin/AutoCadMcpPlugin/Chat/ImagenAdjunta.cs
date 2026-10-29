using System;
using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace AutoCadMcpPlugin.Chat
{
    /// <summary>
    /// Una imagen que la persona adjunta a su pedido (un croquis, una foto de referencia, una captura): se reduce si es muy grande
    /// (el modelo no gana nada con más de ~1500 px y cada imagen cuesta tokens) y viaja como data URL. Solo para modelos que ven.
    /// </summary>
    internal sealed class ImagenAdjunta
    {
        public const int MaxLado = 1568;                 // píxeles: más grande se reduce
        public const int MaxBytes = 4500000;             // lo que ya reducida pesa como máximo
        public string Nombre, DataUrl;
        public BitmapSource Miniatura;

        public static ImagenAdjunta DesdeArchivo(string ruta)
        {
            var ext = Path.GetExtension(ruta).ToLowerInvariant();
            if (ext != ".png" && ext != ".jpg" && ext != ".jpeg" && ext != ".gif" && ext != ".bmp" && ext != ".webp")
                throw new InvalidOperationException("Solo imágenes (png, jpg, gif, bmp o webp): " + Path.GetFileName(ruta));
            if (new FileInfo(ruta).Length > 25000000) throw new InvalidOperationException("La imagen pesa demasiado (más de 25 MB): " + Path.GetFileName(ruta));
            var bi = new BitmapImage();
            bi.BeginInit();
            bi.CacheOption = BitmapCacheOption.OnLoad;
            bi.UriSource = new Uri(Path.GetFullPath(ruta));
            bi.EndInit();
            bi.Freeze();
            return Desde(bi, Path.GetFileName(ruta), ext == ".png");
        }

        public static ImagenAdjunta Desde(BitmapSource origen, string nombre, bool png)
        {
            double f = Math.Min(1.0, (double)MaxLado / Math.Max(origen.PixelWidth, origen.PixelHeight));
            BitmapSource final = f < 1 ? new TransformedBitmap(origen, new ScaleTransform(f, f)) : origen;
            BitmapEncoder enc = png ? (BitmapEncoder)new PngBitmapEncoder() : new JpegBitmapEncoder { QualityLevel = 88 };
            enc.Frames.Add(BitmapFrame.Create(final));
            byte[] bytes;
            using (var ms = new MemoryStream()) { enc.Save(ms); bytes = ms.ToArray(); }
            if (bytes.Length > MaxBytes) throw new InvalidOperationException("La imagen sigue pesando demasiado aunque se reduzca: " + nombre);
            double g = Math.Min(1.0, 48.0 / Math.Max(origen.PixelWidth, origen.PixelHeight));
            BitmapSource mini = g < 1 ? new TransformedBitmap(origen, new ScaleTransform(g, g)) : origen;
            mini.Freeze();
            return new ImagenAdjunta
            {
                Nombre = nombre,
                DataUrl = "data:image/" + (png ? "png" : "jpeg") + ";base64," + Convert.ToBase64String(bytes),
                Miniatura = mini,
            };
        }
    }
}
