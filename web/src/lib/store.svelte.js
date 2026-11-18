// One shared, reactive picture of Omni: server state, the feed, and the route.

export const FEED_TYPES = ['created', 'revised', 'post', 'reply', 'rejected', 'note', 'draft', 'report'];

export const app = $state({
	ready: false,
	online: true,
	now: Date.now() / 1000,
	skew: 0, // server clock minus ours, so "ago" stays right on a phone
	status: { gate: { state: 'starting', reason: '' }, job: null },
	personas: [],
	settings: {},
	models: [],
	loaded: [],
	discord: { state: 'off' },
	remote: {},
	is_remote: false,
	counts: { live: 0, drafts: 0, archived: 0 },
	feed: [],
	feedMore: true,
	feedLoading: false,
	projects: [],
	logs: [],
	saver: { state: 'off' },
	hotkey: { ok: false },
	downloads: {}, // model -> download state, live from the event stream
	modelsBump: 0, // raised when the installed models change
	tokens: '', // the tail of what the model is writing right now
	probe: {}, // slug -> what the project's pages reported while the person used them
	route: { name: 'feed', slug: null },
	bump: {}, // slug -> counter, raised whenever something happens to that project
	error: ''
});

export async function api(path, body) {
	let r;
	try {
		r = await fetch(
			path,
			body === undefined
				? undefined
				: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
		);
	} catch (e) {
		app.online = false;
		throw new Error('Omni is not answering');
	}
	app.online = true;
	if (r.status === 401) {
		location.reload();
		throw new Error('not paired');
	}
	const data = await r.json().catch(() => ({}));
	if (!r.ok) throw new Error(data.error || 'request failed (' + r.status + ')');
	return data;
}

export function persona(handle) {
	const h = String(handle || '').replace(/^@/, '');
	return app.personas.find((p) => p.handle === h) || null;
}

export function personaById(id) {
	return app.personas.find((p) => p.id === id) || null;
}

export async function loadState() {
	const s = await api('/api/state');
	const { status, ...rest } = s;
	Object.assign(app, rest);
	if (status?.job?.tail && !app.tokens) app.tokens = status.job.tail;
	setStatus(status);
	app.ready = true;
}

function setStatus(s) {
	if (s.now) app.skew = s.now - Date.now() / 1000;
	app.status = s;
}

export async function loadFeed() {
	if (app.feedLoading) return;
	app.feedLoading = true;
	try {
		const d = await api('/api/feed?limit=30');
		app.feed = d.events;
		app.feedMore = d.more;
	} finally {
		app.feedLoading = false;
	}
}

export async function moreFeed() {
	if (app.feedLoading || !app.feedMore || !app.feed.length) return;
	app.feedLoading = true;
	try {
		const last = app.feed[app.feed.length - 1].id;
		const d = await api('/api/feed?limit=30&before=' + last);
		const have = new Set(app.feed.map((e) => e.id));
		app.feed.push(...d.events.filter((e) => !have.has(e.id)));
		app.feedMore = d.more;
	} finally {
		app.feedLoading = false;
	}
}

let projTimer = null;
export async function loadProjects() {
	const d = await api('/api/projects');
	app.projects = d.projects;
}
function loadProjectsSoon() {
	clearTimeout(projTimer);
	projTimer = setTimeout(() => loadProjects().catch(() => {}), 400);
}

function bump(slug) {
	if (slug) app.bump[slug] = (app.bump[slug] || 0) + 1;
}

export function connect() {
	const es = new EventSource('/api/stream');
	es.onopen = () => {
		if (!app.online) {
			app.online = true;
			loadState().catch(() => {});
			loadFeed().catch(() => {});
		}
	};
	es.onerror = () => {
		app.online = false;
	};
	es.onmessage = (ev) => {
		const m = JSON.parse(ev.data);
		if (m.type === 'status') {
			if (!m.job) app.tokens = '';
			return setStatus(m);
		}
		if (m.type === 'tokens') {
			app.tokens = (app.tokens + m.text).slice(-6000);
			return;
		}
		if (m.type === 'pull') {
			app.downloads[m.model] = m;
			if (m.state === 'done') loadState().catch(() => {});
			return;
		}
		if (m.type === 'models') {
			app.modelsBump++;
			return loadState().catch(() => {});
		}
		if (m.type === 'event') {
			if (FEED_TYPES.includes(m.event) && !app.feed.some((e) => e.id === m.id)) {
				const task = m.data && m.data.task_id ? { id: m.data.task_id, status: m.author === 'you' ? 'queued' : 'done' } : undefined;
				app.feed.unshift({ ...m, type: m.event, task });
			}
			bump(m.slug);
			loadProjectsSoon();
			if (m.event === 'created' || m.event === 'draft') loadState().catch(() => {});
			return;
		}
		if (m.type === 'task') {
			for (const e of app.feed) {
				if (e.data && e.data.task_id === m.id) e.task = { ...(e.task || {}), id: m.id, status: m.status, result: m.result };
			}
			app.bump['*'] = (app.bump['*'] || 0) + 1;
			return;
		}
		if (m.type === 'program') {
			bump(m.slug);
			return loadProjectsSoon();
		}
		if (m.type === 'log') {
			app.logs.unshift(m);
			if (app.logs.length > 40) app.logs.length = 40;
			return;
		}
		if (m.type === 'personas' || m.type === 'settings' || m.type === 'discord') loadState().catch(() => {});
	};
}

// --- routing: #/ feed, #/projects, #/p/<slug>, #/personas, #/settings -------------------------

export function readRoute() {
	let h = location.hash.replace(/^#/, '');
	if (h && !h.startsWith('/')) {
		// Older links (the ones already posted to Discord) are just #slug.
		history.replaceState(null, '', '#/p/' + h);
		h = '/p/' + h;
	}
	const parts = h.split('/').filter(Boolean);
	if (parts[0] === 'p' && parts[1]) app.route = { name: 'project', slug: decodeURIComponent(parts[1]) };
	else if (['projects', 'personas', 'settings', 'status', 'models', 'saver'].includes(parts[0])) app.route = { name: parts[0], slug: null };
	else app.route = { name: 'feed', slug: null };
}

export function go(path) {
	location.hash = path;
}

export async function setSetting(patch) {
	Object.assign(app.settings, patch);
	const d = await api('/api/settings', patch);
	app.settings = d.settings;
}

export async function control(action) {
	await api('/api/control', { action });
}

// What a project's pages send up while the person uses them inside Omni (see static/probe.js).
export function probeLog(slug) {
	if (!app.probe[slug]) app.probe[slug] = [];
	return app.probe[slug];
}

export function addProbe(slug, entry) {
	const log = probeLog(slug);
	log.push(entry);
	if (log.length > 200) log.splice(0, log.length - 200);
}

// Where a project page is served from. Remote devices use a path that carries permission,
// because the browser does not send the session cookie for a sandboxed page's own files.
export function projectBase(slug) {
	return (app.is_remote && app.remote.view ? '/v/' + app.remote.view : '') + '/p/' + slug + '/';
}

export function start() {
	readRoute();
	window.addEventListener('hashchange', readRoute);
	setInterval(() => (app.now = Date.now() / 1000), 15000);
	loadState()
		.then(() => Promise.all([loadFeed(), loadProjects()]))
		.catch((e) => (app.error = e.message));
	// ?static skips the live stream, so a headless browser can take a still picture of the page.
	if (!new URLSearchParams(location.search).has('static')) connect();
}
