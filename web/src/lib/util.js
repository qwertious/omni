import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import javascript from 'highlight.js/lib/languages/javascript';
import xml from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';
import json from 'highlight.js/lib/languages/json';

hljs.registerLanguage('python', python);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('css', css);
hljs.registerLanguage('json', json);

const LANG = { py: 'python', js: 'javascript', mjs: 'javascript', html: 'xml', htm: 'xml', svg: 'xml', css: 'css', json: 'json' };

export function esc(s) {
	return String(s == null ? '' : s)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

export function highlight(name, code) {
	const lang = LANG[(name.split('.').pop() || '').toLowerCase()];
	if (!lang || code.length > 150000) return esc(code);
	try {
		return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
	} catch {
		return esc(code);
	}
}

export function ago(t, now) {
	const d = Math.max(0, now - t);
	if (d < 50) return 'just now';
	if (d < 3600) return Math.round(d / 60) + 'm';
	if (d < 86400) return Math.round(d / 3600) + 'h';
	if (d < 86400 * 30) return Math.round(d / 86400) + 'd';
	return new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// "5m ago", but "just now" and dates read fine without the suffix.
export function since(t, now) {
	const a = ago(t, now);
	return /^\d+[mhd]$/.test(a) ? a + ' ago' : a;
}

export function clock(seconds) {
	const s = Math.max(0, Math.round(seconds));
	return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

export function gb(bytes) {
	return (bytes / 1073741824).toFixed(1);
}

export function kindWord(kind) {
	return kind === 'python' ? 'python' : 'web';
}

export function shortModel(name) {
	if (!name) return '';
	let n = name.replace(/^hf\.co\/[^/]+\//, '').replace(/-GGUF/i, '');
	return n.replace(/:latest$/, '');
}

// Splits text so @mentions can be rendered as links to a persona.
export function mentionParts(text) {
	return String(text || '').split(/(@[A-Za-z0-9_]{2,20})/g);
}
