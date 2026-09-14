# Implementação não visual — revisão de 14/09/2026

Base de integração: `openqa-single-instance-experiment` em
`72005536ee6a8d71381a8f87dd7c637212343a3e`.
Destino de trabalho: `fix/openqa-nonvisual-accessibility-20260914`, PR #11.

## Revisão de escopo: smoke simples e programas opcionais

O requisito atualizado prioriza abrir → observar janela/conteúdo AT-SPI → fechar
pelo atalho → confirmar saída 0. A implementação compartilha esse caminho entre
live e sistema instalado. Não exige todos os controles nomeados, tarefas específicas
ou gravação do Orca. Os quatro percursos antigos ficam preservados, mas desativados
por padrão (`BIGLINUX_DEEP_APPLICATION_TESTS=0`). As descrições históricas de
obrigatoriedade abaixo aplicam-se agora apenas ao opt-in desses percursos.

A seleção `critical` não obriga instalar programas. Ausência comprovada no inventário
é não aplicável. A agregação aceita ausências da política (inclusive exclusões e
aliases não presentes), mas ainda exige todas as shards e resultados dos aplicativos
realmente selecionados. Não permite usar `skipped` para esconder crash de programa
instalado. Metadados de cobertura passam ao schema 4, para não aceitar como smoke
completo uma execução antiga que comprovou apenas abertura.

O inventário respeita `TryExec`, `Hidden` e as listas de ambientes do Desktop Entry;
programas de terminal e serviços não são certificados por este teste gráfico. A
sessão é lida de `XDG_CURRENT_DESKTOP`, sem nome KDE fixo no relatório. Os testes de
aplicativos podem ser reutilizados em GNOME; a adaptação de login/instalador permanece
responsabilidade do perfil de ISO. Ver README para parâmetros e limites.

Fontes adicionais conferidas: https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html
(semântica de TryExec/Hidden/OnlyShowIn/NotShowIn),
https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.Accessible.html
(conteúdo, interfaces e PID),
https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/enum.StateType.html
(estado da janela antes de enviar atalho) e https://open.qa/api/testapi/ (send_key).

## Mudanças de contrato

| Área | Implementação | Validação esperada |
| --- | --- | --- |
| Aparência | Needles removidas; APIs visuais/pointer bloqueadas no CI | Alterar cor, wallpaper ou ícones não exige nova referência |
| Sonda | Sem dependência de geometria; ID, PID, estados e unicidade | Alvo homônimo ou invisível não é acionado |
| Travessia | Limites de tempo, nós e fila; falha explícita em truncamento | Árvore parcial não confirma ausência |
| Teclado | Tab/setas com foco observado; ação e pós-condição distintas | Foco preso não é resgatado por `grab_focus` |
| Sessão | Sem reparo silencioso de AT-SPI e sem X11/toolkit forçado | Exercitar ambiente entregue ao usuário |
| Aplicativos | Removidas aprovações GUI por processo/X11/delegação ampla | Falta de observabilidade não vira sucesso |
| Instalação | Seleção conferida; espera de páginas obrigatória; sem reset forçado | Reinício natural continua sendo exigido pelo fluxo |
| Encerramento | Registrar saída graciosa separadamente da limpeza | SIGTERM/SIGKILL não corrigem resultado funcional |
| Orca | Introspecção e captura da saída real de seu apresentador | Falta da API ou da informação esperada bloqueia |
| Proveniência | Commit/ISO não vazios e shards completos | Resultados incompatíveis ou fracos não agregam como aprovação |
| Relatório | Função, teclado e Orca em campos separados | Ausência/incompletude não é certificação |

## Percursos implementados (não executados em uma ISO nesta revisão local)

Kate: digitar um texto único, salvar pela GUI, comprovar conteúdo no disco,
reabrir e verificar apresentação do conteúdo selecionado. Konsole: digitar um
comando na GUI, confirmar arquivo de resultado e apresentação da saída. Dolphin:
renomear pela GUI, confirmar os caminhos resultantes e o nome apresentado. Brave:
abrir fixture local isolada, acionar botão por teclado e confirmar região dinâmica
acessível e sua apresentação pelo Orca. Nenhuma ação é efetuada por screenshot.

A sonda usa um nonce por execução para evitar reutilização de saída anterior.
Fixtures contêm apenas dados sintéticos. O console faz preparação/observação;
ações de usuário passam pelo teclado de openQA. Os quatro percursos podem ser inseridos
após login nos três schedules de instalação somente com o opt-in explícito. A varredura antiga de críticos é
um teste de abertura/fechamento e não foi renomeada em uma certificação funcional.

## Compatibilidade e limitações conhecidas

O adaptador do Orca foi confrontado com a API do upstream GNOME/orca consultada
em 14/09/2026, `main` em `c69e258cd276e2013e7931c1f986550b8af60adc`.
A presença dessa API na ISO não foi presumida: introspecção exige o método
`SetLogFileForTesting`, dois argumentos string e retorno booleano. Ausência
bloqueia com motivo, sem baixar/substituir Orca nem fabricar anúncios.

A instância instrumentada não comprova ativação nativa. Captura do apresentador
não comprova emissão audível nem hardware braille. Tab/setas não cobrem todas as
estratégias de navegação de controles compostos; erro deve distinguir limitação
da automação de regressão da interface. Os seletores de nome têm traduções
explícitas, não são magicamente independentes de idioma. ID estável permite
reduzir essa dependência, mas não dispensa nomes legíveis por pessoas.

Também falta validar end-to-end o leitor no assistente live, instalação, SDDM,
desbloqueio e autorizações, recuperação de erros, demais críticos e enumeração de
todos os temas. Não há certificação humana ou integral. Um plano pode começar a
reprovar falhas antes mascaradas; não reintroduzir fallback fraco para deixá-lo verde.

## Testes e aplicação

O PR altera apenas o harness, workflows e documentação; não modifica `main` nem
substitui pacotes do desktop. Revisar o diff e executar os comandos de teste do
README. Os testes Python usam fakes/mocks para a árvore e JSONL, não uma GUI real.
Os testes Perl usam doubles confinados a `openqa/t/lib`; isso verifica o contrato
do código, não compatibilidade integral do runtime os-autoinst.

Na máquina de integração: validar a capacidade do Orca da ISO; rodar BIOS/UEFI;
inspecionar `nonvisual-contracts.json` e `orca-probe-error.json`; testar alterações
estéticas com o mesmo código; injetar falhas (nome ausente, Tab preso, evento não
anunciado, operação não persistida, sonda indisponível) e exigir reprovação. Para
investigar a árvore: `python3 /tmp/openqa-atspi-probe.py dump-widgets --state
/tmp/openqa-atspi-baseline.json --timeout 30`; não publicar conteúdo de senhas.

## Documentação oficial consultada

* openQA: https://open.qa/docs/ e https://open.qa/api/testapi/ — isotovideo,
  resultados dos módulos, teclado e capturas diagnósticas.
* AT-SPI 2.0: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Accessible.get_accessible_id.html
  — ID estável de automação, distinto de informação apresentada ao usuário.
* AT-SPI Object: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/class.Object.html
  — caminho de objeto da instância, herdado pelos objetos acessíveis.
* AT-SPI: https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Component.grab_focus.html
  e https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Action.do_action.html
  — atribuir foco/invocar ação não comprova o percurso nem a pós-condição.
* Orca upstream (capacidade inspecionada, não requisito inferido por versão):
  https://github.com/GNOME/orca/blob/c69e258cd276e2013e7931c1f986550b8af60adc/src/orca/speech_presenter.py
  https://github.com/GNOME/orca/blob/c69e258cd276e2013e7931c1f986550b8af60adc/src/orca/dbus_service.py
  https://github.com/GNOME/orca/blob/c69e258cd276e2013e7931c1f986550b8af60adc/src/orca/output_recorder.py
* Orca: https://gnome.pages.gitlab.gnome.org/orca/help/commands_controlling_orca.html
  — comandos do leitor e ativação nos ambientes que oferecem esse atalho.
* GNOME HIG: https://developer.gnome.org/hig/guidelines/accessibility.html
  e https://developer.gnome.org/hig/guidelines/keyboard.html — navegação real,
  ordem de foco e avaliação com leitor de tela.
* KDE Linux: https://linux.kde.org/docs/openqa/ — referência de combinação de
  openQA, verificações de sistema e automação por acessibilidade. Este PR não
  migra o projeto para Appium nem adiciona esse serviço à ISO.
