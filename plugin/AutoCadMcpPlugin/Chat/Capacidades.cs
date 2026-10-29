using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace AutoCadMcpPlugin.Chat
{
    internal sealed class AvisoModelo
    {
        public string Nivel, Etiqueta, Texto;          // nivel: alto | medio | bajo
    }

    internal sealed class CapacidadesModelo
    {
        public bool Limitado, Imagenes;
        public readonly List<AvisoModelo> Avisos = new List<AvisoModelo>();
    }

    /// <summary>
    /// Qué NO puede hacer el modelo elegido, dicho con palabras para la persona: sin imágenes, pequeño, no es de chat,
    /// local sin herramientas fiables, tope de herramientas del proveedor. No hay API estándar que lo informe, así que
    /// se reconoce por el nombre y se falla del lado cauteloso: un aviso de más es mejor que una promesa falsa.
    /// </summary>
    internal static class Capacidades
    {
        // No son modelos de conversación: no pueden llevar el agente.
        private static readonly string[] NoChat =
            { "whisper", "tts", "playai", "orpheus", "embed", "guard", "moderation", "rerank", "dall-e", "stable-diffusion", "sdxl" };

        // Modelos que ACEPTAN imágenes. Mandarle una imagen a uno que no las entiende no da un error claro: unos la
        // ignoran en silencio y otros rechazan el pedido entero con un 400 críptico.
        private static readonly string[] Vision =
        {
            "gpt-4o", "gpt-4-turbo", "gpt-4-vision", "gpt-4.1", "gpt-5", "gpt-6", "o1", "o3", "o4-mini", "chatgpt-4o",
            "claude-3", "claude-4", "claude-5", "claude-sonnet", "claude-opus", "claude-haiku", "claude-fable",
            "gemini", "llava", "bakllava", "pixtral", "molmo", "internvl",
            "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "llama-3.2-11b", "llama-3.2-90b", "llama-4", "vision",
            "grok-2-vision", "grok-4", "phi-3-vision", "phi-4-multimodal", "deepseek-vl", "mistral-small-3",
            "mistral-large-4", "mistral-medium-3", "step-1v", "yi-vision", "omni",
        };

        private static readonly HashSet<string> PalabrasChico = new HashSet<string> { "mini", "nano", "lite", "tiny", "small", "instant" };
        private const double MaxBChico = 20.0;          // hasta 20 mil millones de parámetros se considera chico

        // Cuántas herramientas acepta cada proveedor por pedido (mismo dato que usa el agente para pasar a «bajo demanda»).
        internal static int LimiteHerramientas(string proveedor)
        {
            switch (proveedor) { case "groq": case "openai": case "deepseek": return 128; default: return 0; }
        }

        public static bool SoportaImagenes(string modelo)
        {
            if (string.IsNullOrEmpty(modelo)) return false;
            var n = modelo.ToLowerInvariant();
            // «gpt-oss» contiene «gpt» pero es de solo texto: se descarta primero para que ningún patrón amplio lo dé por multimodal.
            if (n.Contains("gpt-oss") || n.Contains("oss-safeguard")) return false;
            return Vision.Any(p => n.Contains(p));
        }

        /// <summary>«mini» no está en «gemini»: se mira por palabras sueltas y por tamaño en miles de millones («8b», «20b»).</summary>
        public static bool EsPequeno(string modelo)
        {
            var fichas = Regex.Split((modelo ?? "").ToLowerInvariant(), "[^a-z0-9.]+");
            if (fichas.Any(f => PalabrasChico.Contains(f))) return true;
            foreach (var f in fichas)
            {
                var m = Regex.Match(f, @"^(\d+(?:\.\d+)?)b$");
                if (m.Success && double.Parse(m.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture) <= MaxBChico) return true;
            }
            return false;
        }

        /// <param name="imagenesPublicado">Lo que el proveedor dice de visión, si lo dice (OpenRouter lo publica); manda sobre el nombre.</param>
        public static CapacidadesModelo Evaluar(string proveedor, string modelo, bool? imagenesPublicado = null)
        {
            var r = new CapacidadesModelo();
            var n = (modelo ?? "").ToLowerInvariant();
            if (n.Length == 0) return r;
            void Aviso(string nivel, string etiqueta, string texto) => r.Avisos.Add(new AvisoModelo { Nivel = nivel, Etiqueta = etiqueta, Texto = texto });

            if (NoChat.Any(p => n.Contains(p)))
            {
                Aviso("alto", "no es de chat", "Este no es un modelo de conversación (voz, moderación o búsqueda): no puede dibujar ni usar herramientas. Elige otro.");
                r.Limitado = true;
                return r;
            }

            r.Imagenes = imagenesPublicado ?? SoportaImagenes(modelo);
            if (!r.Imagenes)
                Aviso("medio", "no ve imágenes", "Este modelo está limitado: no puede ver imágenes. No va a poder mirar capturas del dibujo ni croquis que le adjuntes; trabaja solo con lo que le cuentan las herramientas.");
            if (EsPequeno(n))
                Aviso("medio", "modelo pequeño", "Modelo pequeño: sirve para dibujo simple, pero puede equivocarse en pedidos largos, planos completos o al elegir entre muchas herramientas. Para algo serio usa uno más grande.");
            if (proveedor == "local")
                Aviso("medio", "herramientas dudosas", "Los modelos locales muchas veces no saben llamar herramientas: si no dibuja, es el modelo, no AutoCAD.");
            var limite = LimiteHerramientas(proveedor);
            if (limite > 0)
                Aviso("bajo", "máx. " + limite + " herramientas", "Este proveedor acepta máximo " + limite + " herramientas por pedido: el agente las busca bajo demanda (cada pedido tarda una vuelta más).");

            r.Limitado = r.Avisos.Any(a => a.Nivel != "bajo");
            return r;
        }
    }
}
