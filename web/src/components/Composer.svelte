<script>
	import { app } from '../lib/store.svelte.js';

	let { placeholder = '', button = 'Post', hint = '', onsubmit } = $props();
	let text = $state('');
	let busy = $state(false);
	let err = $state('');
	let el = $state(null);
	let partial = $state(null); // the "@abc" being typed, if any

	const people = $derived(app.personas.filter((p) => p.enabled));
	const matches = $derived(
		partial === null ? [] : people.filter((p) => p.handle.startsWith(partial) || p.name.toLowerCase().startsWith(partial))
	);

	function track() {
		const upto = text.slice(0, el ? el.selectionStart : text.length);
		const m = upto.match(/(?:^|\s)@([A-Za-z0-9_]{0,20})$/);
		partial = m ? m[1].toLowerCase() : null;
		if (el) {
			el.style.height = 'auto';
			el.style.height = Math.min(el.scrollHeight, 220) + 'px';
		}
	}

	function pick(p) {
		const at = el ? el.selectionStart : text.length;
		const head = text.slice(0, at).replace(/@([A-Za-z0-9_]{0,20})$/, '@' + p.handle + ' ');
		text = head + text.slice(at);
		partial = null;
		el && el.focus();
	}

	function mention(p) {
		if (!text.includes('@' + p.handle)) text = ('@' + p.handle + ' ' + text).replace(/\s+$/, ' ');
		el && el.focus();
	}

	async function send() {
		const body = text.trim();
		if (!body || busy) return;
		busy = true;
		err = '';
		try {
			await onsubmit(body);
			text = '';
			if (el) el.style.height = 'auto';
		} catch (e) {
			err = e.message;
		} finally {
			busy = false;
		}
	}

	function key(e) {
		if (matches.length && (e.key === 'Tab' || e.key === 'Enter')) {
			e.preventDefault();
			return pick(matches[0]);
		}
		if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			send();
		}
	}
</script>

<div class="composer panel">
	<textarea bind:this={el} bind:value={text} rows="2" {placeholder} oninput={track} onkeydown={key} onclick={track}
	></textarea>
	{#if matches.length}
		<div class="menu">
			{#each matches as p (p.id)}
				<button class="quiet" onclick={() => pick(p)}>@{p.handle} <span class="faint">{p.name}</span></button>
			{/each}
		</div>
	{/if}
	<div class="row bar wrap">
		<span class="label">hand to</span>
		{#each people as p (p.id)}
			<button class="chip" class:on={text.includes('@' + p.handle)} onclick={() => mention(p)}>@{p.handle}</button>
		{/each}
		<span class="grow faint hint">{err || hint}</span>
		<button class="solid" disabled={busy || !text.trim()} onclick={send}>{busy ? '…' : button}</button>
	</div>
</div>

<style>
	.composer {
		position: relative;
	}
	textarea {
		border: 0;
		background: transparent;
		padding: 0.8rem 0.9rem 0.3rem;
		min-height: 3.6rem;
		resize: none;
		display: block;
	}
	textarea:focus {
		outline: none;
	}
	.composer:focus-within {
		border-color: var(--rule-hi);
	}
	.bar {
		padding: 0.4rem 0.6rem 0.6rem 0.9rem;
		gap: 0.4rem;
	}
	.chip {
		cursor: pointer;
		background: transparent;
	}
	.hint {
		font-size: 11px;
		text-align: right;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.menu {
		position: absolute;
		left: 0.6rem;
		top: 100%;
		z-index: 5;
		background: var(--bg);
		border: 1px solid var(--rule-hi);
		display: grid;
	}
	.menu button {
		text-align: left;
		padding: 0.35rem 0.8rem;
	}
</style>
