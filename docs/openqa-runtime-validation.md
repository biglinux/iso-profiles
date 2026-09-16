# openQA: validação real e correções de integração

## Contrato preservado

O teste comum continua sendo abrir um aplicativo presente/aplicável, observar uma
janela própria com conteúdo AT-SPI útil e enviar um atalho normal de fechamento.
O contrato padrão exige saída zero; contratos locais podem delimitar a janela de
um serviço residente ou o cancelamento de um diálogo, sem aceitar crash ou código
não declarado. Aplicativos opcionais ausentes são não aplicáveis. Não há comparação
de aparência. Percursos aprofundados com Orca continuam opt-in.

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


## Triagem das falhas de aplicativos e política v2

A matriz `34925637884` cobriu 225 entradas launchable: 173 passaram e 52 falharam.
Os diagnósticos mostraram que as entradas não têm todas o mesmo ciclo de vida.
A correção não remove falhas indiscriminadamente; ela registra a natureza de cada
caso em `application-policy.yaml`:

- `steam.desktop` deixa de ser executado porque é o bootstrap de instalação da
  Steam, conforme requisito do projeto;
- handlers de URI/arquivo e o launcher do instalador já coberto por BIOS/UEFI são
  excluídos com motivo e permanecem visíveis no inventário;
- aliases de menu são associados ao teste canônico, evitando contar duas vezes o
  mesmo programa;
- guvcview, GNOME ALSA Mixer, QEFIEntryManager e o modo X11 do YAD são executados
  somente quando a capacidade correspondente existe;
- serviços residentes e hosts compartilhados precisam fechar sua janela observada,
  sem crash; o processo pode permanecer apenas nos contratos nomeados;
- diálogos transitórios aceitam saída 1 somente quando ela representa cancelamento
  explicitamente declarado;
- interfaces pesadas recebem prazo de publicação/encerramento maior, ainda limitado.

A agregação usa cobertura schema 5 e métricas schema 3, valida que o resultado
corresponde exatamente ao contrato do inventário e separa não aplicável de aprovado.
Um erro da sonda de capacidade é falha, não ausência. Saída 1 não é globalmente
aceita. `mpv`, `lstopo`, `urxvt`, Timeshift e qualquer outro caso que continue
abortando ou sem janela AT-SPI permanecem vermelhos até correção real.


## Matriz de contratos de aplicações e bloqueios seguintes

A matriz real `34938679011`, fonte `9129cdc`, confirmou que `steam.desktop` foi excluído como bootstrap e não executado. O inventário classificou 215 entradas lançáveis: 175 passaram, 37 falharam e 3 ficaram não aplicáveis por capacidade ausente. O agregador recusou corretamente uma aprovação cuja saída `0` havia sido serializada como texto, revelando um defeito no produtor.

A correção converte o valor do supervisor para número antes do JSON, mantém o agregador estrito, prioriza aplicações recentes em consultas PID-scoped, percorre irmãos de modo justo e observa a janela exata de processos compartilhados. Aplicativos com ação `app.quit` documentada usam um único Ctrl+Q. Crashes e janelas sem AT-SPI permanecem falhas.


## Superfícies auxiliares de primeira execução

A matriz `34938679011` mostrou GIMP e LibreOffice com uma janela inicial ativa
sobre a janela principal. Enviar apenas `Ctrl+Q` nessa superfície não comprovou
o encerramento da aplicação. A correção não cria uma heurística global: somente
contratos explicitamente marcados com `dismiss_auxiliary: true` podem enviar um
único `Alt+F4` à superfície ativa e, depois, o `Ctrl+Q` documentado.

A sonda exige que o foco retorne a outra janela de nível superior do mesmo PID.
Em contratos de processo compartilhado, a identidade exata dessa nova janela
substitui a identidade da superfície inicial antes de observar o fechamento.
Outros aplicativos que usam `Ctrl+Q` não recebem uma ação preliminar inferida.
O relatório registra `pre_close_action` separadamente, e qualquer falha ao
confirmar a transição permanece vermelha.

## Baseline durante transições do registro AT-SPI

Na matriz `34944015215`, fonte `c5f5578`, o primeiro shard de aplicações
encerrou antes de testar qualquer entrada: um provedor saiu entre a leitura da
quantidade de janelas e a consulta da primeira janela. A sonda tratou essa
corrida transitória como uma baseline estruturalmente inválida.

A baseline agora repete **a leitura completa** sob um único prazo e só grava o
arquivo depois de obter um retrato coerente. Uma entrada residual é ignorada
apenas quando o PID publicado já não existe e a consulta é global de baseline;
consultas restritas ao aplicativo testado continuam retornando falha. Erros de
provedores vivos, limites de árvore e leituras parciais continuam bloqueantes.
Assim, a limpeza não recebe uma baseline incompleta e um processo vivo não é
silenciosamente dispensado.

## Foco direcionado sem varrer aplicações alheias

Na execução UEFI `34944015215`, fonte `c5f5578`, o instalador já havia exposto
os controles esperados e o teste conhecia a identidade do botão-alvo e seu PID.
Mesmo assim, a consulta seguinte de foco reiniciava a enumeração do registro
AT-SPI inteiro e consumiu o prazo antes de retornar ao aplicativo conhecido.

Cada janela e controle agora carrega também o índice do aplicativo no registro
AT-SPI. Esse índice é apenas uma dica efêmera: a consulta o visita primeiro e
confirma que o PID ainda pertence à árvore do lançamento. Se o índice mudou ou
aponta para outro PID, a busca volta à ordem limitada normal. Quando a dica é
válida, a observação de foco termina dentro daquele aplicativo e não percorre
provedores sem relação com o instalador.

A mudança não escolhe foco, não aciona controles e não transforma ausência em
sucesso. A identidade, o PID e o estado `FOCUSED` continuam obrigatórios; erros
do provedor-alvo permanecem bloqueantes. Regressões cobrem prioridade da dica,
índice obsoleto, propagação do índice nos controles e encaminhamento Perl →
sonda convidada. A instalação ainda depende de nova execução real.

## Conteúdo e fechamento no aplicativo já identificado

A mesma matriz `34944015215` mostrou cinco aplicações em que a janela havia sido
aberta e associada ao PID correto, mas a verificação simples de conteúdo voltou
a percorrer todo o registro AT-SPI e expirou antes de retornar ao provedor-alvo.
Isso afetou, entre outros, Brave, RustDesk, Big Kernel Manager, BigLinux Config
e Stoken. Aumentar o prazo global apenas tornaria a suíte mais lenta e ainda
permitiria que um provedor alheio consumisse o orçamento.

O resultado de abertura agora conserva o índice do aplicativo que produziu a
janela. As verificações subsequentes de conteúdo e de janela ativa encaminham
essa dica e revalidam o PID antes de usá-la. Quando a dica é válida, a sonda
inspeciona integralmente aquele aplicativo e encerra a enumeração antes de tocar
em provedores sem relação com o teste. Quando a dica está fora do intervalo ou
aponta para outro PID, a busca limitada normal continua; portanto, a otimização
não transforma um índice reutilizado em identidade.

A identidade exata da janela continua sendo usada para confirmar o fechamento
de processos compartilhados. A dica não substitui PID, identidade, estado
`SHOWING`/`ACTIVE`, conteúdo útil ou código de saída. Falha do provedor-alvo,
árvore incompleta, janela vazia e encerramento não observado continuam
bloqueantes. Os testes cobrem propagação abertura → conteúdo → fechamento,
parada antes de provedores alheios e fallback de índice obsoleto.

## Diálogos iniciais confirmados no código-fonte

A ampliação do contrato auxiliar permanece explícita e restrita. Além de GIMP
e LibreOffice, o código-fonte dos próprios projetos confirma superfícies de
primeira execução em Qt Designer (New Form), BigOCR PDF (boas-vindas ou
dependências), Editor PDF do BigOCR (ajuda inicial), Big Video Converter
(boas-vindas) e WebApps Manager (boas-vindas).

Essas entradas recebem `dismiss_auxiliary: true`: somente quando a janela ativa
é um diálogo ou existem várias janelas de nível superior, o teste envia um único
`Alt+F4`, comprova o retorno a outra janela do mesmo PID e então envia o
`Ctrl+Q` já documentado pelo aplicativo. A regra não é inferida por nome, toolkit
ou presença de um botão; qualquer outro programa continua recebendo apenas seu
atalho configurado. Falha ao fechar o diálogo, reencontrar a janela principal ou
encerrar normalmente permanece vermelha.


## Contratos explícitos para KRunner e qBittorrent

A política não usa mais `Alt+F4` nesses dois casos. O QML oficial do KRunner
trata `Escape` ocultando a janela do runner, enquanto preserva o serviço
residente. Por isso o smoke exige o desaparecimento daquela janela exata, sem
exigir que o processo da sessão termine. O qBittorrent registra `Ctrl+Q` como
a ação **Exit** e conecta essa ação a `QApplication::exit()`. Seu contrato é
portanto estrito: a janela deve ser acessível e o processo testado deve terminar
normalmente com código zero. Esses contratos são individuais; `Escape` e
`Ctrl+Q` não são inferidos para outros aplicativos.

## Baseline mínima e resposta serial compacta

A primeira reexecução do runtime v6 (`34983271661`) revelou dois efeitos
independentes da mesma coleta excessiva. Um shard concluiu a leitura, mas o JSON
hexadecimal com todos os nomes, papéis e contagens de filhos ultrapassou o
buffer de captura serial: o marcador inicial saiu da janela observada e o host
recebeu apenas o fim da resposta. No instalador UEFI, a baseline curta gastou o
prazo consultando semântica de janelas que ainda não seriam usadas e terminou
como enumeração incompleta.

A baseline de lançamento agora consulta somente o PID da aplicação, a
quantidade de janelas de nível superior e a identidade de cada proxy. Esses são
os únicos dados necessários para formar as chaves persistidas que distinguem
janelas anteriores das janelas abertas pelo teste. Nome, papel, título e árvore
de conteúdo continuam sendo lidos apenas nas operações que realmente os
validam.

O arquivo no convidado permanece autoritativo e conserva todas as chaves e PIDs
necessários para `wait-open` e `cleanup`. Pela serial, a operação devolve apenas
`status`, quantidade de janelas, memória disponível e desktop. Isso elimina o
payload proporcional ao número de janelas sem relaxar a prova: erro de provedor
vivo ou não identificado continua invalidando a leitura; somente um PID já
encerrado pode desaparecer durante a enumeração. O prazo de três segundos da
baseline por lançamento não foi ampliado.

## Matriz compacta v7 e correções de atribuição v8

A matriz real `34985013609`, fonte `1d185a6f`, confirmou que a baseline
compacta eliminou o colapso total do primeiro shard: os quatro shards voltaram
a executar sua partição do inventário. O inventário registrou 288 entradas,
215 lançáveis, 70 exclusões justificadas e três aliases. Foram testadas 212
entradas: 160 passaram e 52 falharam. Os relatórios de todos os planos e o
consolidado foram publicados, enquanto o gate permaneceu reprovado.

A triagem mostrou que 25 dessas falhas ocorreram **depois** de a aplicação já
ter comprovado janela própria, conteúdo acessível e fechamento normal. Uma
varredura global de limpeza encontrava um provedor AT-SPI alheio e já encerrado
e convertia retroativamente a aplicação em falha. A limpeza agora separa duas
provas: primeiro encerra e verifica somente os grupos de processos pertencentes
ao lançamento; depois tenta a limpeza global. Uma leitura global inconclusiva
pode ser registrada como `cleanup_degraded` apenas quando todos os processos
do teste já estão comprovadamente ausentes. Janela remanescente, PID próprio
vivo ou falha real da limpeza continuam bloqueantes.

Quatro contratos de processos residentes também mantinham no registro o objeto
de uma janela já ocultada. `wait-close` agora lê os estados de nível superior e
considera a identidade exata encerrada quando deixa de estar `SHOWING` ou fica
`DEFUNCT`. A abertura exige o inverso: a janela deve estar `SHOWING` e não pode
estar `DEFUNCT`. A existência de um proxy ou de um processo residente não é
suficiente para aprovar.

As verificações de conteúdo, foco e fechamento carregam a identidade exata da
janela, a árvore do processo lançado e a dica revalidada do aplicativo AT-SPI.
Isso evita que provedores antigos consumam o prazo antes de Brave, RustDesk,
gerenciadores BigLinux e outros aplicativos já identificados, sem aumentar
globalmente os timeouts. Uma dica obsoleta sempre cai na busca normal e nunca
substitui PID, identidade ou estado.

Superfícies iniciais embutidas em uma única janela, como `Adw.Dialog`, não são
visíveis como um segundo top-level. Nos contratos explicitamente revisados,
uma única tecla `Escape` devolve o controle à aplicação antes do `Ctrl+Q` já
documentado. Diálogos top-level continuam usando um único `Alt+F4` e precisam
comprovar a transição para a janela principal. Audio Converter e Big Network
Info foram incluídos nesse grupo porque seus próprios códigos exibem a tela de
boas-vindas na primeira ativação e registram `Ctrl+Q` para a ação de sair.
Outros aplicativos não recebem essa sequência.

No instalador, a identidade do controle-alvo conhecido passa a ser localizada
pela hierarquia estrutural antes de ler a semântica de todos os irmãos. Se o
controle existe, mas ainda não tem foco, a resposta é `target-not-focused` e a
navegação envia apenas `Tab`; o teste não força foco nem aciona o controle por
AT-SPI. Incompletude sem o alvo continua bloqueante.

Antes da publicação desta revisão, passaram 283 testes Python e 168 asserções
Perl, além da política não visual, compilação Python, sintaxe Bash e
`git diff --check`. A integração GTK/AT-SPI e a matriz da ISO continuam sendo
provas separadas obrigatórias; esses testes locais não aprovam a instalação nem
as aplicações reais.

## Matriz v8 e transferência de escopo v9

A matriz real `35003218961`, fonte `1b055f6a`, executou os quatro shards e
publicou todos os relatórios. A cobertura dos shards permaneceu completa: 288
entradas no inventário, 215 lançáveis, 70 exclusões justificadas, três aliases
e 212 entradas efetivamente testadas. Foram 121 aprovações, 91 falhas e três
resultados não aplicáveis por capacidade ausente. O consolidado também inclui
14 verificações adicionais do plano BIOS; elas não são novos aplicativos e não
devem ser somadas ao inventário.

A regressão não foi tratada com aumento global de timeout nem com exclusões.
Oitenta das 91 falhas tinham a mesma evidência: `wait-open` já havia comprovado
PID, índice AT-SPI e identidade exata da janela, mas a consulta seguinte expirava
em `application enumeration exceeded its deadline`. O índice do registro podia
mudar quando um provedor antigo desaparecia. A identidade exata era priorizada
somente se o índice antigo ainda coincidisse; caso contrário, a sonda ignorava a
janela conhecida e voltava a percorrer provedores sem relação com o teste.

A identidade da janela agora prevalece sobre a posição antiga no registro,
sempre dentro da árvore de PIDs do lançamento. O índice continua sendo apenas
uma dica de ordenação: cada candidato tem o PID revalidado e uma dica obsoleta
não aprova nada. Conteúdo, janela ativa e fechamento reaproveitam a identidade
exata retornada pela etapa anterior. Um teste de regressão desloca o aplicativo
do índice 2 para o índice 1 e exige que a sonda encontre a mesma janela sem
consultar provedores mais antigos.

A execução UEFI confirmou que a correção anterior de foco funcionou: o teste
alcançou e acionou o botão **Instalar** sem forçar foco ou usar coordenadas. O
bloqueio seguinte ocorreu na troca do launcher GTK para o Calamares Qt. Ambos
pertencem à mesma árvore supervisionada, mas a primeira consulta da página Qt
não carregava a dica do aplicativo GTK e percorria o desktop até expirar.

As consultas de widgets agora podem receber o último índice AT-SPI comprovado.
Elas começam perto dessa posição, revalidam a árvore de processos do lançamento
e concluem um aplicativo candidato por vez. Quando um aplicativo da mesma árvore
expõe uma correspondência única, a busca termina antes de provedores alheios. O
Calamares preserva o PID raiz do launcher como proveniência, memoriza o índice
de cada controle encontrado e usa essa dica limitada na página seguinte. Um
teste simula a transição GTK no índice 14 para Qt no índice 15 e exige parada
antes de um terceiro processo não relacionado.

As 11 falhas restantes da matriz v8 não foram automaticamente convertidas em
aprovação. Cinco não expuseram janela AT-SPI (incluindo lstopo e urxvt), o mpv
abortou com código 134, o Timeshift registrou erro crítico, o Audio Converter não
encerrou após `Escape` seguido de seu `Ctrl+Q`, dois fluxos do LibreOffice não
concluíram o contrato de fechamento e três KCMs ainda precisam ser reavaliados
após a correção estrutural. Esses casos continuam vermelhos até nova evidência.


## Runtime v10: posição AT-SPI é dica, não identidade

A matriz real `35006675104` revelou uma regressão de desempenho: 83 das 91
falhas de aplicativos terminaram em `application enumeration exceeded its
deadline`. Quase todas reutilizavam o índice 14 observado por um processo de
sonda anterior. O índice é apenas a posição momentânea do provedor sob a raiz
do registry; processos curtos podem entrar e sair entre duas consultas.

A busca agora tenta essa posição uma única vez, sempre revalidando o PID, e
depois retoma a ordem normal do provedor mais novo para o mais antigo. Ela não
percorre posições numericamente próximas ao índice antigo. Assim, um alvo novo
não fica atrás de dezenas de chamadas D-Bus a provedores sem relação com o
teste. O escopo por árvore de processos, a identidade exata da janela e os
limites originais continuam obrigatórios.

A mesma execução mostrou que o último Continue do frontend GTK antecede o
processo Qt do Calamares. Nesse ponto específico, o harness descarta o índice
GTK, mas conserva o PID raiz supervisionado. A primeira âncora da interface Qt
redescobre um descendente dessa mesma árvore e passa a registrar seu novo
índice. Nenhuma busca global por título, clique por coordenada, foco forçado ou
aumento de timeout foi acrescentado. A correção precisa ser confirmada por uma
nova matriz da ISO.

## Runtime v12: escopo explícito do lançamento após reparenting

A matriz real `35038811476`, fonte `48d178c7`, manteve a cobertura completa do
inventário: 288 entradas, 215 lançáveis, 70 exclusões justificadas, três aliases,
212 testes executados e três resultados não aplicáveis. Foram 121 aprovações e
91 falhas. A Steam permaneceu excluída como instalador bootstrap e não foi
executada.

O resultado concentrou 82 das 91 falhas no mesmo diagnóstico:
`application enumeration exceeded its deadline`. A evidência não indicava 82
aplicativos comprovadamente defeituosos. Em um caso representativo,
`big-driver-manager.desktop`, `wait-open` comprovou em 2,04 s o PID 5621, o
índice AT-SPI 14 e a identidade exata
`/org/a11y/atspi/accessible/2147483652`, todos pertencentes ao lançamento de
PID 5613. Após os dois segundos de estabilização, a consulta de conteúdo com
esses mesmos identificadores consumiu os 20 segundos e expirou antes de chegar
ao provedor correto.

Cada aplicação é iniciada por `gui_supervisor.sh` em uma nova sessão com
`setsid`. Wrappers e launchers podem criar a interface em outro processo e
terminar ou reparentar esse processo; a árvore baseada apenas em `PPid` deixa de
representar a propriedade do lançamento, embora o filho continue no mesmo grupo
de processos supervisionado. A posição no registro AT-SPI também continua sendo
apenas uma dica transitória.

O escopo de leitura passa a combinar, sem busca por nome ou título:

- a árvore de descendentes ainda observável do PID raiz;
- os PIDs de janela já comprovados pelas etapas anteriores;
- os membros vivos do grupo de processos criado para o PID raiz supervisionado.

O alargamento por grupo só é habilitado quando o chamador fornece
explicitamente esse PID raiz. Um PID obtido de uma janela arbitrária, do
assistente live ou de outro objeto da sessão continua limitado à sua árvore de
descendentes. Isso impede que uma consulta de acessibilidade importe outros
processos apenas porque eles compartilham o grupo da sessão gráfica. O PID da
janela e o PID raiz trafegam separadamente pelas operações de conteúdo, foco e
fechamento.

O grupo é obtido por `NSpgid` em `/proc/PID/status`; para kernels ou fixtures sem
essa linha, usa-se o campo `pgrp` de `/proc/PID/stat`. O parser localiza primeiro
o último `)` do campo `comm`, que pode conter espaços e parênteses, antes de ler
o quinto campo. O PID de uma janela conhecida não autoriza importar o grupo
dele: somente o grupo do lançamento supervisionado amplia o escopo. Isso evita
aceitar serviços do desktop que por acaso compartilhem outro grupo.

O encerramento do líder do grupo também deixou de ser interpretado como fim da
aplicação enquanto qualquer PID do escopo comprovado continuar vivo. Essa regra
vale para abertura X11/AT-SPI, conteúdo, foco e fechamento. A rotina genérica de
limpeza não foi ampliada para grupos encontrados a partir de janelas residuais;
ela continua limitada às árvores desses PIDs, enquanto a limpeza do lançamento
segue sob responsabilidade do supervisor já existente.

A publicação intermediária do runtime v11 validou a primitiva de grupo em CI, mas
a matriz real `35049852378` mostrou que a integração ainda estava incompleta: os
quatro shards e os fluxos BIOS/UEFI continuaram registrando
`application enumeration exceeded its deadline`, e o UEFI terminou uma leitura
do instalador como `incomplete tree after 20 nodes`. As operações Perl de
conteúdo, foco e fechamento ainda enviavam apenas o PID da janela e o índice
AT-SPI; o PID raiz supervisionado não chegava à sonda Python. O runtime v12
propaga separadamente `--root-pid` por `atspi.pm` e `calamares.pm`, inclusive em
`wait-open`, widgets, foco, conteúdo, janela ativa e fechamento. Regressões
diretas conferem os argumentos enviados e o escopo persistido após a abertura.

Foram acrescentadas regressões para líder já encerrado, filho reparentado, PID
de janela pertencente a grupo não autorizado, fallback de `/proc/PID/stat`,
escopo vazio e espera de abertura após o reparenting. A integração GTK/AT-SPI
agora contém ainda um launcher real que cria a janela no seu grupo, encerra e
deixa o processo GTK reparentado; o CI deve comprovar abertura, conteúdo,
foco, `Alt+F4` e desaparecimento da janela sem screenshots.

Na árvore local desta revisão passaram 297 testes Python e 180 asserções Perl,
além da política não visual, compilação Python, sintaxe Bash e
`git diff --check`. PyGObject, `xdotool`, ShellCheck e actionlint não estavam
disponíveis no executor local; a integração real e essas verificações continuam
obrigatórias no CI antes da publicação. A correção não aprova a ISO: BIOS, UEFI
e os quatro shards precisam ser reexecutados, e as falhas reais restantes —
como abort do mpv, janelas X11 sem AT-SPI e encerramentos não comprovados —
continuam bloqueantes.

### Superfícies transitórias em sequência

A mesma matriz mostrou dois comportamentos diferentes no primeiro uso do
LibreOffice. O Base perdeu toda a sua janela quando o harness fechou o assistente
como se houvesse obrigatoriamente uma janela principal posterior; por isso o
Base agora recebe diretamente o atalho documentado `Ctrl+Q`, sem uma ação
preliminar. No Impress, após fechar o seletor inicial, o diálogo “Tip of the Day”
apareceu antes do `Ctrl+Q` e interceptou o encerramento.

Para contratos explicitamente marcados com `dismiss_auxiliary`, o harness agora
pode fechar até três superfícies observadas em sequência. Cada passo exige uma
janela ativa do mesmo PID e do mesmo lançamento supervisionado; depois de cada
tecla há nova observação estável antes de qualquer próxima ação. Um diálogo
separado recebe `Alt+F4`; uma sobreposição libadwaita no mesmo top-level recebe
`Escape`. Só então é enviado o único atalho de saída do aplicativo. Não há
sequência cega, clique, busca por título ou aprovação baseada em processo vivo.
As ações preliminares ficam registradas no resultado.
