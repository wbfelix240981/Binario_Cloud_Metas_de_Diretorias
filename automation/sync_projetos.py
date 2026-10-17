#!/usr/bin/env python3
"""
Sincroniza o Painel de Projetos (projetos.html) com o ClickUp.

Cada projeto é UMA LISTA do ClickUp (configurada em projetos_config.json)
e vira uma aba no painel. Dentro da lista:
- tarefa de 1º nível COM subtarefas  -> "fase" (as subtarefas, em qualquer
  nível, viram as atividades da fase)
- tarefa de 1º nível SEM subtarefas  -> atividade do grupo "Atividades sem fase"

Regras de alarme (aplicadas no template, por atividade):
- prazo vencido (a partir do dia seguinte)  -> ATRASADA (vermelho)
- prazo = hoje                              -> PENDENTE (amarelo)
- atividade sem data preenchida             -> PENDENTE PLANEJAMENTO
- "Nova previsão" (campo do ClickUp) só aparece como anotação ao lado.

Desde 17/10/2026 (pedido do usuário) o alarme segue SEMPRE a data ATUAL
do ClickUp: se a data for alterada lá, o painel passa a contar pela nova
data (original_due = due a cada sincronização).

Na mesma data, os alarmes de atraso existentes foram limpos: cada
atividade atrasada recebeu "alarme_limpo_due" = a data vencida que tinha.
Enquanto a data no ClickUp continuar a mesma, ela não fica vermelha; se a
data mudar, o campo é descartado e a regra normal volta a valer.
"""
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error

BASE = "https://api.clickup.com/api/v2"
DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(DIR, "projetos_config.json")
DATA_PATH = os.path.join(DIR, "projetos.json")

# Status do ClickUp -> status interno do painel (mesmo vocabulário do painel de metas,
# mais "waiting" e "cancelled", que existem nas listas de projetos).
STATUS_MAP = {
    "fechado": "shipped",
    "concluído": "shipped",
    "concluido": "shipped",
    "entregue": "shipped",
    "complete": "shipped",
    "aberto": "backlog",
    "open": "backlog",
    "to do": "backlog",
    "planejamento": "in planning",
    "em planejamento": "in planning",
    "em andamento": "in progress",
    "in progress": "in progress",
    "revisando": "in review",
    "em revisão": "in review",
    "em teste": "in test",
    "aguardando retorno": "waiting",
    "bloqueada": "blocked",
    "impedimento": "blocked",
    "rejeitada": "cancelled",
    "cancelado": "cancelled",
    "cancelada": "cancelled",
}


def map_status(task):
    raw = (task.get("status") or {}).get("status", "").strip().lower()
    if raw in STATUS_MAP:
        return STATUS_MAP[raw]
    # Status desconhecido: usa o "type" do ClickUp para não errar o essencial
    tipo = (task.get("status") or {}).get("type")
    if tipo in ("closed", "done"):
        return "shipped"
    if tipo == "open":
        return "backlog"
    return "in progress"


def api_get(path, token):
    url = BASE + path
    req = urllib.request.Request(url, headers={"Authorization": token})
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(5)
    raise RuntimeError(f"Falha ao buscar {url}: {last_err}")


def fetch_all_tasks(list_id, token):
    """Todas as tarefas da lista, INCLUINDO subtarefas de qualquer nível
    (cada uma traz o campo 'parent') e as fechadas. Paginado."""
    todas = []
    page = 0
    while True:
        resp = api_get(f"/list/{list_id}/task?subtasks=true&include_closed=true&page={page}", token)
        tasks = resp.get("tasks", [])
        todas.extend(tasks)
        if resp.get("last_page", True) or not tasks:
            break
        page += 1
        if page > 50:
            break
    return todas


def to_ms(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def assignee_name(task):
    names = [a.get("username") for a in task.get("assignees", []) if a.get("username")]
    return " / ".join(names) if names else "—"


def nova_previsao(task):
    for cf in task.get("custom_fields", []) or []:
        if (cf.get("name") or "").strip().lower() == "nova previsão" and cf.get("value") not in (None, ""):
            return to_ms(cf["value"])
    return None


def order_key(t):
    try:
        return float(t.get("orderindex") or 0)
    except (TypeError, ValueError):
        return 0.0


def build_activity(t, depth, old_by_id):
    due = to_ms(t.get("due_date"))
    old = old_by_id.get(t["id"])
    # Alarme limpo manualmente: vale só enquanto a data no ClickUp não mudar
    limpo = old.get("alarme_limpo_due") if old else None
    if limpo is not None and limpo != due:
        limpo = None
    return {
        "n": t.get("name", "").strip(),
        "status": map_status(t),
        "raw_status": (t.get("status") or {}).get("status", ""),
        "assignee": assignee_name(t),
        "due": due,
        "original_due": due,
        "alarme_limpo_due": limpo,
        "nova_previsao": nova_previsao(t),
        "depth": depth,
        "id": t["id"],
    }


def build_project(cfg, tasks, old_project):
    old_by_id = {}
    for f in (old_project or {}).get("fases", []):
        for a in f.get("ativ", []):
            old_by_id[a["id"]] = a
        if f.get("id"):
            old_by_id[f["id"]] = f

    ids = {t["id"] for t in tasks}
    children = {}
    roots = []
    for t in tasks:
        p = t.get("parent")
        if p and p in ids:
            children.setdefault(p, []).append(t)
        else:
            roots.append(t)
    for lst in children.values():
        lst.sort(key=order_key)
    roots.sort(key=order_key)

    def descendants(tid, depth):
        out = []
        for c in children.get(tid, []):
            out.append(build_activity(c, depth, old_by_id))
            out.extend(descendants(c["id"], depth + 1))
        return out

    fases = []
    avulsas = []
    for r in roots:
        if children.get(r["id"]):
            fases.append({
                "n": r.get("name", "").strip(),
                "status": map_status(r),
                "raw_status": (r.get("status") or {}).get("status", ""),
                "assignee": assignee_name(r),
                "due": to_ms(r.get("due_date")),
                "id": r["id"],
                "ativ": descendants(r["id"], 0),
            })
        else:
            avulsas.append(build_activity(r, 0, old_by_id))
    if avulsas:
        fases.append({
            "n": "Atividades sem fase",
            "status": "shipped" if all(a["status"] in ("shipped", "cancelled") for a in avulsas) else "in progress",
            "raw_status": "",
            "assignee": "—",
            "due": None,
            "id": None,
            "virtual": True,
            "ativ": avulsas,
        })

    return {
        "key": cfg["key"],
        "nome": cfg["nome"],
        "descricao": cfg.get("descricao", ""),
        "finalizado": bool(cfg.get("finalizado")),
        "list_id": cfg["list_id"],
        "url": f"https://app.clickup.com/3080406/v/li/{cfg['list_id']}",
        "fases": fases,
    }


def main():
    token = os.environ.get("CLICKUP_API_TOKEN")
    if not token:
        print("CLICKUP_API_TOKEN não definido", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    old = {}
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            old = {p["key"]: p for p in json.load(f).get("projetos", [])}

    projetos = []
    for cfg in config:
        print(f"Sincronizando projeto {cfg['nome']} (lista {cfg['list_id']})...")
        try:
            tasks = fetch_all_tasks(cfg["list_id"], token)
            proj = build_project(cfg, tasks, old.get(cfg["key"]))
            n_ativ = sum(len(f["ativ"]) for f in proj["fases"])
            print(f"  -> {len(proj['fases'])} fase(s), {n_ativ} atividade(s)")
            projetos.append(proj)
        except Exception as e:
            print(f"ERRO no projeto {cfg['nome']}: {type(e).__name__}: {e} (mantendo dado anterior)", file=sys.stderr)
            if cfg["key"] in old:
                anterior = dict(old[cfg["key"]])
                anterior.update({k: cfg[k] for k in ("nome", "descricao") if k in cfg})
                anterior["finalizado"] = bool(cfg.get("finalizado"))
                projetos.append(anterior)

    agora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_sync_utc": agora, "projetos": projetos}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("projetos.json gravado")


if __name__ == "__main__":
    main()
