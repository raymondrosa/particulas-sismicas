# Aviso automático en Facebook

Este automatizador revisa los sensores del **Observatorio de Partículas del TOA**
y, cuando el nivel es **`alerta`** (anomalía coincidente en al menos dos familias
de medición), publica un aviso en la página de Facebook:

https://www.facebook.com/estudioenergeticodesismos/

## Cómo funciona

- Un **GitHub Action** se ejecuta cada 10 minutos (GitHub puede retrasarlo).
- Lee los mismos canales de ThingSpeak que la página.
- Aplica la misma detección que la página: mediana y MAD de las últimas horas,
  umbral de 6 desviaciones para una señal fuerte y coincidencia en al menos
  **dos familias de medición** (partículas, molecular o aceleración).
- Si el nivel es `alerta`, publica en la página de Facebook con el descargo
  científico incluido.
- También se ejecuta al subir cambios al propio workflow o al script, para
  probar de inmediato.
- Tiene un **tiempo de espera de 12 horas** entre avisos para no repetir el mismo
  mensaje mientras la alerta siga activa.
- Si no hay alerta, no publica nada.

## Configuración (una sola vez)

### 1. Crear la app de Meta

1. Entra a https://developers.facebook.com/ y crea una app tipo **Business**.
2. Agrega el producto **Facebook Login** o usa directamente **Graph API Explorer**.
3. La app puede quedar en modo desarrollo si la usarás solo tú como administrador
   de la página. Si Meta te pide revisión para `pages_manage_posts`, solicítala.

### 2. Obtener el token de la página

Necesitas un **Page Access Token** (no un token personal) con estos permisos:

- `pages_manage_posts` — para publicar en la página.
- `pages_read_engagement` — para leer las publicaciones recientes y evitar duplicados.
- `pages_show_list` — para listar tus páginas y obtener el token.

Pasos con Graph API Explorer:

1. Selecciona tu app.
2. Pide un **User Access Token** con los permisos anteriores.
3. Llama a `GET /me/accounts` y localiza la página **Estudio Energético de Sismos**.
4. Copia el `access_token` de esa página (es el token de página).
5. Si quieres que no caduque pronto, genera un **System User Token** desde
   Meta Business Suite con los mismos permisos. Es la opción más estable.

### 3. Guardar el token en GitHub

En el repositorio `raymondrosa/particulas-sismicas`:

1. **Settings → Secrets and variables → Actions → New repository secret**
2. Nombre: `FB_PAGE_TOKEN`
3. Valor: el token de página.
4. Opcional: si `me` no funciona, crea el secreto `FB_PAGE_ID` con el ID numérico
   de la página.

### 4. Probar

En **Actions → Aviso sísmico a Facebook → Run workflow**:

- `dry_run = true`: muestra en el log el mensaje que se publicaría, sin publicar.
- `force = true`: publica un mensaje de prueba en la página.
- Después de probar, deja el flujo programado activo.

## Seguridad

- **Nunca** pongas el token en `index.html` ni en el repositorio. Solo en
  **GitHub Secrets**.
- Si el token se expone, revócalo y genera uno nuevo.
- El workflow solo tiene permiso de lectura del repositorio.
- El token se pasa por variable de entorno; el script no lo imprime.

## Notas

- Facebook **no permite enviar notificaciones push** a todos los seguidores desde
  una página. Lo que hace este automatizador es **publicar en el muro de la página**;
  Facebook decide a quién mostrárselo.
- El aviso incluye siempre el descargo: estudio en desarrollo, no es una autoridad
  oficial y la hipótesis no ha sido validada científicamente.
- Si la página se ve con datos pero el Action no publica, revisa el log:
  puede que el nivel sea `estable` o que ya se publicó un aviso en las últimas
  12 horas.
- GitHub puede pausar los flujos programados si el repositorio pasa 60 días sin
  actividad; revive el flujo desde la pestaña **Actions**.
