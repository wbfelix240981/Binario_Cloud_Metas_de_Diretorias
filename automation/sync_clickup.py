#!/usr/bin/env python3
"""
Sincroniza os dados (Rafael, Tiago, RoadMap) com o ClickUp.
Roda via GitHub Actions 3x ao dia (06h/12h/20h de Brasília).

Regra de preservação:
- Campos CURADOS à mão (num, short, name, detail em cada meta) NUNCA são sobrescritos.
- Campos DINÂMICOS (status, due, assignee, tags, fases/atividades) são sempre
  substituídos pelo estado atual do ClickUp.
- Casamento de cada meta com sua tarefa no ClickUp é feito primeiro por "id"
  salvo no JSON; se não encontrar (tarefa recriada no ClickUp, troca de id),
  cai para casamento por nome (campo "short"), e o novo id é regravado no JSON.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

TOKEN = os.environ["CLICKUP_API_TOKEN"]
BASE = "https://api.clickup.com/api/v2"
DIR = os.path.dirname(os.path.abspath(__file__))

RAFAEL_LIST_ID = "901328012510"
TIAGO_LIST_ID = "901323683841"
ROADMAP_LIST_ID = "901323996843"

STATUS_MAP = {
    "fechado": "shipped",
    "concluído": "shipped",
    "aberto": "backlog",
    "em andamento": "in progress",
    "revisando": "in review",
    "em revisão": "in review",
    "bloqueada": "blocked",
    "em planejamento": "in planning",
    "planejamento": "in planning",
    "em teste": "in test",
}

# Metas que devem SEMPRE aparecer como 100% concluído, sem fases detalhadas,
# independente do que o ClickUp mostrar (regra de negócio definida manualmente).
# (vazio: a meta ClaudIA no Suporte saiu dessa lista em 05/08/2026 — passou a ter
# estrutura de fases real e detalhada no ClickUp, igual às demais metas)
FORCE_SIMPLE_100 = set()

# Status usados no board do RoadMap (mantidos como o texto original em pt-BR, sem mapear)
ROADMAP_STATUS_PASSTHROUGH = True


def api_get(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={"Authorization": TOKEN})
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


def assignee_name(task):
    names = [a["username"] for a in task.get("assignees", [])]
    return " / ".join(names) if names else "—"


def to_ms(due_date):
    return int(due_date) if due_date else None


# Algumas listas do ClickUp usam status customizados em português (ex.: lista do Rafael:
# "aberto", "em andamento", "fechado"...), outras usam o vocabulário padrão do ClickUp,
# já em inglês (ex.: lista do Tiago: "backlog", "in progress", "in planning", "shipped"...).
# Por isso o mapeamento reconhece os dois casos.
VALID_INTERNAL_STATUSES = {
    "backlog", "in planning", "in progress", "in test", "in review", "blocked", "shipped"
}


def map_status(raw_status):
    raw = raw_status.strip().lower()
    if raw in VALID_INTERNAL_STATUSES:
        return raw
    return STATUS_MAP.get(raw, "backlog")


def build_activity(t):
    return {
        "n": t["name"],
        "status": map_status(t["status"]["status"]),
        "due": to_ms(t.get("due_date")),
        "id": t["id"],
    }


def build_phase(ph_full):
    subtasks = ph_full.get("subtasks", [])
    return {
        "n": ph_full["name"],
        "status": map_status(ph_full["status"]["status"]),
        "assignee": assignee_name(ph_full),
        "due": to_ms(ph_full.get("due_date")),
        "id": ph_full["id"],
        "ativ": [build_activity(s) for s in subtasks],
    }


def find_live_task(live_tasks, meta):
    """Casa uma meta salva com a tarefa viva do ClickUp: por id, senão por nome."""
    for t in live_tasks:
        if t["id"] == meta.get("id"):
            return t
    short_lower = meta["short"].strip().lower()
    for t in live_tasks:
        if t["name"].strip().lower() == short_lower:
            return t
    # match parcial (contém) como último recurso
    for t in live_tasks:
        if short_lower in t["name"].strip().lower() or t["name"].strip().lower() in short_lower:
            return t
    return None


def sync_metas_file(json_path, list_id, extra_allowed_names=None):
    """Sincroniza um arquivo de metas (rafael.json ou tiago.json) com uma lista do ClickUp."""
    with open(json_path, encoding="utf-8") as f:
        metas = json.load(f)

    live_tasks = api_get(f"/list/{list_id}/task?subtasks=false&include_closed=true")["tasks"]

    changed = False
    for meta in metas:
        live = find_live_task(live_tasks, meta)
        if not live:
            print(f"AVISO: meta '{meta['short']}' não encontrada no ClickUp (mantendo dado anterior)", file=sys.stderr)
            continue

        # Captura ANTES de qualquer atualização, pra não perder o vínculo se o nome mudar nesta mesma rodada.
        is_forced_simple = meta["short"] in FORCE_SIMPLE_100

        if meta.get("id") != live["id"]:
            meta["id"] = live["id"]
            changed = True

        new_status = map_status(live["status"]["status"])
        new_due = to_ms(live.get("due_date"))
        new_assignee = assignee_name(live)
        new_tags = [tag["name"] for tag in live.get("tags", [])]
        new_short = live["name"]

        if meta.get("short") != new_short:
            print(f"NOME MUDOU: '{meta['short']}' -> '{new_short}'", file=sys.stderr)
            meta["short"] = new_short
            changed = True
        if meta.get("status") != new_status:
            meta["status"] = new_status
            changed = True
        if meta.get("due") != new_due:
            meta["due"] = new_due
            changed = True
        if meta.get("assignee") != new_assignee:
            meta["assignee"] = new_assignee
            changed = True
        if meta.get("tags") != new_tags and new_tags:
            meta["tags"] = new_tags
            changed = True

        # Regra de negócio: metas forçadas a 100%/sem fases (ex.: ClaudIA no Suporte)
        if is_forced_simple:
            if meta.get("status") != "shipped" or meta.get("fases") != []:
                meta["status"] = "shipped"
                meta["fases"] = []
                changed = True
            continue

        # Reconstrói fases + atividades a partir do estado atual do ClickUp
        full = api_get(f"/task/{live['id']}?include_subtasks=true")
        new_fases = []
        for ph in full.get("subtasks", []):
            if ph.get("name", "").strip().lower() == "dummy":
                continue
            if ph.get("subtasks_count", 0) > 0:
                ph_full = api_get(f"/task/{ph['id']}?include_subtasks=true")
            else:
                ph_full = ph
            new_fases.append(build_phase(ph_full))

        if meta.get("fases") != new_fases:
            meta["fases"] = new_fases
            changed = True

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metas, f, ensure_ascii=False, indent=1)
        f.write("\n")

    return changed


def sync_roadmap_file(json_path, list_id):
    """Sincroniza o roadmap.json (lista flat, sem fases) com o ClickUp."""
    with open(json_path, encoding="utf-8") as f:
        old_tasks = json.load(f)

    live_tasks = api_get(f"/list/{list_id}/task?subtasks=false&include_closed=true")["tasks"]

    new_tasks = []
    for t in live_tasks:
        new_tasks.append({
            "id": t["id"],
            "name": t["name"],
            "status": t["status"]["status"].strip().lower(),
            "assignees": [a["username"] for a in t.get("assignees", [])] or [],
            "url": f"https://app.clickup.com/t/{t['id']}",
        })

    changed = old_tasks != new_tasks
    if changed:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(new_tasks, f, ensure_ascii=False, indent=1)
            f.write("\n")

    return changed


def main():
    any_changed = False

    print("Sincronizando Rafael...")
    if sync_metas_file(os.path.join(DIR, "rafael.json"), RAFAEL_LIST_ID):
        print("  -> rafael.json atualizado")
        any_changed = True
    else:
        print("  -> sem mudanças")

    print("Sincronizando Tiago...")
    if sync_metas_file(os.path.join(DIR, "tiago.json"), TIAGO_LIST_ID):
        print("  -> tiago.json atualizado")
        any_changed = True
    else:
        print("  -> sem mudanças")

    print("Sincronizando RoadMap...")
    if sync_roadmap_file(os.path.join(DIR, "roadmap.json"), ROADMAP_LIST_ID):
        print("  -> roadmap.json atualizado")
        any_changed = True
    else:
        print("  -> sem mudanças")

    # Grava o horário real desta checagem (independente de ter mudado algo),
    # para o site mostrar "Atualizado em" fiel à última sincronização de verdade.
    import datetime
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(os.path.join(DIR, "last_sync.json"), "w", encoding="utf-8") as f:
        json.dump({"last_sync_utc": now_iso}, f)
        f.write("\n")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"changed={'true' if any_changed else 'false'}\n")

    print("CHANGED=" + ("true" if any_changed else "false"))


if __name__ == "__main__":
    main()
