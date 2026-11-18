<script>
	import { app, api, loadState } from '../lib/store.svelte.js';
	import { gb, shortModel } from '../lib/util.js';
	import Avatar from '../components/Avatar.svelte';

	let drafts = $state({}); // id -> edited copy
	let saving = $state(null);
	let msg = $state({});

	const blank = () => ({ handle: '', name: '', model: app.models[0]?.name || '', bio: '', interestsText: '', temperature: 0.8, num_ctx: 16384, enabled: true, roles: 'both' });
	const ROLES = [
		['both', 'new projects and edits'],
		['create', 'only new projects'],
		['edit', 'only edits and fixes'],
		['asked', 'only when asked by @name']
	];
	const roleWord = (r) => (ROLES.find((x) => x[0] === r) || ROLES[0])[1];
	let fresh = $state(null);

	function edit(p) {
		drafts[p.id] = { ...p, interestsText: p.interests.join('\n') };
	}

	function fit(model) {
		const m = app.models.find((x) => x.name === model);
		if (!m || !m.size) return '';
		const total = app.status.vram_total || 0;
		if (!total) return gb(m.size) + ' GB';
		return gb(m.size) + ' GB · ' + (m.size * 1.08 < total ? 'fits on the video card' : 'larger than the video card, so it will be slow');
	}

	function count(p) {
		return app.projects.filter((x) => x.persona_id === p.id && !x.archived).length;
	}

	async function save(d, id) {
		saving = id ?? 'new';
		try {
			const body = { ...d, interests: d.interestsText.split('\n').map((s) => s.trim()).filter(Boolean) };
			delete body.interestsText;
			await api(id ? '/api/personas/' + id : '/api/personas', body);
			await loadState();
			if (id) delete drafts[id];
			else fresh = null;
			msg = {};
		} catch (e) {
			msg = { [id ?? 'new']: e.message };
		} finally {
			saving = null;
		}
	}

	async function toggle(p) {
		await api('/api/personas/' + p.id, { enabled: !p.enabled });
		await loadState();
	}
</script>

{#snippet form(d, id)}
	<div class="form">
		<label><span class="label">name</span><input type="text" bind:value={d.name} /></label>
		<label><span class="label">handle</span><input type="text" bind:value={d.handle} placeholder="letters and digits, used as @handle" /></label>
		<label class="wide"
			><span class="label">model</span>
			<select bind:value={d.model}>
				{#each app.models as m (m.name)}<option value={m.name}>{shortModel(m.name)}{m.params ? ' · ' + m.params : ''}</option>{/each}
				{#if d.model && !app.models.some((m) => m.name === d.model)}<option value={d.model}>{d.model} (not installed)</option>{/if}
			</select>
			<span class="faint small">{fit(d.model)}</span>
		</label>
		<label class="wide"><span class="label">who they are</span><textarea rows="3" bind:value={d.bio}></textarea></label>
		<label class="wide"
			><span class="label">interests, one per line</span><textarea rows="5" bind:value={d.interestsText}></textarea></label
		>
		<label
			><span class="label">boldness {Number(d.temperature).toFixed(2)}</span>
			<input type="range" min="0.2" max="1.3" step="0.05" bind:value={d.temperature} /></label
		>
		<label class="wide"
			><span class="label">on their own, they make</span>
			<select bind:value={d.roles}>
				{#each ROLES as [v, l] (v)}<option value={v}>{l}</option>{/each}
			</select>
			<span class="faint small">Requests you make go to whoever you mention; without a mention, to a maker who does that kind of work.</span></label
		>
		<label
			><span class="label">working memory</span>
			<select bind:value={d.num_ctx}>
				{#each [8192, 16384, 24576, 32768, 49152, 65536] as n (n)}<option value={n}>{n / 1024}k tokens</option>{/each}
			</select></label
		>
		<div class="row wide">
			<span class="bad small grow">{msg[id ?? 'new'] || ''}</span>
			<button onclick={() => (id ? delete drafts[id] : (fresh = null))}>Cancel</button>
			<button class="solid" disabled={saving !== null || !d.handle || !d.model} onclick={() => save(d, id)}>Save</button>
		</div>
	</div>
{/snippet}

<div class="page">
	<p class="dim intro">
		Each persona is a maker with its own model, taste and voice. Mention one with @ in a post or reply to hand it the work.
		Only one model fits in video memory at a time, so they take turns. New models are on the <a href="#/models">models</a> page.
	</p>
	{#each app.personas as p (p.id)}
		<section class="panel card" class:off={!p.enabled}>
			<div class="row wrap">
				<Avatar who={'@' + p.handle} size={40} />
				<div class="grow">
					<div class="t">{p.name} <span class="faint">@{p.handle}</span></div>
					<div class="dim small">{shortModel(p.model)} · {count(p)} projects · {p.num_ctx / 1024}k memory · {roleWord(p.roles)}</div>
				</div>
				{#if app.status.job?.persona === p.handle}<span class="chip live"><span class="dot live"></span> working</span>{/if}
				{#if app.loaded.some((m) => m === p.model || m === p.model + ':latest')}<span class="chip on">in memory</span>{/if}
				<button onclick={() => toggle(p)}>{p.enabled ? 'on' : 'off'}</button>
				{#if !drafts[p.id]}<button onclick={() => edit(p)}>Edit</button>{/if}
			</div>
			{#if drafts[p.id]}
				{@render form(drafts[p.id], p.id)}
			{:else}
				<p class="dim bio">{p.bio}</p>
				<div class="row wrap">
					{#each p.interests as i (i)}<span class="chip">{i}</span>{/each}
				</div>
			{/if}
		</section>
	{/each}

	{#if fresh}
		<section class="panel card">
			<div class="t">New persona</div>
			{@render form(fresh, null)}
		</section>
	{:else}
		<button class="add" onclick={() => (fresh = blank())}>+ add a persona</button>
	{/if}
</div>

<style>
	.page {
		max-width: 52rem;
		margin: 0 auto;
		padding: 1.2rem 1.4rem 6rem;
		display: grid;
		gap: 1rem;
	}
	.intro {
		margin: 0;
	}
	.card {
		padding: 1rem;
		display: grid;
		gap: 0.8rem;
	}
	.card.off {
		opacity: 0.55;
	}
	.t {
		font-weight: 600;
		font-size: 1.05rem;
	}
	.small {
		font-size: 11.5px;
	}
	.bio {
		margin: 0;
	}
	.chip {
		white-space: normal;
	}
	.form {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.8rem;
		border-top: 1px solid var(--rule);
		padding-top: 0.9rem;
	}
	label {
		display: grid;
		gap: 0.25rem;
	}
	.wide {
		grid-column: 1 / -1;
	}
	input[type='range'] {
		padding: 0;
		border: 0;
		accent-color: var(--fg);
	}
	.add {
		border-style: dashed;
		padding: 0.9rem;
		color: var(--dim);
	}
	@media (max-width: 600px) {
		.form {
			grid-template-columns: 1fr;
		}
	}
</style>
