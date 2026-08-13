#!/usr/bin/env python3
"""
Sincroniza os dados (Rafael, Tiago, RoadMap) com o ClickUp.
Roda via GitHub Actions (agendamento configurável) ou manualmente.

O que É sincronizado automaticamente (fiel ao ClickUp), APENAS para as
metas que já estão mapeadas no painel:
- Status de cada meta, fase e atividade
- Nome de exibição (short) de cada meta
- Responsável, prazo, tags
- Fases e atividades (reconstruídas do zero a cada checagem, com IDs
  pra permitir o link direto "abrir no ClickUp" em cada atividade)
- EXCLUSÃO: se uma meta mapeada sumir da lista do ClickUp, ela é removida
- Metas sem plano de fases ficam marcadas para não distorcer o índice
  geral (excludeFromIndex), e voltam a contar assim que ganharem fases

O que NÃO é feito automaticamente:
- INCLUSÃO de metas novas: tarefas que aparecem na lista do ClickUp mas
  ainda não estão mapeadas NÃO viram metas sozinhas — o script só avisa
  nos logs que existem. Uma meta nova só entra no painel quando pedida
  explicitamente (usar markdown_to_detail() pra gerar a ficha resumida
  a partir da descrição do ClickUp nesse momento).
- O campo "name" (descrição curada mais longa) e o "detail" de metas
  já existentes nunca são sobrescritos automaticamente.
"""
import json
import os
import re
import sys
import time
import datetime
import urllib.request
import urllib.error

TOKEN = os.environ["CLICKUP_API_TOKEN"]
BASE = "https://api.clickup.com/api/v2"
DIR = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG_PATH = os.path.join(DIR, "sync_errors.log")


def log_error(contexto, exc):
    """Grava o erro num arquivo que é commitado junto com os dados, já que os
    logs brutos do GitHub Actions não são fáceis de consultar depois. Mantém
    só as últimas 50 entradas para o arquivo não crescer indefinidamente."""
    import traceback
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entrada = f"[{ts}] {contexto}\n{traceback.format_exc()}\n{'-'*70}\n"
    linhas_antigas = ""
    if os.path.exists(ERROR_LOG_PATH):
        with open(ERROR_LOG_PATH, encoding="utf-8") as f:
            linhas_antigas = f.read()
    blocos = (linhas_antigas + entrada).split('-'*70 + "\n")
    blocos = [b for b in blocos if b.strip()][-50:]
    with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
        f.write(('-'*70 + "\n").join(blocos) + ('-'*70 + "\n" if blocos else ""))

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

VALID_INTERNAL_STATUSES = {
    "backlog", "in planning", "in progress", "in test", "in review", "blocked", "shipped"
}

# Metas que devem SEMPRE aparecer como 100% concluído, sem fases detalhadas,
# independente do que o ClickUp mostrar (regra de negócio definida manualmente).
FORCE_SIMPLE_100 = set()

# Nomes de tarefas que NUNCA devem virar metas automaticamente numa lista,
# mesmo que apareçam nela — tipicamente itens que já pertencem a outra
# diretoria e aparecem duplicados por engano em outra lista do ClickUp.
EXCLUDE_NAMES_BY_LIST = {
    TIAGO_LIST_ID: {"ClaudIA no Suporte", "Observabilidade de BCloud 3.0"},
}


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


def api_get_all_tasks(list_id, extra_params=""):
    """Busca TODAS as tarefas de uma lista, paginando corretamente.
    Bug corrigido em 13/08/2026: a API do ClickUp pagina os resultados
    (não retorna tudo numa página só quando a lista cresce); sem paginar,
    o último item da lista ficava intermitentemente de fora."""
    todas = []
    page = 0
    while True:
        resp = api_get(f"/list/{list_id}/task?subtasks=false&include_closed=true&page={page}{extra_params}")
        pagina_tasks = resp.get("tasks", [])
        todas.extend(pagina_tasks)
        if resp.get("last_page", True) or not pagina_tasks:
            break
        page += 1
        if page > 20:  # trava de segurança contra loop infinito
            break
    return todas


def assignee_name(task):
    names = [a["username"] for a in task.get("assignees", [])]
    return " / ".join(names) if names else "—"


def to_ms(due_date):
    return int(due_date) if due_date else None


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


def build_fases_for_task(task_id):
    """Busca e reconstrói as fases + atividades de uma tarefa (meta) do zero."""
    full = api_get(f"/task/{task_id}?include_subtasks=true")
    new_fases = []
    for ph in full.get("subtasks", []):
        if ph.get("name", "").strip().lower() == "dummy":
            continue
        if ph.get("subtasks_count", 0) > 0:
            ph_full = api_get(f"/task/{ph['id']}?include_subtasks=true")
        else:
            ph_full = ph
        new_fases.append(build_phase(ph_full))
    return new_fases


def markdown_to_detail(md_text, fallback_status_label):
    """Gera uma ficha resumida (campo 'detail') a partir da descrição em markdown
    de uma tarefa nova do ClickUp. Extrai as seções mais relevantes quando existem
    (Objetivo, Entregáveis, Critério de aceite, Prazo final, Risco principal);
    se a descrição não tiver esse padrão, usa um resumo simples."""
    if not md_text or not md_text.strip():
        return f"Status: {fallback_status_label}, ainda sem fases detalhadas cadastradas no ClickUp."

    def clean(s):
        s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
        s = re.sub(r"^#+\s*", "", s, flags=re.M)
        s = re.sub(r"^\*\s+", "", s, flags=re.M)
        s = re.sub(r"[ \t]+", " ", s)
        return s.strip()

    secoes_desejadas = [
        ("Objetivo", "objetivo"),
        ("Entregáveis", "entregáveis"),
        ("Prazo final", "prazo final"),
        ("Critério de aceite", "critério de aceite"),
        ("Risco principal", "risco principal"),
    ]
    linhas = md_text.split("\n")
    partes = []
    atual_titulo = None
    atual_conteudo = []

    def flush():
        if atual_titulo and atual_conteudo:
            linhas_limpas = [re.sub(r"^[\*\-]\s+", "", clean(l)) for l in atual_conteudo if l.strip()]
            texto = "; ".join(l.rstrip(";.") for l in linhas_limpas if l)
            if len(texto) > 400:
                texto = texto[:400].rsplit(" ", 1)[0] + "…"
            partes.append(f"{atual_titulo}: {texto}.")

    for linha in linhas:
        titulo_encontrado = None
        linha_s = linha.strip()
        resto_mesma_linha = ""
        for label, _ in secoes_desejadas:
            padrao_heading = rf"^#+\s*\d*\\?\.?\s*{re.escape(label)}"
            padrao_bold = rf"^\*\*\s*{re.escape(label)}\s*:?\s*\*\*"
            if re.match(padrao_heading, linha_s, re.I):
                titulo_encontrado = label
                break
            if re.match(padrao_bold, linha_s, re.I):
                titulo_encontrado = label
                resto_mesma_linha = re.sub(padrao_bold, "", linha_s, flags=re.I).strip()
                break
        if titulo_encontrado:
            flush()
            atual_titulo = titulo_encontrado
            atual_conteudo = [resto_mesma_linha] if resto_mesma_linha else []
        elif atual_titulo:
            if linha.strip().startswith("#"):
                flush()
                atual_titulo = None
                atual_conteudo = []
            elif re.match(r"^[\*\-_\s]{3,}$", linha.strip()):
                pass  # linha de separador horizontal (* * *, ---), ignora
            else:
                atual_conteudo.append(linha.strip())
    flush()

    if partes:
        return "\n".join(partes)

    texto = clean(md_text)
    if len(texto) > 500:
        texto = texto[:500].rsplit(" ", 1)[0] + "…"
    return texto


def find_live_task(live_tasks, meta):
    """Casa uma meta salva com a tarefa viva do ClickUp: por id, senão por nome."""
    for t in live_tasks:
        if t["id"] == meta.get("id"):
            return t
    short_lower = meta["short"].strip().lower()
    for t in live_tasks:
        if t["name"].strip().lower() == short_lower:
            return t
    for t in live_tasks:
        if short_lower in t["name"].strip().lower() or t["name"].strip().lower() in short_lower:
            return t
    return None


def sync_metas_file(json_path, list_id):
    """Sincroniza um arquivo de metas (rafael.json ou tiago.json) com uma lista do ClickUp.
    Cobre: status, nome, inclusão de metas novas, exclusão de metas removidas,
    fases/atividades, e a flag excludeFromIndex para metas sem plano de fases."""
    with open(json_path, encoding="utf-8") as f:
        metas = json.load(f)

    live_tasks = api_get_all_tasks(list_id)
    exclude_names = {n.lower() for n in EXCLUDE_NAMES_BY_LIST.get(list_id, set())}

    changed = False
    matched_live_ids = set()

    # 1) Atualiza metas já existentes
    for meta in metas:
        try:
            live = find_live_task(live_tasks, meta)
            if not live:
                print(f"AVISO: meta '{meta['short']}' não encontrada no ClickUp (mantendo dado anterior)", file=sys.stderr)
                continue

            matched_live_ids.add(live["id"])
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

            if is_forced_simple:
                if meta.get("status") != "shipped" or meta.get("fases") != []:
                    meta["status"] = "shipped"
                    meta["fases"] = []
                    changed = True
                meta.pop("excludeFromIndex", None)
                continue

            new_fases = build_fases_for_task(live["id"])
            if meta.get("fases") != new_fases:
                meta["fases"] = new_fases
                changed = True

            # Metas sem plano de fases não distorcem o índice geral, até ganharem um plano
            should_exclude = (len(meta["fases"]) == 0 and meta["status"] != "shipped")
            if should_exclude and not meta.get("excludeFromIndex"):
                meta["excludeFromIndex"] = True
                changed = True
            elif not should_exclude and meta.get("excludeFromIndex"):
                meta.pop("excludeFromIndex")
                changed = True

        except Exception as e:
            print(f"ERRO ao sincronizar a meta '{meta.get('short','?')}': {type(e).__name__}: {e} "
                  f"(pulando esta meta, mantendo dado anterior, seguindo com as demais)", file=sys.stderr)
            log_error(f"meta '{meta.get('short','?')}' (id={meta.get('id')}) na lista {list_id}", e)
            continue

    # 2) Remove metas que sumiram do ClickUp (exclusão)
    antes = len(metas)
    ainda_existentes = []
    for meta in metas:
        live = find_live_task(live_tasks, meta)
        if live:
            ainda_existentes.append(meta)
        else:
            print(f"REMOVIDA: meta '{meta['short']}' não existe mais na lista do ClickUp", file=sys.stderr)
    if len(ainda_existentes) != antes:
        metas = ainda_existentes
        changed = True

    # 3) Tarefas novas na lista NÃO são incluídas automaticamente — só entram
    #    quando pedidas explicitamente. Aqui só avisamos que existem, pra ficar
    #    visível nos logs da sincronização.
    known_ids = {m.get("id") for m in metas}
    known_short_lower = {m["short"].strip().lower() for m in metas}
    exclude_names_lower = exclude_names
    for t in live_tasks:
        if t["id"] in known_ids:
            continue
        if t["name"].strip().lower() in known_short_lower:
            continue
        if t["name"].strip().lower() in exclude_names_lower:
            continue
        if not t.get("due_date"):
            continue
        print(f"INFO: tarefa nova na lista, ainda NÃO incluída no painel (peça explicitamente se quiser): '{t['name']}'", file=sys.stderr)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metas, f, ensure_ascii=False, indent=1)
        f.write("\n")

    return changed


def sync_roadmap_file(json_path, list_id):
    """Sincroniza o roadmap.json (lista flat, sem fases) com o ClickUp."""
    with open(json_path, encoding="utf-8") as f:
        old_tasks = json.load(f)

    live_tasks = api_get_all_tasks(list_id)

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
    houve_erro = False

    print("Sincronizando Rafael...")
    try:
        if sync_metas_file(os.path.join(DIR, "rafael.json"), RAFAEL_LIST_ID):
            print("  -> rafael.json atualizado")
            any_changed = True
        else:
            print("  -> sem mudanças")
    except Exception as e:
        print(f"ERRO GERAL ao sincronizar Rafael: {type(e).__name__}: {e} (mantendo rafael.json anterior)", file=sys.stderr)
        log_error("Rafael (geral)", e)
        houve_erro = True

    print("Sincronizando Tiago...")
    try:
        if sync_metas_file(os.path.join(DIR, "tiago.json"), TIAGO_LIST_ID):
            print("  -> tiago.json atualizado")
            any_changed = True
        else:
            print("  -> sem mudanças")
    except Exception as e:
        print(f"ERRO GERAL ao sincronizar Tiago: {type(e).__name__}: {e} (mantendo tiago.json anterior)", file=sys.stderr)
        log_error("Tiago (geral)", e)
        houve_erro = True

    print("Sincronizando RoadMap...")
    try:
        if sync_roadmap_file(os.path.join(DIR, "roadmap.json"), ROADMAP_LIST_ID):
            print("  -> roadmap.json atualizado")
            any_changed = True
        else:
            print("  -> sem mudanças")
    except Exception as e:
        print(f"ERRO GERAL ao sincronizar RoadMap: {type(e).__name__}: {e} (mantendo roadmap.json anterior)", file=sys.stderr)
        log_error("RoadMap (geral)", e)
        houve_erro = True

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(os.path.join(DIR, "last_sync.json"), "w", encoding="utf-8") as f:
        json.dump({"last_sync_utc": now_iso}, f)
        f.write("\n")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"changed={'true' if any_changed else 'false'}\n")

    if houve_erro:
        print("ATENÇÃO: houve erro em pelo menos uma fonte, mas o restante foi sincronizado normalmente "
              "(o job NÃO falha por completo, pra garantir que o que deu certo seja publicado).", file=sys.stderr)

    print("CHANGED=" + ("true" if any_changed else "false"))


if __name__ == "__main__":
    main()
