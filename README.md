# Binário Cloud — Metas de Diretorias 2026

Painel de acompanhamento de metas estratégicas, com dados sincronizados do ClickUp.

## Abas
- **Rafael Alves** — Diretoria Engenharia & Operações
- **Tiago Oliveira** — Diretoria Produto & Inovação (P&D)
- **RoadMap** — Backlog técnico e melhorias

## Painel de Projetos (`projetos.html`)
Uma aba por projeto (cada projeto = uma lista do ClickUp, configurada em `automation/projetos_config.json`), com as mesmas regras de alarme do painel de metas: atrasada (prazo original vencido), pendente (prazo hoje) e pendente planejamento (sem data). Mesmo login do painel de metas.

## Torre de Controle (`torre.html`)
Visão de risco e cobrança dos mesmos projetos: plano de ação do dia, nota de risco por projeto com previsão de término (ritmo de entregas dos últimos 28 dias), fila de cobrança com mensagem pronta e registro de data prometida, pessoas, agenda, 6 temas e modo reunião. As cobranças registradas ficam salvas no navegador de quem usa. Mesmo login dos outros painéis.

🔗 Publicado via GitHub Pages.
