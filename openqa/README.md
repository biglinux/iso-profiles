# BigLinux — validação funcional e acessibilidade não visual

O gate usa `isotovideo` diretamente, no container fixado por digest em
`openqa-image.txt`. Não há servidor openQA nesse caminho. Os planos, máquinas,
shards e limites de execução continuam definidos em `release-gate.yaml`.

## Critério de aprovação

Comparações de screenshots, coordenadas de mouse e espera por estabilização da
imagem não são critérios de aprovação. Capturas e vídeo são apenas diagnóstico.
Não existem needles ativas. `production/check-nonvisual.py` impede a reintrodução
dessas APIs nos módulos de teste.

O teste padrão é **simples e genérico**: executar o programa instalado, aguardar
uma janela da aplicação, observar ao menos um conteúdo/controle útil no AT-SPI e
enviar um único atalho normal de fechamento. O resultado final segue o contrato
de ciclo de vida daquela entrada: normalmente a janela e o processo precisam
encerrar com saída zero; processos residentes precisam fechar a janela observada
sem crash; diálogos transitórios só aceitam os códigos de cancelamento declarados.
Não percorre todas as funções ou todos os controles. O Orca não precisa estar
rodando e sua API de gravação não é requisito do smoke.

`lib/application_smoke.pm` é compartilhado pela varredura live e pela seleção de
aplicativos instalados. Há uma breve estabilização (2 s), uma consulta limitada de
conteúdo e um prazo de fechamento (15 s). O atalho padrão é `Alt+F4`; contratos
podem declarar `Ctrl+Q` quando esse é o comando documentado de sair. Não há clique
nem ação interna de fechar. Uma janela inativa não recebe o atalho. Saída diferente
da lista explícita, falta de janela/conteúdo, crash ou necessidade de matar o
processo reprovam.

A política é **adaptável à ISO**, não uma lista de pacotes obrigatórios. Entradas
configuradas ausentes aparecem como `skipped` / não aplicável, nunca como aprovação.
`TryExec`, `Hidden`, `OnlyShowIn` e `NotShowIn` distinguem ausências e aplicabilidade
à sessão. Comandos `Terminal=true` e serviços sem janela ficam fora do smoke gráfico.
Um lançador presente mas quebrado (sem `Exec` válido, ou comando que falha) continua
sendo erro; não é convertido em ausência para esconder falhas de empacotamento.

`application-policy.yaml` usa o schema 2 e mantém a decisão auditável:

- `exclude`: serviços, handlers ou instaladores bootstrap que não representam um
  aplicativo gráfico autônomo. `steam.desktop` está aqui porque a ISO entrega um
  instalador que baixa a Steam, não o cliente já instalado;
- `aliases`: duas entradas de menu para a mesma função são cobertas por um único
  lançamento canônico, sem apagar a entrada do inventário;
- `contracts`: `standard`, `shared-window` e `transient-dialog`, com atalhos,
  prazos, códigos de saída e capacidades explícitas;
- `requires`: câmera, placa ALSA, variáveis UEFI ou sessão X11 podem tornar uma
  entrada **não aplicável naquele ambiente**, mas erro da própria checagem é falha.

Não existe aceitação global de saída 1. Somente diálogos nomeados podem declarar
cancelamento 1. Fechar a janela de um processo residente também não permite crash
ou código de saída inesperado; a limpeza posterior continua fora do veredito.
Aplicativos que realmente abortam ou não expõem AT-SPI permanecem reprovados.

A seção histórica `critical` seleciona smokes depois da instalação. Ausência de
qualquer item não reprova. As quatro shards live descobrem os aplicativos desta ISO
em `/usr/share/applications`, incluindo aplicativos GNOME sem novos scripts.
Os módulos de boot/login/instalador continuam específicos do perfil da distribuição;
a portabilidade dos smokes não significa que o login SDDM já suporte GDM.

**Percursos profundos são opt-in:** definir `BIGLINUX_DEEP_APPLICATION_TESTS=1` em
`settings` de um plano habilita `nonvisual_tasks.pm` e o diagnóstico extra do Brave.
O padrão é `0`. Ausências também são ignoradas nesses percursos. Somente com esse
opt-in o adaptador de fala do Orca e as pós-condições específicas são exigidos.
Não é necessário ampliar esses percursos para cada aplicativo da ISO.

Parâmetros opcionais: `BIGLINUX_APPLICATION_SETTLE_SECONDS` (0–10),
`BIGLINUX_APPLICATION_CONTENT_TIMEOUT` (1–120),
`BIGLINUX_APPLICATION_CLOSE_TIMEOUT` (1–120) e `BIGLINUX_APPLICATION_CLOSE_KEY`
(`alt-f4` ou `ctrl-q`). A política pode definir limites próprios e ainda limitados por aplicativo;
a varredura usa uma amostra de memória, sem amostragem
repetida por aplicativo. Uma mudança apenas estética não exige novo teste.

## Semântica e teclado

Seletores aceitam PID, identificador acessível estável, janela, papel e nomes
localizados. Correspondência ambígua reprova. O identificador de automação não
substitui o nome compreensível para quem usa leitor de tela. O caminho do objeto
AT-SPI é identidade apenas durante a execução, não um ID estável entre versões.

A ativação usada pelos testes navega pelo teclado e observa o foco após cada
tecla, com detecção de ciclos e limite de passos. Não usa `grab_focus` para
contornar uma barreira de navegação. Controles compostos podem precisar de uma
estratégia específica além de Tab e setas; essa limitação não deve ser escondida
por clique programático. A operação Python de ação AT-SPI permanece separada
para diagnóstico e não representa prova de alcance por teclado.

Toda espera obrigatória deve ser verificada. Desaparecimento exige uma consulta
completa que confirme ausência: erro no barramento, timeout, limite de nós ou
árvore parcial resultam em **inconclusivo bloqueante**, nunca em sucesso. Para
seleções, verificar `checked`/`selected`, não somente existência do controle.

O harness não reinicia silenciosamente o barramento, não força X11, outro plugin
de toolkit ou variáveis de acessibilidade na aplicação. A preparação de fixtures
usa console; a ação avaliada usa a GUI. Postcondições em arquivos são observações,
não uma implementação alternativa da tarefa.

## Orca: captura real, capacidade verificada

`data/orca_probe.py` inicia uma instância instrumentada do Orca com `--replace`
na sessão do usuário e introspecta a API upstream `SetLogFileForTesting(s,s)->b`.
A API só existe quando o Orca é iniciado com `ORCA_TEST_RPC_SECRET`; o segredo
aleatório fica no ambiente desse processo, nunca nas variáveis do isotovideo.
Não é instalada outra versão do Orca durante o teste e não é fabricada fala pela
API `SpeakMessage`.

A versão de Orca da ISO precisa oferecer essa capacidade. Ausência ou assinatura
incompatível são inconclusivas e bloqueantes, com diagnóstico explícito. O
adaptador não presume que um número de versão garanta a API. Ele consome apenas
registros `kind=speech` após o marcador da ação, respeita interrupções e não
aceita teclas ecoadas, histórico anterior ou linhas incompletas como resposta.

Isso comprova conteúdo do **apresentador de fala instrumentado**, não som audível,
entrega a hardware braille ou ativação do leitor pelo caminho nativo do usuário.
As transcrições privadas não são publicadas como artefatos; o resultado estruturado
usa somente fixtures de teste e fica separado dos testes de senha.

## Executar

```bash
openqa/production/run-plan.sh \
  --plan bios --iso /caminho/candidate.iso \
  --results /var/tmp/gate/bios --password-file /run/user/1000/gate-password \
  --build candidato --commit "$(git rev-parse HEAD)" \
  --iso-sha256 "$(sha256sum /caminho/candidate.iso | cut -d' ' -f1)"
```

UEFI também exige `--uefi-code` e `--uefi-vars`. KVM é obrigatório. O diretório
precisa ter espaço para o disco virtual, conforme `run-plan.sh`.

`isotovideo -e` aceita módulos `ok`/`softfail`; as medições de postura de segurança
continuam não bloqueantes conforme a política anterior. Acessibilidade e tarefas
não visuais obrigatórias não devem ser transformadas em `softfail` para liberar
uma versão. O workflow atual executa cada plano uma vez; duas passagens seguidas
exigem duas execuções completas, não são garantidas pela matriz atual.

## Resultados e validação do próprio harness

Os resultados ficam em `testresults/`, `ulogs/`, `autoinst-log.txt` e
`virtio_console.log`. `nonvisual-contracts.json` distingue efeito funcional,
percurso por teclado, saída do Orca e limpeza. HTML/Markdown exibem essa camada
separadamente. O agregador exige proveniência não vazia, consistência de todos os
shards e evidência semântica; modo `process-alive` não é aceitável como aprovação
GUI. O commit informado é comparado ao commit esperado pelo workflow.

```bash
python3 -m unittest discover -s data -p 'test_*.py'
python3 -m unittest discover -s openqa/data -p 'test_*.py'
python3 -m unittest discover -s openqa/report -p 'test_*.py'
python3 openqa/production/check-nonvisual.py
prove -Iopenqa/t/lib -Iopenqa/lib openqa/t/*.t
```

`openqa/t/lib` contém doubles apenas para testes unitários de contrato. Nunca
adicionar esse diretório ao ambiente do isotovideo: esses testes não simulam o
backend, QEMU ou o desktop. Os testes negativos verificam que o harness recusa
aprovações indevidas; não substituem a execução da ISO.

## Escopo ainda não certificado

Esta implementação não certifica o sistema inteiro. Permanecem necessários os
percursos de ativação nativa do leitor, assistente live e instalação com anúncios
em todas as etapas, greeter SDDM, desbloqueio, autorização, recuperação de erros,
saída audível/braille e demais aplicativos críticos. O login atual continua sendo
uma verificação de autenticação/sessão, não uma aprovação do greeter com Orca.

Não há imagens diferentes para cada tema. Os mesmos contratos semânticos devem
ser reutilizados. A enumeração automática de todos os temas e a seleção de cada
um no assistente ainda precisam ser implementadas/validadas na ISO; não existe
alegação de cobertura de todos os temas nesta revisão. Mudança de cor não reprova;
perda de nome, estado ou navegação acessível é uma regressão real.

Antes de integrar, executar a ISO em BIOS/UEFI e ajustar seletores somente com
base na árvore e no percurso reais. Não enfraquecer condições para esconder uma
sonda incompatível. Avaliações com pessoas cegas continuam necessárias para
compreensão, descoberta, conforto e tarefas não cobertas.

Referências e detalhes: `../docs/openqa-nonvisual-implementation.md`.

## Relatório em sucesso ou falha

Cada execução publica `RESULTADO.md`, `RESULTADO.json` e HTML; o consolidado
publica também PDF e o resumo do Actions, mesmo quando os testes falham ou não
chegam a iniciar. O executor local grava seus relatórios em `<results>/report/`.
Falha no renderizador mantém um relatório resumido e não permite aprovação
silenciosa. Consulte [contrato de publicação e limites](../docs/openqa-reports-always.md).
