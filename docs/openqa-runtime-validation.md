# openQA: validação real e correções de integração

## Contrato preservado

O teste comum continua sendo abrir um aplicativo presente/aplicável, observar uma
janela própria com conteúdo AT-SPI útil, enviar um atalho normal de fechamento e
observar saída zero. Aplicativos opcionais ausentes são não aplicáveis. Não há
comparação de aparência. Percursos aprofundados com Orca continuam opt-in.

Relatórios são emitidos também na falha. Publicar um relatório de falha não
aprova a ISO; não se pode trocar uma falha funcional por sucesso do upload.

## Resultados efetivamente observados

- Execução `34919737154`, fonte `e815379`: o prefixo live passou nos seis planos,
  mas a sessão ainda não estava pronta para os testes seguintes. Houve falhas nos
  seis planos, com relatórios por plano e consolidado publicados. Não é aprovação
  da instalação nem dos aplicativos.
- Correção `06056ced9d0d02b8c18c7340f7d96c0e284f4e66`: espera a sessão gráfica,
  endpoints de display e barramento AT-SPI realmente conectáveis, sem repará-los.
  Árvore `2cceb77f534e1854fa314729a0469edbecbd54ae`; 213 testes Python e 64
  asserções Perl passaram no CI `34921855995`.
- Execução `34922055602`, fonte `06056ced`: o prefixo live e a prontidão da sessão
  passaram em BIOS e UEFI. No plano BIOS, 11 aplicativos chegaram ao smoke, seis
  passaram (Base, Math, Start Center, Writer, filtros XSLT e Dolphin) e cinco
  falharam (Brave, GIMP, Calc, Draw e Impress). Os módulos do instalador ainda
  falharam; os relatórios por plano foram publicados. Os shards ainda não estavam
  encerrados quando essa observação foi registrada. Isso não certifica a ISO.

## Correções motivadas pelos resultados

### Propriedade das janelas do instalador

`installer_launch.pm` esperava uma janela sem restringir o processo; uma nova
janela do Plasma podia ser aceita como a abertura do instalador. `assert_page`
também descartava o PID anterior e percorria o desktop inteiro.

Agora a primeira janela deve pertencer à árvore do processo iniciado. O PID do
wrapper é preservado entre páginas: seus diálogos GTK e o Calamares Qt podem ter
PIDs diferentes sem perder a proveniência. Ausência, ambiguidade ou erro da
sonda continuam sendo falhas, sem aceitar qualquer outra janela como substituta.

### Consultas limitadas ao aplicativo

A enumeração resolve o PID de cada aplicação antes de consultar seu nome e
suas janelas. Quando existe escopo, não lê controles de outros processos. Isso
reduz interferência do Plasma e de aplicações que não estão sendo testadas.
Falhas da aplicação-alvo ou de identificação não são ignoradas.

A busca simples de conteúdo usa travessia preguiçosa: termina no primeiro
conteúdo útil, visita um objeto compartilhado uma vez, distingue compartilhamento
de ciclo de ancestrais e não encerra a busca ao receber um filho nulo. Sem
conteúdo e com filhos ausentes, retorna inconclusivo; nunca aprovação por silêncio.
Prazos, limite de nós e limite de referências impedem trabalho ilimitado.

### Atalho de sair versus fechar uma janela

GIMP e os lançadores padronizados do LibreOffice usam `Ctrl+Q`, que seus manuais
identificam como sair da aplicação. Nos demais aplicativos o padrão permanece
`Alt+F4`. A variável `BIGLINUX_APPLICATION_CLOSE_KEY` ainda permite override
explícito. É enviado um único atalho normal, não uma sequência de tentativas.
Saída desconhecida, saída não zero ou processo sobrevivente continuam falhando.
Não são usadas ações internas, sinais ou comandos de serviço para aprovar.

A captura de diagnóstico de uma falha ocorre antes da limpeza remover as
janelas. Não é utilizada para comparar tema ou determinar aprovação.

## Testes e limites

As regressões acrescentadas cobrem a troca de PID GTK/Qt, proibição de busca
global no instalador, enumeração restrita, falhas do alvo, grafos compartilhados,
filhos nulos, limites de trabalho e escolha do atalho. Testes Perl usam doubles
somente em `openqa/t/lib`; não se confundem com a execução real do isotovideo.

As falhas observadas não autorizam excluir programas presentes para tornar a
matriz verde. A integração do instalador e o término de todos os shards devem
ser consultados nos resultados de cada execução. A exposição AT-SPI não é
certificação de fala, braille ou usabilidade integral para pessoas cegas.

## Fontes oficiais

- AT-SPI, identificação por processo (consulta ao barramento, não ao widget):
  https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Accessible.get_process_id.html
- GIMP, comando Quit e Ctrl+Q:
  https://docs.gimp.org/3.0/en/gimp-file-quit.html
- LibreOffice, atalhos gerais:
  https://help.libreoffice.org/latest/en-US/text/shared/04/01010000.html
- openQA, teclado e captura de diagnóstico:
  https://open.qa/api/testapi/
- Wrapper do instalador e filhos sequenciais GTK/Qt:
  `biglinux/biglinux-livecd`, `biglinux-livecd/usr/bin/calamares-biglinux_polkit`
  e `biglinux-livecd/usr/bin/calamares-biglinux` (upstream consultado, não prova
  de identidade byte a byte com o pacote da ISO).

## Esperas de leitura e publicação inicial da janela

Na execução UEFI `34923508645`, o escopo corrigido encontrou a janela do filho
`4478` da árvore `4451`, em vez da janela do Plasma. A consulta seguinte de
controle terminou com leitura incompleta em cerca de 7,4 segundos, embora o
prazo do chamador fosse 60 segundos. Isso confirma uma falha da espera; não
comprova que o aplicativo responderia ao repetir a leitura.

A espera agora repete somente a observação de leitura dentro do prazo original.
Cada tentativa descarta os dados incompletos e precisa obter uma consulta
completa do mesmo escopo. Não repete ações, não move foco, não reinicia o
barramento e não aumenta prazos. Erro persistente continua inconclusivo
bloqueante. Limite estrutural de árvore não é repetido. Exceções de enumeração
passam a identificar PID/índice/tipo, sem publicar o texto arbitrário da exceção.

A documentação AT-SPI distingue o tempo de chamada do período de inicialização
da aplicação, durante o qual ela pode bloquear temporariamente:
<https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/func.set_timeout.html>.
A inspeção do fonte upstream mostrou que o período de inicialização era
aplicado a cada aplicação recém-descoberta pela *sonda*, mesmo que o aplicativo
já estivesse rodando. Isso podia dar a uma chamada até 15 segundos dentro de
um smoke cujo prazo era 8 segundos. Agora o limite de chamada é 800 ms (o
padrão normal upstream), sem uma segunda carência por aplicação; as esperas
externas continuam permitindo a inicialização. As leituras transitórias de
janela, conteúdo, foco e controles são repetidas até o mesmo prazo, sem
repetir ações nem converter um erro persistente em aprovação.
Fonte: `GNOME/at-spi2-core`, `atspi/atspi-misc.c`, função `set_timeout`,
blob `f3124965f07ddf2db5f67bacffbc228cb977eeb1` consultado no upstream.

No mesmo run, o shard 0 concluiu 55 smokes: 43 passaram e 12 falharam. Konsole e
SMPlayer esgotaram o orçamento de nós. A busca percorria descendentes de menus
ocultos antes do conteúdo visível. Agora poda ramos não `SHOWING` ou `DEFUNCT`
antes de ler seus filhos, sem aumentar o limite ou aceitar conteúdo oculto.
Isso segue a definição de `SHOWING`, que inclui os ancestrais do controle:
<https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/enum.StateType.html>.
Essa correção ainda precisa de confirmação na ISO; não converte as falhas do
run anterior em aprovações. No BIOS do mesmo run, 5 de 11 smokes passaram e 6
falharam; a troca para Ctrl+Q não resolveu todos os encerramentos observados.


## Publicação de foco após a troca de janela

Na execução UEFI `34925637884`, fonte `f2749233`, a leitura e a navegação
avançaram além do erro anterior: o aviso de firmware foi confirmado e a página
principal expôs o botão Instalar. O bloqueio seguinte ocorreu quando a sonda
recebeu dois objetos com `FOCUSED`. Ela retornava imediatamente, sem aguardar o
prazo de cinco segundos que seu chamador fornecia para obter o foco.

A observação agora aguarda um foco único até o prazo original. Não escolhe entre
candidatos, não força foco e não envia teclas durante essa espera. Se a duplicidade
persistir, continua reprovando e registra até oito identidades/papéis (com limites
de comprimento), sem incluir valores dos campos. A nova mensagem permite distinguir
composição de widget, duplicidade persistente e transição; nenhuma causa específica
foi presumida sem essa evidência. São cinco regressões adicionais de estado e
limite. A aprovação da instalação continua dependendo de execução real.
