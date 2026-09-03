'use strict';

const STATUSES = [
    'DISCOVERED', 'SCORED', 'SKIPPED', 'SHORTLISTED', 'APPROVED', 'RESUME_READY',
    'APPLIED', 'QUEUED_FOR_MANUAL', 'SCREENING', 'INTERVIEW', 'OFFER',
    'REJECTED', 'WITHDRAWN', 'GHOSTED'
];

const TRACKER_STATUSES = ['APPLIED', 'SCREENING', 'INTERVIEW', 'OFFER', 'REJECTED', 'GHOSTED'];

const VIEWS = {
    today: { title: 'Today', subtitle: 'Everything that needs you right now.' },
    pipeline: { title: 'All Jobs', subtitle: 'Your full corpus of discovered roles.' },
    review: { title: 'Review & Launch', subtitle: 'Shortlisted jobs waiting for resumes or submission.' },
    tracker: { title: 'Applications', subtitle: 'Every job you applied to and where it stands.' },
    interviews: { title: 'Interviews', subtitle: 'Rounds, outcomes, and prep notes.' },
    documents: { title: 'Documents', subtitle: 'Every resume and cover letter you have generated.' },
    assistant: { title: 'Ask About Me', subtitle: 'Grounded answers from your profile and job history only.' },
    manual: { title: 'Manual Queue', subtitle: 'Auto-apply could not finish these. Download the resume and apply yourself.' },
    analytics: { title: 'Analytics', subtitle: 'Funnel conversion, platform mix, and LLM spend.' },
    runs: { title: 'Run History', subtitle: 'Every pipeline execution and its outcome.' }
};

const state = {
    view: 'today',
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
    const abs = Math.abs(diff);
    const suffix = diff >= 0 ? ' ago' : ' from now';
    if (abs < 60) return 'just now';
    if (abs < 3600) return Math.floor(abs / 60) + 'm' + suffix;
    if (abs < 86400) return Math.floor(abs / 3600) + 'h' + suffix;
    return Math.floor(abs / 86400) + 'd' + suffix;
}

function fmtDate(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '-' : d.toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
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

const send = (path, method, body) => api(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
});

const postJSON = (path, body) => send(path, 'POST', body);
const patchJSON = (path, body) => send(path, 'PATCH', body);

function panel(titleText) {
    const section = el('section', 'panel');
    if (titleText) section.append(el('h2', null, titleText));
    return section;
}

function jobLinkRow(job, extraText) {
    const row = el('div', 'mini-row');
    const left = el('div');
    left.append(el('div', 'cell-company', job.company));
    left.append(el('div', 'cell-muted', job.title));
    row.append(left);

    if (extraText) row.append(el('div', 'cell-muted', extraText));

    const open = el('button', 'btn btn-sm btn-ghost', 'Open');
    open.addEventListener('click', () => openDrawer(job.id));
    row.append(open);
    return row;
}

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
        { label: 'In Corpus', value: data.total_jobs, note: 'all time', cls: '' },
        { label: 'Shortlisted', value: (counts.SHORTLISTED || 0) + (counts.APPROVED || 0), note: 'awaiting resume', cls: 'accent' },
        { label: 'Applied', value: data.total_applied, note: data.applied_today + ' of ' + data.daily_limit + ' today', cls: 'good' },
        { label: 'Interviews', value: (counts.INTERVIEW || 0) + (counts.OFFER || 0), note: data.interview_rate + '% of applies', cls: 'accent' },
        { label: 'Response Rate', value: data.response_rate + '%', note: 'heard back', cls: '' },
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

async function loadProfileBanner() {
    const banner = $('profile-banner');
    try {
        const status = await api('/profile/status');
        if (status.score >= 100 && !status.is_placeholder) {
            banner.hidden = true;
            return;
        }
        banner.replaceChildren();
        const msg = status.is_placeholder
            ? 'Your profile still contains the sample "John Doe" data. Matching and resumes will be wrong until you replace config/profile.yaml with your real details.'
            : 'Profile is ' + status.score + '% complete. Missing: ' + status.missing.join(', ') + '.';
        banner.append(el('strong', null, status.is_placeholder ? 'Placeholder profile detected' : 'Incomplete profile'));
        banner.append(el('span', null, ' ' + msg));
        banner.className = 'banner ' + (status.is_placeholder ? 'banner-warn' : '');
        banner.hidden = false;
    } catch (_) {
        banner.hidden = true;
    }
}

// ---------------------------------------------------------------- jobs table

function statusForView() {
    if (state.view === 'review') return 'SHORTLISTED,APPROVED,RESUME_READY';
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

function emptyMessage() {
    // A generic "run discovery" hint is wrong once jobs already exist - it hides
    // the real reason a view is empty, which is usually a missing earlier step.
    if (state.total === 0 && state.view === 'pipeline' && !state.filters.search
        && !state.filters.status && !state.filters.platform && !state.filters.min_score) {
        return 'No jobs yet. Hit "Run Discovery" to scrape your configured searches.';
    }
    if (state.total === 0) {
        if (state.view === 'review') {
            return 'Nothing shortlisted yet. Go to All Jobs, tick the roles you want, '
                + 'and press "Shortlist" - they will appear here ready for resume generation.';
        }
        if (state.view === 'manual') {
            return 'Nothing here, which is good. Jobs land in this queue only when auto-apply '
                + 'cannot finish them - for example a non-LinkedIn posting or a form it got stuck on.';
        }
        return 'Nothing here yet.';
    }
    return 'No jobs match these filters.';
}

function renderJobs() {
    const body = $('jobs-body');
    body.replaceChildren();

    const empty = $('jobs-empty');
    if (!state.jobs.length) {
        empty.hidden = false;
        empty.textContent = emptyMessage();
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

        const starCell = el('td', 'col-star');
        const star = el('button', 'star-btn' + (job.is_favorite ? ' on' : ''), job.is_favorite ? '\u2605' : '\u2606');
        star.title = job.is_favorite ? 'Remove from favourites' : 'Mark as favourite';
        star.addEventListener('click', async (ev) => {
            ev.stopPropagation();
            try {
                await patchJSON('/jobs/' + encodeURIComponent(job.id), { is_favorite: !job.is_favorite });
                job.is_favorite = !job.is_favorite;
                star.textContent = job.is_favorite ? '\u2605' : '\u2606';
                star.classList.toggle('on', job.is_favorite);
            } catch (err) {
                toast(err.message, 'error');
            }
        });
        starCell.append(star);

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

        row.append(checkCell, starCell, company, role, platform, scoreCell, statusCell, found, actions);
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

// ---------------------------------------------------------------- today view

async function renderToday() {
    const container = $('view-today');
    container.replaceChildren();

    let data;
    try {
        data = await api('/dashboard/today');
    } catch (err) {
        container.append(el('div', 'empty', 'Could not load: ' + err.message));
        return;
    }

    const sections = [
        ['Interviews coming up', data.upcoming_interviews, (iv) => {
            const row = el('div', 'mini-row');
            const left = el('div');
            left.append(el('div', 'cell-company', iv.company));
            left.append(el('div', 'cell-muted', iv.round_name + ' - ' + iv.title));
            row.append(left, el('div', 'cell-muted', fmtDate(iv.scheduled_at)));
            const open = el('button', 'btn btn-sm btn-ghost', 'Open');
            open.addEventListener('click', () => openDrawer(iv.job_id));
            row.append(open);
            return row;
        }],
        ['Follow-ups due', data.due_follow_ups, (j) => jobLinkRow(j, 'due ' + timeAgo(j.follow_up_at))],
        ['Closing soon', data.closing_soon, (j) => jobLinkRow(j, 'closes ' + timeAgo(j.deadline_at))],
        ['Ready to apply', data.ready_to_apply, (j) => jobLinkRow(j, 'score ' + (j.match_score ?? '-'))],
        ['No response yet', data.stale_applications, (j) => jobLinkRow(j, 'applied ' + timeAgo(j.applied_at))]
    ];

    let anything = false;
    for (const [title, items, renderer] of sections) {
        if (!items || !items.length) continue;
        anything = true;
        const p = panel(title + ' (' + items.length + ')');
        items.forEach((item) => renderer && p.append(renderer(item)));
        container.append(p);
    }

    // Unscored jobs are invisible everywhere else, so a failed scoring run looks
    // like discovery found nothing. Call it out explicitly.
    let stats = null;
    try {
        stats = await api('/analytics/summary');
    } catch (_) { /* stats are advisory here */ }

    if (stats) {
        const unscored = stats.status_counts.DISCOVERED || 0;
        if (unscored > 0) {
            anything = true;
            const p = panel('Waiting to be scored (' + unscored + ')');
            const msg = stats.llm_configured
                ? 'These were discovered but never scored. Run Discovery again to score them, '
                  + 'or shortlist them by hand from All Jobs.'
                : 'These cannot be scored because no LLM API key is configured. Set '
                  + 'JOBSEARCH_LLM_API_KEY or config/secrets.yaml, then run Discovery again. '
                  + 'You can still shortlist them by hand from All Jobs.';
            p.append(el('p', 'cell-muted', msg));
            const go = el('button', 'btn btn-sm', 'Open All Jobs');
            go.addEventListener('click', () => switchView('pipeline'));
            p.append(go);
            container.append(p);
        }
    }

    if (!anything) {
        const p = panel('All clear');
        p.append(el('p', 'cell-muted',
            'Nothing needs attention right now. Run Discovery to find new roles, or shortlist jobs from All Jobs.'));
        container.append(p);
    }
}

// ---------------------------------------------------------------- tracker

async function renderTracker() {
    const container = $('view-tracker');
    container.replaceChildren();

    let data;
    try {
        data = await api('/jobs?status=' + TRACKER_STATUSES.join(',') + '&page_size=200&sort=applied_at');
    } catch (err) {
        container.append(el('div', 'empty', 'Could not load: ' + err.message));
        return;
    }

    if (!data.jobs.length) {
        container.append(el('div', 'empty', 'No applications yet. Apply to a job and it will show up here.'));
        return;
    }

    // Board layout mirrors how a job hunt actually feels: columns you move through.
    const board = el('div', 'board');
    for (const status of TRACKER_STATUSES) {
        const items = data.jobs.filter((j) => j.status === status);
        const col = el('div', 'board-col');
        const head = el('div', 'board-head');
        head.append(el('span', 'badge ' + status, status.replace(/_/g, ' ')));
        head.append(el('span', 'cell-muted', items.length));
        col.append(head);

        if (!items.length) col.append(el('div', 'board-empty', '-'));
        for (const job of items) {
            const card = el('div', 'board-card');
            card.append(el('div', 'cell-company', job.company));
            card.append(el('div', 'cell-muted', job.title));
            card.append(el('div', 'cell-muted', job.applied_at ? 'applied ' + timeAgo(job.applied_at) : ''));
            card.addEventListener('click', () => openDrawer(job.id));
            col.append(card);
        }
        board.append(col);
    }
    container.append(board);
}

// ---------------------------------------------------------------- interviews

async function renderInterviews() {
    const container = $('view-interviews');
    container.replaceChildren();

    let data;
    try {
        data = await api('/interviews');
    } catch (err) {
        container.append(el('div', 'empty', 'Could not load: ' + err.message));
        return;
    }

    if (!data.interviews.length) {
        container.append(el('div', 'empty',
            'No interviews logged. Open any job and use "Add interview" to start tracking rounds.'));
        return;
    }

    const p = panel('All interview rounds');
    const table = el('table', 'jobs-table');
    const head = el('thead');
    const hr = el('tr');
    ['When', 'Company', 'Round', 'Mode', 'Interviewer', 'Outcome', ''].forEach((h) => hr.append(el('th', null, h)));
    head.append(hr);
    table.append(head);

    const tbody = el('tbody');
    for (const iv of data.interviews) {
        const row = el('tr');
        const outcomeCell = el('td');
        const select = el('select', 'input input-sm');
        ['SCHEDULED', 'PASSED', 'FAILED', 'CANCELLED', 'NO_SHOW', 'PENDING'].forEach((o) => {
            const opt = el('option', null, o);
            opt.value = o;
            if (o === iv.outcome) opt.selected = true;
            select.append(opt);
        });
        select.addEventListener('change', async () => {
            try {
                await patchJSON('/interviews/' + encodeURIComponent(iv.id), { outcome: select.value });
                toast('Outcome updated.', 'success');
                refresh();
            } catch (err) {
                toast(err.message, 'error');
            }
        });
        outcomeCell.append(select);

        const openCell = el('td');
        const open = el('button', 'btn btn-sm btn-ghost', 'Open');
        open.addEventListener('click', () => openDrawer(iv.job_id));
        openCell.append(open);

        row.append(
            el('td', 'cell-muted', fmtDate(iv.scheduled_at)),
            el('td', 'cell-company', iv.company),
            el('td', null, iv.round_name),
            el('td', 'cell-muted', iv.mode || '-'),
            el('td', 'cell-muted', iv.interviewer || '-'),
            outcomeCell,
            openCell
        );
        tbody.append(row);
    }
    table.append(tbody);
    p.append(table);
    container.append(p);
}

// ---------------------------------------------------------------- documents

async function renderDocuments() {
    const container = $('view-documents');
    container.replaceChildren();

    let data;
    try {
        data = await api('/documents?page_size=200');
    } catch (err) {
        container.append(el('div', 'empty', 'Could not load: ' + err.message));
        return;
    }

    if (!data.documents.length) {
        container.append(el('div', 'empty',
            'No documents yet. Shortlist jobs and hit "Generate Resumes" to build tailored PDFs.'));
        return;
    }

    const p = panel(data.total + ' generated document(s)');
    const table = el('table', 'jobs-table');
    const head = el('thead');
    const hr = el('tr');
    ['Created', 'Company', 'Role', 'Kind', 'Version', 'File', ''].forEach((h) => hr.append(el('th', null, h)));
    head.append(hr);
    table.append(head);

    const tbody = el('tbody');
    for (const doc of data.documents) {
        const row = el('tr');
        const kindCell = el('td');
        kindCell.append(el('span', 'badge ' + (doc.kind === 'resume' ? 'RESUME_READY' : 'SCORED'),
            doc.kind.replace(/_/g, ' ')));

        const versionCell = el('td');
        versionCell.append(el('span', null, 'v' + doc.version));
        if (doc.is_current) versionCell.append(el('span', 'tag', 'current'));

        const dlCell = el('td');
        if (doc.exists) {
            const dl = el('a', 'btn btn-sm btn-ghost', 'Download');
            dl.href = '/api/documents/' + encodeURIComponent(doc.id) + '/download';
            dlCell.append(dl);
        } else {
            dlCell.append(el('span', 'cell-muted', 'file missing'));
        }

        row.append(
            el('td', 'cell-muted', fmtDate(doc.created_at)),
            el('td', 'cell-company', doc.company || '-'),
            el('td', 'cell-muted', doc.title || '-'),
            kindCell,
            versionCell,
            el('td', 'cell-muted', doc.file_name),
            dlCell
        );
        tbody.append(row);
    }
    table.append(tbody);
    p.append(table);
    container.append(p);
}

// ---------------------------------------------------------------- assistant

function renderAssistant() {
    const container = $('view-assistant');
    container.replaceChildren();

    const p = panel('Ask about your profile and job search');
    p.append(el('p', 'cell-muted',
        'Answers come only from config/profile.yaml and your job data. If something is not in there, ' +
        'the assistant will say so rather than invent it. Every answer lists the sources it used.'));

    const form = el('div', 'ask-row');
    const input = el('input', 'input');
    input.placeholder = 'e.g. Which of my applications have gone quiet?';
    input.id = 'ask-input';
    const btn = el('button', 'btn btn-primary', 'Ask');
    form.append(input, btn);
    p.append(form);

    const suggestions = el('div', 'chips');
    [
        'What roles am I best matched to so far?',
        'Which applications have I not heard back on?',
        'What skills gaps keep coming up in my matches?',
        'Summarise my experience for a recruiter.'
    ].forEach((q) => {
        const chip = el('button', 'chip', q);
        chip.addEventListener('click', () => { input.value = q; btn.click(); });
        suggestions.append(chip);
    });
    p.append(suggestions);

    const answer = el('div', 'answer');
    answer.id = 'ask-answer';
    p.append(answer);
    container.append(p);

    const ask = async () => {
        const question = input.value.trim();
        if (!question) return;
        answer.replaceChildren(el('p', 'cell-muted', 'Thinking...'));
        try {
            const res = await postJSON('/assistant/ask', { question });
            answer.replaceChildren();
            answer.append(el('div', 'answer-text', res.answer));
            const src = el('div', 'cell-muted');
            src.textContent = 'Grounded on: ' + res.grounded_on.join(', ');
            answer.append(src);
        } catch (err) {
            answer.replaceChildren(el('p', 'answer-error', err.message));
        }
    };

    btn.addEventListener('click', ask);
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') ask(); });
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

    // -- actions
    const actions = el('div', 'drawer-actions');
    const open = el('a', 'btn btn-primary btn-sm', 'Open posting');
    open.href = job.job_url;
    open.target = '_blank';
    open.rel = 'noopener noreferrer';
    actions.append(open);

    if (job.has_resume) {
        const dl = el('a', 'btn btn-sm', 'Resume');
        dl.href = '/api/jobs/' + encodeURIComponent(job.id) + '/document/resume';
        actions.append(dl);
    }
    if (job.has_cover_letter) {
        const dl = el('a', 'btn btn-sm', 'Cover letter');
        dl.href = '/api/jobs/' + encodeURIComponent(job.id) + '/document/cover_letter';
        actions.append(dl);
    }
    body.append(actions);

    // -- status control
    const statusRow = el('div', 'drawer-actions');
    const statusSelect = el('select', 'input input-sm');
    STATUSES.forEach((s) => {
        const opt = el('option', null, s.replace(/_/g, ' '));
        opt.value = s;
        if (s === job.status) opt.selected = true;
        statusSelect.append(opt);
    });
    statusSelect.addEventListener('change', async () => {
        try {
            await patchJSON('/jobs/' + encodeURIComponent(job.id) + '/status', { status: statusSelect.value });
            toast('Status updated.', 'success');
            openDrawer(job.id);
            loadStats();
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    statusRow.append(el('span', 'field-label', 'Status'), statusSelect);

    const prioritySelect = el('select', 'input input-sm');
    [['0', 'No priority'], ['1', 'Low'], ['2', 'Medium'], ['3', 'High']].forEach(([v, label]) => {
        const opt = el('option', null, label);
        opt.value = v;
        if (Number(v) === job.priority) opt.selected = true;
        prioritySelect.append(opt);
    });
    prioritySelect.addEventListener('change', async () => {
        try {
            await patchJSON('/jobs/' + encodeURIComponent(job.id), { priority: Number(prioritySelect.value) });
            toast('Priority updated.', 'success');
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    statusRow.append(el('span', 'field-label', 'Priority'), prioritySelect);
    body.append(statusRow);

    // -- reminders
    const reminderRow = el('div', 'drawer-actions');
    const followUp = el('input', 'input input-sm');
    followUp.type = 'date';
    if (job.follow_up_at) followUp.value = job.follow_up_at.slice(0, 10);
    followUp.addEventListener('change', async () => {
        try {
            await patchJSON('/jobs/' + encodeURIComponent(job.id), {
                follow_up_at: followUp.value ? followUp.value + 'T09:00:00' : null
            });
            toast('Follow-up saved.', 'success');
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    reminderRow.append(el('span', 'field-label', 'Follow up'), followUp);

    const deadline = el('input', 'input input-sm');
    deadline.type = 'date';
    if (job.deadline_at) deadline.value = job.deadline_at.slice(0, 10);
    deadline.addEventListener('change', async () => {
        try {
            await patchJSON('/jobs/' + encodeURIComponent(job.id), {
                deadline_at: deadline.value ? deadline.value + 'T23:59:00' : null
            });
            toast('Deadline saved.', 'success');
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    reminderRow.append(el('span', 'field-label', 'Closes'), deadline);
    body.append(reminderRow);

    // -- meta
    const meta = el('dl', 'meta-grid');
    [
        ['Match score', job.match_score ?? 'not scored'],
        ['Platform', job.platform || '-'],
        ['Work mode', job.work_mode || 'unknown'],
        ['Salary', job.salary_info || 'not listed'],
        ['Discovered', timeAgo(job.discovered_at)],
        ['Applied', job.applied_at ? timeAgo(job.applied_at) : 'not yet'],
        ['Method', job.applied_method || '-'],
        ['LLM cost', '$' + Number(job.llm_cost_usd || 0).toFixed(4)]
    ].forEach(([label, value]) => {
        const cell = el('div');
        cell.append(el('dt', null, label), el('dd', null, value));
        meta.append(cell);
    });
    body.append(meta);

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

    // -- notes
    body.append(el('h3', null, 'Add a note'));
    const noteRow = el('div', 'ask-row');
    const noteInput = el('input', 'input');
    noteInput.placeholder = 'Recruiter call went well, asked about system design...';
    const noteBtn = el('button', 'btn btn-sm', 'Save');
    noteBtn.addEventListener('click', async () => {
        if (!noteInput.value.trim()) return;
        try {
            await postJSON('/jobs/' + encodeURIComponent(job.id) + '/notes', { note: noteInput.value.trim() });
            toast('Note saved.', 'success');
            openDrawer(job.id);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    noteRow.append(noteInput, noteBtn);
    body.append(noteRow);

    // -- interviews
    body.append(el('h3', null, 'Interviews'));
    if (job.interviews.length) {
        job.interviews.forEach((iv) => {
            const row = el('div', 'mini-row');
            const left = el('div');
            left.append(el('div', 'cell-company', iv.round_name));
            left.append(el('div', 'cell-muted', fmtDate(iv.scheduled_at) + ' - ' + (iv.mode || 'mode n/a')));
            row.append(left, el('span', 'badge ' + (iv.outcome === 'PASSED' ? 'OFFER' : 'INTERVIEW'), iv.outcome));
            body.append(row);
        });
    } else {
        body.append(el('p', 'cell-muted', 'No rounds logged yet.'));
    }

    const ivRow = el('div', 'ask-row');
    const ivName = el('input', 'input');
    ivName.placeholder = 'Round name (e.g. Tech Screen)';
    const ivWhen = el('input', 'input input-sm');
    ivWhen.type = 'datetime-local';
    const ivBtn = el('button', 'btn btn-sm', 'Add');
    ivBtn.addEventListener('click', async () => {
        if (!ivName.value.trim()) { toast('Give the round a name.', 'error'); return; }
        try {
            await postJSON('/jobs/' + encodeURIComponent(job.id) + '/interviews', {
                round_name: ivName.value.trim(),
                scheduled_at: ivWhen.value || null
            });
            toast('Interview added.', 'success');
            openDrawer(job.id);
            loadStats();
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    ivRow.append(ivName, ivWhen, ivBtn);
    body.append(ivRow);

    // -- contacts
    body.append(el('h3', null, 'Contacts'));
    if (job.contacts.length) {
        job.contacts.forEach((c) => {
            const row = el('div', 'mini-row');
            const left = el('div');
            left.append(el('div', 'cell-company', c.name));
            left.append(el('div', 'cell-muted', [c.role, c.email, c.phone].filter(Boolean).join(' - ')));
            row.append(left);
            const del = el('button', 'btn btn-sm btn-ghost', 'Remove');
            del.addEventListener('click', async () => {
                try {
                    await api('/contacts/' + encodeURIComponent(c.id), { method: 'DELETE' });
                    openDrawer(job.id);
                } catch (err) {
                    toast(err.message, 'error');
                }
            });
            row.append(del);
            body.append(row);
        });
    } else {
        body.append(el('p', 'cell-muted', 'No contacts saved.'));
    }

    const contactRow = el('div', 'ask-row');
    const cName = el('input', 'input');
    cName.placeholder = 'Name';
    const cRole = el('input', 'input input-sm');
    cRole.placeholder = 'Role';
    const cBtn = el('button', 'btn btn-sm', 'Add');
    cBtn.addEventListener('click', async () => {
        if (!cName.value.trim()) { toast('Contact needs a name.', 'error'); return; }
        try {
            await postJSON('/jobs/' + encodeURIComponent(job.id) + '/contacts', {
                name: cName.value.trim(), role: cRole.value.trim() || null
            });
            toast('Contact added.', 'success');
            openDrawer(job.id);
        } catch (err) {
            toast(err.message, 'error');
        }
    });
    contactRow.append(cName, cRole, cBtn);
    body.append(contactRow);

    // -- documents
    if (job.documents.length) {
        body.append(el('h3', null, 'Document history'));
        job.documents.forEach((d) => {
            const row = el('div', 'mini-row');
            const left = el('div');
            left.append(el('div', 'cell-company', d.kind.replace(/_/g, ' ') + ' v' + d.version));
            left.append(el('div', 'cell-muted', fmtDate(d.created_at)));
            row.append(left);
            const dl = el('a', 'btn btn-sm btn-ghost', 'Download');
            dl.href = '/api/documents/' + encodeURIComponent(d.id) + '/download';
            row.append(dl);
            body.append(row);
        });
    }

    // -- timeline
    body.append(el('h3', null, 'Timeline'));
    if (job.events.length) {
        const timeline = el('div', 'timeline');
        job.events.forEach((e) => {
            const item = el('div', 'timeline-item');
            item.append(el('div', 'timeline-time', fmtDate(e.created_at)));
            const content = el('div');
            content.append(el('div', null, e.summary));
            if (e.detail) content.append(el('div', 'cell-muted', e.detail));
            item.append(content);
            timeline.append(item);
        });
        body.append(timeline);
    } else {
        body.append(el('p', 'cell-muted', 'No history recorded yet.'));
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

    const funnelPanel = panel('Conversion funnel');
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

    const platformPanel = panel('Jobs by platform');
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

    const costPanel = panel('Cost and configuration');
    const grid = el('dl', 'meta-grid');
    [
        ['Total LLM spend', '$' + data.total_llm_cost_usd.toFixed(4)],
        ['Average applied score', data.avg_match_score],
        ['Applied today', data.applied_today + ' / ' + data.daily_limit],
        ['Interview rate', data.interview_rate + '%'],
        ['Response rate', data.response_rate + '%'],
        ['Min match score', data.min_match_score],
        ['Apply mode', data.dry_run ? 'Dry run (no submissions)' : 'LIVE submissions'],
        ['LLM key', data.llm_configured ? 'configured' : 'NOT configured'],
        ['Ghosted', data.total_ghosted]
    ].forEach(([label, value]) => {
        const cell = el('div');
        cell.append(el('dt', null, label), el('dd', null, value));
        grid.append(cell);
    });
    costPanel.append(grid);

    const ghostBtn = el('button', 'btn btn-sm', 'Run ghosting check now');
    ghostBtn.addEventListener('click', async () => {
        try {
            const res = await postJSON('/cron/ghosting-check');
            toast('Marked ' + res.ghosted_count + ' job(s) as ghosted.', 'success');
            refresh();
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

    const p = panel(null);
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
    p.append(table);
    container.append(p);
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
    const panelEl = $('log-panel');
    const open = force === undefined ? !panelEl.classList.contains('open') : force;
    panelEl.classList.toggle('open', open);
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

const TABLE_VIEWS = ['pipeline', 'review', 'manual'];

function switchView(view) {
    state.view = view;
    state.page = 1;
    state.selected.clear();

    document.querySelectorAll('.nav-item').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });

    $('view-title').textContent = VIEWS[view].title;
    $('view-subtitle').textContent = VIEWS[view].subtitle;

    const isTable = TABLE_VIEWS.includes(view);
    $('view-today').hidden = view !== 'today';
    $('view-pipeline').hidden = !isTable;
    $('view-tracker').hidden = view !== 'tracker';
    $('view-interviews').hidden = view !== 'interviews';
    $('view-documents').hidden = view !== 'documents';
    $('view-assistant').hidden = view !== 'assistant';
    $('view-analytics').hidden = view !== 'analytics';
    $('view-runs').hidden = view !== 'runs';
    document.querySelector('.toolbar').hidden = view !== 'pipeline';

    const renderers = {
        today: renderToday,
        tracker: renderTracker,
        interviews: renderInterviews,
        documents: renderDocuments,
        assistant: renderAssistant,
        analytics: renderAnalytics,
        runs: renderRuns
    };
    if (isTable) loadJobs();
    else renderers[view]();
}

function refresh() {
    loadStats();
    loadProfileBanner();
    switchView(state.view);
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

    $('btn-export').addEventListener('click', () => { window.location.href = '/api/export/jobs.csv'; });
    $('btn-refresh').addEventListener('click', refresh);
    $('btn-logs').addEventListener('click', () => toggleLogs());
    $('btn-log-close').addEventListener('click', () => toggleLogs(false));
    $('btn-drawer-close').addEventListener('click', closeDrawer);
    $('scrim').addEventListener('click', closeDrawer);

    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') closeDrawer();
    });

    loadStats();
    loadProfileBanner();
    switchView('today');
    connectStream();
}

document.addEventListener('DOMContentLoaded', init);
