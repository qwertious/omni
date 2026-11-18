<script>
	import { persona } from '../lib/store.svelte.js';

	let { who = '', size = 34 } = $props();
	const p = $derived(who === 'you' ? null : persona(who));
	const letter = $derived(
		(who === 'you' ? 'Y' : p ? p.name[0] : String(who || '?').replace('@', '')[0] || '?').toUpperCase()
	);
	const style = $derived(p ? p.id % 4 : 0);
</script>

<span
	class="av v{style}"
	class:you={who === 'you'}
	class:sys={who !== 'you' && !p}
	style="width:{size}px;height:{size}px;font-size:{Math.round(size * 0.42)}px"
	title={p ? p.name + ' (@' + p.handle + ')' : who}>{letter}</span
>

<style>
	.av {
		display: inline-grid;
		place-items: center;
		flex: none;
		font-weight: 700;
		border: 1px solid var(--fg);
		color: var(--fg);
		background: var(--bg);
		line-height: 1;
		user-select: none;
	}
	.v1 {
		border-style: double;
		border-width: 3px;
	}
	.v2 {
		border-style: dashed;
	}
	.v3 {
		box-shadow: inset 0 0 0 2px var(--bg), inset 0 0 0 3px var(--fg);
	}
	.you {
		background: var(--fg);
		color: var(--bg);
	}
	.sys {
		border-color: var(--faint);
		color: var(--faint);
	}
</style>
