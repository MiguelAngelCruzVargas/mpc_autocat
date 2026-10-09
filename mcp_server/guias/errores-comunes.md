# Errores comunes de run_code y cómo evitarlos

Una excepción no atrapada aborta la transacción entera: el dibujo queda
exactamente como estaba, incluido lo que el código ya había hecho antes de
fallar. Es una red, no un problema: corregí y repetí. Si atrapás la
excepción adentro, lo hecho hasta ahí SÍ queda.

## eNotOpenForWrite

Modificaste algo abierto para lectura.

```csharp
var ent = (Entity)tr.GetObject(id, OpenMode.ForWrite);   // si vas a cambiarlo
// o, si ya lo tenías ForRead:
ent.UpgradeOpen();
```

`space` ya viene ForWrite. Las tablas (`LayerTable`, `BlockTable`) abrilas
ForRead y `UpgradeOpen()` solo si vas a agregar.

## eLockViolation

El plugin ya bloquea el documento activo. Aparece si tocás OTRO documento
(`Application.DocumentManager`, otra `Database`): no lo hagas. Para cambiar
de dibujo están `open_document` / `set_active_document`.

## La transacción y Dispose

- No llames `tr.Commit()` ni `tr.Abort()` ni `tr.Dispose()`: los maneja el
  plugin (es lo que da la atomicidad y el undo de una sola vez).
- Lo que sale de `tr.GetObject` NO se dispone: es de la transacción.
- Lo que creás con `new` y NO agregás con `Add()` (polilíneas auxiliares,
  las `Region` de `CreateFromCurves`, el sólido que restaste) SÍ: `Dispose()`.
  Si no, queda memoria nativa sin liberar.
- `Add(entidad)` ya hace `AppendEntity` + `AddNewlyCreatedDBObject`. No lo
  repitas a mano. Para objetos que no son entidades (una capa, un
  diccionario) sí: `tabla.Add(obj); tr.AddNewlyCreatedDBObject(obj, true);`

## eInvalidInput / eDegenerateGeometry

Geometría imposible: una región de una polilínea abierta o que se cruza, un
sólido de altura 0, una booleana entre sólidos que no se tocan. Validá los
números antes de crear (anchos > 0, contorno cerrado).

## Unidades: metros

En este proyecto se dibuja en metros. Un muro de 2.50 de alto es `2.50`, no
`2500`. Un error de unidades no da excepción: da un edificio de 2.5 km.

## Lo que bloquea el filtro (y qué usar en su lugar)

El plugin rechaza, antes de ejecutar, todo lo que no es AutoCAD:

| Bloqueado | En su lugar |
|---|---|
| `System.IO` (archivos), `System.Net` (red) | tools: `save_drawing`, `export_pdf`, `attach_xref`, `insert_block` |
| `Process`, `Microsoft.Win32` (registro), `Environment` | nada: no hace falta para dibujar |
| `Type.GetType(string)`, `Assembly.Load`, `Reflection.Emit`, `DllImport`, `dynamic` | `describe_api` para mirar la API |
| `Database.SaveAs`, `ReadDwgFile`, `DocumentManager.Open/Add` | `save_drawing`, `open_document`, `new_document` |
| `Editor.Command`, `SendStringToExecute` | la API directa (ver abajo) |

`ed.Command` y `SendStringToExecute` están bloqueados por dos motivos: los
comandos de línea incluyen `SHELL` (que lanza cualquier programa), y además
corren FUERA de la transacción — no se deshacen con ella ni respetan la
atomicidad. Todo lo que hace un comando tiene su equivalente en la API.

El error de bloqueo dice línea, columna, símbolo y motivo. El usuario puede
apagar el filtro, pero eso es decisión suya: no se lo pidas para resolver
algo que tiene tool.

## Prompts interactivos

`ed.GetPoint`, `GetSelection`, `GetEntity`, `GetString`... esperan al
usuario: el socket queda colgado. Ver `api_guide("seleccion")`.

## Bucles largos

El código corre en el hilo de AutoCAD y no se puede cortar desde afuera. Un
bucle infinito deja AutoCAD ocupado y el cliente devuelve timeout: NO
repitas el run_code (se encolaría otro). Poné un tope a todo `while`.

## Versión de C#

Si el plugin compila con el compilador de .NET Framework (plan B), solo
entiende C# 5: sin `$"..."`, sin `?.`, sin funciones locales, sin `=>` en
miembros. El error de compilación lo avisa. Escribir en C# 5 compila en los
dos: `"x=" + x` en vez de `$"x={x}"`.

## No sé la firma

No la adivines: `describe_api("Solid3d", "Extrude")` lista las sobrecargas
reales del AutoCAD instalado. Y `compile_only=True` prueba que compila sin
ejecutar nada.
