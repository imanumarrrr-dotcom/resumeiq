// ResumeIQ assistant widget. Talks to /api/chat, which searches the real database.
(function () {
  var root = document.getElementById('cw');
  if (!root) return;
  var launch = root.querySelector('.cw-launch'), panel = root.querySelector('.cw-panel'),
      log = root.querySelector('.cw-log'), chips = root.querySelector('.cw-chips'),
      form = root.querySelector('.cw-form'), input = form.querySelector('input');
  var csrf = document.querySelector('meta[name=csrf-token]').content;
  var KEY = 'cw-history', history = [];
  try { history = JSON.parse(sessionStorage.getItem(KEY) || '[]'); } catch (e) {}

  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(history.slice(-30))); } catch (e) {} }
  function scroll() { log.scrollTop = log.scrollHeight; }

  function bubble(cls, text) {
    var d = document.createElement('div'); d.className = 'cw-m ' + cls; d.textContent = text; log.appendChild(d); return d;
  }
  function card(c) {
    var a = document.createElement('a'); a.className = 'cw-card'; a.href = c.url;
    var b = document.createElement('b'); b.textContent = c.title; a.appendChild(b);
    if (c.sub) { var s = document.createElement('span'); s.textContent = c.sub; a.appendChild(s); }
    log.appendChild(a);
  }
  function setChips(list) {
    chips.textContent = '';
    (list || []).forEach(function (t) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'cw-chip'; b.textContent = t;
      b.addEventListener('click', function () { ask(t); }); chips.appendChild(b);
    });
  }
  function render(m) {
    if (m.who === 'me') { bubble('me', m.text); return; }
    bubble('bot', m.text); (m.cards || []).forEach(card); setChips(m.chips);
  }

  function ask(text, hidden) {
    text = text.trim(); if (!text) return;
    if (!hidden) { var u = { who: 'me', text: text }; history.push(u); render(u); }
    var typing = document.createElement('div'); typing.className = 'cw-m bot cw-dots';
    typing.innerHTML = '<span></span><span></span><span></span>'; log.appendChild(typing); scroll();
    fetch(root.dataset.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({ message: text })
    }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { typing.remove(); var m = { who: 'bot', text: d.text, cards: d.cards, chips: d.chips }; history.push(m); render(m); save(); scroll(); })
      .catch(function () { typing.remove(); bubble('bot', 'Something went wrong. Please try again.'); scroll(); });
  }

  function open(show) {
    panel.hidden = !show; launch.hidden = show; launch.setAttribute('aria-expanded', show);
    if (!show) return;
    if (!log.childElementCount) { if (history.length) { history.forEach(render); } else { ask('hi', true); } }
    scroll(); input.focus();
  }
  launch.addEventListener('click', function () { open(true); });
  root.querySelector('.cw-x').addEventListener('click', function () { open(false); launch.focus(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) open(false); });
  form.addEventListener('submit', function (e) { e.preventDefault(); var t = input.value; input.value = ''; ask(t); });
})();
