# Capas, colores y grosores con la paleta del proyecto

Si solo necesitás una capa, la tool `set_layer` ya lo resuelve (incluido el
tipo de línea con fallback a los nombres en castellano). Usá run_code para
capas cuando lo que dibujás en el mismo código las necesita.

## Paleta: nunca los colores puros 1-7 (salvo 7 y 8)

Los puros se lavan al imprimir (2 amarillo, 3 verde, 4 cian, 9 gris claro)
o no se leen en pantalla (5 azul). Los del 10 al 249 son los mismos matices
atenuados y se leen en los dos medios.

| Para | Índice |
|---|---|
| Base: muros, contornos, texto | 7 (blanco/negro) |
| Achurados, secundarios, 3D neutro | 8 o 253 (gris) |
| Ejes | 32 (ámbar) |
| Cotas | 12 (rojo oscuro) |
| Hidráulica, drenaje | 152 (azul acero) |
| Guarniciones, vegetación | 96 (verde oliva) |
| Pozos, registros | 172 (violeta) |

## Grosores (centésimas de mm)

Cajón 70 · muros cortados 50 · contornos vistos y mobiliario 25-35 ·
ejes y cotas 13-18 · achurados 5-13. Si todo sale igual, el plano no se lee.

## Crear una capa si no existe

```csharp
var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
if (!lt.Has("3D-MUROS"))
{
    lt.UpgradeOpen();
    var capa = new LayerTableRecord();
    capa.Name = "3D-MUROS";
    capa.Color = Autodesk.AutoCAD.Colors.Color.FromColorIndex(
        Autodesk.AutoCAD.Colors.ColorMethod.ByAci, 8);
    capa.LineWeight = LineWeight.LineWeight050;
    lt.Add(capa);
    tr.AddNewlyCreatedDBObject(capa, true);
}
```

`Has` + `Add` siempre juntos: agregar una capa que ya existe tira
`eDuplicateRecordName` y aborta todo. Los nombres de `LineWeight` son
`LineWeight000`, `LineWeight005`, `LineWeight013`, `LineWeight018`,
`LineWeight025`, `LineWeight035`, `LineWeight050`, `LineWeight070`...
(`describe_api("LineWeight")` lista los válidos).

## Propiedades de una entidad

```csharp
ent.Layer = "3D-MUROS";            // la capa tiene que existir antes
ent.ColorIndex = 256;              // 256 = PorCapa (lo normal), 0 = PorBloque
ent.LineWeight = LineWeight.ByLayer;
```

Preferí PorCapa: cambiar el color de la capa reajusta todo el plano de una;
color fijo por entidad obliga a ir una por una.

## Tipos de línea

Cargar un tipo de línea lee `acad.lin` del disco y es justo el caso que la
tool `set_layer` ya maneja (cae a CENTRO2/OCULTA2 en un AutoCAD en
castellano). Creá la capa con `set_layer(..., linetype=...)` y usala desde
run_code. Para asignar uno ya cargado:

```csharp
var lts = (LinetypeTable)tr.GetObject(db.LinetypeTableId, OpenMode.ForRead);
if (lts.Has("CENTER2")) capa.LinetypeObjectId = lts["CENTER2"];
```

## Estilos de texto y de cota

Usá las tools: `set_text_style` (nunca dejar `txt.shx`, no mapea acentos ni
Ø), `set_dim_style` y `set_dim_style_family`. Si un tipo de AutoCAD no
resuelve en tu código, escribilo con el namespace completo
(`Autodesk.AutoCAD.Colors.Color`, `Autodesk.AutoCAD.GraphicsInterface...`).
