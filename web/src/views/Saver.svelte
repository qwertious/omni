<script>
	// The away screen. Omni opens this full screen while the makers work and nobody is at the
	// computer, and closes it on the first key press or mouse movement. Everything is drawn in
	// characters: block letters, bars, a sparkline and the model's own output as it is written.
	import { app, persona } from '../lib/store.svelte.js';
	import { highlight, shortModel, ago } from '../lib/util.js';

	const FONT = {
		A: ['01110', '10001', '11111', '10001', '10001'], B: ['11110', '10001', '11110', '10001', '11110'],
		C: ['01111', '10000', '10000', '10000', '01111'], D: ['11110', '10001', '10001', '10001', '11110'],
		E: ['11111', '10000', '11110', '10000', '11111'], F: ['11111', '10000', '11110', '10000', '10000'],
		G: ['01111', '10000', '10011', '10001', '01111'], H: ['10001', '10001', '11111', '10001', '10001'],
		I: ['11111', '00100', '00100', '00100', '11111'], J: ['00111', '00001', '00001', '10001', '01110'],
		K: ['10001', '10010', '11100', '10010', '10001'], L: ['10000', '10000', '10000', '10000', '11111'],
		M: ['10001', '11011', '10101', '10001', '10001'], N: ['10001', '11001', '10101', '10011', '10001'],
		O: ['01110', '10001', '10001', '10001', '01110'], P: ['11110', '10001', '11110', '10000', '10000'],
		Q: ['01110', '10001', '10101', '10010', '01101'], R: ['11110', '10001', '11110', '10010', '10001'],
		S: ['01111', '10000', '01110', '00001', '11110'], T: ['11111', '00100', '00100', '00100', '00100'],
		U: ['10001', '10001', '10001', '10001', '01110'], V: ['10001', '10001', '10001', '01010', '00100'],
		W: ['10001', '10001', '10101', '11011', '10001'], X: ['10001', '01010', '00100', '01010', '10001'],
		Y: ['10001', '01010', '00100', '00100', '00100'], Z: ['11111', '00010', '00100', '01000', '11111'],
		0: ['01110', '10011', '10101', '11001', '01110'], 1: ['00100', '01100', '00100', '00100', '01110'],
		2: ['11110', '00001', '01110', '10000', '11111'], 3: ['11110', '00001', '00110', '00001', '11110'],
		4: ['10010', '10010', '11111', '00010', '00010'], 5: ['11111', '10000', '11110', '00001', '11110'],
		6: ['01110', '10000', '11110', '10001', '01110'], 7: ['11111', '00001', '00010', '00100', '00100'],
		8: ['01110', '10001', '01110', '10001', '01110'], 9: ['01110', '10001', '01111', '00001', '01110'],
		'@': ['01110', '10111', '10101', '10110', '01111'], ':': ['0', '1', '0', '1', '0'],
		'-': ['000', '000', '111', '000', '000'], '.': ['0', '0', '0', '0', '1'], ' ': ['00', '00', '00', '00', '00'],
		_: ['000', '000', '000', '000', '111']
	};

	function big(text) {
		const rows = ['', '', '', '', ''];
		for (const ch of String(text).toUpperCase().slice(0, 12)) {
			const g = FONT[ch] || FONT[' '];
			for (let r = 0; r < 5; r++) rows[r] += g[r].replace(/1/g, '█').replace(/0/g, ' ') + ' ';
		}
		return rows.join('\n');
	}

	const BLOCKS = '▁▂▃▄▅▆▇█';
	function spark(values) {
		const max = Math.max(1, ...values);
		return values.map((v) => (v <= 0 ? ' ' : BLOCKS[Math.min(7, Math.floor((v / max) * 7.99))])).join('');
	}
	function bar(frac, width) {
		const n = Math.round(Math.max(0, Math.min(1, frac)) * width);
		return '█'.repeat(n) + '░'.repeat(width - n);
	}
	function hms(sec) {
		const s = Math.max(0, Math.floor(sec));
		return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((x) => String(x).padStart(2, '0')).join(':');
	}

	const st = $derived(app.status);
	const job = $derived(st.job);
	const who = $derived(job ? persona(job.persona) : null);

	let now = $state(Date.now());
	let tps = $state([]);
	let shown = $state('');
	let canvas = $state(null);
	let drift = $state({ x: 0, y: 0 });

	// Ease the visible text towards what the model has written, so it reads like typing.
	$effect(() => {
		let raf;
		const step = () => {
			const target = app.tokens;
			if (!target.startsWith(shown.slice(0, Math.min(shown.length, 200))) || target.length < shown.length - 200) shown = '';
			if (shown.length < target.length) {
				const behind = target.length - shown.length;
				const add = Math.max(1, Math.ceil(behind / 18));
				shown = target.slice(0, shown.length + add);
			} else if (shown.length > target.length) {
				shown = target;
			}
			raf = requestAnimationFrame(step);
		};
		raf = requestAnimationFrame(step);
		return () => cancelAnimationFrame(raf);
	});

	$effect(() => {
		const t = setInterval(() => {
			now = Date.now();
			const v = app.status.job ? app.status.job.tps || 0 : 0;
			tps = [...tps.slice(-47), v];
			const k = now / 60000;
			drift = { x: Math.round(Math.sin(k) * 10), y: Math.round(Math.cos(k * 0.7) * 8) };
		}, 1000);
		return () => clearInterval(t);
	});

	// Background: sparse columns of falling characters, mostly grey, now and then cyan.
	$effect(() => {
		if (!canvas) return;
		const ctx = canvas.getContext('2d');
		const glyphs = '01<>{}[]()=+-*/;:.#$%&@abcdefghijklmnopqrstuvwxyz';
		let cols = [];
		let cell = 16;
		let raf;
		let last = 0;
		const resize = () => {
			canvas.width = innerWidth;
			canvas.height = innerHeight;
			cols = Array.from({ length: Math.ceil(innerWidth / cell) }, () => ({ y: Math.random() * -60, v: 0.15 + Math.random() * 0.5, on: Math.random() < 0.22 }));
			ctx.font = '13px ' + getComputedStyle(document.body).fontFamily;
		};
		resize();
		addEventListener('resize', resize);
		const draw = (t) => {
			raf = requestAnimationFrame(draw);
			if (t - last < 50) return;
			last = t;
			ctx.fillStyle = 'rgba(0,0,0,0.16)';
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			const busy = !!app.status.job;
			for (let i = 0; i < cols.length; i++) {
				const c = cols[i];
				if (!c.on) {
					if (Math.random() < 0.0008) c.on = true;
					continue;
				}
				const ch = glyphs[(Math.random() * glyphs.length) | 0];
				ctx.fillStyle = busy && Math.random() < 0.03 ? '#29e6ff' : Math.random() < 0.1 ? '#5a5a5a' : '#262626';
				ctx.fillText(ch, i * cell, c.y * cell);
				c.y += c.v * (busy ? 1 : 0.4);
				if (c.y * cell > canvas.height + 40) {
					c.y = Math.random() * -30;
					c.on = Math.random() < 0.5;
				}
			}
		};
		raf = requestAnimationFrame(draw);
		return () => {
			cancelAnimationFrame(raf);
			removeEventListener('resize', resize);
		};
	});

	const lines = $derived.by(() => {
		const all = shown.split('\n').filter((l) => !/^\s*={2,}\s*(END|FILE|DELETE)\b/.test(l));
		return all.slice(-30);
	});
	const lang = $derived.by(() => {
		const f = job?.plan?.[job.file_i];
		return f || (job?.kind === 'python' ? 'x.py' : 'x.html');
	});
	const code = $derived(highlight(lang, lines.join('\n')));
	const vramFrac = $derived(st.vram_total ? 1 - st.vram_free / st.vram_total : 0);
	const ramFrac = $derived(st.ram_total ? 1 - st.ram_free / st.ram_total : 0);
	const recent = $derived(app.feed.filter((e) => e.type === 'created' || e.type === 'revised').slice(0, 5));
	const clockText = $derived(new Date(now).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }));
	const nextIn = $derived(st.next_auto_at ? st.next_auto_at - (now / 1000 + app.skew) : 0);
	const elapsed = $derived(job ? now / 1000 + app.skew - job.started_at : 0);
	const fileFrac = $derived(job && job.plan?.length && job.file_i >= 0 ? Math.min(1, job.file_i / job.plan.length) : 0);
</script>

<svelte:head><title>Omni · away</title></svelte:head>

<div class="saver">
	<canvas bind:this={canvas}></canvas>
	<div class="frame" style="transform: translate({drift.x}px, {drift.y}px)">
		<header class="row">
			<span class="brand">OMNI</span>
			<span class="faint">░░ away mode ░░</span>
			<span class="grow"></span>
			<span class="dim">{new Date(now).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}</span>
			<span>{new Date(now).toLocaleTimeString(undefined, { hour12: false })}</span>
		</header>

		{#if job}
			<section class="who">
				<pre class="big" class:live={true}>{big('@' + (job.persona || 'omni'))}</pre>
				<div class="whoText">
					<div class="label">{who ? who.name : 'omni'} · {shortModel(job.model)}</div>
					<div class="title">
						{job.what === 'revision' ? 'improving' : job.what === 'model test' ? 'testing' : 'making'}
						<b>{job.title || 'a new idea'}</b>
					</div>
					<div class="dim">&gt; {job.phase}<span class="cursor">▌</span></div>
				</div>
			</section>

			<section class="cols">
				<div class="box plan">
					<div class="label">┤ files ├</div>
					{#if job.plan?.length}
						{#each job.plan as f, i (f)}
							<div class:dim={i > job.file_i} class:live={i === job.file_i}>
								{job.what === 'revision' ? '[·]' : i < job.file_i ? '[✓]' : i === job.file_i ? '[>]' : '[ ]'}
								{f}
							</div>
						{/each}
						{#if job.what !== 'revision'}
							<div class="faint gap">{bar(fileFrac, 22)} {Math.round(fileFrac * 100)}%</div>
						{/if}
					{:else}
						<div class="faint">still deciding what to build…</div>
					{/if}
					<div class="label gap">┤ pace ├</div>
					<div class="spark live">{spark(tps)}</div>
					<div class="row"><span class="dim">tokens/s</span><span class="grow"></span><b>{job.tps || 0}</b></div>
					<div class="row"><span class="dim">written</span><span class="grow"></span><span>{(job.chars || 0).toLocaleString()} chars</span></div>
					<div class="row"><span class="dim">elapsed</span><span class="grow"></span><span>{hms(elapsed)}</span></div>
				</div>
				<div class="box out">
					<div class="label">┤ {job.plan?.[job.file_i] || 'output'} ├</div>
					<pre class="code">{@html code}<span class="cursor live">█</span></pre>
				</div>
			</section>
		{:else}
			<section class="idle">
				<pre class="big clock">{big(clockText)}</pre>
				<div class="dim">
					{#if st.aside}stepped aside · carrying on once you have been away a while
					{:else if st.gate?.state === 'resting' && nextIn > 0}resting · next job in {hms(nextIn)}
					{:else}{st.gate?.reason || 'waiting'}{/if}
				</div>
			</section>
		{/if}

		<footer class="cols2">
			<div class="box">
				<div class="label">┤ machine ├</div>
				<div class="meter"><span class="dim">video  </span>{bar(vramFrac, 24)} <span class="dim">{((st.vram_total - st.vram_free) / 2 ** 30 || 0).toFixed(1)}/{(st.vram_total / 2 ** 30 || 0).toFixed(0)} GB</span></div>
				<div class="meter"><span class="dim">system </span>{bar(ramFrac, 24)} <span class="dim">{((st.ram_total - st.ram_free) / 2 ** 30 || 0).toFixed(1)}/{(st.ram_total / 2 ** 30 || 0).toFixed(0)} GB</span></div>
				<div class="faint">{app.counts.live} projects · {st.queued || 0} requests waiting</div>
			</div>
			<div class="box">
				<div class="label">┤ lately ├</div>
				{#each recent as e (e.id)}
					<div class="ell">
						<span class="faint">{ago(e.created_at, now / 1000 + app.skew).padStart(8)}</span>
						<span class="dim">{e.type === 'created' ? '+' : '~'}</span>
						<span>{e.title}</span> <span class="faint">{e.author}</span>
					</div>
				{:else}
					<div class="faint">nothing yet</div>
				{/each}
			</div>
		</footer>
		<div class="hint faint">move the mouse or press a key to come back</div>
	</div>
</div>

<style>
	.saver {
		position: fixed;
		inset: 0;
		background: #000;
		cursor: none;
		overflow: hidden;
		font-size: 13px;
	}
	canvas {
		position: absolute;
		inset: 0;
	}
	.frame {
		position: relative;
		height: 100%;
		max-width: 1500px;
		margin: 0 auto;
		padding: 2.2rem 3rem 1.6rem;
		display: grid;
		grid-template-rows: auto auto minmax(0, 1fr) auto auto;
		gap: 1.4rem;
		transition: transform 2s linear;
	}
	header {
		gap: 1rem;
		letter-spacing: 0.08em;
	}
	.brand {
		font-weight: 700;
		letter-spacing: 0.42em;
	}
	.who {
		display: flex;
		gap: 2.4rem;
		align-items: center;
	}
	.big {
		font-size: 11px;
		line-height: 1.05;
		letter-spacing: 0;
		margin: 0;
		color: var(--fg);
	}
	.big.live {
		color: var(--live);
	}
	.whoText {
		display: grid;
		gap: 0.35rem;
		min-width: 0;
	}
	.title {
		font-size: 1.35rem;
		line-height: 1.3;
	}
	.cols {
		display: grid;
		grid-template-columns: 22rem minmax(0, 1fr);
		gap: 1.4rem;
		min-height: 0;
	}
	.cols2 {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.4rem;
	}
	.box {
		border: 1px solid var(--rule-hi);
		background: rgba(0, 0, 0, 0.82);
		padding: 0.8rem 1rem;
		display: grid;
		align-content: start;
		gap: 0.15rem;
		min-height: 0;
		overflow: hidden;
	}
	.box .label {
		margin-bottom: 0.4rem;
	}
	.gap {
		margin-top: 0.9rem;
	}
	.spark {
		font-size: 16px;
		line-height: 1.1;
		letter-spacing: -0.05em;
		white-space: pre;
		overflow: hidden;
	}
	.out {
		grid-template-rows: auto minmax(0, 1fr);
	}
	.code {
		font-size: 12.5px;
		line-height: 1.5;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		overflow: hidden;
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		display: block;
		color: var(--dim);
	}
	.cursor {
		animation: blink 1s steps(2, end) infinite;
	}
	.idle {
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 1.4rem;
	}
	.clock {
		font-size: 22px;
	}
	.meter {
		white-space: pre;
		overflow: hidden;
	}
	.ell {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.hint {
		text-align: center;
		font-size: 11px;
		letter-spacing: 0.2em;
	}
	@media (max-width: 900px) {
		.frame {
			padding: 1.2rem;
		}
		.cols,
		.cols2 {
			grid-template-columns: 1fr;
		}
		.who {
			flex-direction: column;
			align-items: flex-start;
			gap: 1rem;
		}
	}
</style>
