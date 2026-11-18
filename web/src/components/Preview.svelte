<script>
	import { addProbe, projectBase } from '../lib/store.svelte.js';
	// A web project, shown in a frame that cannot reach Omni: the server sends every project
	// page with a sandbox policy, and the frame repeats it. A project that throws only breaks itself.
	let { slug, pages = ['index.html'], rev = null, version = 0, height = '62vh', interactive = true } = $props();
	let page = $state('index.html');
	let nonce = $state(0);
	let frame = $state(null);

	// The page reports errors, console output and clicks through postMessage. Only messages
	// from this frame count.
	$effect(() => {
		const onMsg = (e) => {
			if (!frame || e.source !== frame.contentWindow) return;
			const d = e.data;
			if (!d || d.__omni !== 'probe') return;
			addProbe(slug, { kind: String(d.kind), level: String(d.level || ''), text: String(d.text).slice(0, 600), page: String(d.page || ''), t: Number(d.t) || Date.now() });
		};
		window.addEventListener('message', onMsg);
		return () => window.removeEventListener('message', onMsg);
	});

	$effect(() => {
		if (!pages.includes(page)) page = pages.includes('index.html') ? 'index.html' : pages[0];
	});

	const src = $derived(
		projectBase(slug) + (page === 'index.html' ? '' : page) + '?' + (rev ? 'rev=' + rev + '&' : '') + 'v=' + version + '.' + nonce
	);
</script>

<div class="frame">
	{#if interactive}
		<div class="row bar">
			{#if pages.length > 1}
				<div class="seg">
					{#each pages as pg (pg)}
						<button class:on={pg === page} onclick={() => (page = pg)}>{pg}</button>
					{/each}
				</div>
			{:else}
				<span class="label">{page}</span>
			{/if}
			<span class="grow"></span>
			<button class="quiet" onclick={() => nonce++} title="Reload the page">reload</button>
			<a class="dim" href={src} target="_blank" rel="noopener">open ↗</a>
		</div>
	{/if}
	<iframe
		bind:this={frame}
		title="project preview"
		{src}
		style="height:{height}"
		loading="lazy"
		class:still={!interactive}
		sandbox="allow-scripts allow-pointer-lock allow-modals allow-forms allow-popups"
	></iframe>
</div>

<style>
	.frame {
		border: 1px solid var(--rule);
		background: var(--panel);
	}
	.bar {
		padding: 0.35rem 0.6rem;
		border-bottom: 1px solid var(--rule);
		font-size: 12px;
		overflow-x: auto;
	}
	iframe {
		display: block;
		width: 100%;
		border: 0;
		background: #fff;
	}
	iframe.still {
		pointer-events: none;
	}
</style>
