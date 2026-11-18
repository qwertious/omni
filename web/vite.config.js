import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// The built files land in ../ui/dist, which the Python server serves. No Node at runtime.
export default defineConfig({
	plugins: [svelte()],
	build: { outDir: '../ui/dist', emptyOutDir: true, chunkSizeWarningLimit: 900 },
	server: { port: 5177, proxy: { '/api': 'http://127.0.0.1:7777', '/p': 'http://127.0.0.1:7777' } }
});
