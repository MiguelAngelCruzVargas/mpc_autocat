' Doble clic para abrir AutoCAD IA SIN ninguna consola visible (ni un
' parpadeo). La logica real (elegir pythonw.exe y mandar la salida a un
' log) vive en tools\lanzar_silencioso.bat - este script solo lo lanza
' con la ventana oculta (0 = hidden), que es lo unico que un .bat no
' puede hacer solo consigo mismo.
'
' Para apagarlo: el boton "Apagar" dentro de la interfaz web (ya no hay
' ventana que cerrar). Si algo no arranca, revisa autocad-ia.log en esta
' misma carpeta - ahi va a parar lo que antes se veia en la consola negra.
'
' Para ver la consola en vivo mientras se depura algo, usa AutoCAD-IA.bat
' en su lugar - ese sigue mostrando todo en pantalla a proposito.

Dim fso, raiz, shell, comillas
comillas = Chr(34)

Set fso = CreateObject("Scripting.FileSystemObject")
raiz = fso.GetParentFolderName(WScript.ScriptFullName)

Set shell = CreateObject("WScript.Shell")
shell.Run comillas & raiz & "\tools\lanzar_silencioso.bat" & comillas, 0, False
