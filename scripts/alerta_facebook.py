#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aviso experimental de tendencia sísmica -> página de Facebook.

Lee los canales públicos de ThingSpeak del Observatorio de Partículas del TOA,
aplica la misma detección que la página y, si el nivel es "alerta", publica
un aviso en la página de Facebook indicada.

Requisitos:
  - Variable de entorno FB_PAGE_TOKEN con un token de página (nunca en el HTML).
  - Permisos: pages_manage_posts y pages_read_engagement.
  - Opcional: FB_PAGE_ID (si no se indica, se usa "me").
  - Opcional: DRY_RUN=1 para mostrar el mensaje sin publicar.
  - Opcional: FORCE=1 para publicar una prueba aunque no haya alerta.
  - Opcional: COOLDOWN_HOURS (por defecto 12).

Uso local:
  DRY_RUN=1 python scripts/alerta_facebook.py
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

CHANNELS = {
    "ch1": (2439912, "BCX6UVTLQZ7VMK4F"),
    "ch2": (2972050, "8LMMRSTHHX26Z4MI"),
}

# (canal, campo, etiqueta, unidad, minSigma, minDelta)
SERIES = [
    ("ch1", "field1", "Partículas reales", "u", 15.0, 20.0),
    ("ch1", "field2", "Partículas imaginarias", "u", 15.0, 20.0),
    ("ch1", "field3", "Física molecular", "u", 8.0, 10.0),
    ("ch2", "field1", "Aceleración X", "m/s²", 0.05, 0.15),
    ("ch2", "field2", "Aceleración Y", "m/s²", 0.05, 0.15),
    ("ch2", "field3", "Aceleración Z", "m/s²", 0.05, 0.15),
    ("ch2", "field4", "Aceleración resultante", "m/s²", 0.10, 0.20),
]

RECENT_POINTS = 240       # ~1 hora con muestreo de ~15 s
BASELINE_POINTS = 1200    # ~5 horas previas
MIN_BASELINE = 90
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
    for channel, field, label, unit, min_sigma, min_delta in SERIES:
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
        if len(baseline) < MIN_BASELINE or len(recent) < 30:
            continue

        center = median(baseline)
        sigma = robust_sigma(baseline, center, min_sigma)
        recent_center = median(recent)
        delta = recent_center - center
        z_recent = delta / sigma
        z_last = (values[-1] - center) / sigma
        meaningful = abs(delta) >= min_delta

        state = "normal"
        if meaningful:
            if abs(z_recent) >= Z_STRONG:
                state = "strong"
            elif abs(z_recent) >= Z_WATCH:
                state = "watch"
            elif abs(z_last) >= Z_SPIKE:
                state = "spike"

        results.append(
            {
                "label": label,
                "unit": unit,
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

    if not results:
        level = "nodata"
    elif strong:
        level = "alerta"
    elif watch or spikes:
        level = "vigilancia"
    else:
        level = "estable"

    if len(strong) >= 3:
        confidence = "alta"
    elif len(strong) == 2:
        confidence = "media"
    else:
        confidence = "baja"

    return {
        "level": level,
        "confidence": confidence,
        "strong": strong,
        "watch": watch,
        "spikes": spikes,
        "signals": strong + watch + spikes,
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
        "🟠 Aviso experimental: posible aumento en la tendencia sísmica\n\n"
        "El Observatorio de Partículas del TOA detectó una variación sostenida en "
        + str(count)
        + " variable(s) de sus sensores. Ventana de referencia: próximas 24 horas (aprox.).\n\n"
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
        body = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Facebook GET {path} falló (HTTP {error.code}): {body}")
    except urllib.error.URLError as error:
        raise RuntimeError(f"No se pudo conectar con Facebook: {error.reason}")


def last_marked_post(token):
    data = facebook_get(
        "/me/posts",
        {"fields": "created_time,message", "limit": "25"},
        token,
    )
    for post in data.get("data", []):
        message = post.get("message") or ""
        if MARKER in message:
            return parse_facebook_time(post.get("created_time"))
    return None


def publish(token, message):
    page = os.environ.get("FB_PAGE_ID", "").strip() or "me"
    url = GRAPH + "/" + page + "/feed"
    body = urllib.parse.urlencode(
        {"message": message, "link": PAGE_URL, "access_token": token}
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
        body_text = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Facebook POST falló (HTTP {error.code}): {body_text}")


def env_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def main():
    dry_run = env_flag("DRY_RUN")
    force = env_flag("FORCE")
    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    try:
        cooldown_hours = float(os.environ.get("COOLDOWN_HOURS", "12") or 12)
    except ValueError:
        cooldown_hours = 12.0

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
    )
    for item in result["signals"]:
        print(
            f"  - {item['label']}: Δ {format_delta(item['delta'])} {item['unit']} "
            f"(z={item['z_recent']:.1f}) estado={item['state']}"
        )

    message = build_message(result, is_test=force)

    if dry_run:
        if result["level"] != "alerta" and not force:
            print("\nSin alerta activa: no se publicaría nada.")
            return 0
        print("\n--- MENSAJE QUE SE PUBLICARÍA ---")
        print(message)
        return 0

    if not token:
        print(
            "AVISO: falta el secreto FB_PAGE_TOKEN; no se publica nada. "
            "Configúralo en GitHub > Settings > Secrets and variables > Actions.",
            file=sys.stderr,
        )
        return 0

    if not force:
        if result["level"] != "alerta":
            print("Sin alerta activa: no se publica.")
            return 0
        try:
            last_post = last_marked_post(token)
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
        response = publish(token, message)
    except Exception as error:  # noqa: BLE001
        print(f"ERROR al publicar en Facebook: {error}", file=sys.stderr)
        return 1

    print("Publicado en Facebook. id=" + str(response.get("id", "?")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
