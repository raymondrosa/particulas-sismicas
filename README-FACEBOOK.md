# Aviso automático en Facebook

Este automatizador revisa los sensores del **Observatorio de Partículas del TOA**
y, cuando el nivel es **`alerta`** (anomalía coincidente en al menos dos familias
de medición), publica un aviso en la página de Facebook:

https://www.facebook.com/estudioenergeticodesismos/

## Cómo funciona

- Un **GitHub Action** se ejecuta cada 10 minutos (GitHub puede retrasarlo).
- Lee los mismos canales de ThingSpeak que la página.
- Aplica la misma detección: mediana y MAD de las últimas horas, umbral de
  6 desviaciones para una señal fuerte y coincidencia en al menos **dos familias**
  de medición (partículas, molecular o aceleración).
- Si el nivel es `alerta`, publica en la página de Facebook con el descargo
  científico incluido.
- Si no hay alerta, no publica nada.
- Tiene un **tiempo de espera de 12 horas** entre avisos.

## Configuración recomendada: token de usuario

El script puede tomar un **token de usuario** y obtener automáticamente el token
de la página que administras. Para eso:

### 1. Tu usuario debe ser administrador de la página

En Facebook, abre la página → **Configuración de la página → Acceso a la página**
y confirma que tu usuario tenga **Control total** o **Administrador**.

Si no lo tienes, pídelo a quien administre la página o agrégalo desde
**Meta Business Suite → Configuración → Cuentas → Páginas → Proyecto EESE →
Personas**.

### 2. Crear la app de Meta

1. Entra a https://developers.facebook.com/ y usa una app tipo **Business**
   (por ejemplo **Avisos EESE**).
2. Agrega **Facebook Login** o usa directamente **Graph API Explorer**.
3. La app puede quedar en modo desarrollo si la usarás solo tú como
   administrador de la página.

### 3. Obtener el token de usuario

En **Graph API Explorer**:

1. Selecciona la app **Avisos EESE**.
2. Agrega los permisos:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
3. Pulsa **Generate Access Token** y autoriza.
4. Comprueba que tu usuario administra la página:
   ```
   me/accounts?fields=name,id,access_token
   ```
   Debe aparecer **Proyecto EESE**. Si sale `{"data":[]}`, tu usuario no es
   administrador de la página: vuelve al paso 1.
5. Guarda el **token de usuario** (el que aparece arriba, no el de la página).

Para que no caduque en 1–2 horas, cámbialo por uno de **larga duración**
(60 días) con:
```
GET /oauth/access_token?grant_type=fb_exchange_token
    &client_id=APP_ID
    &client_secret=APP_SECRET
    &fb_exchange_token=TOKEN_CORTO
```
También puedes usar un **token de System User** (no caduca) como alternativa.

### 4. Guardar en GitHub

En `raymondrosa/particulas-sismicas`:

1. **Settings → Secrets and variables → Actions → New repository secret**
2. Crea **`FB_USER_TOKEN`** con el token de usuario de larga duración.
3. Opcional: crea **`FB_PAGE_ID`** con el ID numérico de la página
   (por defecto el script usa `10329524066772157`).

El script llama a `/me/accounts`, encuentra la página, obtiene su token y publica
en `/{FB_PAGE_ID}/feed`.

> También se admite un **token de página** o de **System User** en
> `FB_PAGE_TOKEN` (con `FB_PAGE_ID`). Si existen ambos, tiene prioridad el flujo
> de `FB_USER_TOKEN`.

### 5. Probar

En **Actions → Aviso sísmico a Facebook → Run workflow**:

- `dry_run = true`: valida las credenciales y muestra el mensaje, sin publicar.
- `force = true` (con `dry_run = false`): publica un mensaje de prueba.

En el log debe aparecer:
```
Página de Facebook: Proyecto EESE (id ...)
Publicado en Facebook. id=...
```

Después de probar, deja el flujo programado activo.

## Si algo falla

- **`/me/accounts` sale vacío** → tu usuario no es administrador de la página.
  Agrégalo en Configuración de la página → Acceso a la página.
- **Error `#200`** → el token no tiene `pages_manage_posts` o no es administrador
  de la página. Revisa los permisos en Graph API Explorer.
- **`No encontré la página`** → revisa el nombre o ajusta `FB_PAGE_ID`.
- **Token inválido o caducado** → genera uno nuevo. Los tokens de usuario cortos
  duran 1–2 horas; usa uno de larga duración o un System User.
- **Facebook no permite notificaciones push** a todos los seguidores; el script
  publica en el muro de la página y Facebook decide a quién mostrarlo.

## Seguridad

- **Nunca** pongas el token en `index.html` ni en el repositorio. Solo en
  **GitHub Secrets**.
- Si el token se expone, revócalo y genera uno nuevo.
- El workflow solo tiene permiso de lectura del repositorio.
- El token se pasa por variable de entorno; el script no lo imprime.

## Notas

- El aviso incluye siempre el descargo: estudio en desarrollo, no es una autoridad
  oficial y la hipótesis no ha sido validada científicamente.
- GitHub puede pausar los flujos programados si el repositorio pasa 60 días sin
  actividad; revívelo desde la pestaña **Actions**.
