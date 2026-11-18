<script>
	import { app, api, control, setSetting, loadState } from '../lib/store.svelte.js';
	import { since, gb, shortModel } from '../lib/util.js';

	const s = $derived(app.settings);
	const st = $derived(app.status);

	function num(key, min, max) {
		return (e) => {
			const v = Math.max(min, Math.min(max, Number(e.target.value)));
			if (!Number.isNaN(v)) setSetting({ [key]: v });
		};
	}

	async function forget() {
		if (!confirm('Unpair every phone and tablet? Each one will need a new code.')) return;
		await control('forget_devices');
		await loadState();
	}

	let hotkeyText = $state('');
	let hotkeyErr = $state('');
	$effect(() => {
		hotkeyText = s.hotkey || '';
	});
	async function saveHotkey() {
		hotkeyErr = '';
		try {
			await setSetting({ hotkey: hotkeyText.trim().toLowerCase() });
			setTimeout(() => loadState().catch(() => {}), 400);
		} catch (e) {
			hotkeyErr = e.message;
		}
	}

	async function preview() {
		await api('/api/saver', { action: 'show' });
	}

	async function unload() {
		await control('unload');
		setTimeout(() => loadState().catch(() => {}), 1500);
	}
</script>

<div class="page">
	<section class="panel block">
		<h2 class="label">when they work</h2>
		<div class="seg">
			{#each [['off', 'only when asked'], ['idle', 'when I am away'], ['always', 'always']] as [v, l] (v)}
				<button class:on={s.autonomy === v} onclick={() => setSetting({ autonomy: v })}>{l}</button>
			{/each}
		</div>
		<div class="grid">
			<label
				><span>Minutes of no keyboard or mouse before they start</span>
				<input type="number" min="1" max="240" value={s.idle_minutes} onchange={num('idle_minutes', 1, 240)} /></label
			>
			<label
				><span>Seconds of rest between jobs</span>
				<input type="number" min="5" max="3600" value={s.interval} onchange={num('interval', 5, 3600)} /></label
			>
			<label
				><span>Jobs in a row before the next persona takes over (each switch reloads a model from disk, about a minute)</span>
				<input type="number" min="1" max="20" value={s.batch} onchange={num('batch', 1, 20)} /></label
			>
		</div>
		<p class="faint small">
			Things you ask for run straight away, whatever this is set to, as long as there is memory for the model.
		</p>
		<div class="label">when you come back to the computer</div>
		<div class="seg">
			<button class:on={s.on_return !== 'stop'} onclick={() => setSetting({ on_return: 'finish' })}>let them finish the job</button>
			<button class:on={s.on_return === 'stop'} onclick={() => setSetting({ on_return: 'stop' })}>stop at once</button>
		</div>
		<p class="faint small">
			Either way their model is then unloaded so the video card is yours again, and they carry on once you have been away for
			{s.idle_minutes} minutes. “Stop at once” throws away the half-made job (a request of yours goes back in the queue).
		</p>
		<div class="row wrap">
			<span class="dim small">Step aside now (stop, unload, carry on once you are away):</span>
			<input class="hk" type="text" bind:value={hotkeyText} onkeydown={(e) => e.key === 'Enter' && saveHotkey()} />
			<button onclick={saveHotkey} disabled={hotkeyText.trim().toLowerCase() === (s.hotkey || '')}>Set</button>
			{#if app.hotkey.ok}<span class="chip on">works anywhere in Windows</span>
			{:else}<span class="chip bad">{app.hotkey.error || 'not active'}</span>{/if}
			<span class="bad small">{hotkeyErr}</span>
		</div>
	</section>

	<section class="panel block">
		<h2 class="label">what they make on their own</h2>
		<div class="seg">
			{#each [['any', 'anything'], ['web', 'only web projects'], ['python', 'only python']] as [v, l] (v)}
				<button class:on={(s.kinds || 'any') === v} onclick={() => setSetting({ kinds: v })}>{l}</button>
			{/each}
		</div>
		<p class="faint small">
			This covers new projects and the ones they choose to improve. Requests you make are built the way you ask; when you do
			not say, they follow this. Which maker starts new projects and which one edits is set on each persona.
		</p>
		<label class="check"
			><input type="checkbox" checked={s.deep_check !== false} onchange={(e) => setSetting({ deep_check: e.target.checked })} />
			<span>Before a web project is published, click every button, type into every field and press keys, and refuse it if
				something throws or nothing responds</span></label
		>
	</section>

	<section class="panel block">
		<h2 class="label">away screen</h2>
		<div class="seg">
			<button class:on={s.screensaver === 'on'} onclick={() => setSetting({ screensaver: 'on' })}>show what they are doing</button>
			<button class:on={s.screensaver !== 'on'} onclick={() => setSetting({ screensaver: 'off' })}>off</button>
		</div>
		<div class="grid">
			<label
				><span>Minutes of no keyboard or mouse before it appears</span>
				<input type="number" min="1" max="240" value={s.saver_minutes} onchange={num('saver_minutes', 1, 240)} /></label
			>
		</div>
		<p class="faint small">
			A full-screen view of the model writing, while they work and you are away. Any key or mouse movement closes it. It stays
			hidden while the computer is locked, while a full-screen game, video or presentation is up, and while an app keeps the
			display on. It does not stop the display from turning off.
		</p>
		<div class="row wrap">
			{#if !app.is_remote}<button onclick={preview}>Show it now</button>{/if}
			<a class="dim small" href="#/saver" target="_blank">open it in a tab</a>
			<span class="faint small"
				>{app.saver.state === 'showing' ? 'showing now' : app.saver.state === 'held back' ? 'held back: ' + app.saver.reason : app.saver.state}</span
			>
		</div>
	</section>

	<section class="panel block">
		<h2 class="label">memory</h2>
		<div class="grid">
			<label
				><span>System memory to keep free while a model runs (GB)</span>
				<input type="number" min="1" max="64" step="0.5" value={s.ram_reserve_gb} onchange={num('ram_reserve_gb', 1, 64)} /></label
			>
			<label
				><span>Extra video memory to allow beyond the model itself (GB)</span>
				<input type="number" min="0" max="8" step="0.5" value={s.vram_headroom_gb} onchange={num('vram_headroom_gb', 0, 8)} /></label
			>
		</div>
		<div class="row wrap small">
			<span class="dim">Right now: {gb(st.vram_free || 0)} of {gb(st.vram_total || 0)} GB video free, {gb(st.ram_free || 0)} of {gb(st.ram_total || 0)} GB system free.</span>
		</div>
		<div class="row wrap small">
			<span class="dim">In memory: {app.loaded.length ? app.loaded.map(shortModel).join(', ') : 'nothing'}</span>
			{#if app.loaded.length}<button onclick={unload}>Unload now</button>{/if}
		</div>
	</section>

	<section class="panel block">
		<h2 class="label">new ideas</h2>
		<div class="grid">
			<label
				><span>How alike a new idea may be to an existing project before it is turned down ({Math.round(s.similarity * 100)}%)</span>
				<input type="range" min="0.6" max="0.95" step="0.01" value={s.similarity} onchange={num('similarity', 0.6, 0.95)} />
				<span class="faint small">Lower is stricter. Things you ask for by name are never turned down.</span></label
			>
			<label
				><span>Most files a new project may have</span>
				<input type="number" min="1" max="12" value={s.max_files} onchange={num('max_files', 1, 12)} /></label
			>
		</div>
	</section>

	<section class="panel block">
		<h2 class="label">remote access</h2>
		{#if app.is_remote}
			<p class="dim">You are connected remotely. Pairing codes are only shown on the computer Omni runs on.</p>
		{:else if app.remote.enabled}
			<p class="dim">
				From a phone or another computer on your Tailscale network, open
				{#if app.remote.url}<b>{app.remote.url}</b>{:else}this machine's Tailscale address on port {app.remote.port - 1}{/if}
				and type this code. It works once and changes every 15 minutes.
			</p>
			<div class="code">{app.remote.code}</div>
			{#if app.remote.devices?.length}
				<div class="devices">
					{#each app.remote.devices as d (d.id)}
						<div class="row small"><span class="dim grow">{d.label || 'device'}</span><span class="faint">paired {since(d.created_at, app.now + app.skew)}</span></div>
					{/each}
				</div>
				<div><button class="danger" onclick={forget}>Unpair all devices</button></div>
			{:else}
				<p class="faint small">No devices are paired.</p>
			{/if}
		{:else}
			<p class="dim">Remote access is off.</p>
		{/if}
	</section>

	<section class="panel block">
		<h2 class="label">discord</h2>
		<p class="dim">
			{#if app.discord.state === 'connected'}
				Mirroring new projects, updates and your posts to {app.discord.channel} in {app.discord.guild}. {app.discord.sent || 0} sent.
				Discord is for watching; requests are made here.
			{:else if app.discord.state === 'off'}
				Not connected.
			{:else}
				{app.discord.state}: {app.discord.error}
			{/if}
		</p>
	</section>
</div>

<style>
	.page {
		max-width: 52rem;
		margin: 0 auto;
		padding: 1.2rem 1.4rem 6rem;
		display: grid;
		gap: 1rem;
	}
	.block {
		padding: 1rem;
		display: grid;
		gap: 0.8rem;
		justify-items: start;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
		gap: 0.9rem;
		width: 100%;
		align-items: end;
	}
	label {
		display: grid;
		gap: 0.3rem;
		font-size: 12.5px;
		color: var(--dim);
	}
	input[type='range'] {
		padding: 0;
		border: 0;
		accent-color: var(--fg);
		width: 100%;
	}
	p {
		margin: 0;
	}
	.small {
		font-size: 12px;
	}
	.code {
		font-size: 2rem;
		letter-spacing: 0.4em;
		border: 1px solid var(--rule-hi);
		padding: 0.3rem 0.6rem 0.3rem 1rem;
	}
	.check {
		display: flex;
		gap: 0.6rem;
		align-items: flex-start;
	}
	.check input {
		width: auto;
		margin-top: 0.3rem;
		accent-color: var(--fg);
	}
	.hk {
		width: 12rem;
	}
	.devices {
		width: 100%;
		display: grid;
		gap: 0.2rem;
	}
</style>
