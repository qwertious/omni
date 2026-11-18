/* Omni's page probe. Served as /__omni/probe.js and added to the <head> of every project page.

   data-mode="check": used by the publish gate in a headless browser. Records what the page
   throws, then uses every control on it (clicks buttons, types into fields, changes selects,
   presses keys) and records which ones throw and which ones change nothing. The result is
   left in <script id="__omni_check__"> for the gate to read.

   data-mode="live": used when the person opens a project inside Omni. Sends errors, console
   messages and what they clicked to the Omni window, so a problem report can carry the log. */
(function () {
	var me = document.currentScript;
	var MODE = (me && me.getAttribute('data-mode')) || 'live';
	var errors = [];
	var consoleLines = [];
	var started = Date.now();

	function str(v) {
		try {
			if (v instanceof Error) return v.name + ': ' + v.message;
			if (typeof v === 'object') return JSON.stringify(v).slice(0, 300);
		} catch (e) {}
		return String(v);
	}

	function where() {
		var p = location.pathname.split('/');
		return p[p.length - 1] || 'index.html';
	}

	function send(kind, text, level) {
		if (MODE !== 'live' || window.parent === window) return;
		try {
			window.parent.postMessage({ __omni: 'probe', kind: kind, level: level || '', text: String(text).slice(0, 600), page: where(), t: Date.now() }, '*');
		} catch (e) {}
	}

	function addError(m) {
		m = String(m).slice(0, 300);
		if (errors.length < 30) errors.push(m);
		send('error', m, 'error');
	}

	window.addEventListener(
		'error',
		function (e) {
			var t = e.target;
			if (t && t !== window && (t.src || t.href)) addError('could not load ' + (t.getAttribute('src') || t.getAttribute('href')));
			else addError((e.message || 'script error') + (e.lineno ? ' (line ' + e.lineno + ')' : ''));
		},
		true
	);
	window.addEventListener('unhandledrejection', function (e) {
		addError('unhandled promise rejection: ' + ((e.reason && e.reason.message) || e.reason));
	});

	['error', 'warn', 'log', 'info'].forEach(function (level) {
		var orig = console[level];
		console[level] = function () {
			var text = Array.prototype.map.call(arguments, str).join(' ');
			if (consoleLines.length < 60) consoleLines.push(level + ': ' + text.slice(0, 300));
			send('console', text, level);
			if (orig) return orig.apply(console, arguments);
		};
	});

	function label(el) {
		var t = (el.getAttribute('aria-label') || el.innerText || el.value || el.title || el.placeholder || el.name || el.id || '').trim();
		t = t.replace(/\s+/g, ' ').slice(0, 40);
		var tag = el.tagName.toLowerCase();
		if (tag === 'input') tag = 'input[' + (el.type || 'text') + ']';
		return t ? tag + ' "' + t + '"' : tag;
	}

	if (MODE === 'live') {
		send('page', 'opened ' + where());
		document.addEventListener(
			'click',
			function (e) {
				var el = e.target && e.target.closest ? e.target.closest('button,a,input,select,textarea,label,summary,canvas,[role=button],[onclick]') : null;
				send('action', 'clicked ' + (el ? label(el) : e.target.tagName.toLowerCase()));
			},
			true
		);
		document.addEventListener(
			'change',
			function (e) {
				if (e.target && e.target.tagName) send('action', 'changed ' + label(e.target) + (e.target.type === 'password' ? '' : ' to "' + String(e.target.value).slice(0, 40) + '"'));
			},
			true
		);
		document.addEventListener(
			'keydown',
			function (e) {
				if (/^(Arrow|Enter$|Escape$| $)/.test(e.key) || e.key === ' ') send('action', 'pressed ' + (e.key === ' ' ? 'Space' : e.key));
			},
			true
		);
		return;
	}

	/* ---- check mode ------------------------------------------------------------------ */

	var out = null;
	var mutations = 0;
	var sounds = 0;

	/* the headless browser draws no frames under virtual time, so drive animation from timers */
	var frames = 0;
	window.requestAnimationFrame = function (cb) {
		return setTimeout(function () {
			if (report.done || ++frames > 400) return;
			cb(performance.now());
		}, 33);
	};
	window.cancelAnimationFrame = function (id) {
		clearTimeout(id);
	};
	window.alert = function (m) {
		consoleLines.push('alert: ' + str(m).slice(0, 200));
	};
	window.confirm = function () {
		return true;
	};
	window.prompt = function (m, d) {
		return d || '3';
	};
	window.open = function () {
		return null;
	};
	try {
		var Src = window.AudioScheduledSourceNode || window.OscillatorNode;
		if (Src && Src.prototype.start) {
			var st = Src.prototype.start;
			Src.prototype.start = function () {
				sounds++;
				return st.apply(this, arguments);
			};
		}
		var play = HTMLMediaElement.prototype.play;
		HTMLMediaElement.prototype.play = function () {
			sounds++;
			try {
				return play.apply(this, arguments);
			} catch (e) {
				return Promise.resolve();
			}
		};
		if (window.speechSynthesis) {
			var speak = speechSynthesis.speak.bind(speechSynthesis);
			speechSynthesis.speak = function (u) {
				sounds++;
				try {
					speak(u);
				} catch (e) {}
			};
		}
	} catch (e) {}

	/* keep the test on this page: no following links away, no form submissions */
	document.addEventListener(
		'click',
		function (e) {
			var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
			if (a && (a.getAttribute('href') || '')[0] !== '#') e.preventDefault();
		},
		true
	);
	document.addEventListener(
		'submit',
		function (e) {
			e.preventDefault();
		},
		true
	);

	function ours(n) {
		return out && (n === out || n.parentNode === out);
	}

	function flush(extra) {
		if (!out) {
			out = document.createElement('script');
			out.type = 'application/json';
			out.id = '__omni_check__';
			document.documentElement.appendChild(out);
		}
		var b = document.body;
		var r = { errors: errors.slice(), console: consoleLines.slice(0, 30), nodes: b ? b.querySelectorAll('*').length : 0, text: b ? (b.innerText || '').trim().length : 0 };
		if (extra) for (var k in extra) r[k] = extra[k];
		out.textContent = JSON.stringify(r);
	}

	var thumb = document.createElement('canvas');
	thumb.width = thumb.height = 24;
	function canvases() {
		var sig = 0;
		var list = document.querySelectorAll('canvas');
		for (var i = 0; i < list.length && i < 4; i++) {
			try {
				var g = thumb.getContext('2d');
				g.clearRect(0, 0, 24, 24);
				g.drawImage(list[i], 0, 0, 24, 24);
				var d = g.getImageData(0, 0, 24, 24).data;
				for (var j = 0; j < d.length; j += 3) sig = (sig * 31 + d[j]) % 1000000007;
			} catch (e) {}
		}
		return sig;
	}

	function textSig() {
		var t = document.body ? document.body.innerText || '' : '';
		var h = t.length;
		for (var i = 0; i < t.length && i < 20000; i += 7) h = (h * 33 + t.charCodeAt(i)) % 1000000007;
		var v = '';
		var fields = document.querySelectorAll('input,select,textarea,output,progress,meter');
		for (var k = 0; k < fields.length && k < 60; k++) v += '|' + (fields[k].value || '');
		return h + ':' + v.length + ':' + v.slice(0, 400);
	}

	function state() {
		return { m: mutations, c: canvases(), t: textSig(), s: sounds };
	}

	function differs(a, b) {
		return a.m !== b.m || a.c !== b.c || a.t !== b.t || a.s !== b.s;
	}

	function visible(el) {
		if (el.disabled) return false;
		var r = el.getClientRects();
		if (!r.length) return false;
		var cs = getComputedStyle(el);
		return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.pointerEvents !== 'none';
	}

	function controls() {
		var sel = 'button,input,select,textarea,summary,canvas,[role=button],[role=tab],[onclick],a[href^="#"],[tabindex]:not([tabindex="-1"])';
		var all = Array.prototype.slice.call(document.querySelectorAll(sel));
		var seen = [];
		var list = [];
		all.forEach(function (el) {
			if (ours(el) || el === thumb) return;
			if (el.tagName === 'INPUT' && /^(hidden|file|image)$/i.test(el.type)) return;
			if (!visible(el)) return;
			for (var i = 0; i < seen.length; i++) if (seen[i].contains(el) || el.contains(seen[i])) return;
			seen.push(el);
			list.push(el);
		});
		/* fields first, so a button that needs input finds some */
		list.sort(function (a, b) {
			var fa = /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName) && !/^(button|submit|reset|checkbox|radio)$/i.test(a.type) ? 0 : 1;
			var fb = /^(INPUT|SELECT|TEXTAREA)$/.test(b.tagName) && !/^(button|submit|reset|checkbox|radio)$/i.test(b.type) ? 0 : 1;
			return fa - fb;
		});
		return list.slice(0, 24);
	}

	function fire(el, type, init) {
		var E = /^key/.test(type) ? KeyboardEvent : /^pointer/.test(type) && window.PointerEvent ? PointerEvent : /^(mouse|click)/.test(type) ? MouseEvent : Event;
		init = init || {};
		init.bubbles = true;
		init.cancelable = true;
		try {
			el.dispatchEvent(new E(type, init));
		} catch (e) {
			el.dispatchEvent(new Event(type, { bubbles: true }));
		}
	}

	function setValue(el, v) {
		var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
		var d = Object.getOwnPropertyDescriptor(proto, 'value');
		if (d && d.set) d.set.call(el, v);
		else el.value = v;
	}

	function use(el) {
		var tag = el.tagName;
		var type = (el.type || '').toLowerCase();
		try {
			el.focus && el.focus();
		} catch (e) {}
		if (tag === 'SELECT') {
			if (el.options.length > 1) el.selectedIndex = (el.selectedIndex + 1) % el.options.length;
			fire(el, 'input');
			fire(el, 'change');
			return;
		}
		if (tag === 'TEXTAREA' || (tag === 'INPUT' && !/^(button|submit|reset|checkbox|radio|range|color)$/.test(type))) {
			var v = { number: '7', email: 'a@b.co', url: 'https://example.com', date: '2024-05-01', time: '12:30', tel: '5551234', month: '2024-05', week: '2024-W18' }[type] || 'hello 42';
			setValue(el, v);
			fire(el, 'input');
			fire(el, 'change');
			fire(el, 'keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13 });
			fire(el, 'keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13 });
			return;
		}
		if (type === 'range') {
			var lo = Number(el.min || 0);
			var hi = Number(el.max || 100);
			setValue(el, String(Number(el.value) >= (lo + hi) / 2 ? lo + (hi - lo) / 4 : hi - (hi - lo) / 4));
			fire(el, 'input');
			fire(el, 'change');
			return;
		}
		if (type === 'color') {
			setValue(el, '#ff3366');
			fire(el, 'input');
			fire(el, 'change');
			return;
		}
		var r = el.getBoundingClientRect();
		var pt = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0, buttons: 1, pointerId: 1, isPrimary: true };
		fire(el, 'pointerdown', pt);
		fire(el, 'mousedown', pt);
		if (tag === 'CANVAS') {
			var p2 = { clientX: pt.clientX + 20, clientY: pt.clientY + 12, buttons: 1, pointerId: 1, isPrimary: true };
			fire(el, 'pointermove', p2);
			fire(el, 'mousemove', p2);
		}
		fire(el, 'pointerup', pt);
		fire(el, 'mouseup', pt);
		if (tag === 'CANVAS' || !el.click) fire(el, 'click', pt);
		else el.click();
	}

	function later(ms, fn) {
		setTimeout(function () {
			try {
				fn();
			} catch (e) {
				addError('omni test: ' + e.message);
				finish({ crashed: true });
			}
		}, ms);
	}

	var report = { animated: false, controls: [], keys: null, done: false };
	var loadErrors = 0;

	function finish(extra) {
		report.done = true;
		if (extra) for (var k in extra) report[k] = extra[k];
		flush({ load_errors: loadErrors, exercise: report });
	}

	function exercise() {
		new MutationObserver(function (list) {
			for (var i = 0; i < list.length; i++) {
				var r = list[i];
				if (ours(r.target)) continue;
				if (r.addedNodes.length === 1 && ours(r.addedNodes[0])) continue;
				mutations++;
			}
		}).observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
		loadErrors = errors.length;
		flush({ load_errors: loadErrors, exercise: report });
		var s0 = state();
		later(700, function () {
			var s1 = state();
			report.animated = differs(s0, s1);
			var list = controls();
			var i = 0;
			function next() {
				if (i >= list.length) return keys();
				var el = list[i++];
				var before = state();
				var errs = errors.length;
				var entry = { label: label(el) };
				try {
					use(el);
				} catch (e) {
					addError(e.message);
				}
				later(320, function () {
					entry.changed = differs(before, state());
					entry.errors = errors.slice(errs, errs + 3);
					report.controls.push(entry);
					flush({ load_errors: loadErrors, exercise: report });
					next();
				});
			}
			next();
		});
	}

	function keys() {
		var before = state();
		var errs = errors.length;
		var target = document.body || document;
		['ArrowRight', 'ArrowUp', ' ', 'Enter', 'ArrowLeft'].forEach(function (k, n) {
			later(60 * n, function () {
				var init = { key: k, code: k === ' ' ? 'Space' : k, keyCode: { ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ' ': 32, Enter: 13 }[k] };
				fire(target, 'keydown', init);
				fire(target, 'keyup', init);
			});
		});
		later(700, function () {
			report.keys = { changed: differs(before, state()), errors: errors.slice(errs, errs + 3) };
			finish();
		});
	}

	window.addEventListener('load', function () {
		flush();
		later(600, exercise);
	});
})();
