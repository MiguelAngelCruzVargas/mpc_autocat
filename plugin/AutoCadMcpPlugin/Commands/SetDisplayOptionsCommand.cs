using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Variables de sistema que deciden si los grosores de línea se VEN o no.
    /// Sin esto, un dibujo con capas de 0.50mm se sigue viendo todo a 1 píxel:
    /// AutoCAD trae LWDISPLAY apagado de fábrica y se guarda por dibujo, así que
    /// abrir otro DWG lo vuelve a apagar.
    /// params: [lineweightDisplay] (bool), [defaultLineweightHundredthsMm] (int)
    /// </summary>
    public static class SetDisplayOptionsCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var result = new JsonObject();

            if (pars["lineweightDisplay"] != null)
            {
                bool on = pars["lineweightDisplay"].GetValue<bool>();
                Application.SetSystemVariable("LWDISPLAY", on ? (short)1 : (short)0);
                result["lineweightDisplay"] = on;
            }

            if (pars["defaultLineweightHundredthsMm"] != null)
            {
                short lw = (short)pars["defaultLineweightHundredthsMm"].GetValue<int>();
                Application.SetSystemVariable("LWDEFAULT", lw);
                result["defaultLineweightHundredthsMm"] = lw;
            }

            // LTSCALE decide cada cuanto se repite el patron de un tipo de
            // linea. Dibujando en metros con el valor 1 por defecto, un CENTER
            // (trazo-punto) se ve CONTINUO: el patron es mucho mas largo que
            // el propio eje. Sin esto los ejes no se distinguen de una linea
            // llena.
            if (pars["linetypeScale"] != null)
            {
                double ls = pars["linetypeScale"].GetValue<double>();
                if (ls <= 0)
                    throw new ArgumentException("linetypeScale tiene que ser > 0.");
                Application.SetSystemVariable("LTSCALE", ls);
                result["linetypeScale"] = ls;
            }

            doc.Editor.Regen();
            return result;
        }
    }
}
