# Perguntas Frequentes

Respostas rápidas para as perguntas mais comuns. Se sua pergunta não estiver aqui, clique no link **Feedback** no rodapé e pergunte para nós no Discord.

## Como desfaço as alterações que o Smart Citizen faz?

Facilmente, e a qualquer momento. O Smart Citizen nunca edita os arquivos originais do jogo diretamente, então voltar ao vanilla é um clique só:

- **Barra de ferramentas → Mais → Limpar Localização** exclui o `global.ini` personalizado que o Smart Citizen escreveu. O jogo volta imediatamente ao seu texto original. Suas edições não são perdidas, elas continuam salvas no app e você pode reaplicá-las quando quiser.
- Prefere voltar apenas uma versão em vez de tudo de uma vez? **Barra de ferramentas → Mais → Restaurar Backup** volta o arquivo do jogo para um backup com data e hora (o Smart Citizen mantém os últimos 5, e cria um novo a cada aplicação).

Suas edições pessoais ficam em `user.ini`, na sua pasta de dados do Smart Citizen, separada do jogo, então limpar o arquivo do jogo nunca as afeta.

## Serei banido por usar o Smart Citizen?

O Smart Citizen só edita o texto de localização (as palavras que o jogo mostra), ele não mexe na lógica do jogo, não te dá nenhuma vantagem, nem se comunica com os servidores da CIG. Nossas modificações **devem** estar tranquilas.

A **Sobreposição do Smart Citizen** opcional (aba Sobreposição) funciona do mesmo jeito, sem interferir no jogo. Ela desenha janelas comuns por cima do jogo, lê pixels da sua tela como faz uma ferramenta de captura de tela e lê o arquivo `Game.log` do jogo. Ela nunca se injeta no jogo nem se engancha nele, nunca abre o processo do jogo nem lê a memória dele, e nunca envia entradas de teclado ou mouse. A CIG não disse nada sobre sobreposições como esta, então vale o mesmo aviso de uso por sua conta e risco abaixo.

A CIG apoiou publicamente a localização feita pela comunidade. O post deles [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) explica o suporte oficial a traduções feitas por jogadores, o que entendemos como uma permissão explícita para o tipo de edição de localização que o Smart Citizen faz.

Streamers de grande visibilidade mantêm projetos de localização parecidos abertamente, e nenhum deles foi mandado parar.

Dito isso: a forma como você usa o Smart Citizen é por sua conta e risco. Nossas alterações devem estar tranquilas, mas por qualquer coisa que você fizer por conta própria, você e seus associados são responsáveis pelos danos que possam ocorrer. Se tiver dúvida se uma alteração é apropriada, fique no cosmético e mantenha um backup.

## Quais arquivos o Smart Citizen modifica?

Só um, e apenas quando você clica em **Aplicar Aprimoramentos**:

- `StarCitizen\<canal>\data\Localization\<idioma>\global.ini` — o arquivo de localização do jogo para o canal (LIVE, PTU, etc.) e o idioma que você selecionou. O Smart Citizen faz backup do arquivo existente primeiro, depois grava o resultado combinado.
- Ele também garante que `g_language` esteja definido no seu `user.cfg` para que o jogo carregue a localização certa. Nada mais na sua instalação do jogo é tocado.

Tudo que o Smart Citizen gera para uso próprio (o cache de origem, os arquivos de aprimoramentos, os backups, seu `user.ini`) fica na sua pasta de dados do Smart Citizen, não no jogo.

## Por que o Windows diz que este app não é reconhecido?

Porque o Smart Citizen ainda não tem assinatura de código. O Windows SmartScreen e o Smart App Control sinalizam qualquer app novo de um publisher para o qual não têm um certificado de assinatura registrado, mesmo que seja totalmente seguro. É um aviso de "não conhecemos isso ainda", não de "isso é perigoso".

Para executar: no aviso do SmartScreen, clique em **Mais informações → Executar assim mesmo**. Se o Smart App Control estiver bloqueando totalmente, você pode permitir o app pelo próprio aviso, ou desativar o Smart App Control temporariamente, instalar, e reativar depois.

A assinatura de código está no nosso roadmap, o que vai fazer esse aviso desaparecer. Até lá, baixe o Smart Citizen só pelos nossos releases oficiais no GitHub, para ter certeza de que é a build genuína.
