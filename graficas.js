(function() {
    'use strict';

    const CHANNEL1 = 2439912;
    const KEY1 = 'BCX6UVTLQZ7VMK4F';
    const CHANNEL2 = 2972050;
    const KEY2 = '8LMMRSTHHX26Z4MI';
    const GRAVITY_PR = 9.78;
    const ACCEL_ZERO_DEFAULT = { x: 0.12, y: -1.88, z: 9.14 };

    const AXIS_COLOR = '#334155';
    const GRID_COLOR = 'rgba(15, 23, 42, 0.12)';
    const LEGEND_COLOR = '#1F2937';
    const MAX_COLOR = '#FFB000';
    const MAX_BORDER = '#1F2937';
    const MIN_COLOR = '#00BFFF';
    const MIN_BORDER = '#1F2937';

    const UTC_LABEL = new Intl.DateTimeFormat('es-PR', {
        month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false
    });
    const UTC_DATETIME = new Intl.DateTimeFormat('es-PR', {
        dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC', hour12: false
    });
    const UTC_TICK = new Intl.DateTimeFormat('es-PR', {
        month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false
    });

    function utcLabel(value) {
        const date = new Date(value);
        return isNaN(date.getTime()) ? '' : UTC_LABEL.format(date) + ' UTC';
    }

    function utcDateTime(value) {
        const date = new Date(value);
        return isNaN(date.getTime()) ? '' : UTC_DATETIME.format(date) + ' UTC';
    }

    function utcTick(value) {
        const date = new Date(value);
        return isNaN(date.getTime()) ? '' : UTC_TICK.format(date) + ' UTC';
    }

    const CHART_CONFIGS = [
        { id: 'realParticles', label: 'Partículas Reales', field: 'field1', color: '#36A2EB', channel: 1, core: true, group: 'particulas' },
        { id: 'imaginaryParticles', label: 'Partículas Imag.', field: 'field2', color: '#FF6384', channel: 1, core: true, group: 'particulas' },
        { id: 'molecularPhysics', label: 'Física Molecular', field: 'field3', color: '#4BC0C0', channel: 1, core: false, group: 'molecular' },
        { id: 'xCoord', label: 'Coord. x', field: 'field4', color: '#FF9F40', channel: 1, core: false, group: 'contexto' },
        { id: 'yCoord', label: 'Coord. y', field: 'field5', color: '#9966FF', channel: 1, core: false, group: 'contexto' },
        { id: 'zCoord', label: 'Coord. z', field: 'field6', color: '#FFCD56', channel: 1, core: false, group: 'contexto' },
        { id: 'angle', label: 'Ángulo', field: 'field7', color: '#C9CBCF', channel: 1, core: false, group: 'contexto' },
        { id: 'accelX', label: 'Acel. X (cero op.)', field: '_ax', color: '#FF5733', channel: 2, core: true, group: 'aceleracion' },
        { id: 'accelY', label: 'Acel. Y (cero op.)', field: '_ay', color: '#33FF57', channel: 2, core: true, group: 'aceleracion' },
        { id: 'accelZ', label: 'Acel. Z (cero op.)', field: '_az', color: '#5733FF', channel: 2, core: true, group: 'aceleracion' },
        { id: 'accelResult', label: 'Acel. result. (g_PR)', field: '_ares', color: '#FF33A1', channel: 2, core: true, group: 'aceleracion' }
    ];

    const LABEL_ALIASES = {
        realParticles: ['partículas reales', 'particulas reales'],
        imaginaryParticles: ['partículas imaginarias', 'particulas imaginarias', 'partículas imag.'],
        molecularPhysics: ['física molecular', 'fisica molecular'],
        accelX: ['aceleración x', 'aceleracion x'],
        accelY: ['aceleración y', 'aceleracion y'],
        accelZ: ['aceleración z', 'aceleracion z'],
        accelResult: ['aceleración resultante', 'aceleracion resultante',
            'aceleración resultante (g_pr)', 'aceleracion resultante (g_pr)',
            'aceleración resultante dinámica']
    };

    function normalizeLabel(value) {
        return String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
    }

    function eventMatchesConfig(event, cfg) {
        const aliases = (LABEL_ALIASES[cfg.id] || []).map(normalizeLabel);
        const labels = (event.variables || []).map(variable => normalizeLabel(variable.label));
        if (labels.length) return labels.some(label => aliases.includes(label));
        const groups = event.groups || [];
        return groups.includes(cfg.group);
    }

    const chartInstances = {};
    let combinedChart = null;
    let seismicChart = null;
    let accelOffsets = Object.assign({}, ACCEL_ZERO_DEFAULT);
    let historyEvents = [];
    const chartMeta = {};
    let modalChart = null;

    const alertLinesPlugin = {
        id: 'alertLines',
        afterDatasetsDraw(chart, args, options) {
            const lines = options && options.lines ? options.lines : [];
            if (!lines.length) return;
            const { ctx, chartArea, scales } = chart;
            ctx.save();
            lines.forEach(line => {
                const position = scales.x.getPixelForValue(line.value);
                if (!Number.isFinite(position) || position < chartArea.left || position > chartArea.right) return;
                ctx.beginPath();
                ctx.setLineDash([4, 3]);
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = line.color;
                ctx.moveTo(position, chartArea.top);
                ctx.lineTo(position, chartArea.bottom);
                ctx.stroke();
                ctx.setLineDash([]);
            });
            ctx.restore();
        }
    };
    if (window.Chart) Chart.register(alertLinesPlugin);

    function median(values) {
        if (!values.length) return NaN;
        const sorted = values.slice().sort((a, b) => a - b);
        const n = sorted.length;
        return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
    }

    function mad(values, center) {
        if (!values.length) return NaN;
        return 1.4826 * median(values.map(value => Math.abs(value - center)));
    }

    function fetchJSON(url) {
        return fetch(url, { cache: 'no-store' }).then(response => {
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return response.json();
        });
    }

    function calibrate(feeds, offsets) {
        return (feeds || []).map(feed => {
            const ax = parseFloat(feed.field1);
            const ay = parseFloat(feed.field2);
            const az = parseFloat(feed.field3);
            if (!Number.isFinite(ax) || !Number.isFinite(ay) || !Number.isFinite(az)) {
                return Object.assign({}, feed);
            }
            const dx = ax - offsets.x;
            const dy = ay - offsets.y;
            const dz = az - offsets.z;
            return Object.assign({}, feed, {
                _ax: dx,
                _ay: dy,
                _az: dz,
                _ares: Math.sqrt(dx * dx + dy * dy + (dz + GRAVITY_PR) * (dz + GRAVITY_PR))
            });
        });
    }

    function processFeeds(feeds, field, maxPoints = 500) {
        if (!feeds || !feeds.length) return { labels: [], data: [] };
        const result = { labels: [], data: [], times: [] };
        const total = feeds.length;
        const step = total > maxPoints ? Math.max(1, Math.floor(total / maxPoints)) : 1;
        for (let i = 0; i < total; i += step) {
            const feed = feeds[i];
            const value = parseFloat(feed[field]);
            if (Number.isFinite(value)) {
                result.labels.push(utcLabel(feed.created_at));
                result.data.push(value);
                result.times.push(Date.parse(feed.created_at));
            }
        }
        const last = feeds[total - 1];
        const lastValue = parseFloat(last[field]);
        if (Number.isFinite(lastValue)) {
            const lastLabel = utcLabel(last.created_at);
            if (!result.labels.length || result.labels[result.labels.length - 1] !== lastLabel) {
                result.labels.push(lastLabel);
                result.data.push(lastValue);
                result.times.push(Date.parse(last.created_at));
            }
        }
        return result;
    }

    function highlight(data, baseColor) {
        let maxIdx = -1, maxVal = -Infinity, minIdx = -1, minVal = Infinity;
        data.forEach((value, index) => {
            if (!Number.isFinite(value)) return;
            if (value > maxVal) { maxVal = value; maxIdx = index; }
            if (value < minVal) { minVal = value; minIdx = index; }
        });
        const bg = data.map((_, i) => i === maxIdx ? MAX_COLOR : (i === minIdx ? MIN_COLOR : baseColor));
        const border = data.map((_, i) => i === maxIdx ? MAX_BORDER : (i === minIdx ? MIN_BORDER : baseColor));
        const width = data.map((_, i) => (i === maxIdx || i === minIdx) ? 1 : 0);
        const radius = data.map((_, i) => (i === maxIdx || i === minIdx) ? 2.5 : 1);
        return { maxIdx, maxVal, minIdx, minVal, bg, border, width, radius };
    }

    function normalizeZ(data) {
        const values = data.filter(value => Number.isFinite(value));
        if (!values.length) return data.map(() => null);
        const center = median(values);
        const sigma = Math.max(mad(values, center), Math.abs(center) * 0.005, 1e-9);
        return data.map(value => Number.isFinite(value) ? (value - center) / sigma : null);
    }

    function formatValue(value) {
        if (!Number.isFinite(value)) return '';
        const abs = Math.abs(value);
        if (abs >= 100) return value.toFixed(0);
        if (abs >= 10) return value.toFixed(1);
        return value.toFixed(2);
    }

    function setCaption(id, text) {
        const element = document.getElementById('max-' + id);
        if (element) element.textContent = text;
    }

    function setStatus(text) {
        const element = document.getElementById('chartStatus');
        if (element) element.textContent = text;
    }

    function buildWrappers() {
        const grid = document.getElementById('chartsGrid');
        if (!grid) return;
        grid.innerHTML = '';

        CHART_CONFIGS.forEach(cfg => {
            const wrapper = document.createElement('div');
            wrapper.className = 'chart-wrapper';
            wrapper.dataset.chartId = cfg.id;
            wrapper.title = 'Clic para ampliar la gráfica';
            wrapper.addEventListener('click', () => openChartModal(cfg.id, cfg.label), { passive: true });
            const label = document.createElement('div');
            label.className = 'chart-label';
            label.textContent = cfg.label;
            const max = document.createElement('span');
            max.className = 'chart-max';
            max.id = 'max-' + cfg.id;
            label.appendChild(max);
            wrapper.appendChild(label);
            const canvas = document.createElement('canvas');
            canvas.id = 'chart-' + cfg.id;
            canvas.width = 300;
            canvas.height = 150;
            wrapper.appendChild(canvas);
            const hint = document.createElement('span');
            hint.className = 'expand-hint';
            hint.textContent = '🔍 Ampliar';
            wrapper.appendChild(hint);
            grid.appendChild(wrapper);
        });

        const seismicWrapper = document.createElement('div');
        seismicWrapper.className = 'chart-wrapper seismic';
        seismicWrapper.dataset.chartId = 'earthquakes';
        seismicWrapper.title = 'Clic para ampliar la gráfica';
        seismicWrapper.addEventListener('click', () => openChartModal('earthquakes', 'Sismos M≥6.0 (USGS)'), { passive: true });
        const seismicLabel = document.createElement('div');
        seismicLabel.className = 'chart-label';
        seismicLabel.textContent = '🌍 Sismos M≥6.0 (USGS) · UTC';
        const seismicMax = document.createElement('span');
        seismicMax.className = 'chart-max';
        seismicMax.id = 'max-earthquakes';
        seismicLabel.appendChild(seismicMax);
        seismicWrapper.appendChild(seismicLabel);
        const seismicCanvas = document.createElement('canvas');
        seismicCanvas.id = 'chart-earthquakes';
        seismicCanvas.width = 600;
        seismicCanvas.height = 200;
        seismicWrapper.appendChild(seismicCanvas);
        const seismicHint = document.createElement('span');
        seismicHint.className = 'expand-hint';
        seismicHint.textContent = '🔍 Ampliar';
        seismicWrapper.appendChild(seismicHint);
        grid.appendChild(seismicWrapper);
    }

    function individualOptions(lines) {
        return {
            responsive: true,
            maintainAspectRatio: true,
            animation: { duration: 150 },
            interaction: { mode: 'nearest', intersect: false },
            plugins: {
                legend: { display: false },
                alertLines: { lines: lines || [] },
                tooltip: {
                    enabled: true,
                    mode: 'nearest',
                    intersect: false,
                    callbacks: {
                        title: items => items && items[0] ? items[0].label : '',
                        label: ctx => ctx.parsed.y !== null
                            ? ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(4) : 'N/A'
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        color: AXIS_COLOR,
                        maxTicksLimit: 6,
                        font: { size: 11 },
                        maxRotation: 30
                    },
                    grid: { display: false }
                },
                y: {
                    ticks: {
                        color: AXIS_COLOR,
                        font: { size: 11 },
                        callback: value => value.toFixed(2)
                    },
                    grid: { color: GRID_COLOR },
                    beginAtZero: false
                }
            }
        };
    }

    function renderIndividual(cfg, feeds) {
        const canvas = document.getElementById('chart-' + cfg.id);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const parsed = processFeeds(feeds, cfg.field);
        const labels = parsed.labels;
        const data = parsed.data;
        chartMeta[cfg.id] = { labels: parsed.labels, times: parsed.times };
        const lines = buildAlertLines(chartMeta[cfg.id], cfg, false);
        const hl = highlight(data, cfg.color);
        lines.forEach(line => {
            if (Number.isInteger(line.index) && line.index >= 0 && line.index < data.length) {
                hl.bg[line.index] = line.color;
                hl.border[line.index] = '#1F2937';
                hl.width[line.index] = 1;
                hl.radius[line.index] = 4;
            }
        });
        setCaption(cfg.id, data.length && hl.maxIdx >= 0
            ? 'máx: ' + formatValue(hl.maxVal) + ' · mín: ' + formatValue(hl.minVal)
            : '');

        if (chartInstances[cfg.id]) {
            const chart = chartInstances[cfg.id];
            chart.data.labels = labels;
            chart.data.datasets[0].data = data;
            chart.data.datasets[0].pointBackgroundColor = hl.bg;
            chart.data.datasets[0].pointBorderColor = hl.border;
            chart.data.datasets[0].pointBorderWidth = hl.width;
            chart.data.datasets[0].pointRadius = hl.radius;
            chart.options.plugins.alertLines = { lines: lines };
            chart.update('none');
            return;
        }

        chartInstances[cfg.id] = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: cfg.label,
                    data,
                    borderColor: cfg.color,
                    backgroundColor: cfg.color + '33',
                    borderWidth: 2,
                    pointBackgroundColor: hl.bg,
                    pointBorderColor: hl.border,
                    pointBorderWidth: hl.width,
                    pointRadius: hl.radius,
                    pointHoverRadius: 5,
                    pointHitRadius: 10,
                    fill: true,
                    tension: 0.2
                }]
            },
            options: individualOptions(lines)
        });
    }

    function renderCombined(feeds1, feeds2) {
        const canvas = document.getElementById('chart-combined');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const datasets = [];
        let labels = [];
        let meta = null;
        CHART_CONFIGS.forEach(cfg => {
            const feeds = cfg.channel === 2 ? feeds2 : feeds1;
            const parsed = processFeeds(feeds, cfg.field);
            if (!meta && parsed.labels.length) meta = { labels: parsed.labels.slice(), times: parsed.times.slice() };
            if (parsed.labels.length && labels.length === 0) labels = parsed.labels.slice();
            if (!parsed.data.length) return;
            datasets.push({
                label: cfg.label,
                data: normalizeZ(parsed.data),
                borderColor: cfg.color,
                backgroundColor: cfg.color + '10',
                borderWidth: cfg.core ? 2 : 1.2,
                borderDash: cfg.core ? [] : [4, 3],
                pointRadius: 0,
                pointHoverRadius: 3,
                fill: false,
                tension: 0.25,
                spanGaps: true
            });
        });
        chartMeta.combined = meta;
        const lines = buildAlertLines(meta, null, false);
        if (combinedChart) {
            combinedChart.data.labels = labels;
            combinedChart.data.datasets = datasets;
            combinedChart.options.plugins.alertLines = { lines: lines };
            combinedChart.update('none');
            return;
        }
        combinedChart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2.6,
                animation: { duration: 150 },
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom',
                        labels: {
                            color: LEGEND_COLOR,
                            font: { size: 10 },
                            boxWidth: 9,
                            boxHeight: 9,
                            padding: 8,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: ctx => {
                                if (ctx.parsed.y === null || ctx.parsed.y === undefined) return 'N/A';
                                const value = ctx.parsed.y;
                                return ctx.dataset.label + ': ' + (value >= 0 ? '+' : '') + value.toFixed(2) + 'σ';
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: AXIS_COLOR, font: { size: 11 }, maxTicksLimit: 8, maxRotation: 30 },
                        grid: { color: GRID_COLOR }
                    },
                    y: {
                        title: { display: true, text: 'z (desviaciones robustas)', color: AXIS_COLOR, font: { size: 11, weight: 'bold' } },
                        ticks: { color: AXIS_COLOR, font: { size: 11 }, callback: value => value.toFixed(1) },
                        grid: {
                            color: ctxGrid => ctxGrid && ctxGrid.tick && ctxGrid.tick.value === 0
                                ? 'rgba(15, 23, 42, 0.32)' : GRID_COLOR
                        },
                        beginAtZero: false
                    }
                },
                elements: { point: { radius: 0, hoverRadius: 3 }, line: { borderJoinStyle: 'round' } }
            }
        });
        if (combinedChart) {
            combinedChart.options.plugins.alertLines = { lines: lines };
            combinedChart.update('none');
        }
    }

    async function updateChartsData() {
        try {
            const [data1, data2] = await Promise.all([
                fetchJSON('https://api.thingspeak.com/channels/' + CHANNEL1 + '/feeds.json?api_key=' + KEY1 + '&results=8000'),
                fetchJSON('https://api.thingspeak.com/channels/' + CHANNEL2 + '/feeds.json?api_key=' + KEY2 + '&results=8000')
            ]);
            const feeds1 = data1.feeds || [];
            const feeds2 = data2.feeds || [];

            const samples = field => feeds2
                .map(feed => parseFloat(feed[field]))
                .filter(value => Number.isFinite(value));
            const x = samples('field1');
            const y = samples('field2');
            const z = samples('field3');
            if (x.length) accelOffsets.x = median(x);
            if (y.length) accelOffsets.y = median(y);
            if (z.length) accelOffsets.z = median(z);
            const feeds2c = calibrate(feeds2, accelOffsets);

            CHART_CONFIGS.forEach(cfg => {
                renderIndividual(cfg, cfg.channel === 2 ? feeds2c : feeds1);
            });
            setStatus('Datos actualizados: ' + utcDateTime(new Date()));
        } catch (error) {
            setStatus('No se pudieron actualizar las gráficas: ' + error.message);
        }
    }

    function processEarthquakes(features) {
        return (features || []).slice().reverse().map(feature => {
            const props = feature.properties || {};
            if (props.mag === null || props.mag === undefined || isNaN(props.mag)) return null;
            return { x: props.time, y: props.mag, place: props.place || 'Ubicación desconocida' };
        }).filter(Boolean);
    }

    function usgsUrl() {
        const end = new Date();
        const start = new Date(end);
        start.setDate(start.getDate() - 7);
        return 'https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson'
            + '&starttime=' + encodeURIComponent(start.toISOString())
            + '&endtime=' + encodeURIComponent(end.toISOString())
            + '&minmagnitude=6&orderby=time';
    }

    async function updateSeismic() {
        try {
            const data = await fetchJSON(usgsUrl());
            const points = processEarthquakes(data.features || []);
            const canvas = document.getElementById('chart-earthquakes');
            if (!canvas) return;
            let maxIdx = -1, maxVal = -Infinity;
            points.forEach((point, index) => {
                if (point.y > maxVal) { maxVal = point.y; maxIdx = index; }
            });
            const bg = points.map((point, index) => index === maxIdx ? MAX_COLOR
                : (point.y >= 8 ? '#8B0000' : point.y >= 7 ? '#FF0000' : '#FF8C00'));
            const border = points.map((_, index) => index === maxIdx ? MAX_BORDER : '#FFFFFF');
            const width = points.map((_, index) => index === maxIdx ? 2 : 1);
            const radius = points.map((_, index) => index === maxIdx ? 6 : 4);
            setCaption('earthquakes', points.length ? 'M' + maxVal.toFixed(1) : '');
            chartMeta.earthquakes = { labels: [], times: points.map(point => point.x) };
            const lines = buildAlertLines(chartMeta.earthquakes, null, true);
            const range = { min: Date.now() - 7 * 24 * 60 * 60 * 1000, max: Date.now() };
            if (seismicChart) {
                const dataset = seismicChart.data.datasets[0];
                dataset.data = points;
                dataset.pointBackgroundColor = bg;
                dataset.pointBorderColor = border;
                dataset.pointBorderWidth = width;
                dataset.pointRadius = radius;
                seismicChart.options.scales.x.min = range.min;
                seismicChart.options.scales.x.max = range.max;
                seismicChart.options.plugins.alertLines = { lines: lines };
                seismicChart.update('none');
                return;
            }
            const ctx = canvas.getContext('2d');
            seismicChart = new Chart(ctx, {
                type: 'line',
                data: { datasets: [{
                    label: 'Magnitud',
                    data: points,
                    borderColor: '#FF4444',
                    backgroundColor: 'rgba(255, 68, 68, 0.15)',
                    pointBackgroundColor: bg,
                    pointBorderColor: border,
                    pointBorderWidth: width,
                    pointRadius: radius,
                    pointHoverRadius: 7,
                    borderWidth: 2,
                    fill: true,
                    tension: 0,
                    spanGaps: true
                }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    animation: { duration: 150 },
                    parsing: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: ctx => ctx[0] ? utcDateTime(ctx[0].parsed.x) : '',
                                label: ctx => {
                                    const place = ctx.raw && ctx.raw.place ? ctx.raw.place : '';
                                    return 'M' + ctx.parsed.y.toFixed(1) + ' - ' + place;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            min: range.min,
                            max: range.max,
                            time: {
                                unit: 'day',
                                displayFormats: { day: 'MMM D' },
                                tooltipFormat: 'lll'
                            },
                            ticks: {
                                color: AXIS_COLOR,
                                maxTicksLimit: 6,
                                font: { size: 11 },
                                maxRotation: 30,
                                callback: value => utcTick(value)
                            },
                            grid: { display: false }
                        },
                        y: {
                            beginAtZero: true,
                            suggestedMax: 9,
                            ticks: {
                                color: AXIS_COLOR,
                                font: { size: 11 },
                                callback: value => value.toFixed(1)
                            },
                            grid: { color: GRID_COLOR }
                        }
                    }
                }
            });
            if (seismicChart) {
                seismicChart.options.plugins.alertLines = { lines: lines };
                seismicChart.update('none');
            }
        } catch (error) {
            setCaption('earthquakes', 'Error USGS');
        }
    }

    function parseEventTime(value) {
        if (!value) return NaN;
        return Date.parse(value);
    }

    function isMolecularOnly(event) {
        const groups = event.groups || [];
        const variables = event.variables || [];
        const groupsOnly = groups.length > 0 && groups.every(group => group === 'molecular');
        const varsOnly = groups.length === 0 && variables.length > 0 &&
            variables.every(variable => variable && variable.group === 'molecular');
        return groupsOnly || varsOnly;
    }

    function buildAlertLines(meta, cfg, timeAxis) {
        if (!meta || !meta.times || !meta.times.length || !historyEvents.length) return [];
        const maxGap = 2 * 60 * 60 * 1000;
        const lines = [];
        const seen = new Set();
        historyEvents.forEach(event => {
            if (cfg && !eventMatchesConfig(event, cfg)) return;
            const eventTime = parseEventTime(event.timestamp);
            if (!Number.isFinite(eventTime)) return;

            let bestIndex = -1;
            let bestDiff = Infinity;
            meta.times.forEach((time, index) => {
                const diff = Math.abs(time - eventTime);
                if (diff < bestDiff) {
                    bestDiff = diff;
                    bestIndex = index;
                }
            });
            if (bestIndex < 0 || bestDiff > maxGap) return;

            const value = timeAxis ? eventTime : (meta.labels[bestIndex] || null);
            if (!value) return;
            const color = event.level === 'alerta' ? '#FF5252' : '#FF9800';
            const label = '';
            const key = String(value) + color;
            if (seen.has(key)) return;
            seen.add(key);
            lines.push({ value, color, label, index: bestIndex });
        });
        return lines;
    }

    function applyHistoryLines() {
        CHART_CONFIGS.forEach(cfg => {
            const chart = chartInstances[cfg.id];
            const meta = chartMeta[cfg.id];
            if (!chart || !meta) return;
            const lines = buildAlertLines(meta, cfg, false);
            const dataset = chart.data.datasets[0];
            lines.forEach(line => {
                if (Number.isInteger(line.index) && line.index >= 0 && line.index < dataset.data.length) {
                    dataset.pointBackgroundColor[line.index] = line.color;
                    dataset.pointBorderColor[line.index] = '#1F2937';
                    dataset.pointBorderWidth[line.index] = 1;
                    dataset.pointRadius[line.index] = 4;
                }
            });
            chart.options.plugins.alertLines = { lines: lines };
            chart.update('none');
        });
        if (seismicChart && chartMeta.earthquakes) {
            seismicChart.options.plugins.alertLines = { lines: buildAlertLines(chartMeta.earthquakes, null, true) };
            seismicChart.update('none');
        }
    }

    async function loadHistory() {
        try {
            let data;
            try {
                data = await fetchJSON('alertas.json?t=' + Date.now());
            } catch (error) {
                data = await fetchJSON('https://raw.githubusercontent.com/raymondrosa/particulas-sismicas/main/alertas.json?t=' + Date.now());
            }
            historyEvents = (data.events || []).filter(event => event.timestamp && !isMolecularOnly(event));
            applyHistoryLines();
        } catch (error) {
            historyEvents = [];
            applyHistoryLines();
        }
    }

    function closeChartModal() {
        const modal = document.getElementById('chartModal');
        const canvas = document.getElementById('modalCanvas');
        if (canvas && canvas._chart) {
            canvas._chart.destroy();
            canvas._chart = null;
        }
        if (modal) modal.classList.remove('active');
        document.body.style.overflow = '';
    }

    function openChartModal(chartId, title) {
        const source = chartId === 'combined' ? combinedChart
            : chartId === 'earthquakes' ? seismicChart
            : chartInstances[chartId];
        if (!source) return;
        const modal = document.getElementById('chartModal');
        const modalTitle = document.getElementById('modalTitle');
        const modalCanvas = document.getElementById('modalCanvas');
        if (!modal || !modalTitle || !modalCanvas) return;

        if (modalCanvas._chart) {
            modalCanvas._chart.destroy();
            modalCanvas._chart = null;
        }

        modalTitle.textContent = title;
        const data = JSON.parse(JSON.stringify(source.data));
        const options = {
            responsive: true,
            maintainAspectRatio: true,
            animation: { duration: 0 },
            parsing: source.options.parsing,
            interaction: source.options.interaction,
            plugins: {
                legend: {
                    display: chartId === 'combined',
                    position: 'bottom',
                    labels: { color: LEGEND_COLOR, font: { size: 13 }, boxWidth: 10, padding: 10 }
                },
                tooltip: source.options.plugins ? source.options.plugins.tooltip : undefined,
                alertLines: source.options.plugins && source.options.plugins.alertLines
                    ? source.options.plugins.alertLines : { lines: [] }
            },
            scales: source.options.scales,
            elements: source.options.elements
        };

        modalCanvas._chart = new Chart(modalCanvas.getContext('2d'), {
            type: source.config.type,
            data: data,
            options: options
        });
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function init() {
        buildWrappers();
        loadHistory();
        updateChartsData();
        updateSeismic();
        setInterval(updateChartsData, 20000);
        setInterval(updateSeismic, 300000);
        setInterval(loadHistory, 600000);

        const closeButton = document.getElementById('modalCloseBtn');
        const modal = document.getElementById('chartModal');
        if (closeButton) closeButton.addEventListener('click', event => {
            event.stopPropagation();
            closeChartModal();
        });
        if (modal) modal.addEventListener('click', event => {
            if (event.target === modal) closeChartModal();
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') closeChartModal();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
