#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anomalía estadística multivariable -> página de Facebook.

Modos de autenticación (elige uno):

A) TOKEN DE USUARIO (recomendado si administras la página desde tu perfil):
   - FB_USER_TOKEN = token de usuario con pages_show_list,
     pages_read_engagement y pages_manage_posts.
   - El script pide /me/accounts, obtiene el token de la página y publica
     en /{FB_PAGE_ID}/feed.
   - Tu usuario debe ser administrador de la página.

B) TOKEN DE PÁGINA O DE SYSTEM USER:
   - FB_PAGE_TOKEN = token de página (o de System User con la página asignada).
   - FB_PAGE_ID = ID numérico de la página (obligatorio si es System User).

La alerta exige coincidencia en al menos DOS familias de medición
(partículas, molecular o aceleración), igual que la página.

Opcionales:
  DRY_RUN=1       -> muestra el mensaje y valida credenciales sin publicar.
  FORCE=1         -> publica una prueba aunque no haya alerta.
  COOLDOWN_HOURS  -> horas entre avisos (por defecto 12).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PAGE_URL = "https://raymondrosa.github.io/particulas-sismicas/"
MARKER = "#AvisoTendenciaEESE"
GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION", "v23.0").strip() or "v23.0"
GRAPH = "https://graph.facebook.com/" + GRAPH_VERSION

# ID público de la página "Proyecto EESE".
# Se puede sobrescribir con el secreto FB_PAGE_ID.
DEFAULT_PAGE_ID = "10329524066772157"

CHANNELS = {
    "ch1": (2439912, "BCX6UVTLQZ7VMK4F"),
    "ch2": (2972050, "8LMMRSTHHX26Z4MI"),
}

# (canal, campo, etiqueta, unidad, grupo, minSigma, minDelta)
SERIES = [
    ("ch1", "field1", "Partículas reales", "u", "particulas", 15.0, 20.0),
    ("ch1", "field2", "Partículas imaginarias", "u", "particulas", 15.0, 20.0),
    ("ch1", "field3", "Física molecular", "u", "molecular", 8.0, 10.0),
    ("ch2", "field1", "Aceleración X", "m/s²", "aceleracion", 0.05, 0.15),
    ("ch2", "field2", "Aceleración Y", "m/s²", "aceleracion", 0.05, 0.15),
    ("ch2", "field3", "Aceleración Z", "m/s²", "aceleracion", 0.05, 0.15),
    ("ch2", "field4", "Aceleración resultante", "m/s²", "aceleracion", 0.10, 0.20),
]
CORE_COUNT = len(SERIES)

RECENT_POINTS = 240
BASELINE_POINTS = 1200
MIN_BASELINE = 90
MIN_RECENT = 120
Z_WATCH = 4.5
Z_STRONG = 6.0
Z_SPIKE = 10.0
MAX_FEEDS = 8000


def median(values):
    if not values:
        return float("nan")
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def robust_sigma(values, center, floor):
    if not values:
        return floor
    mad = 1.4826 * median([abs(v - center) for v in values])
    return max(mad, abs(center) * 0.005, floor, 1e-9)


def fetch_feeds(channel_id, api_key):
    url = (
        "https://api.thingspeak.com/channels/"
        + str(channel_id)
        + "/feeds.json?api_key="
        + urllib.parse.quote(str(api_key), safe="")
        + "&results="
        + str(MAX_FEEDS)
    )
    request = urllib.request.Request(url, headers={"User-Agent": "EESE-alerta/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    return payload.get("feeds", [])


def analyze(feeds_by_channel):
    results = []
    for channel, field, label, unit, group, min_sigma, min_delta in SERIES:
        values = []
        for feed in feeds_by_channel.get(channel, []):
            raw = feed.get(field)
            if raw is None or raw == "":
                continue
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                continue

        if len(values) < RECENT_POINTS + MIN_BASELINE:
            continue

        recent = values[-RECENT_POINTS:]
        baseline = values[-(RECENT_POINTS + BASELINE_POINTS):-RECENT_POINTS]
        if len(baseline) < MIN_BASELINE or len(recent) < MIN_RECENT:
            continue

        center = median(baseline)
        sigma = robust_sigma(baseline, center, min_sigma)
        recent_center = median(recent)
        delta = recent_center - center
        z_recent = delta / sigma
        z_last = (values[-1] - center) / sigma
        meaningful = abs(delta) >= min_delta

        state = "normal"
        if meaningful and abs(z_recent) >= Z_STRONG:
            state = "strong"
        elif meaningful and abs(z_recent) >= Z_WATCH:
            state = "watch"
        elif abs(values[-1] - center) >= min_delta and abs(z_last) >= Z_SPIKE:
            state = "spike"

        results.append(
            {
                "label": label,
                "unit": unit,
                "group": group,
                "state": state,
                "delta": delta,
                "z_recent": z_recent,
                "z_last": z_last,
                "baseline": center,
                "recent": recent_center,
            }
        )

    strong = [r for r in results if r["state"] == "strong"]
    watch = [r for r in results if r["state"] == "watch"]
    spikes = [r for r in results if r["state"] == "spike"]
    active = [r for r in results if r["state"] != "normal"]
    strong_groups = sorted({r["group"] for r in strong})
    active_groups = sorted({r["group"] for r in active})

    if len(results) < CORE_COUNT:
        level = "nodata"
        reason = "partial"
    elif len(strong_groups) >= 2:
        level = "alerta"
        reason = ""
    elif active:
        level = "vigilancia"
        reason = ""
    else:
        level = "estable"
        reason = ""

    return {
        "level": level,
        "reason": reason,
        "available": len(results),
        "required": CORE_COUNT,
        "strong": strong,
        "watch": watch,
        "spikes": spikes,
        "signals": active,
        "strong_groups": strong_groups,
        "active_groups": active_groups,
        "evaluated_at": datetime.now(timezone.utc),
    }


def format_delta(value):
    magnitude = abs(value)
    if magnitude >= 100:
        return f"{value:+.0f}"
    if magnitude >= 10:
        return f"{value:+.1f}"
    return f"{value:+.2f}"


def build_message(result, is_test=False):
    if is_test:
        return (
            "🧪 Publicación de prueba — Observatorio de Partículas del TOA\n\n"
            "Estamos probando el envío automático de avisos a esta página de Facebook. "
            "Si ves este mensaje, la conexión funciona.\n\n"
            "Más información: " + PAGE_URL + "\n\n"
            + MARKER + " #Ciencia #PuertoRico"
        )

    count = len(result["strong"])
    groups = len(result["strong_groups"])
    details = []
    for item in result["strong"]:
        details.append(
            "• "
            + item["label"]
            + ": Δ "
            + format_delta(item["delta"])
            + " "
            + item["unit"]
            + " (z="
            + f"{item['z_recent']:.1f}"
            + ")"
        )
    details_text = "\n".join(details) if details else "• Variación sostenida en los sensores."

    return (
        "🟠 Anomalía estadística multivariable detectada\n\n"
        "El Observatorio de Partículas del TOA detectó una variación sostenida en "
        + str(count)
        + " variable(s) de "
        + str(groups)
        + " familia(s) de medición. Es un indicador experimental: no predice terremotos.\n\n"
        + details_text
        + "\n\n⚠️ Información de un estudio en desarrollo. No proviene de una autoridad oficial "
        "ni de un organismo de alerta, y su hipótesis aún no ha sido validada científicamente. "
        "No sustituye los avisos de la Red Sísmica de Puerto Rico, USGS o NOAA. "
        "No uses esta información para decisiones de seguridad.\n\n"
        "Más información: " + PAGE_URL + "\n\n"
        + MARKER + " #Ciencia #PuertoRico #Sismología"
    )


def parse_facebook_time(value):
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def facebook_get(path, params, token):
    query = dict(params)
    query["access_token"] = token
    url = GRAPH + path + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"User-Agent": "EESE-alerta/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"Facebook GET {path} falló (HTTP {error.code}): {body}")
    except urllib.error.URLError as error:
        raise RuntimeError(f"No se pudo conectar con Facebook: {error.reason}")


def resolve_page_credentials():
    """Devuelve (page_token, page_id, page_name).

    Si hay FB_USER_TOKEN, lo cambia por el token de la página usando
    /me/accounts. Si hay FB_PAGE_TOKEN, lo usa directamente y valida la página.
    """
    user_token = os.environ.get("FB_USER_TOKEN", "").strip()
    page_token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    page_id = os.environ.get("FB_PAGE_ID", "").strip() or DEFAULT_PAGE_ID

    if user_token:
        data = facebook_get(
            "/me/accounts",
            {"fields": "id,name,access_token", "limit": "100"},
            user_token,
        )
        pages = [p for p in data.get("data", []) if p.get("access_token")]
        if not pages:
            raise RuntimeError(
                "El token de usuario no administra ninguna página. "
                "Agrega tu usuario como administrador de la página "
                "(Configuración de la página > Acceso a la página) y vuelve a intentar."
            )

        target = None
        if page_id:
            for page in pages:
                if str(page.get("id")) == str(page_id):
                    target = page
                    break
        if target is None:
            for page in pages:
                name = (page.get("name") or "").lower()
                if "proyecto eese" in name or "eese" in name or "estudio energ" in name:
                    target = page
                    break
        if target is None:
            available = ", ".join(p.get("name", "?") for p in pages)
            raise RuntimeError(
                "No encontré la página en las que administra tu usuario. "
                "Páginas disponibles: " + available + ". Ajusta FB_PAGE_ID."
            )

        return (
            target["access_token"],
            str(target.get("id", page_id)),
            target.get("name", "?"),
        )

    if page_token:
        info = facebook_get("/" + page_id, {"fields": "id,name"}, page_token)
        return (
            page_token,
            str(info.get("id", page_id)),
            info.get("name", "?"),
        )

    return None, page_id, None


def last_marked_post(page_token, page_id):
    data = facebook_get(
        "/" + page_id + "/posts",
        {"fields": "created_time,message", "limit": "25"},
        page_token,
    )
    for post in data.get("data", []):
        message = post.get("message") or ""
        if MARKER in message:
            return parse_facebook_time(post.get("created_time"))
    return None


def publish(page_token, page_id, message):
    url = GRAPH + "/" + page_id + "/feed"
    body = urllib.parse.urlencode(
        {"message": message, "link": PAGE_URL, "access_token": page_token}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"User-Agent": "EESE-alerta/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body_text = error.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"Facebook POST falló (HTTP {error.code}): {body_text}")


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def main():
    dry_run = env_flag("DRY_RUN")
    force = env_flag("FORCE")
    try:
        cooldown_hours = float(os.environ.get("COOLDOWN_HOURS", "12") or 12)
    except ValueError:
        cooldown_hours = 12.0

    try:
        page_token, page_id, page_name = resolve_page_credentials()
    except Exception as error:  # noqa: BLE001
        print(f"ERROR de credenciales de Facebook: {error}", file=sys.stderr)
        return 1

    if page_token:
        print(f"Página de Facebook: {page_name} (id {page_id})")
    else:
        print(
            "AVISO: no hay FB_USER_TOKEN ni FB_PAGE_TOKEN. "
            "Se evaluarán los sensores, pero no se publicará nada."
        )

    try:
        feeds = {
            "ch1": fetch_feeds(*CHANNELS["ch1"]),
            "ch2": fetch_feeds(*CHANNELS["ch2"]),
        }
    except Exception as error:  # noqa: BLE001
        print(f"ERROR: no se pudieron leer los sensores: {error}", file=sys.stderr)
        return 1

    result = analyze(feeds)
    print(
        "Estado: "
        + result["level"]
        + " | señales fuertes: "
        + str(len(result["strong"]))
        + " | vigilancia: "
        + str(len(result["watch"]))
        + " | picos: "
        + str(len(result["spikes"]))
        + " | familias fuertes: "
        + str(len(result["strong_groups"]))
        + " | core: "
        + str(result["available"])
        + "/"
        + str(result["required"])
    )
    for item in result["signals"]:
        print(
            f"  - {item['label']}: Δ {format_delta(item['delta'])} {item['unit']} "
            f"(z={item['z_recent']:.1f}) estado={item['state']} grupo={item['group']}"
        )

    message = build_message(result, is_test=force)

    if dry_run:
        if page_token:
            print("Token de página OK: se puede publicar en la página indicada.")
        if result["level"] != "alerta" and not force:
            print("\nSin alerta activa: no se publicaría nada.")
            return 0
        print("\n--- MENSAJE QUE SE PUBLICARÍA ---")
        print(message)
        return 0

    if not page_token:
        if force:
            print(
                "ERROR: no hay credenciales de Facebook para la prueba de publicación.",
                file=sys.stderr,
            )
            return 1
        print("Sin credenciales de Facebook: no se publica.")
        return 0

    if not force:
        if result["level"] != "alerta":
            print("Sin alerta activa: no se publica.")
            return 0
        try:
            last_post = last_marked_post(page_token, page_id)
        except Exception as error:  # noqa: BLE001
            print(f"ERROR al consultar publicaciones recientes: {error}", file=sys.stderr)
            return 1
        if last_post is not None:
            elapsed = datetime.now(timezone.utc) - last_post
            if elapsed < timedelta(hours=cooldown_hours):
                remaining = timedelta(hours=cooldown_hours) - elapsed
                print(
                    f"Ya se publicó un aviso hace {elapsed}. "
                    f"Faltan {remaining} para el próximo."
                )
                return 0

    try:
        response = publish(page_token, page_id, message)
    except Exception as error:  # noqa: BLE001
        print(f"ERROR al publicar en Facebook: {error}", file=sys.stderr)
        return 1

    print("Publicado en Facebook. id=" + str(response.get("id", "?")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
