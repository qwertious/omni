<script>
	import { app, control, setSetting, persona } from '../lib/store.svelte.js';
	import { clock, gb, shortModel } from '../lib/util.js';
	import Avatar from './Avatar.svelte';

	let { compact = false } = $props();
	const s = $derived(app.status);
	const job = $derived(s.job);
	const gate = $derived(s.gate || { state: 'starting', reason: '' });
	const nowS = $derived(app.now + app.skew);
	let tick = $state(0);
	$effect(() => {
		const t = setInterval(() => tick++, 1000);
		return () => clearInterval(t);
	});
	const elapsed = $derived((tick, job ? Date.now() / 1000 + app.skew - job.started_at : 0));
	const headline = $derived.by(() => {
		if (job) return '@' + job.persona + ' is ' + (job.what === 'revision' ? 'working on' : 'making') + ' ' + (job.title || 'something new');
		if (s.held) return 'Stopped';
		if (s.aside) return 'Stepped aside';
		if (gate.state === 'off') return 'Autonomy is off';
		if (gate.state === 'waiting') return 'Waiting';
		if (gate.state === 'resting') return 'Between jobs';
		return 'Idle';
	});
	const vramUsed = $derived(s.vram_total ? 1 - s.vram_free / s.vram_total : 0);
	const ramUsed = $derived(s.ram_total ? 1 - s.ram_free / s.ram_total : 0);
	const tail = $derived(job ? app.tokens.split('\n').slice(-5).join('\n') : '');
	const ours = $derived(app.loaded.some((m) => app.personas.some((p) => p.model === m || p.model + ':latest' === m)));
</script>

<section class="status" class:compact>
	<div class="row head">
		<span class="dot" class:live={!!job} class:bad={!app.online}></span>
		<span class="label">{app.online ? 'now' : 'offline'}</span>
		<span class="grow"></span>
		{#if s.queued}<span class="chip on">{s.queued} queued</span>{/if}
	</div>

	<div class="what">
		{#if job}
			<div class="row">
				<Avatar who={'@' + job.persona} size={26} />
				<div class="grow">
					<div class="t">
						{#if job.slug}<a href={'#/p/' + job.slug}>{headline}</a>{:else}{headline}{/if}
					</div>
				</div>
			</div>
			<div class="phase dim">
				{job.phase}{#if job.chars}
					· {job.chars.toLocaleString()} chars{/if}{#if job.tps}
					· {job.tps} tok/s{/if}
			</div>
			<div class="faint small">{clock(elapsed)} elapsed · {shortModel(job.model || persona(job.persona)?.model)}</div>
			{#if tail.trim() && !compact}<pre class="tail">{tail}</pre>{/if}
		{:else}
			<div class="t">{headline}</div>
			{#if gate.reason && gate.state !== 'off'}<div class="phase dim">{gate.reason}</div>{/if}
		{/if}
	</div>

	<div class="row controls wrap">
		{#if s.held}
			<button class="solid" onclick={() => control('resume')}>Resume</button>
		{:else if s.aside}
			<button onclick={() => control('resume')} title="Carry on now instead of waiting until you are away">Carry on now</button>
		{:else if job}
			<button onclick={() => control('step_aside')} title="Stop, free the video card, and carry on once you are away again{app.hotkey.ok ? ' (' + app.hotkey.keys + ')' : ''}">Step aside</button>
			<button class="danger" onclick={() => control('stop')} title="Stop until you press Resume">Stop</button>
		{:else}
			{#if ours}<button onclick={() => control('step_aside')} title="Unload their model now and carry on once you are away again">Step aside</button>{/if}
			<button onclick={() => control('run_now')} title="Start one job now, without waiting for the computer to be idle"
				>Make something now</button
			>
		{/if}
	</div>

	{#if !compact}
		<hr class="rule" />
		<div class="block">
			<div class="label">autonomy</div>
			<div class="seg">
				{#each [['off', 'off'], ['idle', 'when idle'], ['always', 'always']] as [v, l] (v)}
					<button class:on={app.settings.autonomy === v} onclick={() => setSetting({ autonomy: v })}>{l}</button>
				{/each}
			</div>
			<div class="faint small">
				{#if app.settings.autonomy === 'idle'}
					Works after {app.settings.idle_minutes} min without keyboard or mouse. You have been away {clock(s.idle || 0)}.
				{:else if app.settings.autonomy === 'always'}
					Works whenever there is enough free memory.
				{:else}
					Only works on what you ask for.
				{/if}
			</div>
		</div>
		<hr class="rule" />
		<div class="block">
			<div class="label">memory</div>
			<div class="meter">
				<span>video</span>
				<div class="bar"><i style="width:{vramUsed * 100}%"></i></div>
				<span class="dim">{gb(s.vram_free || 0)} GB free</span>
			</div>
			<div class="meter">
				<span>system</span>
				<div class="bar"><i style="width:{ramUsed * 100}%"></i></div>
				<span class="dim">{gb(s.ram_free || 0)} GB free</span>
			</div>
			{#if app.loaded.length}
				<div class="faint small">in memory: {app.loaded.map(shortModel).join(', ')}</div>
			{/if}
		</div>
		{#if app.logs.length}
			<hr class="rule" />
			<div class="block">
				<div class="label">notes</div>
				{#each app.logs.slice(0, 6) as l, i (i)}
					<div class="small dim log"><span class="faint">@{l.persona}</span> {l.body}</div>
				{/each}
			</div>
		{/if}
	{/if}
</section>

<style>
	.status {
		display: grid;
		gap: 0.8rem;
	}
	.head {
		gap: 0.5rem;
	}
	.what {
		display: grid;
		gap: 0.3rem;
	}
	.t {
		font-weight: 600;
		line-height: 1.4;
	}
	.phase {
		font-size: 12px;
	}
	.small {
		font-size: 11.5px;
		line-height: 1.5;
	}
	.block {
		display: grid;
		gap: 0.45rem;
	}
	.meter {
		display: grid;
		grid-template-columns: 3.6rem 1fr auto;
		align-items: center;
		gap: 0.6rem;
		font-size: 11.5px;
	}
	.bar {
		height: 5px;
		background: var(--rule);
	}
	.bar i {
		display: block;
		height: 100%;
		background: var(--fg);
	}
	.tail {
		font-size: 10.5px;
		line-height: 1.45;
		color: var(--faint);
		border-left: 1px solid var(--live);
		padding-left: 0.5rem;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		max-height: 6.5rem;
		overflow: hidden;
		margin-top: 0.2rem;
	}
	.log {
		border-left: 1px solid var(--rule-hi);
		padding-left: 0.5rem;
	}
	.compact .controls button {
		padding: 0.2rem 0.6rem;
	}
</style>
