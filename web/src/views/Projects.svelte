<script>
	import { app, personaById } from '../lib/store.svelte.js';
	import { ago, kindWord } from '../lib/util.js';
	import Avatar from '../components/Avatar.svelte';

	let q = $state('');
	let filter = $state('live');
	let who = $state(0);
	let sort = $state('recent');

	const broken = (p) => p.health && p.health.ok === false;
	const FILTERS = [
		['live', 'live'],
		['starred', 'starred'],
		['web', 'web'],
		['python', 'python'],
		['broken', 'has problems'],
		['draft', 'drafts'],
		['archived', 'archived']
	];
	const count = (f) => app.projects.filter((p) => match(p, f)).length;

	function match(p, f) {
		if (f === 'archived') return p.archived;
		if (p.archived) return false;
		if (f === 'draft') return p.status === 'draft';
		if (f === 'broken') return broken(p);
		if (f === 'starred') return p.starred;
		if (f === 'web') return p.kind !== 'python' && p.status === 'live';
		if (f === 'python') return p.kind === 'python' && p.status === 'live';
		return p.status === 'live';
	}

	const shown = $derived.by(() => {
		const needle = q.trim().toLowerCase();
		let list = app.projects.filter(
			(p) =>
				match(p, filter) &&
				(!who || p.persona_id === who) &&
				(!needle || (p.title + ' ' + p.description + ' ' + p.tags.join(' ')).toLowerCase().includes(needle))
		);
		if (sort === 'name') list = [...list].sort((a, b) => a.title.localeCompare(b.title));
		if (sort === 'revisions') list = [...list].sort((a, b) => b.rev_count - a.rev_count);
		return list;
	});
</script>

<div class="page">
	<div class="row wrap top">
		<input type="text" class="search" placeholder="search projects" bind:value={q} />
		<select bind:value={who} class="narrow">
			<option value={0}>everyone</option>
			{#each app.personas as p (p.id)}<option value={p.id}>@{p.handle}</option>{/each}
		</select>
		<select bind:value={sort} class="narrow">
			<option value="recent">recently changed</option>
			<option value="name">by name</option>
			<option value="revisions">most revised</option>
		</select>
	</div>
	<div class="row wrap filters">
		{#each FILTERS as [v, l] (v)}
			<button class="chip" class:on={filter === v} onclick={() => (filter = v)}>{l} {count(v)}</button>
		{/each}
	</div>

	<div class="grid">
		{#each shown as p (p.id)}
			<a class="card" href={'#/p/' + p.slug}>
				<div class="row head">
					<Avatar who={'@' + (personaById(p.persona_id)?.handle || '?')} size={22} />
					<span class="t grow">{p.title}</span>
					{#if p.starred}<span title="starred">★</span>{/if}
				</div>
				<p class="dim desc">{p.description}</p>
				<div class="row wrap meta">
					<span class="chip">{kindWord(p.kind)}</span>
					<span class="chip">r{p.rev_count}</span>
					{#if p.status === 'draft'}<span class="chip bad">draft</span>{:else if broken(p)}<span class="chip bad"
							>has problems</span
						>{/if}
					{#if p.direction}<span class="chip on" title={p.direction}>steered</span>{/if}
					<span class="grow"></span>
					<span class="faint">{ago(p.updated_at, app.now + app.skew)}</span>
				</div>
			</a>
		{:else}
			<p class="dim">Nothing matches.</p>
		{/each}
	</div>
</div>

<style>
	.page {
		padding: 1.2rem 1.4rem 5rem;
		max-width: 78rem;
		margin: 0 auto;
	}
	.top {
		gap: 0.6rem;
	}
	.search {
		flex: 1;
		min-width: 12rem;
	}
	.narrow {
		width: auto;
	}
	.filters {
		margin: 0.8rem 0 1.2rem;
		gap: 0.4rem;
	}
	.chip {
		background: transparent;
	}
	button.chip {
		cursor: pointer;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr));
		gap: 0.8rem;
	}
	.card {
		border: 1px solid var(--rule);
		background: var(--panel);
		padding: 0.8rem 0.9rem;
		display: grid;
		gap: 0.5rem;
		align-content: start;
	}
	.card:hover {
		border-color: var(--rule-hi);
		text-decoration: none;
		background: var(--panel-hi);
	}
	.t {
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.desc {
		margin: 0;
		font-size: 12px;
		line-height: 1.55;
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
		min-height: 3.1em;
	}
	.meta {
		gap: 0.35rem;
		font-size: 11px;
	}
</style>
