// Shared date utilities — all user-facing dates use DD/MM/YYYY

function fmtDate(iso) {
  if (!iso) return '';
  const p = iso.split('-');
  if (p.length !== 3) return iso;
  return `${p[2]}/${p[1]}/${p[0]}`;
}

function toISO(dmy) {
  if (!dmy) return null;
  const m = dmy.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return null;
  return `${m[3]}-${m[2]}-${m[1]}`;
}

function bindDateInput(el) {
  el.setAttribute('placeholder', 'DD/MM/YYYY');
  el.setAttribute('maxlength', '10');
  el.addEventListener('input', function () {
    const pos = this.selectionStart;
    let v = this.value.replace(/\D/g, '');
    if (v.length > 2) v = v.slice(0, 2) + '/' + v.slice(2);
    if (v.length > 5) v = v.slice(0, 5) + '/' + v.slice(5);
    this.value = v.slice(0, 10);
    try { this.setSelectionRange(pos, pos); } catch (_) {}
  });
}
