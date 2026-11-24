(function() {
    'use strict';

    const USGS_URL = 'https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=6&orderby=time';
    const UTC_DATETIME = new Intl.DateTimeFormat('es-PR', {
        dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC', hour12: false
    });
    const UTC_SHORT = new Intl.DateTimeFormat('es-PR', {
        month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false
    });

    let map = null;
    let markerLayer = null;
    let events = [];
    let initialFitDone = false;

    function utcDateTime(value) {
        const date = new Date(value);
        return isNaN(date.getTime()) ? '—' : UTC_DATETIME.format(date) + ' UTC';
    }

    function utcShort(value) {
        const date = new Date(value);
        return isNaN(date.getTime()) ? '—' : UTC_SHORT.format(date) + ' UTC';
    }

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function magnitudeColor(magnitude) {
        if (magnitude >= 8) return '#FF2D2D';
        if (magnitude >= 7) return '#FF6B00';
        return '#FFB000';
    }

    function magnitudeRadius(magnitude) {
        return Math.max(4, Math.min(14, 4 + (magnitude - 6) * 2.6));
    }

    function setStatus(text) {
        const element = document.getElementById('mapStatus');
        if (element) element.textContent = text;
    }

    function setStat(id, text) {
        const element = document.getElementById(id);
        if (element) element.textContent = text;
    }

    function buildUrl() {
        const end = new Date();
        const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
        return USGS_URL
            + '&starttime=' + encodeURIComponent(start.toISOString())
            + '&endtime=' + encodeURIComponent(end.toISOString());
    }

    async function fetchJSON(url) {
        const response = await fetch(url, { cache: 'no-store' });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
    }

    function parseEvents(features) {
        return (features || []).map(feature => {
            const props = feature.properties || {};
            const coordinates = feature.geometry && feature.geometry.coordinates ? feature.geometry.coordinates : [];
            if (props.mag === null || props.mag === undefined || isNaN(props.mag)) return null;
            if (!coordinates.length || coordinates.length < 2) return null;
            return {
                id: feature.id || String(props.time),
                magnitude: Number(props.mag),
                place: props.place || 'Ubicación desconocida',
                time: props.time,
                url: props.url || '',
                longitude: Number(coordinates[0]),
                latitude: Number(coordinates[1]),
                depth: coordinates.length > 2 ? Number(coordinates[2]) : null
            };
        }).filter(Boolean).sort((a, b) => b.time - a.time);
    }

    function popupHtml(event) {
        const depth = Number.isFinite(event.depth) ? event.depth.toFixed(1) + ' km' : '—';
        const link = event.url
            ? '<a href="' + escapeHtml(event.url) + '" target="_blank" rel="noopener noreferrer">Ver detalle en USGS ↗</a>'
            : '';
        return '<div class="map-popup">'
            + '<div class="map-popup-mag">M' + event.magnitude.toFixed(1) + '</div>'
            + '<div class="map-popup-place">' + escapeHtml(event.place) + '</div>'
            + '<div class="map-popup-meta">UTC: ' + escapeHtml(utcDateTime(event.time)) + '</div>'
            + '<div class="map-popup-meta">Profundidad: ' + escapeHtml(depth) + '</div>'
            + link
            + '</div>';
    }

    function updateStats() {
        setStat('mapCount', String(events.length));
        setStat('mapMax', events.length ? 'M' + Math.max.apply(null, events.map(event => event.magnitude)).toFixed(1) : '—');
        setStat('mapLast', events.length ? utcShort(events[0].time) : '—');
    }

    function updateList() {
        const list = document.getElementById('mapEventList');
        if (!list) return;
        list.innerHTML = '';
        if (!events.length) {
            const empty = document.createElement('p');
            empty.className = 'map-empty';
            empty.textContent = 'No hay sismos M≥6 en los últimos 7 días.';
            list.appendChild(empty);
            return;
        }

        events.forEach(event => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'map-event-item';
            item.title = 'Centrar el mapa en este evento';

            const mag = document.createElement('span');
            mag.className = 'map-event-mag';
            mag.textContent = 'M' + event.magnitude.toFixed(1);
            mag.style.color = magnitudeColor(event.magnitude);

            const copy = document.createElement('span');
            copy.className = 'map-event-copy';
            const place = document.createElement('span');
            place.className = 'map-event-place';
            place.textContent = event.place;
            const time = document.createElement('span');
            time.className = 'map-event-time';
            time.textContent = utcShort(event.time);
            copy.appendChild(place);
            copy.appendChild(time);

            item.appendChild(mag);
            item.appendChild(copy);
            item.addEventListener('click', () => {
                if (!map) return;
                map.flyTo([event.latitude, event.longitude], 4, { duration: 0.6 });
                if (event.marker) event.marker.openPopup();
            });
            list.appendChild(item);
        });
    }

    function render() {
        if (!map || !markerLayer) return;
        markerLayer.clearLayers();
        events.forEach(event => {
            const color = magnitudeColor(event.magnitude);
            const marker = L.circleMarker([event.latitude, event.longitude], {
                radius: magnitudeRadius(event.magnitude),
                color: '#07111d',
                weight: 1.5,
                fillColor: color,
                fillOpacity: 0.86
            });
            marker.bindTooltip(
                'M' + event.magnitude.toFixed(1) + ' · ' + escapeHtml(event.place),
                { direction: 'top', offset: [0, -4] }
            );
            marker.bindPopup(popupHtml(event), { maxWidth: 320 });
            marker.addTo(markerLayer);
            event.marker = marker;
        });

        updateStats();
        updateList();
        setStatus(events.length
            ? 'Actualizado: ' + utcDateTime(new Date()) + ' · ' + events.length + ' sismos M≥6'
            : 'Actualizado: ' + utcDateTime(new Date()) + ' · sin sismos M≥6');
        setTimeout(() => map.invalidateSize(), 150);

        if (!initialFitDone && events.length) {
            const bounds = L.latLngBounds(events.map(event => [event.latitude, event.longitude]));
            map.fitBounds(bounds, { padding: [30, 30], maxZoom: 3 });
            initialFitDone = true;
        }
    }

    async function load() {
        setStatus('Cargando sismos…');
        try {
            const data = await fetchJSON(buildUrl());
            events = parseEvents(data.features || []);
            render();
        } catch (error) {
            setStatus('No se pudo cargar el mapa: ' + error.message);
            const list = document.getElementById('mapEventList');
            if (list) list.innerHTML = '<p class="map-empty">Error al consultar USGS.</p>';
        }
    }

    function init() {
        if (!window.L) {
            setStatus('No se pudo cargar Leaflet.');
            return;
        }
        const container = document.getElementById('worldMap');
        if (!container) return;

        map = L.map('worldMap', {
            worldCopyJump: true,
            minZoom: 2,
            maxZoom: 8,
            zoomControl: true
        }).setView([15, 0], 2);

        map.createPane('countries');
        map.getPane('countries').style.zIndex = 200;
        map.attributionControl.addAttribution('Natural Earth / world.geo.json');

        markerLayer = L.layerGroup().addTo(map);
        loadWorld();
        load();
        setInterval(load, 300000);
    }

    async function loadWorld() {
        try {
            const world = await fetchJSON('mundo.geojson?v=4');
            L.geoJSON(world, {
                pane: 'countries',
                interactive: false,
                style: {
                    color: '#58C7E8',
                    weight: 0.8,
                    opacity: 1,
                    fillColor: '#123A50',
                    fillOpacity: 1
                }
            }).addTo(map);
        } catch (error) {
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                subdomains: 'abcd',
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
            }).addTo(map);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
