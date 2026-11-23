#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Actualiza alertas.json con los avisos detectados por el observatorio.

Se ejecuta desde GitHub Actions cada 10 minutos. No usa Facebook ni ningún
token: solo lee los canales públicos de ThingSpeak y escribe un archivo JSON
que la página muestra como historial.

Niveles que se registran:
  - alerta: variación sostenida coincidente en al menos 2 familias.
  - pico:   pico aislado (al alza o a la baja) en una variable esencial.

Los picos usan el mismo criterio en ambos sentidos: |z| >= 10 y un cambio
mínimo respecto a la línea base.
"""

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
ALERTAS_PATH = BASE_DIR / "alertas.json"

CHANNELS = {
    "ch1": (2439912, "BCX6UVTLQZ7VMK4F"),
    "ch2": (2972050, "8LMMRSTHHX26Z4MI"),
}

SERIES = [
    ("ch1", "field1", "Partículas reales", "u", "particulas", 15.0, 20.0),
    ("ch1", "field2", "Partículas imaginarias", "u", "particulas", 15.0, 20.0),
    ("ch2", "_ax", "Aceleración X", "m/s²", "aceleracion", 0.05, 0.15),
    ("ch2", "_ay", "Aceleración Y", "m/s²", "aceleracion", 0.05, 0.15),
    ("ch2", "_az", "Aceleración Z", "m/s²", "aceleracion", 0.05, 0.15),
    ("ch2", "_ares", "Aceleración resultante dinámica", "m/s²", "aceleracion", 0.03, 0.10),
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
ACCEL_ZERO_DEFAULT = {"x": 0.12, "y": -1.88, "z": 9.14}  # referencia inicial del módulo

COOLDOWN_ALERTA = timedelta(hours=6)
COOLDOWN_PICO = timedelta(hours=2)
SCAN_HOURS = 6  # ventana de respaldo para cubrir retrasos del workflow
# (umbral z de pico, cambio relativo mínimo respecto a la línea base)
SPIKE_RULES = {
    "Partículas reales": (5.5, 0.10),
}
MAX_EVENTS = 100


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
    request = urllib.request.Request(url, headers={"User-Agent": "EESE-alertas/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    return payload.get("feeds", [])


def analyze(feeds_by_channel):
    results = []
    recent_spikes = []

    # Cero operacional vectorial del acelerómetro.
    raw_ch2 = feeds_by_channel.get("ch2", [])
    axes = {"x": [], "y": [], "z": []}
    for feed in raw_ch2:
        for key, field in (("x", "field1"), ("y", "field2"), ("z", "field3")):
            raw = feed.get(field)
            if raw is None or raw == "":
                continue
            try:
                axes[key].append(float(raw))
            except (TypeError, ValueError):
                continue
    offsets = {
        key: (median(values) if values else ACCEL_ZERO_DEFAULT[key])
        for key, values in axes.items()
    }

    calibrated = []
    for feed in raw_ch2:
        try:
            ax = float(feed["field1"])
            ay = float(feed["field2"])
            az = float(feed["field3"])
        except (KeyError, TypeError, ValueError):
            continue
        dx = ax - offsets["x"]
        dy = ay - offsets["y"]
        dz = az - offsets["z"]
        item = dict(feed)
        item["_ax"] = dx
        item["_ay"] = dy
        item["_az"] = dz
        item["_ares"] = math.sqrt(dx * dx + dy * dy + dz * dz)
        calibrated.append(item)
    feeds_by_channel = dict(feeds_by_channel)
    feeds_by_channel["ch2"] = calibrated

    for channel, field, label, unit, group, min_sigma, min_delta in SERIES:
        pairs = []
        for feed in feeds_by_channel.get(channel, []):
            raw = feed.get(field)
            if raw is None or raw == "":
                continue
            try:
                pairs.append((float(raw), feed.get("created_at")))
            except (TypeError, ValueError):
                continue

        values = [pair[0] for pair in pairs]
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
        spike_z, min_relative = SPIKE_RULES.get(label, (Z_SPIKE, 0.0))

        state = "normal"
        if meaningful and abs(z_recent) >= Z_STRONG:
            state = "strong"
        elif meaningful and abs(z_recent) >= Z_WATCH:
            state = "watch"
        else:
            last_change = abs(values[-1] - center)
            relative_ok = not min_relative or last_change >= abs(center) * min_relative
            if last_change >= min_delta and relative_ok and abs(z_last) >= spike_z:
                state = "spike"

        direction_value = (values[-1] - center) if state == "spike" else delta
        z_threshold = Z_STRONG if state == "strong" else (Z_WATCH if state == "watch" else (spike_z if state == "spike" else None))
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
                "sigma": sigma,
                "min_delta": min_delta,
                "min_relative": min_relative,
                "z_threshold": z_threshold,
                "recent_median": recent_center,
                "last_value": values[-1],
                "direction": "up" if direction_value >= 0 else "down",
            }
        )

        # Revisar las últimas 6 horas (por tiempo, no por cantidad de puntos)
        # para no perder picos cuando GitHub retrasa el workflow.
        latest_time = parse_time(pairs[-1][1]) if pairs else None
        scan_start = latest_time - timedelta(hours=SCAN_HOURS) if latest_time else None
        for value, created_at in pairs:
            timestamp = parse_time(created_at)
            if scan_start and timestamp and timestamp < scan_start:
                continue
            change = abs(value - center)
            relative_ok = not min_relative or change >= abs(center) * min_relative
            if change >= min_delta and relative_ok and abs((value - center) / sigma) >= spike_z:
                recent_spikes.append(
                    {
                        "label": label,
                        "unit": unit,
                        "group": group,
                        "state": "spike",
                        "delta": value - center,
                        "z_recent": (value - center) / sigma,
                        "z_last": (value - center) / sigma,
                        "baseline": center,
                        "sigma": sigma,
                        "min_delta": min_delta,
                        "min_relative": min_relative,
                        "z_threshold": spike_z,
                        "recent_median": recent_center,
                        "last_value": value,
                        "direction": "up" if value >= center else "down",
                        "timestamp": created_at,
                    }
                )

    strong = [r for r in results if r["state"] == "strong"]
    watch = [r for r in results if r["state"] == "watch"]
    active = [r for r in results if r["state"] != "normal"]
    strong_groups = sorted({r["group"] for r in strong})

    # Un pico por variable: el más extremo de la ventana.
    by_label = {}
    for spike in recent_spikes:
        current = by_label.get(spike["label"])
        if current is None:
            by_label[spike["label"]] = spike
            continue
        current_time = parse_time(current.get("timestamp", ""))
        spike_time = parse_time(spike.get("timestamp", ""))
        if spike_time and (current_time is None or spike_time > current_time):
            by_label[spike["label"]] = spike
        elif spike_time == current_time and abs(spike["z_last"]) > abs(current["z_last"]):
            by_label[spike["label"]] = spike
    spikes = sorted(by_label.values(), key=lambda item: abs(item["z_last"]), reverse=True)[:5]

    if len(results) < CORE_COUNT:
        level = "nodata"
    elif len(strong_groups) >= 2:
        level = "alerta"
    elif spikes:
        level = "pico"
    elif active:
        level = "vigilancia"
    else:
        level = "estable"

    return {
        "level": level,
        "available": len(results),
        "strong": strong,
        "watch": watch,
        "spikes": spikes,
        "signals": active,
        "strong_groups": strong_groups,
    }


def direction_of(items):
    directions = {item["direction"] for item in items}
    if directions == {"down"}:
        return "down"
    if directions == {"up"}:
        return "up"
    return "mixed"


def event_is_molecular_only(event):
    groups = event.get("groups") or []
    variables = event.get("variables") or []
    groups_only = bool(groups) and all(group == "molecular" for group in groups)
    vars_only = not groups and bool(variables) and all(
        item.get("group") == "molecular" for item in variables if isinstance(item, dict)
    )
    return groups_only or vars_only


def load_events():
    if not ALERTAS_PATH.exists():
        return []
    try:
        data = json.loads(ALERTAS_PATH.read_text(encoding="utf-8"))
        events = data.get("events", []) if isinstance(data, dict) else []
        return [event for event in events if not event_is_molecular_only(event)]
    except (OSError, ValueError):
        return []


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def already_recorded(events, level, direction, groups, reference_time):
    cooldown = COOLDOWN_ALERTA if level == "alerta" else COOLDOWN_PICO
    group_key = tuple(groups)
    for event in events:
        if event.get("level") != level:
            continue
        if tuple(event.get("groups") or []) != group_key:
            continue
        if event.get("direction") != direction:
            continue
        timestamp = parse_time(event.get("timestamp", ""))
        if timestamp and abs((reference_time - timestamp).total_seconds()) < cooldown.total_seconds():
            return True
    return False


def main():
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
        f"Estado: {result['level']} | fuertes={len(result['strong'])} "
        f"| picos={len(result['spikes'])} | core={result['available']}/{CORE_COUNT}"
    )
    for item in result["signals"]:
        print(
            f"  - {item['label']}: Δ {item['delta']:+.3f} {item['unit']} "
            f"(z={item['z_recent']:.1f}) estado={item['state']} dirección={item['direction']}"
        )

    level = result["level"]
    if level == "alerta":
        items = result["strong"]
        cooldown = "6 horas"
    elif level == "pico":
        items = result["spikes"]
        cooldown = "2 horas"
    else:
        print("Sin alerta ni pico: no se modifica el historial.")
        return 0

    direction = direction_of(items)
    groups = sorted({item["group"] for item in items})
    now = datetime.now(timezone.utc)
    event_time = now
    if level == "pico":
        spike_times = [parse_time(item.get("timestamp", "")) for item in items]
        spike_times = [t for t in spike_times if t is not None]
        if spike_times:
            event_time = max(spike_times)
    events = load_events()

    if already_recorded(events, level, direction, groups, event_time):
        print(f"Evento ya registrado en las últimas {cooldown}: no se duplica.")
        return 0

    event = {
        "id": event_time.strftime("%Y%m%dT%H%M%SZ") + "-" + level,
        "timestamp": event_time.isoformat().replace("+00:00", "Z"),
        "level": level,
        "direction": direction,
        "groups": groups,
        "variables": [
            {
                "label": item["label"],
                "state": item["state"],
                "group": item["group"],
                "unit": item["unit"],
                "delta": round(item["delta"], 4),
                "z": round(item["z_last"] if item["state"] == "spike" else item["z_recent"], 2),
                "baseline": round(item.get("baseline", 0.0), 4),
                "sigma": round(item.get("sigma", 0.0), 4),
                "minDelta": round(item.get("min_delta", 0.0), 4),
                "zThreshold": round(item.get("z_threshold") or 0.0, 2),
                "recentMedian": round(item.get("recent_median", 0.0), 4),
                "lastValue": round(item.get("last_value", 0.0), 4),
                "relative": None if item["group"] == "aceleracion" else round(abs(item.get("delta", 0.0)) / abs(item.get("baseline") or 1.0), 4),
                "direction": item["direction"],
            }
            for item in items
        ],
    }
    events.insert(0, event)
    events.sort(key=lambda item: parse_time(item.get("timestamp", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    events = events[:MAX_EVENTS]
    payload = {
        "version": 1,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "events": events,
    }
    ALERTAS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Evento registrado: {level} {direction} en {', '.join(groups)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
