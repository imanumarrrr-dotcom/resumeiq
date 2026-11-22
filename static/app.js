// Client-side checks (the server validates again, never trust only JS)
document.querySelectorAll('.apply-form').forEach(function (f) {
  f.addEventListener('submit', function (e) {
    var file = f.querySelector('input[type=file]').files[0];
    if (!file) { e.preventDefault(); alert('Please select a PDF resume first.'); return; }
    if (!file.name.toLowerCase().endsWith('.pdf')) { e.preventDefault(); alert('Only PDF files are allowed.'); return; }
    if (file.size > 5 * 1024 * 1024) { e.preventDefault(); alert('The file must be 5 MB or smaller.'); return; }
    var b = f.querySelector('button'); b.disabled = true; b.textContent = 'Analysing resume…';
  });
});
document.querySelectorAll('form[data-confirm]').forEach(function (f) {
  f.addEventListener('submit', function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
});
