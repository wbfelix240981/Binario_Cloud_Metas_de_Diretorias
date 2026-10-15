// build_projetos.js — gera projetos.html (Painel de Projetos) a partir de:
//   - template.html (painel de metas): estilos, logo e o MESMO login/sessão,
//     para que qualquer mudança visual ou de usuários/senhas valha nos dois painéis
//   - template_projetos.html: layout e regras do painel de projetos
//   - projetos.json: dados sincronizados do ClickUp (sync_projetos.py)
const fs = require('fs');
const path = require('path');
const DIR = __dirname;

const metas = fs.readFileSync(path.join(DIR, 'template.html'), 'utf-8');
const corpo = fs.readFileSync(path.join(DIR, 'template_projetos.html'), 'utf-8');
let dados = { last_sync_utc: null, projetos: [] };
try { dados = JSON.parse(fs.readFileSync(path.join(DIR, 'projetos.json'), 'utf-8')); }
catch (e) { console.warn('projetos.json não encontrado, gerando painel vazio.'); }

const fimEstilo = metas.indexOf('</style>');
if (fimEstilo < 0) throw new Error('template.html sem </style>');
const cabecalho = metas.slice(0, fimEstilo).replace(/<title>[^<]*<\/title>/, '<title>Projetos · Binário Cloud</title>');

const logo = (metas.match(/<div class="tb-mark">(<img[^>]*>)<\/div>/) || [, ''])[1];

const iniLogin = metas.indexOf('// ================= LOGIN');
const fimLogin = metas.indexOf('</script>', iniLogin);
if (iniLogin < 0 || fimLogin < 0) throw new Error('bloco de login não encontrado no template.html');
const login = metas.slice(iniLogin, fimLogin);

const out = cabecalho + corpo
  .replace('__LOGO_IMG__', () => logo)
  .replace('/*__PROJETOS_DATA__*/', () => JSON.stringify(dados))
  .replace('/*__LOGIN_SCRIPT__*/', () => login);

const outPath = path.join(DIR, '..', 'publish_out', 'projetos.html');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, out, 'utf-8');
console.log('Build concluído:', outPath, '(' + out.length + ' bytes)');
