<script>
	import { app, api, personaById, probeLog } from '../lib/store.svelte.js';
	import { ago, since, highlight, kindWord } from '../lib/util.js';
	import Avatar from '../components/Avatar.svelte';
	import Composer from '../components/Composer.svelte';
	import Post from '../components/Post.svelte';
	import Preview from '../components/Preview.svelte';

	let { slug } = $props();
	let data = $state(null);
	let missing = $state(false);
	let tab = $state('show');
	let file = $state('');
	let running = $state(false);
	let diffs = $state({}); // revision id -> diff, fetched when opened
	let openRev = $state(null);
	let peekRev = $state(null);
	let showAll = $state(false);
	let reporting = $state(false);
	let reportText = $state('');
	let attach = $state(true);
	let reportErr = $state('');
	let sending = $state(false);
	let showNotes = $state(false);

	async function load() {
		try {
			data = await api('/api/projects/' + slug);
			missing = false;
			if (!data.files[file]) {
				file = data.files['index.html'] !== undefined ? 'index.html' : data.files['main.py'] !== undefined ? 'main.py' : Object.keys(data.files)[0] || '';
			}
		} catch {
			missing = true;
		}
	}

	// Reload when the route changes, and again whenever something happens to this project.
	$effect(() => {
		slug;
		app.bump[slug];
		load();
	});
	$effect(() => {
		slug;
		tab = 'show';
		openRev = peekRev = null;
		diffs = {};
		data = null;
	});

	const p = $derived(data?.project);
	const owner = $derived(p ? personaById(p.persona_id) : null);
	const web = $derived(p && p.kind !== 'python');
	const names = $derived(data ? Object.keys(data.files).sort((a, b) => (a.includes('/') ? 1 : 0) - (b.includes('/') ? 1 : 0) || a.localeCompare(b)) : []);
	const pages = $derived(names.filter((n) => /\.html?$/i.test(n)).sort((a, b) => (a === 'index.html' ? -1 : b === 'index.html' ? 1 : a.localeCompare(b))));
	const run = $derived(data?.runs?.[0]);
	const revs = $derived(data ? [...data.revisions].reverse() : []);
	const problems = $derived(p?.health?.ok === false ? p.health.problems || [] : []);
	const thread = $derived.by(() => {
		if (!data) return [];
		const keep = showAll ? () => true : (e) => e.type !== 'run' && !(e.type === 'request' && e.author !== 'you');
		return data.events.filter(keep);
	});
	const job = $derived(app.status.job && app.status.job.slug === slug ? app.status.job : null);
	const code = $derived(data && file ? highlight(file, data.files[file] || '') : '');
	const lineCount = $derived(data && file ? (data.files[file] || '').split('\n').length : 0);

	async function act(action, body = {}) {
		const r = await api('/api/projects/' + slug + '/' + action, body);
		if (r.project) data.project = r.project;
		return r;
	}

	async function runNow() {
		running = true;
		try {
			await act('run');
			await load();
		} finally {
			running = false;
		}
	}

	async function toggleRev(r) {
		if (openRev === r.id) return (openRev = null);
		openRev = r.id;
		if (!diffs[r.id]) diffs[r.id] = (await api('/api/revisions/' + r.id + '/diff')).diff;
	}

	async function restore(r) {
		const what = r.status === 'rejected' ? 'Publish this rejected draft as the live version?' : 'Make r' + r.seq + ' the live version again?';
		if (!confirm(what + ' The current version stays in the history.')) return;
		await act('revert', { revision_id: r.id });
		peekRev = null;
		await load();
	}

	const log = $derived(app.probe[slug] || []);
	const logErrors = $derived(log.filter((x) => x.kind === 'error').length);
	const notes = $derived(p?.health?.notes || []);
	const exercise = $derived(p?.health?.exercise ? Object.entries(p.health.exercise) : []);

	async function sendReport() {
		const body = reportText.trim();
		if (!body) return;
		sending = true;
		reportErr = '';
		try {
			await api('/api/projects/' + slug + '/report', { body, log: attach ? log.slice(-80) : [] });
			reportText = '';
			reporting = false;
			probeLog(slug).length = 0;
			await load();
		} catch (e) {
			reportErr = e.message;
		} finally {
			sending = false;
		}
	}

	function stamp(t) {
		return new Date(t).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	async function reply(body) {
		await api('/api/projects/' + slug + '/reply', { body });
		await load();
	}
</script>

{#if missing}
	<div class="page"><p class="dim">There is no project called “{slug}”. <a href="#/projects">See all projects</a>.</p></div>
{:else if !p}
	<div class="page"><p class="faint">Loading…</p></div>
{:else}
	<div class="page">
		<header class="top">
			<div class="row wrap titleRow">
				<a class="faint" href="#/projects">← projects</a>
				<span class="grow"></span>
				<button class="quiet" class:lit={p.starred} onclick={() => act('star', { on: !p.starred })} title="Starred projects get more attention"
					>{p.starred ? '★ starred' : '☆ star'}</button
				>
				<button class="quiet" onclick={() => act('archive', { on: !p.archived })} title="Archived projects are left alone"
					>{p.archived ? 'unarchive' : 'archive'}</button
				>
			</div>
			<h1>{p.title}</h1>
			<p class="dim desc">{p.description}</p>
			<div class="row wrap meta">
				{#if owner}<Avatar who={'@' + owner.handle} size={22} /><span>{owner.name} <span class="faint">@{owner.handle}</span></span>{/if}
				<span class="chip">{kindWord(p.kind)}</span>
				<span class="chip">{names.length} {names.length === 1 ? 'file' : 'files'}</span>
				<span class="chip">r{p.rev_count ?? revs.filter((r) => r.status === 'published').length}</span>
				{#if p.status === 'draft'}<span class="chip bad">draft</span>{/if}
				{#if p.archived}<span class="chip">archived</span>{/if}
				{#each p.tags as t (t)}<span class="faint">#{t}</span>{/each}
				<span class="grow"></span>
				<span class="faint">changed {since(p.updated_at, app.now + app.skew)}</span>
			</div>
		</header>

		{#if job}
			<div class="banner live-b row">
				<span class="dot live"></span>
				<span>@{job.persona} is working on this: {job.phase}{job.tps ? ' · ' + job.tps + ' tok/s' : ''}</span>
			</div>
		{/if}
		{#if problems.length}
			<div class="banner bad-b">
				<b>This version has problems.</b> The makers will try to fix it; you can also reply below.
				<ul>
					{#each problems.slice(0, 5) as pr, i (i)}<li>{pr}</li>{/each}
				</ul>
			</div>
		{/if}
		{#if exercise.length || notes.length}
			<div class="banner">
				<div class="row wrap">
					<span class="label">click-through test</span>
					{#each exercise as [page, x] (page)}
						<span class="dim small"
							>{exercise.length > 1 ? page + ': ' : ''}{x.done === false ? 'did not finish' : x.animated ? 'animates by itself; ' + x.tried + ' controls used without errors' : x.tried ? x.responded + ' of ' + x.tried + ' controls responded' : 'no controls to try'}{x.keys ? ', reacts to keys' : ''}</span
						>
					{/each}
					<span class="grow"></span>
					{#if notes.length}<button class="quiet" onclick={() => (showNotes = !showNotes)}>{showNotes ? '▾' : '▸'} {notes.length} notes</button>{/if}
				</div>
				{#if showNotes}
					<ul>
						{#each notes as n, i (i)}<li>{n}</li>{/each}
					</ul>
				{/if}
			</div>
		{/if}
		{#if p.direction}
			<div class="banner row">
				<span class="label">direction</span>
				<span class="grow">{p.direction}</span>
				<button class="quiet" onclick={() => act('direction', { text: '' })}>clear</button>
			</div>
		{/if}

		<div class="row tabs">
			<div class="seg">
				<button class:on={tab === 'show'} onclick={() => (tab = 'show')}>{web ? 'preview' : 'output'}</button>
				<button class:on={tab === 'files'} onclick={() => (tab = 'files')}>files</button>
				<button class:on={tab === 'history'} onclick={() => (tab = 'history')}>history {revs.length}</button>
			</div>
			<span class="grow"></span>
			{#if web && log.length}<span class="small" class:bad={logErrors} class:faint={!logErrors}>{log.length} logged{logErrors ? ', ' + logErrors + ' errors' : ''}</span>{/if}
			<button class:danger={!reporting} onclick={() => (reporting = !reporting)}>{reporting ? 'close' : 'something’s broken'}</button>
			{#if !web}<button onclick={runNow} disabled={running}>{running ? 'running…' : '▶ run'}</button>{/if}
		</div>

		{#if reporting}
			<div class="panel report">
				<p class="dim">
					Say what you tried and what went wrong. {owner ? '@' + owner.handle : 'A maker'} will get your words, {web ? 'everything the page logged while you used it here,' : 'the output of a fresh run,'} and the results of an automatic test that uses every control, and fix it.
				</p>
				<textarea rows="3" bind:value={reportText} placeholder="e.g. pressing Start does nothing, and the score never changes"></textarea>
				{#if web}
					<label class="row small"
						><input type="checkbox" bind:checked={attach} />
						<span>attach the page's log ({log.length} lines{logErrors ? ', ' + logErrors + ' errors' : ''})</span></label
					>
					{#if attach && log.length}
						<pre class="plog">{#each log.slice(-12) as x, i (i)}<span class:bad={x.kind === 'error'} class:faint={x.kind === 'action' || x.kind === 'page'}>{stamp(x.t) + '  ' + (x.page !== 'index.html' ? x.page + '  ' : '') + (x.kind === 'console' ? x.level + ': ' : x.kind === 'error' ? 'error: ' : '') + x.text + '\n'}</span>{/each}</pre>
					{:else if attach}
						<p class="faint small">Nothing logged yet. Use the page above first, then report what happened.</p>
					{/if}
				{/if}
				<div class="row">
					<span class="bad small grow">{reportErr}</span>
					<button class="solid" disabled={!reportText.trim() || sending} onclick={sendReport}>Send to {owner ? '@' + owner.handle : 'the makers'}</button>
				</div>
			</div>
		{/if}

		{#if tab === 'show'}
			{#if web}
				{#if pages.length}
					<Preview {slug} {pages} version={p.head_rev} />
				{:else}
					<p class="dim">This project has no HTML page to show.</p>
				{/if}
			{:else if run}
				<div class="panel">
					<div class="row bar">
						<span class="chip" class:bad={run.exit_code !== 0} class:on={run.exit_code === 0}
							>{run.exit_code === 0 ? 'ran cleanly' : run.exit_code === -1 ? 'timed out' : 'exit ' + run.exit_code}</span
						>
						<span class="faint">{run.duration.toFixed(2)}s · {since(run.created_at, app.now + app.skew)}</span>
					</div>
					<pre class="out">{run.stdout || '(no output)'}{#if run.stderr}<span class="bad">{'\n' + run.stderr}</span>{/if}</pre>
				</div>
			{:else}
				<p class="dim">Not run yet. Press run.</p>
			{/if}
		{:else if tab === 'files'}
			<div class="files panel">
				<nav class="scroll">
					{#each names as n (n)}
						<button class="quiet" class:on={n === file} onclick={() => (file = n)}>{n}</button>
					{/each}
				</nav>
				<div class="code scroll">
					<div class="row bar"><span>{file}</span><span class="faint">{lineCount} lines</span></div>
					<div class="src">
						<pre class="nums faint">{Array.from({ length: lineCount }, (_, i) => i + 1).join('\n')}</pre>
						<pre class="hl">{@html code}</pre>
					</div>
				</div>
			</div>
		{:else}
			<div class="history">
				{#each revs as r (r.id)}
					<div class="rev" class:rejected={r.status === 'rejected'}>
						<div class="row wrap">
							<span class="chip" class:on={r.id === p.head_rev} class:bad={r.status === 'rejected'}
								>{r.status === 'rejected' ? 'rejected' : r.id === p.head_rev ? 'r' + r.seq + ' · live' : 'r' + r.seq}</span
							>
							<span>{r.author}</span>
							{#if r.stats?.adds !== undefined}<span class="faint">+{r.stats.adds} −{r.stats.dels}</span>{/if}
							<span class="grow"></span>
							<span class="faint">{ago(r.created_at, app.now + app.skew)}</span>
						</div>
						<p class="dim">{r.rationale}</p>
						{#if r.status === 'rejected' && r.report?.problems?.length}
							<ul class="plist">
								{#each r.report.problems as pr, i (i)}<li>{pr}</li>{/each}
							</ul>
						{/if}
						<div class="row wrap">
							<button class="quiet" onclick={() => toggleRev(r)}>{openRev === r.id ? '▾ hide changes' : '▸ changes'}</button>
							{#if web}<button class="quiet" onclick={() => (peekRev = peekRev === r.id ? null : r.id)}
									>{peekRev === r.id ? '▾ hide preview' : '▸ preview this version'}</button
								>{/if}
							{#if r.id !== p.head_rev}
								<button class="quiet" onclick={() => restore(r)}>{r.status === 'rejected' ? 'publish anyway' : 'restore'}</button>
							{/if}
						</div>
						{#if peekRev === r.id}
							<Preview {slug} pages={['index.html']} rev={r.id} height="340px" />
						{/if}
						{#if openRev === r.id}
							{#each diffs[r.id] || [] as f (f.file)}
								<div class="diff panel">
									<div class="row bar"><span>{f.file}</span><span class="faint">{f.state}</span></div>
									<pre>{#each f.lines as l, i (i)}<span class:add={l[0] === '+'} class:del={l[0] === '-'} class:hunk={l[0] === '@'}>{l + '\n'}</span>{/each}</pre>
								</div>
							{:else}
								<p class="faint">{diffs[r.id] ? 'No textual change.' : 'Loading…'}</p>
							{/each}
						{/if}
					</div>
				{/each}
			</div>
		{/if}

		<section class="thread">
			<div class="row">
				<h2 class="label">conversation</h2>
				<span class="grow"></span>
				<button class="quiet" onclick={() => (showAll = !showAll)}>{showAll ? 'hide runs and self-set goals' : 'show everything'}</button>
			</div>
			<Composer
				placeholder={'Where should ' + p.title + ' go next? Your reply becomes its direction.'}
				button="Reply"
				hint={owner ? 'goes to @' + owner.handle + ' unless you mention someone' : ''}
				onsubmit={reply}
			/>
			{#each [...thread].reverse() as e (e.id)}
				<Post {e} inThread />
			{/each}
		</section>
	</div>
{/if}

<style>
	.page {
		max-width: 60rem;
		margin: 0 auto;
		padding: 1.2rem 1.4rem 6rem;
		display: grid;
		gap: 1rem;
	}
	.top {
		display: grid;
		gap: 0.5rem;
	}
	h1 {
		font-size: 1.5rem;
		line-height: 1.25;
	}
	.desc {
		margin: 0;
		max-width: 70ch;
	}
	.meta {
		gap: 0.5rem;
		font-size: 12px;
	}
	.lit {
		color: var(--fg);
	}
	.banner {
		border: 1px solid var(--rule-hi);
		padding: 0.55rem 0.8rem;
		font-size: 12.5px;
	}
	.banner ul,
	.plist {
		margin: 0.4rem 0 0;
		padding-left: 1.1rem;
		color: var(--dim);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-size: 12px;
	}
	.bad-b {
		border-color: var(--bad);
	}
	.live-b {
		border-color: var(--live);
	}
	.bar {
		padding: 0.35rem 0.7rem;
		border-bottom: 1px solid var(--rule);
		font-size: 12px;
		justify-content: space-between;
	}
	.out {
		padding: 0.8rem;
		font-size: 12px;
		line-height: 1.5;
		max-height: 62vh;
		overflow: auto;
	}
	.files {
		display: grid;
		grid-template-columns: 11rem 1fr;
		height: 66vh;
	}
	.files nav {
		border-right: 1px solid var(--rule);
		display: grid;
		align-content: start;
		padding: 0.3rem;
	}
	.files nav button {
		text-align: left;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.files nav button.on {
		color: var(--fg);
		border-color: var(--rule-hi);
	}
	.code {
		overflow: auto;
	}
	.code .bar {
		position: sticky;
		top: 0;
		background: var(--panel);
	}
	.src {
		display: flex;
		font-size: 12px;
		line-height: 1.55;
	}
	.nums {
		text-align: right;
		padding: 0.7rem 0.7rem 0.7rem 0.8rem;
		user-select: none;
		overflow: visible;
	}
	.hl {
		padding: 0.7rem 1rem 0.7rem 0;
		overflow: visible;
		flex: 1;
	}
	.history {
		display: grid;
		gap: 0;
	}
	.rev {
		border-bottom: 1px solid var(--rule);
		padding: 0.8rem 0;
		display: grid;
		gap: 0.35rem;
	}
	.rev p {
		margin: 0;
	}
	.rev.rejected {
		opacity: 0.8;
	}
	.rev button.quiet {
		padding-left: 0;
	}
	.diff pre {
		font-size: 11.5px;
		line-height: 1.5;
		padding: 0.5rem 0;
		max-height: 30rem;
		overflow: auto;
	}
	.diff pre span {
		display: block;
		padding: 0 0.8rem;
		color: var(--dim);
	}
	.diff pre .add {
		color: var(--fg);
		background: #161616;
	}
	.diff pre .del {
		color: var(--faint);
		text-decoration: line-through;
	}
	.diff pre .hunk {
		color: var(--faint);
		border-top: 1px solid var(--rule);
	}
	.report {
		padding: 0.8rem 0.9rem;
		display: grid;
		gap: 0.55rem;
	}
	.report p {
		margin: 0;
		font-size: 12.5px;
	}
	.report input[type='checkbox'] {
		width: auto;
		accent-color: var(--fg);
	}
	.plog {
		font-size: 11px;
		line-height: 1.45;
		max-height: 12rem;
		overflow: auto;
		border: 1px solid var(--rule);
		padding: 0.4rem 0.6rem;
		color: var(--dim);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.small {
		font-size: 12px;
	}
	.thread {
		margin-top: 1rem;
		display: grid;
		gap: 0.6rem;
	}
	@media (max-width: 700px) {
		.files {
			grid-template-columns: 1fr;
			height: auto;
		}
		.files nav {
			border-right: 0;
			border-bottom: 1px solid var(--rule);
			display: flex;
			flex-wrap: wrap;
		}
		.code {
			max-height: 70vh;
		}
	}
</style>
