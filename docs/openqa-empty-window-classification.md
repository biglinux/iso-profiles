# openQA: janela acessível vazia e travessia incompleta

O smoke gráfico precisa distinguir duas situações que não têm o mesmo significado:

- **varredura completa sem conteúdo útil:** a janela existe e foi percorrida integralmente, mas não expõe texto, valor, ação ou outro controle utilizável pelo AT-SPI. O resultado é `failed`, porque o contrato de acessibilidade não foi atendido;
- **varredura incompleta:** o prazo expira durante a travessia, o limite de nós ou referências é alcançado, há ciclo, filho ausente ou erro do provedor. O resultado é inconclusivo e bloqueante; nunca é convertido em aprovação nem em ausência confirmada.

A integração real do PR encontrou um terceiro caso de fronteira: depois de várias varreduras completas de uma janela vazia, uma nova repetição podia começar exatamente após o prazo. Como nenhum nó dessa nova repetição ficou sem leitura — ela sequer começou — esse estado deve conservar a ausência já confirmada e reprovar o conteúdo, em vez de reclassificar o resultado como árvore incompleta.

A correção publicada no commit `1554ce419bc67ad5052d2e5cfea0429f2d23d62d` aplica essa distinção. O comportamento é coberto por teste unitário e pela integração GTK/AT-SPI com janela vazia. Os limites estruturais, erros de provedor e expiração durante uma travessia continuam inconclusivos e bloqueantes.
