# Relatórios openQA em sucesso, falha e execução incompleta

Esta alteração complementa o smoke acessível simples do PR #11. Não altera o
contrato dos aplicativos, não torna programas opcionais obrigatórios e não
reintroduz comparação de screenshots.

## Contrato de publicação

O workflow `openqa-single-instance-experiment.yml` gera um relatório por plano
e um consolidado, inclusive depois de falha de preparação, download da ISO,
checksum, KVM, isotovideo ou agregação. O consolidado espera `static`, `plan` e
`applications-aggregate` com `if: always()`. Suas etapas de geração, resumo e
upload também usam `always()`; só colocar essa condição no job não basta.

O artefato `biglinux-iso-validation-<build>-<run>-<attempt>` contém:

- `biglinux-iso-validation.pdf`: relatório detalhado ou PDF resumido de emergência;
- `biglinux-validation-report.html`: relatório autocontido;
- `RESULTADO.md`: resumo também publicado no GitHub Actions;
- `RESULTADO.json`: veredito, contagens, lacunas e estado dos formatos;
- `run-status.json`: identidade da execução e estados do executor/jobs/etapas.

A inicialização produz um resumo de emergência **antes do checkout**. Quando o
código do finalizador está disponível, ele grava todos os formatos básicos antes
de tentar os geradores detalhados. As substituições são atômicas. A ausência de
`fpdf2`/Pillow, ou um erro de renderização, deixa um PDF de texto válido e os
outros formatos resumidos. Nesse caso o finalizador retorna erro para destacar
que o relatório está degradado, mas os arquivos ainda são publicados.

O PDF de emergência usa fontes padrão do formato, sem downloads nem dependências.
O PDF detalhado também usa fontes padrão: caracteres fora do conjunto suportado
são substituídos; HTML/Markdown/JSON preservam Unicode. Não há novas dependências
na ISO, nem necessidade de um navegador para gerar o relatório.

## Resultado do teste não é resultado do gerador

Uma execução de testes que falhou pode ter um relatório gerado corretamente:
`finalize_report.py` retorna zero e o documento registra **Falhou**. Isso não
converte o resultado do plano em sucesso. O gate exige sucesso dos planos, da
agregação e da publicação do relatório; um relatório ausente/degradado também
não permite liberar a ISO.

O campo de resultado do módulo é considerado, mesmo quando todos os seus
`details` são informativos ou positivos. Falhas de aplicativos, saídas do
executor e dependências do workflow também participam do resultado. Módulos sem
`details`, resultados parciais sem `vars.json`, JSON/UTF-8 inválidos, ausência de
módulos agendados e planos sem evidência não desaparecem nem viram aprovação.
`softfail`, `skipped` e estados inconclusivos são preservados. Aplicativos
opcionais ausentes continuam como não aplicáveis, sem aumentar os aprovados.

Os relatórios mostram módulos e aplicativos sem exigir screenshots. Tentativas
anteriores do mesmo plano são substituídas pela mais recente **numericamente**,
mesmo quando ela falhou; não se escolhe uma execução antiga verde para esconder
uma falha nova. Planos que não foram reexecutados mantêm sua última tentativa.

## Execução local

`openqa/production/run-plan.sh` também chama o finalizador por um trap `EXIT`:

```sh
openqa/production/run-plan.sh --plan bios --iso candidato.iso \
  --results /var/tmp/openqa/bios --password-file /caminho/privado/senha
# Relatórios HTML/Markdown/JSON em /var/tmp/openqa/bios/report/
```

O código de erro original do executor é preservado. Se os testes passaram mas a
publicação local falhou, a execução deixa de ser considerada totalmente bem
sucedida. `run-status.json` diferencia a saída do script da saída do isotovideo
(quando este chegou a iniciar). Para reconstruir os formatos, inclusive PDF:

```sh
python3 openqa/report/finalize_report.py \
  --results-root /var/tmp/openqa/bios \
  --output-dir /var/tmp/openqa/bios/report --pdf
```

O trap é instalado após interpretar os argumentos e localizar o repositório.
Ajuda/erros de uso anteriores a esse ponto não constituem uma execução de teste.
É necessário fornecer um diretório de resultados gravável e ter Python disponível.

## Limites e dados sensíveis

`run-status.json` copia somente identificadores e estados. **Não** grava outputs
das etapas, tokens, senha de teste ou transcrições arbitrárias do runner. Se a
redação de diagnósticos falhar, o plano publica apenas seu relatório seguro, não
os logs possivelmente não tratados. O resumo de emergência não inclui o texto
de exceções que poderia conter dados sensíveis; registra a classe do erro.

O timeout do teste desconta o tempo de preparação já gasto e reserva dez minutos
para coleta e publicação. O consolidado roda em outro job, podendo relatar a falta
de um artefato quando o runner do plano não o produziu.

Nenhum código consegue garantir upload após perda total do runner, falta de
espaço, indisponibilidade do armazenamento do GitHub ou cancelamento que impeça
os próprios finalizadores de executar. Se o checkout do job de relatório falhar,
o resumo pré-inicializado permanece disponível; não se promete o PDF detalhado
sem acesso ao seu código. Esses casos não geram aprovação fictícia.

## Validação e regressões

`openqa/report/test_report_finalization.py` simula sucesso, falha de módulo,
falha de aplicativo, ausência opcional, falta de `vars.json`, JSON inválido,
módulos/planos ausentes, falha de KVM/preparação, falha do gerador HTML, ausência
de dependência PDF, seleção numérica de tentativas e preservação de segredos.
Inclui execução real do script CLI com ISO inexistente: relatório emitido e
código de erro mantido. São testes do mecanismo de relatório, **não execução de
uma ISO ou validação de GUI/Orca reais**.

## Fontes oficiais conferidas em 14/09/2026

- GitHub, dependências e `always()` no job:
  https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds
- GitHub, condições de status e condição de sucesso implícita nas etapas:
  https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions
- Publicação de artefatos e `if-no-files-found`:
  https://github.com/actions/upload-artifact
- openQA, execução direta do isotovideo:
  https://open.qa/docs/#_run_isotovideo_directly_in_the_ci_runner
- os-autoinst, resultado e tempo do módulo:
  https://github.com/os-autoinst/os-autoinst/blob/master/basetest.pm

## Integração e prevenção de regressões de workflow

O relatório consolidado usa `.github/workflows/openqa-report.yml`, chamado
pelo gate e pelo CI. O CI publica três conjuntos **sintéticos** (sucesso,
falha deliberada do produtor e execução incompleta), executa esse mesmo
workflow e baixa os relatórios para conferir PDF, HTML, Markdown e JSON.
Os resultados da ISO não são simulados ou substituídos no gate de produção.

O download de um único artefato é extraído diretamente no destino por
`download-artifact`; o finalizador reconhece esse layout por `run-status.json`
ou `vars.json` na raiz. Com artefatos nomeados, continua selecionando a
última tentativa numericamente, sem ressuscitar uma tentativa verde antiga.

O CI também executa actionlint (validação semântica, não apenas parsing YAML),
ShellCheck, todos os testes de PDF com dependências declaradas e uma integração
GTK/AT-SPI real em Xvfb. A integração verifica janela própria, conteúdo acessível,
fechamento por Alt+F4 e rejeição de janela vazia/processo com SIGSEGV.
Essa aplicação é uma fixture de teste, não os aplicativos da ISO.

`runner.temp` pertence ao ambiente das **etapas**, não ao `env` do job.
Os caminhos dependentes do runner são inicializados na primeira etapa e
exportados por `GITHUB_ENV`. A função do trap EXIT tem uma supressão local
SC2317: ela é invocada indiretamente e seu funcionamento é exercitado pelo
teste de CLI com erro de preflight. Nenhuma checagem ShellCheck é desligada
globalmente.

Referências: tabela de contextos do GitHub Actions
<https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability>
e exceção de funções chamadas por trap do ShellCheck
<https://www.shellcheck.net/wiki/SC2317>.
