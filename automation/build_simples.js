// build_simples.js — gera simples.html (Controle Simples) com o mesmo formato de dados e login da Torre de Controle
//   - template_simples.html: layout, temas e regras (risco, previsão, cobrança)
//   - projetos.json: dados sincronizados do ClickUp (sync_projetos.py)
//   - template.html (painel de metas): reaproveita o MESMO login/sessão
const fs = require('fs');
const path = require('path');
const DIR = __dirname;

let dados = { last_sync_utc: null, projetos: [] };
try { dados = JSON.parse(fs.readFileSync(path.join(DIR, 'projetos.json'), 'utf-8')); }
catch (e) { console.warn('projetos.json não encontrado, gerando painel vazio.'); }

// Formato compacto usado pela página
const DATA = { sync: dados.last_sync_utc, p: [] };
const HIST = []; // [projeto, data_de_conclusao, 1] — base do ritmo de entregas
for (const p of dados.projetos || []) {
  const pp = { k: p.key, n: p.nome, d: p.descricao, u: p.url, f: [] };
  for (const f of p.fases || []) {
    const ff = { n: f.n, s: f.status, id: f.id || null, v: f.virtual ? 1 : 0, a: [] };
    for (const a of f.ativ || []) {
      const x = { n: a.n, s: a.status, r: a.raw_status || '', o: a.assignee || '—', due: a.due, lim: a.alarme_limpo_due ?? null, np: a.nova_previsao ?? null, id: a.id };
      if (a.status !== 'shipped' && a.status !== 'cancelled' && a.u) x.u = a.u;
      if (a.status === 'shipped' && a.dc) HIST.push([p.key, a.dc, 1]);
      ff.a.push(x);
    }
    pp.f.push(ff);
  }
  DATA.p.push(pp);
}

const metas = fs.readFileSync(path.join(DIR, 'template.html'), 'utf-8');
const ini = (s, a) => { const i = metas.indexOf(a); if (i < 0) throw new Error('não achei no template.html: ' + a); return i; };
const loginCss = metas.slice(ini(0, '/* ===== Tela de login (decorativa) ===== */'), ini(0, '</style>'));
const htmlIni = ini(0, '<div id="loginScreen">');
const loginHtml = metas.slice(htmlIni, metas.indexOf('<div class="topbar">', htmlIni));
const jsIni = ini(0, '// ================= LOGIN');
const loginJs = metas.slice(jsIni, metas.indexOf('</script>', jsIni));
// variáveis do painel de metas mapeadas para os temas da Torre
const loginVars = `#loginScreen{--panel-hi:var(--surface-2);--panel:var(--surface);--border-hi:var(--line-2);--border:var(--line);--bg2:var(--surface-2);--text:var(--ink);--text-dim:var(--ink-2);--text-mute:var(--ink-3);--cyan:var(--brand);--cyan-dim:var(--brand-soft);--red:var(--critical-ink);--disp:'Inter',sans-serif;--mono:'JetBrains Mono',monospace;--body:'Inter',sans-serif;}\n`;

let out = fs.readFileSync(path.join(DIR, 'template_simples.html'), 'utf-8')
  .replace('/*__DATA__*/', () => JSON.stringify(DATA))
  .replace('/*__HIST__*/', () => JSON.stringify(HIST))
  .replace('/*__LOGIN_CSS__*/', () => loginVars + loginCss + '\n#loginScreen{background:var(--bg) !important;}\n')
  .replace('<!--__LOGIN_HTML__-->', () => loginHtml.replace('Painel de Metas 2026', 'Controle de Projetos'))
  .replace('/*__LOGIN_SCRIPT__*/', () => loginJs);

const outPath = path.join(DIR, '..', 'publish_out', 'simples.html');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, out, 'utf-8');
console.log('Build concluído:', outPath, '(' + out.length + ' bytes, ' + HIST.length + ' conclusões no histórico)');
