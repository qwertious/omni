<script>
	import { app, api, persona } from '../lib/store.svelte.js';
	import { ago, kindWord, mentionParts } from '../lib/util.js';
	import Avatar from './Avatar.svelte';
	import Preview from './Preview.svelte';

	let { e, inThread = false } = $props();
	const d = $derived(e.data || {});
	const who = $derived(e.author);
	const p = $derived(who === 'you' ? null : persona(who));
	const name = $derived(who === 'you' ? 'You' : p ? p.name : who);
	const when = $derived(ago(e.created_at, app.now + app.skew));
	const task = $derived(e.task);
	const working = $derived(task && app.status.job && app.status.job.task_id === task.id);
	const muted = $derived(['rejected', 'note', 'run'].includes(e.type));
	let open = $state(false);
	let showPreview = $state(false);
	let showLog = $state(false);

	const verb = $derived.by(() => {
		if (e.type === 'created') return 'made';
		if (e.type === 'revised') return d.manual ? 'restored a version of' : 'updated';
		if (e.type === 'draft') return 'drafted';
		if (e.type === 'rejected') return 'tried a change to';
		if (e.type === 'reply') return 'replied on';
		if (e.type === 'report') return 'reported a problem with';
		if (e.type === 'post') return 'asked for something';
		if (e.type === 'run') return 'ran';
		if (e.type === 'request') return who === 'you' ? 'asked on' : 'set a goal on';
		return 'noted';
	});

	async function cancel() {
		await api('/api/tasks/' + task.id + '/cancel', {});
	}
</script>

<article class="post" class:muted>
	<Avatar {who} size={inThread ? 26 : 34} />
	<div class="body">
		<header class="row wrap">
			<b>{name}</b>
			{#if p}<span class="faint">@{p.handle}</span>{/if}
			<span class="dim">{verb}</span>
			{#if e.slug && !inThread && e.type !== 'post'}
				<a class="title" href={'#/p/' + e.slug}>{e.title}</a>
			{/if}
			<span class="grow"></span>
			<span class="faint when">{when}</span>
		</header>

		{#if e.type === 'post' || e.type === 'reply' || e.type === 'request' || e.type === 'report'}
			<p class="say">
				{#each mentionParts(e.body) as part, i (i)}{#if part.startsWith('@') && persona(part)}<b>{part}</b
						>{:else}{part}{/if}{/each}
			</p>
			{#if e.type === 'report' && d.log?.length}
				<button class="quiet" onclick={() => (showLog = !showLog)}
					>{showLog ? '▾' : '▸'} {d.log.length} lines from the page{d.errors ? ', ' + d.errors + ' errors' : ''}</button
				>
				{#if showLog}<pre class="out">{d.log.join('\n')}</pre>{/if}
			{/if}
			{#if task}
				<div class="row wrap">
					{#if working}
						<span class="chip live"><span class="dot live"></span> @{app.status.job.persona} is on it</span>
					{:else if task.status === 'queued'}
						<span class="chip">queued{d.persona ? ' for @' + d.persona : ''}</span>
						<button class="quiet" onclick={cancel}>cancel</button>
					{:else if task.status === 'running'}
						<span class="chip live">working</span>
					{:else if task.status === 'done'}
						<span class="chip on">done</span>
						{#if e.type === 'post' && task.result}<a href={'#/p/' + task.result}>open the project →</a>{/if}
					{:else if task.status === 'rejected'}
						<span class="chip bad">failed its checks; nothing was replaced</span>
					{:else if task.status === 'cancelled'}
						<span class="chip">cancelled</span>
					{:else}
						<span class="chip bad">did not finish</span>
						<span class="dim small">{task.result}</span>
					{/if}
				</div>
			{/if}
		{:else if e.type === 'created'}
			<p>{e.body}</p>
			{#if d.request}<p class="quote dim">You asked: {d.request}</p>{/if}
			{#if !inThread}
				{#if e.kind === 'html'}
					{#if showPreview}
						<Preview slug={e.slug} height="320px" interactive={false} />
					{:else}
						<button class="peek" onclick={() => (showPreview = true)}>▸ show it running</button>
					{/if}
				{:else if d.output}
					<pre class="out">{d.output}</pre>
				{/if}
			{/if}
			<div class="row wrap chips">
				<span class="chip">{kindWord(e.kind)}</span>
				{#if d.files}<span class="chip">{d.files.length} {d.files.length === 1 ? 'file' : 'files'}</span>{/if}
				{#if e.slug && !inThread}<a class="dim" href={'#/p/' + e.slug}>open →</a>{/if}
			</div>
		{:else if e.type === 'revised'}
			<p>{e.body}</p>
			{#if d.request && d.requester === 'you'}
				<p class="quote dim">You asked: {d.request}</p>
			{:else if d.request}
				<p class="quote faint">Own goal: {d.request}</p>
			{/if}
			<div class="row wrap chips">
				{#if d.seq}<span class="chip">r{d.seq}</span>{/if}
				{#if d.adds !== undefined}<span class="chip">+{d.adds} −{d.dels}</span>{/if}
				{#each (d.files || []).slice(0, 4) as f (f)}<span class="chip">{f}</span>{/each}
			</div>
		{:else if e.type === 'rejected' || e.type === 'draft'}
			<p>
				{#if e.type === 'rejected'}
					The change did not pass its checks, so the working version was kept.
				{:else}
					{e.body}
				{/if}
			</p>
			{#if d.problems && d.problems.length}
				<button class="quiet" onclick={() => (open = !open)}
					>{open ? '▾' : '▸'} {d.problems.length} {d.problems.length === 1 ? 'problem' : 'problems'} found</button
				>
				{#if open}
					{#if e.type === 'rejected'}<p class="dim small">Intended change: {e.body}</p>{/if}
					<ul class="problems">
						{#each d.problems as pr, i (i)}<li>{pr}</li>{/each}
					</ul>
				{/if}
			{/if}
		{:else if e.type === 'run'}
			<span class="chip" class:bad={d.exit_code !== 0}>{e.body}</span>
		{:else}
			<p>{e.body}</p>
		{/if}
	</div>
</article>

<style>
	.post {
		display: flex;
		gap: 0.8rem;
		padding: 1rem 0;
		border-bottom: 1px solid var(--rule);
	}
	.body {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 0.45rem;
	}
	header {
		gap: 0.45rem;
		line-height: 1.5;
	}
	.title {
		font-weight: 600;
	}
	.when {
		font-size: 11.5px;
	}
	p {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.say {
		white-space: pre-wrap;
	}
	.quote {
		border-left: 1px solid var(--rule-hi);
		padding-left: 0.7rem;
		font-size: 12.5px;
		white-space: pre-wrap;
	}
	.muted {
		color: var(--dim);
	}
	.muted b {
		font-weight: 500;
	}
	.small {
		font-size: 12px;
	}
	.chips {
		gap: 0.4rem;
	}
	.chip {
		white-space: normal;
	}
	.out {
		border: 1px solid var(--rule);
		background: var(--panel);
		padding: 0.6rem 0.8rem;
		font-size: 11.5px;
		line-height: 1.45;
		max-height: 13rem;
		overflow: hidden;
		color: var(--dim);
	}
	.peek {
		text-align: left;
		border: 1px dashed var(--rule-hi);
		color: var(--dim);
		padding: 0.7rem 0.9rem;
	}
	.problems {
		margin: 0;
		padding-left: 1.1rem;
		font-size: 12px;
		color: var(--dim);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	button.quiet {
		justify-self: start;
		padding-left: 0;
	}
</style>
