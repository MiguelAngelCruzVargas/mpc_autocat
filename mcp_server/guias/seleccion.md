# Seleccionar y recorrer entidades sin preguntarle nada al usuario

Nunca uses los `ed.Get...` interactivos (`GetSelection`, `GetPoint`,
`GetEntity`, `GetString`): esperan un clic del usuario y el socket queda
colgado hasta el timeout. Todo se selecciona por código.

## Recorrer el espacio activo (lo más simple y lo más seguro)

```csharp
var lista = new List<string>();
foreach (ObjectId id in space)                // BlockTableRecord es enumerable
{
    // Filtrar por clase SIN abrir el objeto: es mucho más rápido.
    if (id.ObjectClass.DxfName != "LWPOLYLINE") continue;
    var pl = (Polyline)tr.GetObject(id, OpenMode.ForRead);
    if (pl.Layer != "MUROS" || !pl.Closed) continue;
    lista.Add(pl.Handle.ToString() + " area=" + pl.Area.ToString("0.00"));
}
return lista;                                  // las listas vuelven como JSON
```

DxfName frecuentes: `LINE`, `LWPOLYLINE`, `CIRCLE`, `ARC`, `TEXT`, `MTEXT`,
`INSERT` (bloque), `HATCH`, `DIMENSION`, `3DSOLID`, `REGION`.
Otra forma de comparar clase: `id.ObjectClass == RXObject.GetClass(typeof(Circle))`.

## Por handle (lo que devuelven las demás tools)

```csharp
var ent = (Entity)tr.GetObject(H("2A3"), OpenMode.ForWrite);
ent.Layer = "3D-MUROS";
```

`H()` falla si el handle no existe en este dibujo: los handles cambian entre
dibujos y no sobreviven a un copiar/pegar.

## Con filtro de AutoCAD (SelectAll)

```csharp
var filtro = new SelectionFilter(new TypedValue[] {
    new TypedValue((int)DxfCode.Start, "CIRCLE"),
    new TypedValue((int)DxfCode.LayerName, "COLUMNAS"),
});
PromptSelectionResult psr = ed.SelectAll(filtro);
if (psr.Status != PromptStatus.OK) return 0;  // Error = no encontró nada
return psr.Value.GetObjectIds().Length;
```

`SelectAll` no es interactivo. Ojo: puede devolver entidades de TODOS los
espacios (modelo y layouts); si importa, agregá
`new TypedValue((int)DxfCode.LayoutName, "Model")` o filtrá por
`ent.OwnerId == space.ObjectId`. Los comodines del filtro son los de
AutoCAD (`"MUROS*"`, `"LINE,LWPOLYLINE"`).

## Cajas y geometría

```csharp
Extents3d caja = ent.GeometricExtents;        // puede tirar en entidades vacías
Print(caja.MinPoint + " -> " + caja.MaxPoint);
```

Envolvé `GeometricExtents` en try/catch cuando recorras entidades
cualquiera: un texto vacío o un bloque sin geometría la hacen fallar, y una
excepción no atrapada aborta TODO el run_code.

## Borrar

```csharp
var ent = (Entity)tr.GetObject(id, OpenMode.ForWrite);
ent.Erase();
```

Para borrar muchas por handle hay una tool: `delete_entities`. Usá run_code
cuando el criterio de selección es lo difícil (por ejemplo "las líneas de la
capa X más cortas que 5 cm").

## Devolver resultados

Volvé datos, no texto armado: una lista de handles, un número, una lista
de `Point3d` (vuelven como `[x,y,z]`). `Print` es para notas al costado.
Si devolvés miles de elementos, resumí (cuántos, total de área) en vez de
mandar todo.
