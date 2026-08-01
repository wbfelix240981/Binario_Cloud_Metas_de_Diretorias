// build.js — reconstrói index.html a partir de template.html + rafael.json + tiago.json + roadmap.json
const fs = require('fs');
const path = require('path');

const DIR = __dirname;

const template = fs.readFileSync(path.join(DIR, 'template.html'), 'utf-8');
const rafael = JSON.parse(fs.readFileSync(path.join(DIR, 'rafael.json'), 'utf-8'));
const tiago = JSON.parse(fs.readFileSync(path.join(DIR, 'tiago.json'), 'utf-8'));
const roadmap = JSON.parse(fs.readFileSync(path.join(DIR, 'roadmap.json'), 'utf-8'));
let lastSync = { last_sync_utc: null };
try {
  lastSync = JSON.parse(fs.readFileSync(path.join(DIR, 'last_sync.json'), 'utf-8'));
} catch (e) {
  console.warn('last_sync.json não encontrado, seguindo sem horário de sincronização.');
}

let out = template;
out = out.replace(
  'const RAFAEL_METAS = /*__RAFAEL_METAS__*/;',
  'const RAFAEL_METAS = ' + JSON.stringify(rafael, null, 1) + ';'
);
out = out.replace(
  'const TIAGO_METAS = /*__TIAGO_METAS__*/;',
  'const TIAGO_METAS = ' + JSON.stringify(tiago, null, 1) + ';'
);
out = out.replace(
  'const ROADMAP_TASKS = /*__ROADMAP_TASKS__*/;',
  'const ROADMAP_TASKS = ' + JSON.stringify(roadmap, null, 1) + ';'
);
out = out.replace(
  'const LAST_SYNC_UTC = /*__LAST_SYNC_UTC__*/;',
  'const LAST_SYNC_UTC = ' + JSON.stringify(lastSync.last_sync_utc) + ';'
);

const outPath = path.join(DIR, '..', 'publish_out', 'index.html');
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, out, 'utf-8');
console.log('Build concluído:', outPath, '(' + out.length + ' bytes)');
