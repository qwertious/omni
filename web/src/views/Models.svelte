<script>
	import { app, api, loadState } from '../lib/store.svelte.js';
	import { gb, shortModel, since } from '../lib/util.js';

	let data = $state(null);
	let err = $state('');
	let custom = $state('');
	let openBuilds = $state({});
	let showAll = $state(false);

	async function load() {
		try {
			data = await api('/api/models');
			for (const d of data.downloads) if (!app.downloads[d.model]) app.downloads[d.model] = d;
			err = '';
		} catch (e) {
			err = e.message;
		}
	}
	$effect(() => {
		app.modelsBump;
		load();
	});

	const hw = $derived(data?.hardware);
	const list = $derived(data?.catalog || []);
	const top = $derived(list.filter((m) => m.recommended));
	const rest = $derived(list.filter((m) => !m.recommended));
	const GB = 1e9;

	const WHERE = { gpu: 'all on the video card', split: 'partly in system memory', cpu: 'in system memory' };
	const SUITS = { both: 'new projects and edits', create: 'new projects', edit: 'edits and fixes' };

	function dl(tag) {
		return app.downloads[tag];
	}
	function active(tag) {
		const d = dl(tag);
		return d && (d.state === 'queued' || d.state === 'downloading');
	}
	function pct(d) {
		return d && d.total ? Math.min(100, (d.done / d.total) * 100) : 0;
	}
	function eta(d) {
		if (!d || !d.speed || !d.total) return '';
		const s = (d.total - d.done) / d.speed;
		return s > 5400 ? Math.round(s / 3600) + ' h left' : Math.max(1, Math.round(s / 60)) + ' min left';
	}

	async function pull(tag) {
		err = '';
		try {
			const r = await api('/api/models/pull', { model: tag });
			app.downloads[tag] = r.download;
		} catch (e) {
			err = e.message;
		}
	}
	async function cancel(tag) {
		await api('/api/models/cancel', { model: tag });
	}
	async function tryIt(tag) {
		err = '';
		try {
			await api('/api/models/try', { model: tag });
		} catch (e) {
			err = e.message;
		}
	}
	async function remove(m) {
		const users = m.used_by?.length ? ' It is the model of ' + m.used_by.map((h) => '@' + h).join(', ') + ', who will stop working until you give them another.' : '';
		if (!confirm('Delete ' + m.name + ' (' + gb(m.size) + ' GB) from this computer? This cannot be undone; you would have to download it again.' + users)) return;
		try {
			await api('/api/models/delete', { model: m.name });
			await load();
		} catch (e) {
			err = e.message;
		}
	}
	async function assign(tag, pid) {
		const p = app.personas.find((x) => x.id === Number(pid));
		if (!p) return;
		if (!confirm('Give ' + p.name + ' (@' + p.handle + ') ' + shortModel(tag) + ' instead of ' + shortModel(p.model) + '?')) return;
		await api('/api/personas/' + p.id, { model: tag, enabled: true });
		await loadState();
		await load();
	}
	function usersOf(tag) {
		return app.personas.filter((p) => p.model === tag || p.model + ':latest' === tag || p.model === tag + ':latest');
	}
	function bench(tag) {
		return data?.bench?.[tag];
	}
	const testing = $derived(app.status.job?.what === 'model test' ? app.status.job : null);
</script>

{#snippet progress(tag)}
	{@const d = dl(tag)}
	{#if d && d.state !== 'done'}
		<div class="dl">
			{#if d.state === 'downloading' || d.state === 'queued'}
				<div class="bar"><i style="width:{pct(d)}%"></i></div>
				<div class="row small dim">
					<span class="grow"
						>{d.state === 'queued' ? 'waiting for the download before it' : d.total ? (d.done / GB).toFixed(1) + ' of ' + (d.total / GB).toFixed(1) + ' GB' : d.status || 'starting'}{d.speed ? ' · ' + (d.speed / 1e6).toFixed(0) + ' MB/s · ' + eta(d) : ''}</span
					>
					<button class="quiet" onclick={() => cancel(tag)}>stop</button>
				</div>
			{:else if d.state === 'failed'}
				<div class="bad small">Download failed: {d.error}</div>
			{:else if d.state === 'cancelled'}
				<div class="faint small">Stopped. Download again to carry on where it left off.</div>
			{/if}
		</div>
	{/if}
{/snippet}

{#snippet benchLine(tag)}
	{@const b = bench(tag)}
	{#if testing && testing.model === tag}
		<div class="small live">Testing: {testing.phase}{testing.tps ? ' · ' + testing.tps + ' tok/s' : ''}</div>
	{:else if b}
		<div class="small" class:bad={!b.ok} class:dim={b.ok}>
			{#if b.ok}Tested {since(b.at, app.now + app.skew)}: loaded in {b.load}s, wrote at {b.tps} tok/s{:else}Test failed: {b.error}{/if}
		</div>
	{/if}
{/snippet}

{#snippet card(m)}
	<article class="panel card" class:top={m.recommended}>
		<div class="row wrap">
			{#if m.recommended}<span class="chip on">#{m.rank} for this computer</span>{/if}
			<b class="name">{m.name}</b>
			<span class="faint">{m.maker}{m.released ? ' · ' + m.released : ''}</span>
			<span class="grow"></span>
			{#if m.installed}<span class="chip on">installed</span>{/if}
		</div>
		<p class="dim">{m.blurb}</p>
		<div class="row wrap chips">
			<span class="chip">{m.size} GB · {m.quant}</span>
			<span class="chip">{WHERE[m.where]}</span>
			<span class="chip" class:live={m.speed === 'fast'} class:bad={m.speed === 'very slow'}>{m.speed}</span>
			<span class="chip">best for {SUITS[m.suits]}</span>
			{#each m.good_at as g (g)}<span class="faint small">#{g.replace(/ /g, '-')}</span>{/each}
		</div>
		{@render progress(m.tag)}
		{@render benchLine(m.installed || m.tag)}
		<div class="row wrap actions">
			{#if m.installed}
				{@const users = usersOf(m.installed)}
				{#if users.length}<span class="dim small">used by {users.map((p) => '@' + p.handle).join(', ')}</span>{/if}
				<button onclick={() => tryIt(m.installed)} disabled={!!testing}>Try it</button>
				<select onchange={(e) => (assign(m.installed, e.target.value), (e.target.value = ''))}>
					<option value="">Give it to…</option>
					{#each app.personas.filter((p) => !users.includes(p)) as p (p.id)}<option value={p.id}>{p.name} (@{p.handle}, now {shortModel(p.model)})</option>{/each}
				</select>
			{:else if active(m.tag)}
				<span class="faint small">downloading…</span>
			{:else}
				<button class="solid" onclick={() => pull(m.tag)}>Download {m.size} GB</button>
			{/if}
			{#if m.builds.length > 1}
				<button class="quiet" onclick={() => (openBuilds[m.id] = !openBuilds[m.id])}>{openBuilds[m.id] ? '▾' : '▸'} other sizes</button>
			{/if}
		</div>
		{#if openBuilds[m.id]}
			<div class="builds">
				<p class="faint small">Bigger builds are more accurate and slower; smaller ones are quicker and make more mistakes.</p>
				{#each m.builds as b (b.tag)}
					<div class="row small build">
						<span class="q">{b.quant}</span>
						<span class="dim">{b.size} GB</span>
						<span class="faint grow">{b.where ? WHERE[b.where] : 'too big for this computer'}</span>
						{#if b.installed}<span class="chip on">installed</span>
						{:else if active(b.tag)}<span class="faint">downloading…</span>
						{:else if b.where}<button class="quiet" onclick={() => pull(b.tag)}>download</button>{/if}
					</div>
					{#if !b.installed}{@render progress(b.tag)}{/if}
				{/each}
			</div>
		{/if}
	</article>
{/snippet}

<div class="page">
	{#if err}<p class="bad">{err}</p>{/if}
	{#if !data}
		<p class="faint">Looking at this computer…</p>
	{:else}
		<section class="panel machine">
			<div class="label">this computer</div>
			<div class="row wrap">
				<span><b>{hw.gpu || 'no dedicated video card'}</b>{#if hw.vram} · {gb(hw.vram)} GB video memory{/if}</span>
				<span class="dim">{gb(hw.ram)} GB system memory</span>
				<span class="dim">{(hw.disk_free / GB).toFixed(0)} GB free where models are kept</span>
				<span class="faint">Ollama {hw.ollama || 'not running'}</span>
			</div>
			<p class="faint small">
				Models are stored in {hw.models_dir}. Downloads come from Ollama's library or from Hugging Face, through Ollama, and
				carry on where they left off if they are stopped.
			</p>
		</section>

		{#if !data.installed.some((m) => m.embedding)}
			<section class="panel machine">
				<div class="row wrap">
					<span class="grow">Omni keeps new ideas from repeating old ones with a small model, <b>embeddinggemma</b>. Without it, it can only compare words.</span>
					{#if !active('embeddinggemma')}<button class="solid" onclick={() => pull('embeddinggemma')}>Download 0.6 GB</button>{/if}
				</div>
				{@render progress('embeddinggemma')}
			</section>
		{/if}

		<h2 class="label">recommended</h2>
		{#each top as m (m.id)}{@render card(m)}{/each}

		<div class="row">
			<h2 class="label grow">also fits this computer</h2>
			<button class="quiet" onclick={() => (showAll = !showAll)}>{showAll ? 'show fewer' : 'show all ' + rest.length}</button>
		</div>
		{#each showAll ? rest : rest.slice(0, 4) as m (m.id)}{@render card(m)}{/each}

		<h2 class="label">installed</h2>
		<section class="panel">
			{#each data.installed as m (m.name)}
				<div class="row wrap inst">
					<span class="grow name2">{shortModel(m.name)}</span>
					<span class="faint small">{m.params} · {gb(m.size)} GB</span>
					{#if m.embedding}<span class="chip">for comparing ideas</span>
					{:else if m.used_by.length}<span class="chip on">{m.used_by.map((h) => '@' + h).join(', ')}</span>
					{:else}<span class="chip">not used</span>{/if}
					{#if data.loaded.includes(m.name)}<span class="chip live">in memory</span>{/if}
					{#if !m.embedding}<button class="quiet" onclick={() => tryIt(m.name)} disabled={!!testing}>try</button>{/if}
					{#if !app.is_remote && !m.embedding}<button class="quiet danger" onclick={() => remove(m)}>delete</button>{/if}
				</div>
				{@render benchLine(m.name)}
			{/each}
		</section>

		<h2 class="label">any other model</h2>
		<section class="panel machine">
			<div class="row">
				<input type="text" bind:value={custom} placeholder="an Ollama name (qwen3.5:9b) or hf.co/user/repo-GGUF:Q4_K_M" />
				<button disabled={!custom.trim()} onclick={() => (pull(custom.trim()), (custom = ''))}>Download</button>
			</div>
			{#each Object.values(app.downloads).filter((d) => !list.some((m) => m.builds.some((b) => b.tag === d.model))) as d (d.model)}
				<div class="small">{d.model}</div>
				{@render progress(d.model)}
			{/each}
		</section>
	{/if}
</div>

<style>
	.page {
		max-width: 56rem;
		margin: 0 auto;
		padding: 1.2rem 1.4rem 6rem;
		display: grid;
		gap: 0.9rem;
	}
	.machine {
		padding: 0.9rem 1rem;
		display: grid;
		gap: 0.5rem;
	}
	.machine p {
		margin: 0;
	}
	h2 {
		margin-top: 0.8rem;
	}
	.card {
		padding: 0.9rem 1rem;
		display: grid;
		gap: 0.55rem;
	}
	.card.top {
		border-color: var(--rule-hi);
	}
	.card p {
		margin: 0;
	}
	.name {
		font-size: 1.05rem;
	}
	.chips {
		gap: 0.4rem;
	}
	.small {
		font-size: 11.5px;
	}
	.actions select {
		width: auto;
		max-width: 22rem;
	}
	.dl {
		display: grid;
		gap: 0.25rem;
	}
	.bar {
		height: 5px;
		background: var(--rule);
	}
	.bar i {
		display: block;
		height: 100%;
		background: var(--live);
	}
	.builds {
		border-top: 1px solid var(--rule);
		padding-top: 0.6rem;
		display: grid;
		gap: 0.2rem;
	}
	.build .q {
		width: 9rem;
	}
	.inst {
		padding: 0.45rem 0.9rem;
		border-bottom: 1px solid var(--rule);
	}
	.inst:last-child {
		border-bottom: 0;
	}
	.name2 {
		overflow-wrap: anywhere;
	}
</style>
