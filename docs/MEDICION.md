# Medición de ventas de Vigentra Architech

Qué se mide, cómo se activa y cómo se leen los números. Todo funciona con **consentimiento**: sin IDs el sitio no carga nada de terceros ni muestra aviso de cookies.

## Los dos IDs que hacen falta

| ID | Qué es | Dónde se saca |
|---|---|---|
| **GA4**, forma `G-XXXXXXXXXX` | Identifica tu propiedad de Google Analytics 4. | analytics.google.com → Administrar → Flujos de datos → Web → crear el flujo con `https://vigentra.mx` → copiar el **ID de medición**. |
| **Píxel de Meta**, 15–16 dígitos | Identifica tu píxel para los anuncios de Facebook e Instagram. | business.facebook.com → Administrador de eventos → Orígenes de datos → Conectar datos → Web → Píxel de Meta → copiar el **ID del conjunto de datos**. |

Opcional pero recomendable: en Meta, verificar el dominio `vigentra.mx` (Configuración del negocio → Seguridad de la marca → Dominios), y en GA4 marcar `compra` (`purchase`), `descarga_instalador` e `iniciar_checkout` (`begin_checkout`) como **eventos clave**.

## Activar

Con los IDs en la mano (desde `landing/`):

```
python build/activar_medicion.py --ga4 G-XXXXXXXXXX --pixel 1234567890123456
```

Pone los IDs en `assets/js/medicion.js` y **actualiza el aviso de privacidad** (hoy dice que el sitio no usa analítica; con esto pasa a decir que la usa solo con consentimiento). Después se suben `assets/js/medicion.js` y `aviso-de-privacidad.html` al servidor. Para volver atrás: `--desactivar`.

## Eventos

| Evento del sitio | Cuándo | GA4 | Píxel de Meta |
|---|---|---|---|
| `ver_planes` | clic en cualquier enlace a `/comprar` | `ver_planes` | `VerPlanes` (personalizado) |
| `descarga_instalador` | clic en el `.zip` | `descarga_instalador` | `Lead` |
| `contacto_whatsapp` | clic en WhatsApp | `contacto_whatsapp` | `Contact` |
| `iniciar_checkout` | clic en Comprar de un plan | `begin_checkout` | `InitiateCheckout` |
| `compra` | llegada a `/gracias` con el pago confirmado (una vez por pedido) | `purchase` | `Purchase` |

La **prueba iniciada** ocurre dentro del programa y no la ve el navegador: se lee del servidor (abajo).

## Enlaces por video

`python tools/marketing/enlaces_utm.py <carpeta>` escribe `enlaces_utm.md` con un enlace por corte y por red (`utm_source`, `utm_medium=video_organico`, `utm_campaign=cortes_2026_10`, `utm_content=corte_NN_...`). El sitio guarda los utm de la visita, los manda a Stripe al pagar y quedan en la tabla `compras`.

## Leer los números del servidor

```
python licencias/admin.py estadisticas --dias 30
```

Muestra pruebas iniciadas (por día), equipos activados, licencias creadas y las **compras por canal** (red, campaña y video, con su monto). Los pagos de prueba de Stripe (`cs_test_`) no se cuentan.

## Qué mirar cada semana

Visitas por video (GA4) → descargas → pruebas iniciadas (servidor) → compras por video (servidor). Meta de costo: ≤ $150 por prueba iniciada. Apagar el video o anuncio que no trae pruebas y repetir lo que sí.
