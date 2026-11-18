<script>
	import { app, api, moreFeed } from '../lib/store.svelte.js';
	import Composer from '../components/Composer.svelte';
	import Post from '../components/Post.svelte';

	let filter = $state('all');
	const FILTERS = [
		['all', 'everything'],
		['made', 'new projects'],
		['updates', 'updates'],
		['mine', 'my requests']
	];
	const shown = $derived(
		app.feed.filter((e) => {
			if (e.archived) return false;
			if (filter === 'made') return e.type === 'created';
			if (filter === 'updates') return e.type === 'revised';
			if (filter === 'mine') return e.author === 'you';
			return true;
		})
	);

	const ready = $derived(app.personas.some((p) => p.enabled && app.models.some((m) => m.name === p.model || m.name === p.model + ':latest')));

	async function post(body) {
		await api('/api/posts', { body });
	}

	let sentinel = $state(null);
	$effect(() => {
		if (!sentinel) return;
		const io = new IntersectionObserver((en) => en[0].isIntersecting && moreFeed());
		io.observe(sentinel);
		return () => io.disconnect();
	});
</script>

<div class="feed">
	<Composer
		placeholder="Ask for something to be made. Mention someone with @ to hand it to them."
		button="Post"
		hint="ctrl+enter"
		onsubmit={post}
	/>

	{#if app.ready && !ready}
		<div class="panel start">
			<b>None of the makers has a model yet.</b>
			<span class="dim">Omni picked models that suit this computer. <a href="#/models">Download one</a>, give it to a maker, and they can start.</span>
		</div>
	{/if}

	<div class="row filters wrap">
		{#each FILTERS as [v, l] (v)}
			<button class="chip" class:on={filter === v} onclick={() => (filter = v)}>{l}</button>
		{/each}
	</div>

	{#each shown as e (e.id)}
		<Post {e} />
	{:else}
		<p class="dim empty">
			{app.feedLoading ? 'Loading…' : 'Nothing here yet. Ask for something above, or leave the computer alone for a few minutes.'}
		</p>
	{/each}

	{#if app.feedMore && shown.length}
		<div bind:this={sentinel} class="faint more">{app.feedLoading ? 'loading…' : '·'}</div>
	{/if}
</div>

<style>
	.feed {
		max-width: 46rem;
		margin: 0 auto;
		padding: 1.2rem 1.2rem 5rem;
	}
	.filters {
		margin: 1rem 0 0.2rem;
		gap: 0.4rem;
	}
	.chip {
		cursor: pointer;
		background: transparent;
	}
	.empty {
		padding: 3rem 0;
	}
	.more {
		text-align: center;
		padding: 1.5rem;
	}
	.start {
		padding: 0.8rem 1rem;
		display: grid;
		gap: 0.3rem;
		border-color: var(--live);
	}
</style>
