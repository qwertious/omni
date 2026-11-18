<script>
	import { app } from './lib/store.svelte.js';
	import Avatar from './components/Avatar.svelte';
	import StatusPanel from './components/StatusPanel.svelte';
	import Feed from './views/Feed.svelte';
	import Projects from './views/Projects.svelte';
	import Project from './views/Project.svelte';
	import Personas from './views/Personas.svelte';
	import Settings from './views/Settings.svelte';
	import Models from './views/Models.svelte';
	import Saver from './views/Saver.svelte';

	const NAV = [
		['feed', '#/', 'feed'],
		['projects', '#/projects', 'projects'],
		['personas', '#/personas', 'personas'],
		['models', '#/models', 'models'],
		['settings', '#/settings', 'settings']
	];
	const at = $derived(app.route.name === 'project' ? 'projects' : app.route.name);
	const job = $derived(app.status.job);
</script>

{#if app.route.name === 'saver'}
	<Saver />
{:else}
<div class="shell">
	<aside class="side">
		<a class="brand" href="#/">OMNI</a>
		<nav>
			{#each NAV as [id, href, label] (id)}
				<a {href} class:on={at === id}>
					<span>{label}</span>
					{#if id === 'projects'}<span class="faint">{app.counts.live}</span>{/if}
				</a>
			{/each}
		</nav>
		<div class="people">
			<div class="label">makers</div>
			{#each app.personas.filter((p) => p.enabled) as p (p.id)}
				<a class="person" href="#/personas">
					<Avatar who={'@' + p.handle} size={22} />
					<span class="grow">{p.name}</span>
					<span class="dot" class:live={job?.persona === p.handle}></span>
				</a>
			{/each}
		</div>
		<span class="grow"></span>
		<div class="foot faint">
			{#if !app.online}<span class="bad">disconnected</span>{:else if app.is_remote}remote{:else}local{/if}
		</div>
	</aside>

	<header class="topbar">
		<a class="brand" href="#/">OMNI</a>
		<span class="grow"></span>
		<a class="row mini" href="#/status">
			<span class="dot" class:live={!!job} class:bad={!app.online}></span>
			<span class="dim">{job ? '@' + job.persona + ' working' : app.status.gate?.state || ''}</span>
		</a>
	</header>

	<main class="scroll">
		{#if app.error && !app.ready}
			<p class="bad pad">{app.error}</p>
		{:else if !app.ready}
			<p class="faint pad">Loading…</p>
		{:else if app.route.name === 'project'}
			{#key app.route.slug}<Project slug={app.route.slug} />{/key}
		{:else if app.route.name === 'projects'}
			<Projects />
		{:else if app.route.name === 'personas'}
			<Personas />
		{:else if app.route.name === 'settings'}
			<Settings />
		{:else if app.route.name === 'models'}
			<Models />
		{:else if app.route.name === 'status'}
			<div class="pad"><StatusPanel /></div>
		{:else}
			<Feed />
		{/if}
	</main>

	<aside class="rail scroll">
		<StatusPanel />
	</aside>

	<nav class="tabs">
		{#each NAV as [id, href, label] (id)}
			<a {href} class:on={at === id}>{label}</a>
		{/each}
	</nav>
</div>
{/if}

<style>
	.shell {
		height: 100%;
		display: grid;
		grid-template-columns: 13rem minmax(0, 1fr) 19rem;
		grid-template-rows: minmax(0, 1fr);
	}
	.side {
		border-right: 1px solid var(--rule);
		padding: 1.2rem 1rem;
		display: flex;
		flex-direction: column;
		gap: 1.6rem;
		min-height: 0;
	}
	.brand {
		font-weight: 700;
		letter-spacing: 0.42em;
		font-size: 1.05rem;
	}
	.brand:hover {
		text-decoration: none;
	}
	.side nav {
		display: grid;
		gap: 0.1rem;
	}
	.side nav a {
		display: flex;
		justify-content: space-between;
		padding: 0.3rem 0.6rem;
		color: var(--dim);
		border-left: 1px solid transparent;
	}
	.side nav a:hover {
		color: var(--fg);
		text-decoration: none;
	}
	.side nav a.on {
		color: var(--fg);
		border-left-color: var(--fg);
	}
	.people {
		display: grid;
		gap: 0.45rem;
	}
	.person {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		color: var(--dim);
	}
	.person:hover {
		color: var(--fg);
		text-decoration: none;
	}
	.foot {
		font-size: 11px;
	}
	main {
		min-width: 0;
		overflow-x: hidden;
	}
	.rail {
		border-left: 1px solid var(--rule);
		padding: 1.2rem 1rem;
	}
	.pad {
		padding: 1.4rem;
	}
	.topbar,
	.tabs {
		display: none;
	}

	@media (max-width: 1100px) {
		.shell {
			grid-template-columns: 12rem minmax(0, 1fr);
		}
		.rail {
			display: none;
		}
		.side .foot::after {
			content: '';
		}
	}

	@media (max-width: 760px) {
		.shell {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: auto minmax(0, 1fr) auto;
		}
		.side {
			display: none;
		}
		.topbar {
			display: flex;
			align-items: center;
			padding: 0.7rem 1rem;
			border-bottom: 1px solid var(--rule);
		}
		.mini {
			gap: 0.45rem;
			font-size: 12px;
		}
		.mini:hover {
			text-decoration: none;
		}
		.tabs {
			display: grid;
			grid-template-columns: repeat(5, 1fr);
			border-top: 1px solid var(--rule);
			padding-bottom: env(safe-area-inset-bottom);
		}
		.tabs a {
			text-align: center;
			padding: 0.75rem 0;
			color: var(--dim);
			font-size: 12px;
			letter-spacing: 0.06em;
		}
		.tabs a.on {
			color: var(--fg);
			box-shadow: inset 0 1px 0 var(--fg);
		}
	}
</style>
