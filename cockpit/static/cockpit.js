/* ═══════════════════════════════════════════════════════════════════
   OSMOSIS Cockpit — Moteur de rendu
   WebSocket client + rendering 6 widgets + SVG pipeline
   Target: Corsair Xeneon Edge 2560×720
   ═══════════════════════════════════════════════════════════════════ */

(function () {
    'use strict';

    // ── State ─────────────────────────────────────────────────────
    let ws = null;
    let connected = false;
    let lastState = null;

    // ── SVG namespace ─────────────────────────────────────────────
    const SVG_NS = 'http://www.w3.org/2000/svg';

    // ── Colors ────────────────────────────────────────────────────
    const C = {
        success: '#10B981', successGlow: 'rgba(16,185,129,0.15)',
        warning: '#F59E0B', warningGlow: 'rgba(245,158,11,0.15)',
        error: '#EF4444',   errorGlow: 'rgba(239,68,68,0.15)',
        active: '#3B82F6',
        neutral: '#475569',  neutralDim: '#334155',
        bgElevated: '#131A2B',
        textPrimary: '#E2E8F0', textSecondary: '#94A3B8',
        textTertiary: '#4A5568', textAccent: '#7DD3FC',
    };

    // ── Helpers ───────────────────────────────────────────────────
    function fmt(n) { return n.toLocaleString('fr-FR'); }
    function fmtCost(n) { return '$' + n.toFixed(4); }
    function fmtTime(s) {
        if (s == null || s <= 0) return '';
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = Math.floor(s % 60);
        if (h > 0) return `${h}h${String(m).padStart(2,'0')}m`;
        if (m > 0) return `${m}m${String(sec).padStart(2,'0')}s`;
        return `${sec}s`;
    }
    function fmtClock() {
        const d = new Date();
        return [d.getHours(), d.getMinutes(), d.getSeconds()]
            .map(v => String(v).padStart(2, '0')).join(':');
    }
    function fmtUptime(s) {
        if (s == null) return '';
        const d = Math.floor(s / 86400);
        const h = Math.floor((s % 86400) / 3600);
        if (d > 0) return `${d}d ${h}h`;
        const m = Math.floor((s % 3600) / 60);
        return `${h}h${String(m).padStart(2,'0')}m`;
    }
    function parseTime(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        } catch { return ''; }
    }

    function svgEl(tag, attrs) {
        const el = document.createElementNS(SVG_NS, tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            el.setAttribute(k, v);
        }
        return el;
    }

    // ── Clock ─────────────────────────────────────────────────────
    setInterval(() => {
        const el = document.getElementById('clock');
        if (el) el.textContent = fmtClock();
    }, 1000);

    // ── WebSocket ─────────────────────────────────────────────────
    let reconnectDelay = 1000;
    let lastMessageTs = 0;

    function connect() {
        const url = `ws://${location.host}/cockpit/ws`;
        ws = new WebSocket(url);

        ws.onopen = () => {
            connected = true;
            reconnectDelay = 1000;
            document.getElementById('ws-dot').classList.remove('disconnected');
            console.log('[COCKPIT] WebSocket connected');
        };

        ws.onclose = () => {
            connected = false;
            document.getElementById('ws-dot').classList.add('disconnected');
            console.log(`[COCKPIT] Disconnected, reconnecting in ${reconnectDelay}ms...`);
            setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
        };

        ws.onerror = () => ws.close();

        ws.onmessage = (event) => {
            try {
                const state = JSON.parse(event.data);
                lastState = state;
                lastMessageTs = Date.now();
                render(state);
            } catch (e) {
                console.error('[COCKPIT] Parse error:', e);
            }
        };
    }

    // Watchdog : si aucun message reçu depuis 15s, forcer la reconnexion
    setInterval(() => {
        if (connected && lastMessageTs > 0 && Date.now() - lastMessageTs > 15000) {
            console.warn('[COCKPIT] No data for 15s, forcing reconnect');
            try { ws.close(); } catch (e) {}
        }
        // Fallback HTTP si WebSocket mort
        if (!connected || (lastMessageTs > 0 && Date.now() - lastMessageTs > 20000)) {
            fetch('/cockpit/state')
                .then(r => r.json())
                .then(state => { lastState = state; render(state); })
                .catch(() => {});
        }
    }, 10000);

    // (LLM reset removed — replaced by RAGAS widget)

    // ── Render orchestrator ───────────────────────────────────────
    function render(s) {
        renderBurst(s.burst);
        renderPipelines(s.pipelines || []);
        renderContainers(s.container_groups);
        renderKnowledge(s.knowledge);
        renderQuality(s.ragas, s.t2t5, s.robustness);
        renderEvents(s.events);
    }

    // ── W1: EC2 Burst ─────────────────────────────────────────────

    function gaugeColor(pct) {
        if (pct >= 90) return 'red';
        if (pct >= 70) return 'orange';
        if (pct > 0) return 'green';
        return 'idle';
    }

    function renderGauge(label, value, maxVal, unit, healthOk) {
        const pct = maxVal > 0 ? Math.min(100, (value / maxVal) * 100) : 0;
        const color = healthOk === false ? 'red' : gaugeColor(pct);
        const displayVal = unit === '%' ? `${Math.round(value)}%` :
                           Number.isInteger(value) ? String(value) : value.toFixed(1);

        return `<div class="burst-gauge">
            <div class="burst-gauge-value">${displayVal}</div>
            <div class="burst-gauge-track">
                <div class="burst-gauge-threshold" style="bottom:70%"></div>
                <div class="burst-gauge-threshold" style="bottom:90%"></div>
                <div class="burst-gauge-fill ${color}" style="height:${Math.max(2, pct)}%"></div>
            </div>
            <div class="burst-gauge-label">${label}</div>
        </div>`;
    }

    function renderBurst(b) {
        const pill = document.getElementById('burst-pill');
        const info = document.getElementById('burst-info');

        pill.className = 'burst-status-pill ' + b.status;
        pill.textContent = b.status.toUpperCase();

        if (!b.active || b.status === 'off') {
            info.innerHTML = '';
            return;
        }

        let html = '';

        // IP + type en ligne
        if (b.instance_ip) {
            html += `<div style="font-family:var(--font-mono);font-size:18px;color:var(--text-accent);margin-bottom:2px">${b.instance_ip}</div>`;
        }
        const metaParts = [];
        if (b.instance_type) metaParts.push(b.instance_type);
        if (b.uptime_s != null) metaParts.push(`up ${fmtUptime(b.uptime_s)}`);
        if (metaParts.length > 0) {
            html += `<div style="font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);margin-bottom:8px">${metaParts.join(' · ')}</div>`;
        }

        // Jauges verticales VU-mètre
        const gpuCache = b.vllm_gpu_cache_pct || 0;
        const running = b.vllm_requests_running || 0;
        const waiting = b.vllm_requests_waiting || 0;
        const teiQueue = b.tei_queue_size || 0;

        const tokPerSec = b.vllm_tokens_per_sec || 0;

        html += '<div class="burst-gauges">';
        html += renderGauge('GPU<br>Cache', gpuCache, 100, '%', b.vllm_healthy);
        html += renderGauge('tok/s', tokPerSec, 50, '', b.vllm_healthy);
        html += renderGauge('vLLM<br>Run', running, 10, '', b.vllm_healthy);
        html += renderGauge('TEI', teiQueue, 10, '', b.tei_healthy);
        html += '</div>';

        info.innerHTML = html;
    }

    // ── W2: Pipelines (multi) ───────────────────────────────────────
    // Track previous stage statuses to detect transitions
    let _prevStageStatuses = {};  // key: "pipelineName:stageIdx" → status
    let _animatedTransitions = {};  // key: "pipelineName:stageIdx" → true once SVG animate has been injected

    function renderPipelines(pipelines) {
        const title = document.getElementById('pipeline-title');
        const elapsed = document.getElementById('pipeline-elapsed');
        const empty = document.getElementById('pipeline-empty');
        const body = document.getElementById('pipeline-body');
        body.style.justifyContent = 'flex-start';  // Aligner en haut, pas centré

        // Nettoyer les anciens SVG/meta (sauf empty)
        body.querySelectorAll('.pipeline-row').forEach(el => el.remove());

        if (!pipelines || pipelines.length === 0) {
            elapsed.textContent = '';
            empty.style.display = 'block';
            return;
        }

        empty.style.display = 'none';
        elapsed.textContent = '';

        // Hauteur fixe par slot (3 slots max, 1/3 chacun)
        const bodyHeight = body.clientHeight || 400;
        const slotHeight = Math.floor(bodyHeight / 3);

        for (const p of pipelines) {
            const row = document.createElement('div');
            row.className = 'pipeline-row';
            row.style.cssText = `display:flex;flex-direction:column;align-items:center;height:${slotHeight}px;min-height:120px;width:100%;`;

            // Header ligne par pipeline
            const header = document.createElement('div');
            header.style.cssText = 'display:flex;align-items:center;gap:12px;width:100%;padding:0 8px;margin-bottom:4px;';
            const nameEl = document.createElement('span');
            nameEl.style.cssText = 'font-family:var(--font-sans);font-size:13px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.08em;';
            nameEl.textContent = p.name || '';
            header.appendChild(nameEl);

            if (p.run_id) {
                const runEl = document.createElement('span');
                runEl.style.cssText = 'font-family:var(--font-mono);font-size:12px;color:var(--text-tertiary);';
                runEl.textContent = p.run_id;
                header.appendChild(runEl);
            }

            const elapsedEl = document.createElement('span');
            elapsedEl.style.cssText = 'margin-left:auto;font-family:var(--font-mono);font-size:13px;color:var(--text-accent);';
            elapsedEl.textContent = fmtTime(p.elapsed_s);
            header.appendChild(elapsedEl);

            row.appendChild(header);

            // SVG
            const svg = document.createElementNS(SVG_NS, 'svg');
            svg.classList.add('pipeline-svg');
            svg.style.cssText = 'width:100%;flex:1;min-height:80px;overflow:visible;';
            row.appendChild(svg);

            // Meta (ETA)
            const meta = document.createElement('div');
            meta.style.cssText = 'display:flex;align-items:center;gap:16px;margin-top:4px;';
            if (p.eta_remaining_s) {
                const etaSpan = document.createElement('span');
                etaSpan.style.cssText = 'font-family:var(--font-mono);font-size:14px;color:var(--text-accent);';
                const finishTime = p.eta_finish ? parseTime(p.eta_finish) : '';
                etaSpan.textContent = `ETA ~${fmtTime(p.eta_remaining_s)}` + (finishTime ? ` · fin ${finishTime}` : '');
                meta.appendChild(etaSpan);
            }
            if (p.eta_remaining_s && p.eta_confidence && p.eta_confidence !== 'unknown') {
                const confSpan = document.createElement('span');
                confSpan.className = 'confidence confidence-' + p.eta_confidence;
                confSpan.textContent = p.eta_confidence;
                meta.appendChild(confSpan);
            }
            row.appendChild(meta);

            body.appendChild(row);

            // Snapshot previous statuses BEFORE updating, so drawPipelineSVG can detect transitions
            const prevSnapshot = {};
            p.stages.forEach((st, si) => {
                const key = `${p.name}:${si}`;
                prevSnapshot[key] = _prevStageStatuses[key];
            });

            // Update statuses for next poll cycle
            p.stages.forEach((st, si) => {
                _prevStageStatuses[`${p.name}:${si}`] = st.status;
            });

            // Dessiner le SVG après insertion dans le DOM (pour clientWidth)
            requestAnimationFrame(() => drawPipelineSVG(svg, p.stages, p.current_stage_index, p.name, prevSnapshot));
        }
    }

    function drawPipelineSVG(svg, stages, currentIdx, pipelineName, prevSnapshot) {
        const p = { name: pipelineName || '' };  // pour les clés de transition
        // Clear
        svg.innerHTML = '';

        const n = stages.length;
        const W = Math.max(200, svg.clientWidth || svg.parentElement.clientWidth - 32);
        const H = Math.max(100, svg.clientHeight || 180);

        svg.setAttribute('width', W);
        svg.setAttribute('height', H);
        svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

        const nodeR = Math.min(22, H * 0.15);
        const nodeY = H * 0.42;
        const labelY = nodeY + nodeR + Math.max(14, H * 0.08);
        const durationY = nodeY - nodeR - Math.max(10, H * 0.06);

        // Distribute nodes evenly
        const margin = 60;
        const spacing = (W - 2 * margin) / Math.max(n - 1, 1);

        const positions = stages.map((_, i) => ({
            x: margin + i * spacing,
            y: nodeY,
        }));

        // ── Defs (gradients) ──
        const defs = svgEl('defs');
        svg.appendChild(defs);

        // Progress gradient for active line
        if (currentIdx >= 0 && currentIdx < n) {
            const stage = stages[currentIdx];
            const progress = stage.progress != null ? stage.progress : 0;
            const gradId = 'lineProgress';
            const grad = svgEl('linearGradient', { id: gradId, x1: '0%', y1: '0%', x2: '100%', y2: '0%' });
            const pct = Math.round(progress * 100);
            grad.appendChild(svgEl('stop', { offset: pct + '%', 'stop-color': C.warning, 'stop-opacity': '0.9' }));
            grad.appendChild(svgEl('stop', { offset: pct + '%', 'stop-color': C.neutralDim, 'stop-opacity': '0.4' }));
            defs.appendChild(grad);
        }

        // ── Lines ──
        for (let i = 0; i < n - 1; i++) {
            const from = positions[i];
            const to = positions[i + 1];
            const stageFrom = stages[i];
            const stageTo = stages[i + 1];

            const x1 = from.x + nodeR, x2 = to.x - nodeR;
            const transKey = `${p.name}:${i+1}`;

            // Detect NEW transition: stageTo just became 'running' (was pending before)
            const prevStatus = prevSnapshot ? prevSnapshot[transKey] : undefined;
            const isNewTransition = stageTo.status === 'running'
                && prevStatus && prevStatus !== 'running' && prevStatus !== 'done'
                && !_animatedTransitions[transKey];

            if (isNewTransition) {
                _animatedTransitions[transKey] = true;
            }

            // Reset animated flag if stage goes back to pending (e.g. new pipeline run)
            if (stageTo.status === 'pending') {
                delete _animatedTransitions[transKey];
            }

            if (stageFrom.status === 'done' && stageTo.status === 'done') {
                svg.appendChild(svgEl('line', {
                    x1, y1: from.y, x2, y2: to.y,
                    stroke: C.success, 'stroke-width': '3', 'stroke-opacity': '0.7', 'stroke-linecap': 'round',
                }));
            } else if (stageFrom.status === 'done' && stageTo.status === 'running') {
                if (isNewTransition) {
                    // Background: gray dashed line (visible during animation)
                    svg.appendChild(svgEl('line', {
                        x1, y1: from.y, x2, y2: to.y,
                        stroke: C.neutralDim, 'stroke-width': '3', 'stroke-opacity': '0.3',
                        'stroke-dasharray': '4 4', 'stroke-linecap': 'round',
                    }));
                    // Overlay: green line with animated x2 (fills left to right)
                    const greenLine = svgEl('line', {
                        x1, y1: from.y, x2: x1, y2: to.y,
                        stroke: C.success, 'stroke-width': '3', 'stroke-opacity': '0.8', 'stroke-linecap': 'round',
                    });
                    const anim = svgEl('animate', {
                        attributeName: 'x2',
                        from: x1,
                        to: x2,
                        dur: '2s',
                        fill: 'freeze',
                        repeatCount: '1',
                        begin: '0s',
                    });
                    greenLine.appendChild(anim);
                    svg.appendChild(greenLine);
                } else {
                    // Already animated or no transition detected: static green line
                    svg.appendChild(svgEl('line', {
                        x1, y1: from.y, x2, y2: to.y,
                        stroke: C.success, 'stroke-width': '3', 'stroke-opacity': '0.7', 'stroke-linecap': 'round',
                    }));
                }
            } else if (stageFrom.status === 'running' && stageTo.status === 'pending') {
                svg.appendChild(svgEl('line', {
                    x1, y1: from.y, x2, y2: to.y,
                    stroke: C.neutralDim, 'stroke-width': '3', 'stroke-opacity': '0.3',
                    'stroke-dasharray': '4 4', 'stroke-linecap': 'round',
                }));
            } else if (stageFrom.status === 'failed') {
                svg.appendChild(svgEl('line', {
                    x1, y1: from.y, x2, y2: to.y,
                    stroke: C.error, 'stroke-width': '3', 'stroke-opacity': '0.5',
                    'stroke-dasharray': '4 4', 'stroke-linecap': 'round',
                }));
            } else {
                svg.appendChild(svgEl('line', {
                    x1, y1: from.y, x2, y2: to.y,
                    stroke: C.neutralDim, 'stroke-width': '3', 'stroke-opacity': '0.3',
                    'stroke-dasharray': '4 4', 'stroke-linecap': 'round',
                }));
            }
        }

        // ── Nodes ──
        for (let i = 0; i < n; i++) {
            const pos = positions[i];
            const stage = stages[i];
            const g = svgEl('g', { transform: `translate(${pos.x}, ${pos.y})` });

            if (stage.status === 'done') {
                // Glow
                g.appendChild(svgEl('circle', {
                    r: nodeR, fill: C.successGlow, stroke: C.success,
                    'stroke-width': '2',
                }));
                // Check mark
                const check = svgEl('path', {
                    d: 'M-8,0 L-3,6 L8,-6',
                    fill: 'none', stroke: '#FFFFFF', 'stroke-width': '2.5',
                    'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                });
                g.appendChild(check);

            } else if (stage.status === 'running') {
                // Cercle unique — battement de coeur (scale + luminosité)
                const main = svgEl('circle', {
                    r: nodeR, fill: C.warningGlow, stroke: C.warning,
                    'stroke-width': '2',
                    class: 'node-heartbeat',
                });
                g.appendChild(main);

                // Progress arc (if iterable)
                if (stage.progress != null && stage.progress > 0) {
                    const angle = stage.progress * 360;
                    const rad = nodeR - 4;
                    const arc = describeArc(0, 0, rad, -90, -90 + angle);
                    const arcEl = svgEl('path', {
                        d: arc, fill: 'none', stroke: C.warning,
                        'stroke-width': '3', 'stroke-linecap': 'round',
                    });
                    g.appendChild(arcEl);

                    // Percentage text
                    const pctText = svgEl('text', {
                        x: '0', y: '5', 'text-anchor': 'middle',
                        'font-family': "'Fira Code', monospace",
                        'font-size': '13', 'font-weight': '600',
                        fill: C.warning,
                    });
                    pctText.textContent = Math.round(stage.progress * 100) + '%';
                    g.appendChild(pctText);
                }

            } else if (stage.status === 'failed') {
                g.appendChild(svgEl('circle', {
                    r: nodeR, fill: C.errorGlow, stroke: C.error,
                    'stroke-width': '2.5',
                }));
                // X mark
                const x1 = svgEl('line', {
                    x1: '-7', y1: '-7', x2: '7', y2: '7',
                    stroke: C.error, 'stroke-width': '2.5', 'stroke-linecap': 'round',
                });
                const x2 = svgEl('line', {
                    x1: '7', y1: '-7', x2: '-7', y2: '7',
                    stroke: C.error, 'stroke-width': '2.5', 'stroke-linecap': 'round',
                });
                g.appendChild(x1);
                g.appendChild(x2);

            } else if (stage.status === 'skipped') {
                g.appendChild(svgEl('circle', {
                    r: nodeR, fill: 'none', stroke: C.neutralDim,
                    'stroke-width': '1.5', 'stroke-dasharray': '3 3',
                }));

            } else {
                // Pending
                g.appendChild(svgEl('circle', {
                    r: nodeR, fill: 'none', stroke: C.neutralDim,
                    'stroke-width': '1.5',
                }));
                g.appendChild(svgEl('circle', {
                    r: '5', fill: C.neutralDim,
                }));
            }

            svg.appendChild(g);

            // ── Label below node ──
            const label = svgEl('text', {
                x: pos.x, y: labelY,
                'text-anchor': 'middle',
                'font-family': "'Fira Sans', sans-serif",
                'font-size': stage.status === 'running' ? '15' : '14',
                'font-weight': stage.status === 'running' ? '600' : '400',
                fill: stage.status === 'running' ? C.textPrimary : C.textSecondary,
            });
            label.textContent = stage.short_name || stage.name.slice(0, 6);
            svg.appendChild(label);

            // ── Duration above node ──
            if (stage.duration_s != null && stage.duration_s > 0) {
                const dur = svgEl('text', {
                    x: pos.x, y: durationY,
                    'text-anchor': 'middle',
                    'font-family': "'Fira Code', monospace",
                    'font-size': '14',
                    fill: stage.status === 'running' ? C.warning : C.textTertiary,
                });
                dur.textContent = fmtTime(stage.duration_s);
                svg.appendChild(dur);
            }

            // ── Detail below label (for running stage) ──
            if (stage.status === 'running' && stage.detail) {
                // Wrap long text into 2 lines max, centered in the SVG
                const maxChars = Math.floor(W / 8);  // ~8px per char at font-size 13
                const lines = [];
                let text = stage.detail;
                if (text.length > maxChars * 2) text = text.substring(0, maxChars * 2 - 3) + '...';
                if (text.length > maxChars) {
                    // Split at word boundary near middle
                    const mid = text.lastIndexOf(' ', maxChars);
                    lines.push(text.substring(0, mid > 0 ? mid : maxChars));
                    lines.push(text.substring(mid > 0 ? mid + 1 : maxChars));
                } else {
                    lines.push(text);
                }
                lines.forEach((line, li) => {
                    const det = svgEl('text', {
                        x: W / 2, y: labelY + 30 + li * 16,
                        'text-anchor': 'middle',
                        'font-family': "'Fira Code', monospace",
                        'font-size': '13',
                        fill: C.textAccent,
                    });
                    det.textContent = line;
                    svg.appendChild(det);
                });
            }
        }
    }

    // SVG arc helper
    function describeArc(cx, cy, r, startAngle, endAngle) {
        const start = polarToCartesian(cx, cy, r, endAngle);
        const end = polarToCartesian(cx, cy, r, startAngle);
        const largeArc = endAngle - startAngle <= 180 ? '0' : '1';
        return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
    }

    function polarToCartesian(cx, cy, r, angleDeg) {
        const rad = (angleDeg * Math.PI) / 180;
        return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
    }

    // ── W3: Containers ────────────────────────────────────────────
    function renderContainers(groups) {
        const body = document.getElementById('containers-body');
        if (!groups || groups.length === 0) {
            body.innerHTML = '<div class="events-empty">Aucun conteneur</div>';
            return;
        }

        let html = '';
        for (const group of groups) {
            html += `<div class="container-group">`;
            html += `<div class="group-label">${group.name}</div>`;
            for (const c of group.containers) {
                const dotClass = c.health === 'unhealthy' ? 'unhealthy' : c.status;
                const barW = Math.min(100, Math.max(0, c.cpu_percent));
                const barClass = c.cpu_percent > 50 ? 'busy' : c.cpu_percent > 2 ? 'active' : 'idle';
                const cpuClass = barClass;
                const cpuText = c.status === 'down' ? '—' : c.cpu_percent.toFixed(1) + '%';

                html += `<div class="container-row">
                    <div class="container-dot ${dotClass}"></div>
                    <div class="container-name">${c.name}</div>
                    <div class="container-bar-track">
                        <div class="container-bar-fill ${barClass}" style="width:${barW}%"></div>
                    </div>
                    <div class="container-cpu ${cpuClass}">${cpuText}</div>
                </div>`;
            }
            html += `</div>`;
        }
        body.innerHTML = html;
    }

    // ── W4: Knowledge ─────────────────────────────────────────────
    function renderKnowledge(k) {
        const body = document.getElementById('knowledge-body');
        const qdrantDot = k.qdrant_ok ? 'ok' : 'error';
        const neo4jDot = k.neo4j_ok ? 'ok' : 'error';

        function tile(value, label, cls) {
            const valCls = value === 0 ? 'zero' : (cls || '');
            return `<div class="knowledge-tile">
                <div class="knowledge-tile-value ${valCls}">${fmt(value)}</div>
                <div class="knowledge-tile-label">${label}</div>
            </div>`;
        }

        body.innerHTML = `
            <div class="knowledge-section">
                <div class="knowledge-section-label">
                    <div class="knowledge-section-dot ${qdrantDot}"></div>
                    QDRANT
                </div>
                <div class="knowledge-tiles">
                    <div class="knowledge-tile hero">
                        <div class="knowledge-tile-label">chunks</div>
                        <div class="knowledge-tile-value highlight">${fmt(k.qdrant_chunks)}</div>
                    </div>
                </div>
            </div>
            <div class="knowledge-section">
                <div class="knowledge-section-label">
                    <div class="knowledge-section-dot ${neo4jDot}"></div>
                    NEO4J
                </div>
                <div class="knowledge-tiles">
                    ${tile(k.neo4j_nodes, 'nodes')}
                    ${tile(k.neo4j_claims, 'claims', 'highlight')}
                    ${tile(k.neo4j_entities, 'entities')}
                    ${tile(k.neo4j_relations, 'relations')}
                    ${tile(k.neo4j_subjects, 'subjects')}
                    ${tile(k.neo4j_facets, 'facets')}
                    ${tile(k.neo4j_perspectives, 'perspectives')}
                    ${tile(k.neo4j_contradictions, 'contrad.', k.neo4j_contradictions > 0 ? 'contradictions' : '')}
                </div>
            </div>
        `;
    }

    // ── W5: Qualité Osmosis (RAGAS + T2/T5) ────────────────────────

    function qualityScoreColor(score) {
        if (score >= 0.7) return C.success;
        if (score >= 0.4) return C.warning;
        return C.error;
    }

    function qualityBar(label, value) {
        const pct = Math.min(100, Math.max(0, value * 100));
        const color = value >= 0.7 ? 'var(--success)' : value >= 0.4 ? 'var(--warning)' : 'var(--error, red)';
        return `<div style="margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px;">
                <span style="font-family:var(--font-sans);font-size:15px;color:var(--text-secondary);">${label}</span>
                <span style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:${color};">${pct.toFixed(0)}%</span>
            </div>
            <div style="height:10px;background:var(--bg-tertiary, #1a1a2e);border-radius:5px;overflow:hidden;">
                <div style="height:100%;width:${pct}%;background:${color};border-radius:5px;transition:width 0.5s;"></div>
            </div>
        </div>`;
    }

    // Arc SVG semi-circulaire (270°) — path d'un arc entre deux angles (0 = 12h, clockwise)
    function arcPath(cx, cy, r, startAngle, endAngle) {
        const x1 = cx + r * Math.sin(startAngle);
        const y1 = cy - r * Math.cos(startAngle);
        const x2 = cx + r * Math.sin(endAngle);
        const y2 = cy - r * Math.cos(endAngle);
        const largeArc = (endAngle - startAngle) > Math.PI ? 1 : 0;
        return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
    }

    // Jauge SVG semi-circulaire (identique au composant ScoreGauge.tsx du frontend)
    function qualityGauge(label, value, countSuffix, size) {
        if (value == null) value = 0;
        size = size || 100;
        const cx = size / 2;
        const cy = size / 2;
        const radius = size / 2 - 12;
        const strokeWidth = 10;
        const startAngle = -Math.PI * 0.75;
        const endAngle = Math.PI * 0.75;
        const valueAngle = startAngle + (endAngle - startAngle) * Math.min(Math.max(value, 0), 1);

        const pct = Math.round(value * 100);
        const color = value >= 0.7 ? '#22c55e' : value >= 0.5 ? '#eab308' : '#ef4444';
        const bgPath = arcPath(cx, cy, radius, startAngle, endAngle);
        const gaugeHeight = Math.round(size * 0.78);
        const fontSize = Math.round(size * 0.28);

        // Arc de valeur seulement si > 0 (evite path degenere)
        let valueArc = '';
        if (value > 0.001) {
            const valPath = arcPath(cx, cy, radius, startAngle, valueAngle);
            valueArc = `<path d="${valPath}" fill="none" stroke="${color}" stroke-width="${strokeWidth}" stroke-linecap="round"/>`;
        }

        const suffix = countSuffix
            ? `<span style="color:var(--text-tertiary);font-size:11px;margin-left:4px;font-family:var(--font-mono);">${countSuffix}</span>`
            : '';

        return `<div style="display:flex;flex-direction:column;align-items:center;flex:1;min-width:0;">
            <svg width="${size}" height="${gaugeHeight}" viewBox="0 0 ${size} ${gaugeHeight}" style="overflow:visible;">
                <path d="${bgPath}" fill="none" stroke="#1e1e3a" stroke-width="${strokeWidth}" stroke-linecap="round"/>
                ${valueArc}
                <text x="${cx}" y="${cy + fontSize * 0.35}" text-anchor="middle"
                    font-family="var(--font-mono)" font-size="${fontSize}" font-weight="700" fill="${color}">
                    ${pct}
                </text>
            </svg>
            <div style="font-family:var(--font-sans);font-size:13px;font-weight:600;color:var(--text-secondary);text-align:center;margin-top:-4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;">
                ${label}${suffix}
            </div>
        </div>`;
    }

    // Score global T2/T5 : moyenne des metriques principales (equivalent frontend benchmarks)
    function t2t5GlobalScore(t2t5) {
        const metrics = [
            t2t5.tension_mentioned,
            t2t5.both_sides_surfaced,
            t2t5.both_sources_cited,
            t2t5.proactive_detection,
            t2t5.chain_coverage,
            t2t5.multi_doc_cited,
        ].filter(v => v != null);
        if (metrics.length === 0) return null;
        return metrics.reduce((a, b) => a + b, 0) / metrics.length;
    }

    function renderQuality(ragas, t2t5, robustness) {
        const ragasEl = document.getElementById('ragas-section');
        const t2t5El = document.getElementById('t2t5-section');
        const robEl = document.getElementById('robustness-section');
        if (!ragasEl || !t2t5El) return;

        // ── RAGAS section ──
        try {
            if (!ragas || (ragas.sample_count === 0 && ragas.faithfulness === 0)) {
                ragasEl.innerHTML = '<div style="color:var(--text-tertiary);font-size:15px;padding:8px 0;">Pas de rapport RAGAS</div>';
            } else {
                let rHtml = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <span style="font-family:var(--font-sans);font-size:16px;font-weight:600;color:var(--text-primary);">RAGAS</span>
                    <span style="font-family:var(--font-mono);font-size:14px;color:var(--text-tertiary);">${ragas.sample_count}q</span>
                </div>`;
                if (ragas.faithfulness != null) rHtml += qualityBar('Faithfulness', ragas.faithfulness);
                if (ragas.context_relevance != null) rHtml += qualityBar('Ctx Relevance', ragas.context_relevance);

                if (ragas.timestamp) {
                    const ts = ragas.timestamp.replace('T', ' ').split('.')[0];
                    rHtml += `<div style="font-family:var(--font-mono);font-size:13px;color:var(--text-tertiary);text-align:right;margin-top:4px;">${escapeHtml(ts)}</div>`;
                }
                ragasEl.innerHTML = rHtml;
            }
        } catch (err) {
            ragasEl.innerHTML = `<div style="color:red;font-size:11px;">RAGAS error: ${err.message}</div>`;
        }

        // ── T2/T5 + Robustesse : 2 jauges SVG cote a cote dans t2t5-section ──
        // (robustness-section est laisse vide, tout est rendu dans t2t5-section)
        try {
            const hasT2 = t2t5 && t2t5.total_evaluated > 0;
            const hasRob = robustness && robustness.total_evaluated > 0;

            if (!hasT2 && !hasRob) {
                t2t5El.innerHTML = '<div style="color:var(--text-tertiary);font-size:15px;padding:8px 0;">Pas de rapport T2/T5 ni Robustesse</div>';
            } else {
                let html = `<div style="border-top:1px solid var(--border-dim);padding-top:12px;margin-top:10px;">
                    <div style="display:flex;gap:8px;justify-content:space-around;align-items:flex-start;">`;

                if (hasT2) {
                    const globalT2 = t2t5GlobalScore(t2t5);
                    html += qualityGauge('T2/T5', globalT2 != null ? globalT2 : 0, `${t2t5.total_evaluated}q`, 92);
                } else {
                    html += '<div style="flex:1;text-align:center;color:var(--text-tertiary);font-size:12px;padding:30px 0;">Pas de T2/T5</div>';
                }

                if (hasRob) {
                    html += qualityGauge('Robustesse', robustness.global_score, `${robustness.total_evaluated}q`, 92);
                } else {
                    html += '<div style="flex:1;text-align:center;color:var(--text-tertiary);font-size:12px;padding:30px 0;">Pas de Robustesse</div>';
                }

                html += '</div>';

                // Timestamps en petit, sur une ligne
                const t2ts = hasT2 && t2t5.timestamp ? t2t5.timestamp.replace('T', ' ').split('.')[0] : '';
                const robts = hasRob && robustness.timestamp ? robustness.timestamp.replace('T', ' ').split('.')[0] : '';
                if (t2ts || robts) {
                    html += `<div style="display:flex;justify-content:space-around;font-family:var(--font-mono);font-size:10px;color:var(--text-tertiary);margin-top:4px;">
                        <span>${escapeHtml(t2ts)}</span>
                        <span>${escapeHtml(robts)}</span>
                    </div>`;
                }

                html += '</div>';
                t2t5El.innerHTML = html;
            }
        } catch (err) {
            t2t5El.innerHTML = `<div style="color:red;font-size:11px;">Gauges error: ${err.message}</div>`;
        }

        // robustness-section : vide maintenant (tout est dans t2t5-section)
        if (robEl) robEl.innerHTML = '';
    }

    // ── W6: Events ────────────────────────────────────────────────
    function renderEvents(events) {
        const body = document.getElementById('events-body');
        const empty = document.getElementById('events-empty');
        const count = document.getElementById('events-count');

        if (!events || events.length === 0) {
            empty.style.display = 'block';
            count.textContent = '';
            // Keep empty message, clear any previous events
            const existing = body.querySelectorAll('.event-row');
            existing.forEach(el => el.remove());
            return;
        }

        empty.style.display = 'none';
        count.textContent = events.length;

        let html = '';
        for (const e of events.slice(0, 20)) {
            const time = parseTime(e.timestamp);
            html += `<div class="event-row">
                <div class="event-dot ${e.severity}"></div>
                <div class="event-time">${time}</div>
                <div class="event-message ${e.severity}">${escapeHtml(e.message)}</div>
            </div>`;
        }
        // Replace only event rows, keep empty element
        const existing = body.querySelectorAll('.event-row');
        existing.forEach(el => el.remove());
        body.insertAdjacentHTML('beforeend', html);
    }

    function escapeHtml(s) {
        const div = document.createElement('div');
        div.textContent = s;
        return div.innerHTML;
    }

    // ── Init ──────────────────────────────────────────────────────
    connect();

})();
