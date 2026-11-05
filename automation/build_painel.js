// build_painel.js — gera painel.html (Painel Único: decidir, cobrar, projetos e metas numa página só)
//   - template_painel.html: layout, temas e regras
//   - projetos.json (sync_projetos.py) + rafael.json / tiago.json (sync_clickup.py)
//   - template.html (painel de metas): reaproveita o MESMO login/sessão
const fs = require('fs');
const path = require('path');
const DIR = __dirname;
const ler = (f, d) => { try { return JSON.parse(fs.readFileSync(path.join(DIR, f), 'utf-8')); } catch (e) { console.warn(f + ' não encontrado.'); return d; } };

const dados = ler('projetos.json', { last_sync_utc: null, projetos: [] });
const DATA = { sync: dados.last_sync_utc, p: [] };
const HIST = []; // [projeto, data_de_conclusao, 1] — base do ritmo de entregas

for (const p of dados.projetos || []) {
  const pp = { k: p.key, g: 'proj', n: p.nome, d: p.descricao, u: p.url, f: [] };
  for (const f of p.fases || []) {
    const ff = { n: f.n, s: f.status, a: [] };
    for (const a of f.ativ || []) {
      const x = { n: a.n, s: a.status, r: a.raw_status || '', o: a.assignee || '—', due: a.due, lim: a.alarme_limpo_due ?? null, id: a.id };
      if (a.status !== 'shipped' && a.status !== 'cancelled' && a.u) x.u = a.u;
      if (a.status === 'shipped' && a.dc) HIST.push([p.key, a.dc, 1]);
      ff.a.push(x);
    }
    pp.f.push(ff);
  }
  DATA.p.push(pp);
}

// Metas em andamento (as concluídas saem, como os projetos finalizados)
for (const [dir, arq] of [['Rafael', 'rafael.json'], ['Tiago', 'tiago.json']]) {
  for (const m of ler(arq, [])) {
    if (m.status === 'shipped' || m.status === 'cancelled') continue;
    const dono = (m.assignee && m.assignee !== '—') ? m.assignee : (dir === 'Rafael' ? 'Rafael Alves' : 'Tiago Gomes de Oliveira');
    const pp = { k: `meta-${dir.toLowerCase()}-${m.num}`, g: 'meta', dir, dono: dono.split(' / ')[0],
      n: `Meta ${m.num} · ${(m.short || m.name || '').trim()}`, d: `Diretoria ${dir} · ${(m.name || '').trim()}`, u: m.id ? `https://app.clickup.com/t/${m.id}` : null, f: [] };
    for (const f of m.fases || []) {
      const dono_f = (f.assignee && f.assignee !== '—') ? f.assignee : dono;
      const ff = { n: f.n, s: f.status, a: [] };
      for (const a of f.ativ || []) {
        ff.a.push({ n: a.n, s: a.status === 'shipped' ? 'shipped' : (a.status === 'cancelled' ? 'cancelled' : 'open'), r: a.status, o: a.assignee || dono_f,
          due: a.original_due != null ? a.original_due : a.due, lim: null, id: a.id });
      }
      pp.f.push(ff);
    }
    DATA.p.push(pp);
  }
}

const metas = fs.readFileSync(path.join(DIR, 'template.html'), 'utf-8');
const ini = a => { const i = metas.indexOf(a); if (i < 0) throw new Error('não achei no template.html: ' + a); return i; };
const loginCss = metas.slice(ini('/* ===== Tela de login (decorativa) ===== */'), ini('</style>'));
const htmlIni = ini('<div id="loginScreen">');
const loginHtml = metas.slice(htmlIni, metas.indexOf('<div class="topbar">', htmlIni));
const jsIni = ini('// ================= LOGIN');
const loginJs = metas.slice(jsIni, metas.indexOf('</script>', jsIni));
const loginVars = `#loginScreen{--panel-hi:var(--surface-2);--panel:var(--surface);--border-hi:var(--line-2);--border:var(--line);--bg2:var(--surface-2);--text:var(--ink);--text-dim:var(--ink-2);--text-mute:var(--ink-3);--cyan:var(--brand);--cyan-dim:var(--brand-soft);--red:var(--critical-ink);--disp:'Inter',sans-serif;--mono:'JetBrains Mono',monospace;--body:'Inter',sans-serif;}\n`;

let out = fs.readFileSync(path.join(DIR, 'template_painel.html'), 'utf-8')
  .replace('/*__DATA__*/', () => JSON.stringify(DATA))
  .replace('/*__HIST__*/', () => JSON.stringify(HIST))
  .replace('/*__LOGIN_CSS__*/', () => loginVars + loginCss + '\n#loginScreen{background:var(--bg) !important;}\n')
  .replace('<!--__LOGIN_HTML__-->', () => loginHtml.replace('Painel de Metas 2026', 'Painel de Projetos e Metas'))
  .replace('/*__LOGIN_SCRIPT__*/', () => loginJs);

const outPath = process.argv[2] || path.join(DIR, '..', 'publish_out', 'painel.html');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, out, 'utf-8');
console.log('Build concluído:', outPath, '(' + out.length + ' bytes, ' + DATA.p.length + ' projetos/metas, ' + HIST.length + ' conclusões)');
