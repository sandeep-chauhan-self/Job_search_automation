'use strict';

const STATUSES = [
    'DISCOVERED', 'SCORED', 'SKIPPED', 'APPROVED', 'RESUME_READY',
    'APPLIED', 'QUEUED_FOR_MANUAL', 'REJECTED', 'INTERVIEW', 'OFFER', 'GHOSTED'
];

const VIEWS = {
    pipeline: { title: 'Pipeline', subtitle: 'Discover, score, and triage every opening in one place.' },
    review: { title: 'Review & Launch', subtitle: 'Approved jobs waiting for resume generation or submission.' },
    manual: { title: 'Manual Queue', subtitle: 'Jobs auto-apply could not finish. Download the resume and apply yourself.' },
    analytics: { title: 'Analytics', subtitle: 'Funnel conversion, platform mix, and LLM spend.' },
    runs: { title: 'Run History', subtitle: 'Every pipeline execution and its outcome.' }
};

const state = {
    view: 'pipeline',
    page: 1,
    pages: 1,
    total: 0,
    selected: new Set(),
    jobs: [],
    filters: { search: '', status: '', platform: '', min_score: 0, sort: 'discovered_at' },
    running: false
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- utilities

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

function timeAgo(iso) {
    if (!iso) return '-';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (Number.isNaN(diff)) return '-';
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function scoreColor(score) {
    if (score === null || score === undefined) return '#3a4159';
    if (score >= 80) return '#22c55e';
    if (score >= 60) return '#84cc16';
    if (score >= 40) return '#f59e0b';
    return '#ef4444';
}

let toastTimer = null;
function toast(message, kind) {
    const node = $('toast');
    node.textContent = message;
    node.className = 'toast ' + (kind || '');
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 4200);
}

async function api(path, options) {
    const res = await fetch('/api' + path, options);
    if (!res.ok) {
        let detail = res.statusText;
        try {
            const body = await res.json();
            detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        } catch (_) { /* keep statusText */ }
        throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
}

const postJSON = (path, body) => api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
});

// ---------------------------------------------------------------- stat strip

async function loadStats() {
    let data;
    try {
        data = await api('/analytics/summary');
    } catch (err) {
        toast('Could not load stats: ' + err.message, 'error');
        return null;
    }

    const counts = data.status_counts || {};
    const cards = [
        { label: 'Discovered', value: data.total_jobs, note: 'all time', cls: '' },
        { label: 'Scored', value: counts.SCORED || 0, note: 'score >= ' + data.min_match_score, cls: 'accent' },
        { label: 'Approved', value: counts.APPROVED || 0, note: 'awaiting resume', cls: 'accent' },
        { label: 'Applied', value: data.total_applied, note: data.applied_today + ' of ' + data.daily_limit + ' today', cls: 'good' },
        { label: 'Manual Queue', value: counts.QUEUED_FOR_MANUAL || 0, note: 'needs you', cls: 'warn' },
        { label: 'LLM Spend', value: '$' + data.total_llm_cost_usd.toFixed(2), note: 'total', cls: '' }
    ];

    const strip = $('stat-strip');
    strip.replaceChildren();
    for (const card of cards) {
        const box = el('div', 'stat ' + card.cls);
        box.append(
            el('div', 'stat-label', card.label),
            el('div', 'stat-value', card.value),
            el('div', 'stat-note', card.note)
        );
        strip.append(box);
    }

    $('btn-apply').textContent = data.dry_run ? 'Apply (Dry Run)' : 'Apply Now';
    $('btn-apply').title = data.dry_run
        ? 'Dry run is on: the browser walks each form and screenshots it, but submits nothing. Set application.dry_run to false in config.yaml to submit for real.'
        : 'LIVE: applications will be submitted to LinkedIn.';
    return data;
}

// ---------------------------------------------------------------- jobs table

function statusForView() {
    if (state.view === 'review') return 'APPROVED,RESUME_READY';
    if (state.view === 'manual') return 'QUEUED_FOR_MANUAL';
    return state.filters.status;
}

async function loadJobs() {
    const params = new URLSearchParams({
        page: state.page,
        page_size: 50,
        sort: state.filters.sort,
        order: state.filters.sort === 'company' ? 'asc' : 'desc'
    });
    const status = statusForView();
    if (status) params.set('status', status);
    if (state.filters.platform) params.set('platform', state.filters.platform);
    if (state.filters.min_score > 0) params.set('min_score', state.filters.min_score);
    if (state.filters.search) params.set('search', state.filters.search);

    let data;
    try {
        data = await api('/jobs?' + params.toString());
    } catch (err) {
        toast('Could not load jobs: ' + err.message, 'error');
        return;
    }

    state.jobs = data.jobs;
    state.total = data.total;
    state.pages = data.pages;
    renderJobs();
}

function renderJobs() {
    const body = $('jobs-body');
    body.replaceChildren();

    const empty = $('jobs-empty');
    if (!state.jobs.length) {
        empty.hidden = false;
        empty.textContent = state.total === 0
            ? 'No jobs yet. Hit "Run Discovery" to scrape your configured searches.'
            : 'No jobs match these filters.';
    } else {
        empty.hidden = true;
    }

    for (const job of state.jobs) {
        const row = el('tr');
        if (state.selected.has(job.id)) row.classList.add('selected');

        const checkCell = el('td', 'col-check');
        const check = el('input');
        check.type = 'checkbox';
        check.checked = state.selected.has(job.id);
        check.addEventListener('click', (ev) => ev.stopPropagation());
        check.addEventListener('change', () => {
            check.checked ? state.selected.add(job.id) : state.selected.delete(job.id);
            row.classList.toggle('selected', check.checked);
            renderBulkBar();
        });
        checkCell.append(check);

        const company = el('td');
        company.append(el('div', 'cell-company', job.company));
        company.append(el('div', 'cell-muted', job.location || 'Location not listed'));

        const role = el('td', 'cell-role', job.title);
        role.title = job.title;

        const platform = el('td', 'cell-muted', job.platform || '-');

        const scoreCell = el('td');
        const score = el('div', 'score');
        const bar = el('div', 'score-bar');
        const fill = el('i');
        fill.style.width = (job.match_score || 0) + '%';
        fill.style.background = scoreColor(job.match_score);
        bar.append(fill);
        score.append(bar, el('span', 'score-num', job.match_score ?? '-'));
        scoreCell.append(score);

        const statusCell = el('td');
        statusCell.append(el('span', 'badge ' + job.status, job.status.replace(/_/g, ' ')));

        const found = el('td', 'cell-muted', timeAgo(job.discovered_at));

        const actions = el('td', 'col-actions');
        const link = el('a', 'btn btn-sm btn-ghost', 'Open');
        link.href = job.job_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.addEventListener('click', (ev) => ev.stopPropagation());
        actions.append(link);

        row.append(checkCell, company, role, platform, scoreCell, statusCell, found, actions);
        row.addEventListener('click', () => openDrawer(job.id));
        body.append(row);
    }

    $('page-label').textContent = 'Page ' + state.page + ' of ' + state.pages + ' (' + state.total + ' jobs)';
    $('page-prev').disabled = state.page <= 1;
    $('page-next').disabled = state.page >= state.pages;
    $('check-all').checked = state.jobs.length > 0 && state.jobs.every((j) => state.selected.has(j.id));
    renderBulkBar();
}

function renderBulkBar() {
    const count = state.selected.size;
    $('bulk-bar').hidden = count === 0;
    $('bulk-count').textContent = count + ' selected';
}

// ---------------------------------------------------------------- drawer

async function openDrawer(jobId) {
    let job;
    try {
        job = await api('/jobs/' + encodeURIComponent(jobId));
    } catch (err) {
        toast('Could not load job: ' + err.message, 'error');
        return;
    }

    $('drawer-title').textContent = job.title;
    $('drawer-sub').textContent = job.company + ' - ' + (job.location || 'Location not listed');

    const body = $('drawer-body');
    body.replaceChildren();

    const actions = el('div', 'drawer-actions');
    const open = el('a', 'btn btn-primary btn-sm', 'Open posting');
    open.href = job.job_url;
    open.target = '_blank';
    open.rel = 'noopener noreferrer';
    actions.append(open);

    if (job.has_resume) {
        const dl = el('a', 'btn btn-sm', 'Download resume');
        dl.href = '/api/jobs/' + encodeURIComponent(job.id) + '/document/resume';
        actions.append(dl);
    }
    if (job.has_cover_letter) {
        const dl = el('a', 'btn btn-sm', 'Download cover letter');
        dl.href = '/api/jobs/' + encodeURIComponent(job.id) + '/document/cover_letter';
        actions.append(dl);
    }

    for (const next of ['APPROVED', 'REJECTED', 'APPLIED', 'INTERVIEW']) {
        if (job.status === next) continue;
        const btn = el('button', 'btn btn-sm', 'Mark ' + next.toLowerCase());
        btn.addEventListener('click', async () => {
            try {
                await api('/jobs/' + encodeURIComponent(job.id) + '/status', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: next })
                });
                toast('Marked ' + next.toLowerCase(), 'success');
                closeDrawer();
                refresh();
            } catch (err) {
                toast(err.message, 'error');
            }
        });
        actions.append(btn);
    }
    body.append(actions);

    const meta = el('dl', 'meta-grid');
    const fields = [
        ['Status', job.status.replace(/_/g, ' ')],
        ['Match score', job.match_score ?? 'not scored'],
        ['Platform', job.platform || '-'],
        ['Work mode', job.work_mode || 'unknown'],
        ['Salary', job.salary_info || 'not listed'],
        ['Discovered', timeAgo(job.discovered_at)],
        ['Applied', job.applied_at ? timeAgo(job.applied_at) : 'not yet'],
        ['LLM cost', '$' + Number(job.llm_cost_usd || 0).toFixed(4)]
    ];
    for (const [label, value] of fields) {
        const cell = el('div');
        cell.append(el('dt', null, label), el('dd', null, value));
        meta.append(cell);
    }
    body.append(meta);

    if (job.notes) {
        body.append(el('h3', null, 'Notes'));
        body.append(el('p', 'cell-muted', job.notes));
    }

    if (job.match_reasons.length) {
        body.append(el('h3', null, 'Why it matches'));
        const list = el('ul', 'reasons');
        job.match_reasons.forEach((r) => list.append(el('li', null, r)));
        body.append(list);
    }

    if (job.match_gaps.length) {
        body.append(el('h3', null, 'Gaps'));
        const list = el('ul', 'gaps');
        job.match_gaps.forEach((g) => list.append(el('li', null, g)));
        body.append(list);
    }

    body.append(el('h3', null, 'Job description'));
    body.append(el('div', 'jd', job.description || 'No description captured.'));

    $('drawer').hidden = false;
    $('scrim').hidden = false;
}

function closeDrawer() {
    $('drawer').hidden = true;
    $('scrim').hidden = true;
}

// ---------------------------------------------------------------- analytics

async function renderAnalytics() {
    const container = $('view-analytics');
    container.replaceChildren();

    let data;
    try {
        data = await api('/analytics/summary');
    } catch (err) {
        container.append(el('div', 'empty', 'Could not load analytics: ' + err.message));
        return;
    }

    const funnelPanel = el('section', 'panel');
    funnelPanel.append(el('h2', null, 'Conversion funnel'));
    const max = Math.max(1, ...data.funnel.map((f) => f.count));
    for (const stage of data.funnel) {
        const row = el('div', 'funnel-row');
        const bar = el('div', 'funnel-bar');
        const fill = el('i');
        fill.style.width = Math.max(2, (stage.count / max) * 100) + '%';
        bar.append(fill);
        row.append(
            el('div', 'funnel-name', stage.stage.replace(/_/g, ' ')),
            bar,
            el('div', 'funnel-count', stage.count)
        );
        funnelPanel.append(row);
    }
    container.append(funnelPanel);

    const platformPanel = el('section', 'panel');
    platformPanel.append(el('h2', null, 'Jobs by platform'));
    const entries = Object.entries(data.apps_by_platform);
    if (!entries.length) {
        platformPanel.append(el('p', 'cell-muted', 'No jobs discovered yet.'));
    } else {
        const pmax = Math.max(1, ...entries.map(([, v]) => v));
        for (const [name, count] of entries) {
            const row = el('div', 'funnel-row');
            const bar = el('div', 'funnel-bar');
            const fill = el('i');
            fill.style.width = Math.max(2, (count / pmax) * 100) + '%';
            bar.append(fill);
            row.append(el('div', 'funnel-name', name || 'unknown'), bar, el('div', 'funnel-count', count));
            platformPanel.append(row);
        }
    }
    container.append(platformPanel);

    const costPanel = el('section', 'panel');
    costPanel.append(el('h2', null, 'Cost and configuration'));
    const grid = el('dl', 'meta-grid');
    const rows = [
        ['Total LLM spend', '$' + data.total_llm_cost_usd.toFixed(4)],
        ['Average applied score', data.avg_match_score],
        ['Applied today', data.applied_today + ' / ' + data.daily_limit],
        ['Min match score', data.min_match_score],
        ['Apply mode', data.dry_run ? 'Dry run (no submissions)' : 'LIVE submissions'],
        ['Ghosted', data.total_ghosted]
    ];
    for (const [label, value] of rows) {
        const cell = el('div');
        cell.append(el('dt', null, label), el('dd', null, value));
        grid.append(cell);
    }
    costPanel.append(grid);

    const ghostBtn = el('button', 'btn btn-sm', 'Run ghosting check now');
    ghostBtn.addEventListener('click', async () => {
        try {
            const res = await postJSON('/cron/ghosting-check');
            toast('Marked ' + res.ghosted_count + ' job(s) as ghosted.', 'success');
            renderAnalytics();
            loadStats();
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    costPanel.append(ghostBtn);
    container.append(costPanel);
}

async function renderRuns() {
    const container = $('view-runs');
    container.replaceChildren();

    let data;
    try {
        data = await api('/runs/history');
    } catch (err) {
        container.append(el('div', 'empty', 'Could not load run history: ' + err.message));
        return;
    }

    if (!data.runs.length) {
        container.append(el('div', 'empty', 'No runs recorded yet.'));
        return;
    }

    const panel = el('section', 'panel');
    const table = el('table', 'jobs-table');
    const head = el('thead');
    const headRow = el('tr');
    ['Started', 'Status', 'Discovered', 'Scored', 'Above threshold', 'Error'].forEach((h) => {
        headRow.append(el('th', null, h));
    });
    head.append(headRow);
    table.append(head);

    const tbody = el('tbody');
    for (const run of data.runs) {
        const row = el('tr');
        const statusCell = el('td');
        statusCell.append(el('span', 'badge ' + (run.status === 'COMPLETED' ? 'APPLIED' : 'QUEUED_FOR_MANUAL'), run.status));
        row.append(
            el('td', 'cell-muted', new Date(run.started_at).toLocaleString()),
            statusCell,
            el('td', null, run.jobs_discovered),
            el('td', null, run.jobs_scored),
            el('td', null, run.jobs_above_threshold),
            el('td', 'cell-muted', run.error_log || '-')
        );
        tbody.append(row);
    }
    table.append(tbody);
    panel.append(table);
    container.append(panel);
}

// ---------------------------------------------------------------- live run

function applyRunState(snapshot) {
    state.running = snapshot.active;

    const dot = $('run-dot');
    dot.className = 'dot ' + (snapshot.active ? 'running' : snapshot.status.toLowerCase());
    $('run-label').textContent = snapshot.active
        ? (snapshot.kind || 'run') + ' running'
        : snapshot.status.charAt(0) + snapshot.status.slice(1).toLowerCase();

    const { current, total } = snapshot.progress || {};
    $('run-phase').textContent = snapshot.phase
        ? snapshot.phase + (total ? ' ' + current + '/' + total : '')
        : '';
    $('run-progress').style.width = total ? (current / total) * 100 + '%' : (snapshot.active ? '100%' : '0');

    $('btn-cancel').disabled = !snapshot.active;
    $('btn-discover').disabled = snapshot.active;
    $('btn-prepare').disabled = snapshot.active;
    $('btn-apply').disabled = snapshot.active;
}

function appendLog(entry) {
    const body = $('log-body');
    const placeholder = body.querySelector('.log-empty');
    if (placeholder) placeholder.remove();

    const line = el('div', 'log-line ' + entry.level);
    line.append(
        el('span', 'log-time', new Date(entry.ts).toLocaleTimeString()),
        el('span', 'log-msg', entry.message)
    );
    body.append(line);

    const pinned = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    if (pinned) body.scrollTop = body.scrollHeight;
}

function connectStream() {
    const source = new EventSource('/api/runs/stream');
    let wasActive = false;

    source.addEventListener('log', (ev) => appendLog(JSON.parse(ev.data)));

    source.addEventListener('state', (ev) => {
        const snapshot = JSON.parse(ev.data);
        applyRunState(snapshot);
        if (wasActive && !snapshot.active) {
            toast('Run ' + snapshot.status.toLowerCase() + '.', snapshot.status === 'FAILED' ? 'error' : 'success');
            refresh();
        }
        wasActive = snapshot.active;
    });

    source.onerror = () => {
        source.close();
        setTimeout(connectStream, 3000);
    };
}

function toggleLogs(force) {
    const panel = $('log-panel');
    const open = force === undefined ? !panel.classList.contains('open') : force;
    panel.classList.toggle('open', open);
    document.querySelector('.app').classList.toggle('logs-open', open);
}

async function startRun(path, body, label) {
    try {
        await postJSON(path, body);
        $('log-body').replaceChildren();
        toggleLogs(true);
        toast(label + ' started.', 'success');
    } catch (err) {
        toast(err.message, 'error');
    }
}

// ---------------------------------------------------------------- navigation

function switchView(view) {
    state.view = view;
    state.page = 1;
    state.selected.clear();

    document.querySelectorAll('.nav-item').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });

    $('view-title').textContent = VIEWS[view].title;
    $('view-subtitle').textContent = VIEWS[view].subtitle;

    const isTable = view === 'pipeline' || view === 'review' || view === 'manual';
    $('view-pipeline').hidden = !isTable;
    $('view-analytics').hidden = view !== 'analytics';
    $('view-runs').hidden = view !== 'runs';
    document.querySelector('.toolbar').hidden = view !== 'pipeline';

    if (isTable) loadJobs();
    else if (view === 'analytics') renderAnalytics();
    else renderRuns();
}

function refresh() {
    loadStats();
    if (state.view === 'analytics') renderAnalytics();
    else if (state.view === 'runs') renderRuns();
    else loadJobs();
}

// ---------------------------------------------------------------- wiring

function init() {
    const statusSelect = $('filter-status');
    STATUSES.forEach((s) => {
        const option = el('option', null, s.replace(/_/g, ' '));
        option.value = s;
        statusSelect.append(option);
    });

    const platformSelect = $('filter-platform');
    ['linkedin', 'indeed', 'glassdoor', 'naukri', 'google'].forEach((p) => {
        const option = el('option', null, p);
        option.value = p;
        platformSelect.append(option);
    });

    document.querySelectorAll('.nav-item').forEach((btn) => {
        btn.addEventListener('click', () => switchView(btn.dataset.view));
    });

    let searchTimer = null;
    $('filter-search').addEventListener('input', (ev) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            state.filters.search = ev.target.value.trim();
            state.page = 1;
            loadJobs();
        }, 300);
    });

    statusSelect.addEventListener('change', (ev) => {
        state.filters.status = ev.target.value;
        state.page = 1;
        loadJobs();
    });

    platformSelect.addEventListener('change', (ev) => {
        state.filters.platform = ev.target.value;
        state.page = 1;
        loadJobs();
    });

    $('filter-score').addEventListener('input', (ev) => {
        state.filters.min_score = Number(ev.target.value);
        $('filter-score-out').textContent = ev.target.value;
    });
    $('filter-score').addEventListener('change', () => { state.page = 1; loadJobs(); });

    $('filter-sort').addEventListener('change', (ev) => {
        state.filters.sort = ev.target.value;
        state.page = 1;
        loadJobs();
    });

    $('check-all').addEventListener('change', (ev) => {
        state.jobs.forEach((j) => ev.target.checked ? state.selected.add(j.id) : state.selected.delete(j.id));
        renderJobs();
    });

    $('page-prev').addEventListener('click', () => { if (state.page > 1) { state.page--; loadJobs(); } });
    $('page-next').addEventListener('click', () => { if (state.page < state.pages) { state.page++; loadJobs(); } });

    document.querySelectorAll('[data-bulk]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            try {
                const res = await postJSON('/jobs/bulk-status', {
                    job_ids: [...state.selected],
                    status: btn.dataset.bulk
                });
                toast(res.updated + ' job(s) marked ' + res.status.toLowerCase() + '.', 'success');
                state.selected.clear();
                refresh();
            } catch (err) {
                toast(err.message, 'error');
            }
        });
    });

    $('btn-discover').addEventListener('click', () => startRun('/runs/discover', {}, 'Discovery'));

    $('btn-prepare').addEventListener('click', () => {
        if (!state.selected.size) return;
        startRun('/runs/prepare', { job_ids: [...state.selected] }, 'Resume generation');
    });

    $('btn-apply').addEventListener('click', () => {
        const ids = [...state.selected];
        if (!ids.length) return;
        const live = $('btn-apply').textContent.indexOf('Dry Run') === -1;
        const warning = live
            ? 'LIVE MODE: this will actually submit ' + ids.length + ' application(s) on LinkedIn. Continue?'
            : 'Dry run: the browser will fill each form and screenshot it without submitting. Continue with ' + ids.length + ' job(s)?';
        if (!window.confirm(warning)) return;
        startRun('/runs/apply', { job_ids: ids }, 'Apply');
    });

    $('btn-cancel').addEventListener('click', async () => {
        try {
            await postJSON('/runs/cancel');
            toast('Stopping after the current item...', 'success');
        } catch (err) {
            toast(err.message, 'error');
        }
    });

    $('btn-refresh').addEventListener('click', refresh);
    $('btn-logs').addEventListener('click', () => toggleLogs());
    $('btn-log-close').addEventListener('click', () => toggleLogs(false));
    $('btn-drawer-close').addEventListener('click', closeDrawer);
    $('scrim').addEventListener('click', closeDrawer);

    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') closeDrawer();
    });

    loadStats();
    loadJobs();
    connectStream();
}

document.addEventListener('DOMContentLoaded', init);
