---
title: PRD - AI Developer
status: draft
created: 2026-08-08
updated: 2026-08-08
---

# Visão Geral

Este documento descreve o PRD para o agente autônomo de programação “AI Developer”, uma solução SDD que atua como membro da equipe de desenvolvimento. O objetivo inicial é habilitar um fluxo híbrido de especificação, execução e revisão, composto por:

- Integração BMAD para planejamento, especificação e rastreabilidade.
- Orquestração baseada em eventos via GitHub Projects, Issues, Actions e webhooks.
- Execução de código em sandbox isolado usando containers para edição, testes e PRs auto gerados.
- Ciclo de correção automática com limite de tentativas e intervenção humana quando necessário.

# Problema que Resolve

Equipes de desenvolvimento enfrentam dificuldades para automatizar entrega de software com segurança e disciplina. Falta um agente que não apenas altere código, mas também respeite especificações, execute validações locais antes de abrir PRs e gerencie falhas de CI com correção iterativa e alertas claros para humanos.

# Objetivos

1. Reduzir o tempo de ciclo entre especificação e implementação autônoma.
2. Garantir que alterações de código sejam validadas localmente antes de criar PRs.
3. Capturar falhas de CI e corrigir automaticamente dentro de limites seguros.
4. Encaminhar situações ambíguas ou inseguras para revisão humana.

# Escopo Inicial

## Inclui

- Criação humana do PRD, arquitetura, épicos e histórias usando BMAD.
- Geração automática de issues e cards do GitHub a partir de specs BMAD.
- Detecção de histórias marcadas como prontas para desenvolvimento e acionamento de execução isolada.
- Configuração de sandbox Docker para checkout do código, alterações, testes e linters.
- Criação de PRs semânticos com descrição de mudanças e contexto.
- Monitoramento de GitHub Actions e correção de PRs falhos.
- Notificações HITL por Telegram para revisão e intervenção humana.
- Suporte inicial a projetos Java e Flutter no MVP.

## Exclui (para o MVP)

- Implementação de múltiplos orquestradores concorrentes.
- Suporte a múltiplos repositórios em uma única execução.
- Integrações avançadas com ferramentas de workflow além de GitHub e notificações.
- Criação automatizada de PRD, arquitetura, épicos ou histórias.
- Planejamento ou discovery automatizado além da história pronta para desenvolvimento.

# Fluxo de Trabalho Autônomo do MVP

1. A equipe humana cria o PRD, a arquitetura, os épicos e as histórias com suporte BMAD.
2. A personalização do BMAD cria a história no GitHub Projects com auxílio de MCP ou da CLI `gh`, inicialmente no estado de backlog.
3. O engenheiro move o card para o status "Ready for AI Dev".
4. Um webhook é disparado para a API do AIDEV, que armazena o evento recebido.
5. Um consumidor lê esse evento e determina qual workflow deve ser disparado, escolhendo o workflow de desenvolvimento orientado à história.
6. O agente executa um CLI de automação (OpenCode, Claude, etc.) e passa a história para revisão, sem abrir PR ainda.
7. Um novo webhook é disparado para a API do AIDEV e armazenado.
8. O consumidor lê esse evento e dispara o workflow de code review, que ao final abre uma Pull Request para revisão humana.
9. Se a build falhar, um novo webhook é disparado para a API do AIDEV e o agente recebe o evento para realizar correções.
10. O humano revisa o PR, adiciona comentários e solicita ajustes.
11. Com o pedido de ajustes, um novo webhook é disparado para a API do AIDEV, que deve aplicar as correções ou responder aos comentários.
12. Todos os eventos geram webhooks e, quando houver necessidade de intervenção humana, o agente notifica o humano responsável via Telegram.
13. As documentações devem sempre permanecer na história ou no card do GitHub Projects.
14. O agente deve manter um histórico resumido de tudo o que fez ao longo da jornada, com uma memória persistente de resumos diários.

# Principais Requisitos Funcionais

1. O sistema deve sincronizar itens do GitHub Projects v2 com cards de PRD, épicos, histórias e PRs.
2. O sistema deve iniciar uma execução quando um card for movido para "Ready for AI Dev".
3. O sistema deve armazenar todos os eventos recebidos por webhook na API do AIDEV.
4. O sistema deve consumir eventos e rotear cada um para o workflow apropriado.
5. O workflow de desenvolvimento deve receber a história como input e executar a revisão inicial do agente sem abrir PR.
6. O workflow de code review deve abrir uma PR para revisão humana ao final do processo.
7. Cada execução deve ocorrer em um container Docker isolado.
8. O sistema deve executar testes, linters e validações antes de abrir um PR.
9. O sistema deve registrar e tratar falhas de CI com um máximo de 2 a 3 tentativas.
10. O sistema deve movimentar cards para "Needs Human Action" quando necessário.
11. O sistema deve notificar por Telegram quando houver intervenção humana ou bloqueio.
12. O sistema deve manter a documentação no contexto da história ou do card do GitHub Projects.
13. O sistema deve manter uma memória persistente de resumos diários da jornada do agente.

# Critérios de Sucesso do MVP

- O agente consegue receber uma história pronta para desenvolvimento e executar o fluxo até abrir uma PR para revisão humana.
- O fluxo completo é rastreável por eventos, logs e histórico de execução.
- O agente consegue corrigir falhas simples de build e CI sem intervenção humana em pelo menos uma rodada de tentativa.
- O sistema reduz o tempo de ida e volta entre a história pronta e o PR aberto com revisão humana.
- O restante do processo permanece seguro, auditável e pausado para intervenção humana em cenários ambíguos.

# Requisitos Não Funcionais

- Segurança: o agente deve operar com permissões mínimas, sem acesso irrestrito a repositórios e segredos.
- Auditabilidade: toda ação relevante deve gerar logs estruturados com contexto da história, do evento, do workflow e do resultado.
- Isolamento: cada execução deve acontecer em container Docker efêmero, sem depender do estado do host.
- Confiabilidade: o agente deve tolerar falhas transitórias e encerrar com estado claro quando houver bloqueio.
- Observabilidade: o sistema deve permitir acompanhar o estado da execução em tempo real por logs e eventos.
- Manutenibilidade: o fluxo deve ser modular o suficiente para permitir expansão para novos workflows e integrações.

# Governança e Restrições do MVP

- O agente não deve assumir decisões de negócio fora do escopo da história.
- O agente não deve alterar segredos, arquivos sensíveis ou configurações críticas sem aprovação humana.
- O agente deve parar e pedir intervenção humana se houver ambiguidade, conflito de escopo ou falha persistente.
- O agente deve respeitar o limite máximo de 2 a 3 tentativas de correção de CI antes de parar.
- O agente deve preservar a memória em formato resumido e diário, sem expor dados sensíveis em excesso.

# Próximos Passos de Descoberta

Para continuar, preciso de mais contexto dos seguintes pontos:

- O público-alvo é a equipe interna de desenvolvimento de software.
- O MVP deve suportar inicialmente projetos Java e Flutter.
- Existem requisitos de segurança, compliance ou governança específicos para o projeto?
- Utilizar Telegram como canal de notificação no MVP.
- Você pode descrever a história ideal do início ao fim que o agente deve realizar?

> Se você preferir, posso seguir pelo caminho rápido: consolidar as lacunas em 1-2 perguntas e rascunhar o PRD com tags de [ASSUNPTION].
