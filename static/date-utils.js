// Shared date utilities — all user-facing dates use DD/MM/YYYY

function fmtDate(iso) {
  if (!iso) return '';
  const p = iso.split('-');
  if (p.length !== 3) return iso;
  return `${p[2]}/${p[1]}/${p[0]}`;
}

function toISO(dmy) {
  if (!dmy) return null;
  const m = dmy.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!m) return null;
  const dd = m[1].padStart(2, '0'), mm = m[2].padStart(2, '0'), yyyy = m[3];
  return `${yyyy}-${mm}-${dd}`;
}

// Build a DD / MM / YYYY split-field date input inside the given container element.
// The container takes the place of a single <input> and should have an id for labelling.
function buildDateInput(container) {
  container.className = (container.className + ' date-input-group').trim();
  container.innerHTML = `
    <input type="text" class="date-part dp-dd" maxlength="2" placeholder="DD" inputmode="numeric">
    <span class="date-sep">/</span>
    <input type="text" class="date-part dp-mm" maxlength="2" placeholder="MM" inputmode="numeric">
    <span class="date-sep">/</span>
    <input type="text" class="date-part dp-yyyy" maxlength="4" placeholder="YYYY" inputmode="numeric">
  `;

  const [dd, mm, yyyy] = container.querySelectorAll('.date-part');

  // Digits only
  [dd, mm, mm, yyyy].forEach(inp => {
    inp.addEventListener('keypress', e => { if (!/\d/.test(e.key)) e.preventDefault(); });
  });

  // Auto-advance on fill
  dd.addEventListener('input', () => {
    dd.value = dd.value.replace(/\D/g, '');
    if (dd.value.length === 2) mm.focus();
  });
  mm.addEventListener('input', () => {
    mm.value = mm.value.replace(/\D/g, '');
    if (mm.value.length === 2) yyyy.focus();
  });
  yyyy.addEventListener('input', () => {
    yyyy.value = yyyy.value.replace(/\D/g, '');
  });

  // Backspace from empty field moves back
  mm.addEventListener('keydown',   e => { if (e.key === 'Backspace' && mm.value   === '') dd.focus(); });
  yyyy.addEventListener('keydown', e => { if (e.key === 'Backspace' && yyyy.value === '') mm.focus(); });
}

function getDateValue(container) {
  const dd   = container.querySelector('.dp-dd');
  const mm   = container.querySelector('.dp-mm');
  const yyyy = container.querySelector('.dp-yyyy');
  if (!dd || !mm || !yyyy) return null;
  const d = dd.value.trim(), m = mm.value.trim(), y = yyyy.value.trim();
  if (!d || !m || y.length < 4) return null;
  return toISO(`${d}/${m}/${y}`);
}

function setDateValue(container, isoDate) {
  const dd   = container.querySelector('.dp-dd');
  const mm   = container.querySelector('.dp-mm');
  const yyyy = container.querySelector('.dp-yyyy');
  if (!dd || !mm || !yyyy) return;
  if (!isoDate) { dd.value = mm.value = yyyy.value = ''; return; }
  const p = isoDate.split('-');
  yyyy.value = p[0] || '';
  mm.value   = p[1] || '';
  dd.value   = p[2] || '';
}
