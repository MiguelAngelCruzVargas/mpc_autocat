# Estrategia de ventas de Vigentra Architech

Escrita el 23 de octubre de 2026. Distingue **dato** (con fuente), **supuesto** (hay que medirlo) y **criterio** (mi recomendación).

## 1. Qué se vende

No se vende "IA para AutoCAD" (genérico). Se vende un resultado concreto y demostrable:

> **De un pedido en lenguaje normal a planos, instalaciones, cantidades de obra y 3D, dentro de tu propio AutoCAD, con las normas de México.**

Diferenciadores que sí se pueden comprobar (están en el producto y en las páginas de proyectos):
- Dibuja **dentro** del AutoCAD del cliente (no es otro programa que aprender).
- **Cuantifica**: cuadro de volúmenes y catálogo de conceptos en Excel, medidos del dibujo.
- **Valida antes de dibujar** (programa vs. terreno, muros, geometría) y calcula estructura con artículo de norma.
- Instalaciones eléctrica, hidráulica y sanitaria; cortes, fachadas; 3D con materiales.
- 294 herramientas; 3 proyectos reales publicados (casa, pórtico con barda, celular 3D).

Competencia (dato limitado): Autodesk presenta su *Autodesk Assistant* en AutoCAD 2026 como un chat de ayuda y guía, no como una función que dibuje por ti ([Autodesk](https://www.autodesk.com/uk/products/autocad/features)); lo demás de AutoCAD 2026 que cita son automatizaciones (Smart Blocks, AutoLISP). **No encontré datos de plugins de IA competidores**: hay que investigarlos a mano antes de publicar comparaciones. Los sustitutos reales son el dibujante, las plantillas/AutoLISP y el tiempo propio.

## 2. A quién (en orden)

1. **Arquitectos y despachos pequeños de vivienda** (1–10 personas): su dolor es el tiempo en láminas, instalaciones y cantidades. Compran por demostración.
2. **Ingenieros civiles y residentes de obra**: cuantificación, estructura, zapatas, trabes.
3. **Constructoras y desarrolladoras pequeñas**: presupuesto de obra desde el dibujo.
4. **Estudiantes y docentes** (UNID, tecnológicos): poco dinero, mucho alcance y recomendación. Solo con precio educativo y como canal de boca en boca.

Empezar local (Tuxtepec, Oaxaca, Veracruz, Puebla: red personal y WhatsApp) y escalar en línea al resto del país.
Tamaño de mercado: **sin dato**. El INEGI publica el DENUE con filtro por actividad (SCIAN); hay que descargar arquitectura (SCIAN 5413), ingeniería y edificación y contar establecimientos ([INEGI, DENUE](https://inegi.org.mx/contenidos/saladeprensa/boletines/2024/denue/denue2024_11.pdf)). Confirmar los códigos exactos en el catálogo SCIAN.

## 3. Oferta y precio

- **Prueba gratis de 7 días, sin tarjeta** (ya existe). Referencia: los estudios que encontré ponen la conversión de prueba a pago, en pruebas sin tarjeta, entre ~18 % y 25 %; son blogs de proveedores y se contradicen entre sí ([Userpilot](https://userpilot.com/blog/free-trial-conversion-rate/), [Flint](https://www.flint.com/blog/b2b-saas-free-trial-conversion-rate-statistics), [SHNO](https://www.shno.co/marketing-statistics/free-trial-conversion-statistics)). **Es un supuesto de planeación, no una promesa**: medir el propio.
- **Precios (MXN, IVA incluido):** mensual $349, anual $2,290, perpetua $5,800 (lanzamiento).
- **Fundadores:** las primeras 20 licencias con 20 % de descuento a cambio de un caso o testimonio con permiso de uso. Hoy no hay ni un testimonio: es lo que más falta.
- **Garantía:** 7 días (ya publicada en los términos).
- Urgencia solo si es real: subir el precio de la perpetua en una fecha que se cumpla.

Cuenta de equilibrio (con supuestos): una licencia anual deja ~$2,200 netos tras comisión de Stripe. Con 15 %–25 % de prueba a pago, se puede pagar hasta ~$330–$550 por prueba iniciada y recuperarlo con la primera compra. **Meta: ≤ $150 por prueba iniciada.**

## 4. Embudo y qué medir

Contenido o anuncio → página (video y proyectos) → descarga de la prueba → "Primeros pasos" → **primer plano en 10 minutos** → compra → renovación.

| Etapa | Cómo se mide hoy | Falta |
|---|---|---|
| Visita | Search Console | Meta Pixel y GA4 con eventos |
| Descarga | registros de Caddy del zip | evento en la página |
| Prueba iniciada | servidor de licencias (`/v1/prueba`) | contador visible |
| Compra | Stripe y tabla `compras` | informe por canal (UTM) |
| Activación | no se mide | registrar "primer dibujo hecho" |

KPIs: costo por prueba, prueba→compra, CAC, días a la primera compra, renovaciones.

## 5. Canales (por orden de prioridad)

1. **Video corto vertical (Reels, TikTok, Shorts), 3 por semana.** Salen del video de la casa: "Le pedí una casa de dos niveles a la IA dentro de AutoCAD", "Su cuadro de volúmenes en 20 segundos", "La instalación eléctrica que se dibuja sola". Es el canal de más curiosidad por costo.
2. **YouTube largo** para búsqueda: "Plano eléctrico con IA en AutoCAD", "Cuantificación de obra desde el dibujo".
3. **Grupos de Facebook y comunidades de AutoCAD y arquitectura en México**: aportar primero (demostraciones, respuestas), nunca spam; respetar reglas de cada grupo.
4. **Meta Ads** (descarga de la prueba como objetivo): México; intereses AutoCAD, arquitectura, ingeniería civil, Revit, SketchUp; $150–$200 MXN al día durante 14 días (~$2,000–$3,000) **solo para aprender** qué creativo y audiencia funcionan. Antes de gastar, instalar el Pixel.
5. **Google Ads de búsqueda** con intención alta: "plano eléctrico autocad automático", "cuantificación de obra autocad", "automatizar planos autocad". CPC sin dato: probar con presupuesto chico.
6. **SEO** con una página por problema (cuadro de volúmenes, instalación eléctrica con norma, bajada de cargas); la estructura del sitio ya lo permite.
7. **Outreach directo** (LinkedIn y WhatsApp) a despachos y constructoras: 15–20 mensajes al día con el video del pórtico o la casa, no con un folleto.
8. **Alianzas**: universidades (UNID y tecnológicos), colegios de arquitectos e ingenieros, distribuidores de AutoCAD, creadores de contenido de arquitectura; afiliados con 20 % por venta.

## 6. Lo que frena las ventas hoy (resolver ANTES de gastar en anuncios)

1. **El programa con licencia nunca se probó dentro de AutoCAD de punta a punta.** Es el riesgo número uno: devoluciones y mala reputación.
2. **Solo está probado en AutoCAD 2022 y 2027.** Mucha gente usa 2023–2025. Probar al menos 2024 y 2025 amplía el mercado de verdad; hoy hay que decirle al cliente "escríbenos antes de comprar".
3. **Fricción de la clave de IA:** el cliente debe sacar su propia clave con un proveedor. Es la barrera de conversión más grande del producto. Oportunidad: un plan que incluya la IA (nosotros pagamos los tokens y se los revendemos con margen). Requiere calcular costos reales por uso.
4. **Instalador sin firma digital:** Windows muestra "protegió su PC" y AutoCAD pide confirmar. Un certificado de firma de código baja la fricción.
5. **Sin testimonios ni casos de clientes.**
6. Faltan la llave real de Stripe, el correo con la clave y la revisión legal de los términos.
7. **Capacidad de soporte:** el plan prioritario se prometió; hay que tener quién responda.

## 7. Plan de 30 días

- **Semana 0:** prueba con licencia en AutoCAD, firmar el instalador, llave real de Stripe, correo; probar 2024 y 2025.
- **Semana 1:** Pixel, GA4, UTM y eventos; cortar 10 videos verticales con subtítulos; páginas por segmento ("para arquitectos", "para ingenieros"); sección de objeciones (clave de IA, versión de AutoCAD, precio); invitar a 10 conocidos a probar a cambio de un caso.
- **Semana 2:** publicar 3 videos por semana; entrar a 5 grupos con aportes; lanzar Meta Ads con 3 creativos y $2,000–$3,000 de prueba.
- **Semana 3:** outreach directo y una alianza con una universidad o colegio; primera ronda de testimonios.
- **Semana 4:** medir costo por prueba y prueba→compra; apagar lo que no funciona, duplicar lo que sí; decidir el presupuesto del mes 2.

## 8. Metodología de anuncios

Para el análisis de campañas de Meta con las 3 Q's y la estructura de campañas (presentación, evaluación, conversión, ascensión) hay habilidades instaladas en esta herramienta; cuando existan datos exportados de Ads Manager se pueden aplicar.
