# Smart Citizen: Guia de Início Rápido

> Esta página é uma tradução fornecida para sua conveniência. Em caso de divergência, a versão em inglês prevalece. Status das traduções: `languages/TRANSLATIONS.md`.

## Primeira Configuração

Ao iniciar, o Smart Citizen recarrega as personalizações da sessão anterior e procura sua instalação do Star Citizen: o instalador preenche esse caminho automaticamente, mas você pode alterá-lo na aba **Config**. Toda a localização original e os dados do DataForge vêm **diretamente do seu `Data.p4k` instalado** (sem downloads, sem espelhos da comunidade), então extrair uma vez é um primeiro passo obrigatório após a instalação ou após qualquer patch do jogo.

## Modo Simples e Modo Avançado

O Smart Citizen abre em um de dois modos, e você pode alternar a qualquer momento.

- O **Modo Simples** é uma tela de dois botões: um deles, **Aplicar Aprimoramentos**, executa toda a cadeia com suas configurações atuais (extração, geração e aplicação, com backup prévio do arquivo do jogo); o outro muda para o **Modo Avançado**. É o caminho rápido quando você só quer os aprimoramentos aplicados, sem editar strings à mão.
- O **Modo Avançado** é o app completo: a tabela de strings, os filtros, a aba Aprimoramentos, a aba Config e todo o resto deste guia.

Escolha seu modo padrão na instalação, ou alterne entre eles dentro do app. O Modo Simples usa as últimas configurações salvas no Avançado.

## 1. Extrair a Localização Base do Data.p4k

Abra a aba **Config** e clique em **Extrair do Data.p4k**. Isso descompacta o `global.ini` original e os XMLs de entidades do DataForge usados pelo gerador de aprimoramentos: naves, componentes, armas, missões, blueprints etc.

Quando a extração termina, o `base.ini` extraído é carregado na tabela automaticamente, mesclado com os arquivos de aprimoramento e com as suas alterações salvas no `user.ini`.

## 2. Editar Strings de Localização

- Dê um duplo clique em qualquer célula de **Valor Personalizado** para editar o texto.
- **Valor Padrão**: texto original do `base.ini` extraído do `Data.p4k`.
- **Valor Atual**: o valor efetivo antes da sua alteração (base + camadas INI importadas).
- **Valor Personalizado**: a sua edição pessoal. Salva automaticamente a cada mudança e mantida em `<pasta de dados>\<canal>\user.ini` (a pasta de dados padrão é `Documents\Smart Citizen`, e cada canal do Star Citizen, LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW, tem suas próprias alterações isoladas).
- A coluna **Status** indica a origem do valor atual de cada linha:
  - **Modificado**: você editou explicitamente o Valor Personalizado.
  - **Aprimorado**: gerado automaticamente pelo processo de aprimoramentos (sobreposições de estatísticas, tags de blueprint etc.).
  - **Inalterado**: texto original do `base.ini`.
  - **Novo**: a chave só existe nas suas alterações ou nos aprimoramentos, não no `base.ini` original.
- **Redimensione qualquer coluna** arrastando o separador entre dois cabeçalhos, ou dê um duplo clique em um separador para ajustar a coluna à largura do seu conteúdo mais longo. Suas larguras são lembradas entre as execuções. Enquanto você não redimensionar nada, o Smart Citizen ajusta as colunas à sua janela automaticamente, de modo que uma instalação nova sempre abre de forma adequada na própria tela. Para recuperar esse layout automático, use **Redefinir proporções da janela** (veja abaixo).

## 3. Painel de Pré-visualização

O **painel de pré-visualização** no canto superior direito mostra o texto renderizado da linha selecionada. Os tokens de localização do jogo são convertidos em HTML estilizado para você ver mais ou menos como a string aparecerá no jogo:

- `\n` → quebra de linha
- `<EM3>...</EM3>` → cabeçalho de seção sublinhado
- `<EM4>...</EM4>` → ênfase em azul e negrito (normalmente valores de estatísticas)
- `~mission(Name)` → marcador `[Name]` acinzentado (o jogo substitui pelo valor real em tempo de execução)

O painel fica visível em todas as abas e reflete a última linha selecionada no **Editor de Strings**: útil para conferir a formatação de uma descrição de missão longa ou de uma entrada de diário antes de aplicar.

## 4. Categorias

Use o filtro de **Categoria** para focar em um domínio:

- **Ships**: nomes e descrições de naves (`vehicle_Name*`, `vehicle_Desc*`, além das variantes Wikelo/Collector).
- **Ship Items**: escudos, usinas de energia, refrigeradores, motores quânticos, motores de salto, armas de nave, mísseis, bombas, torretas.
- **Missions**: briefings de missão, textos de contratos, descrições de recompensas.
- **Gear**: armas de FPS, armaduras, capacetes, trajes, miras.
- **Commodities**: mercadorias e materiais de fabricação.
- **Journal**: entradas de diário do jogo, estilo Galactapedia.
- **Other**: todo o resto.

## 5. Busca e Filtros

- Use a **caixa de busca** para encontrar strings por chave ou conteúdo.
- Combine com os filtros de **Categoria** e **Status** (Modificado / Aprimorado / Inalterado / Novo).
- Marque **Esconder Inalterados** para focar apenas nas suas edições.
- As **caixas de filtro por coluna** sob cada cabeçalho refinam ainda mais dentro da tabela.
- Clique em qualquer cabeçalho de coluna para ordenar. Clique no cabeçalho **★** para trazer os favoritos para o topo.

## 6. Naves Favoritas

- Clique na coluna **★** de qualquer linha de nave para marcá-la como favorita. Apenas a linha de nome de uma nave pode ser favoritada; a linha de descrição da mesma nave não tem comportamento equivalente no jogo, então as colunas de estrela e de ordenação ficam em branco nela.
- Naves favoritas recebem um prefixo configurável antes do nome, fazendo-as subir ao topo da lista de naves no jogo.
- Altere o caractere de prefixo na aba **Aprimoramentos** (padrão: `*`).
- Marque **Somente Nomes de Naves e Veículos** na linha de Busca e Filtros para restringir a tabela apenas às linhas de nomes de naves e veículos, ocultando as descrições de naves e todas as outras categorias; combina com **Apenas Favoritos** para navegar exatamente pelas linhas que você pode favoritar.

## 7. Aplicar as Alterações ao Jogo

Clique em **Aplicar Aprimoramentos** para gravar suas edições na instalação do jogo. Um backup com data e hora do `global.ini` atual é criado em `<pasta de dados>\<canal>\backups\` antes de qualquer sobrescrita.

A cor do botão mostra a situação: **vermelho** significa que algo mudou desde a última aplicação (uma edição, uma regeneração, uma troca de idioma ou canal) e o jogo ainda não recebeu; **verde** significa que o jogo já corresponde ao que está carregado, e o botão fica desativado porque não há nada a refazer. A mesma convenção vermelho/verde vale para **Gerar Aprimoramentos** e **Aplicar alterações nas tags** na aba Aprimoramentos. Se você fechar o app com o botão Aplicar ainda vermelho, o Smart Citizen pergunta se deve aplicar agora ou sair sem aplicar, para que trabalho não aplicado nunca se perca em silêncio.

O Smart Citizen também carimba uma pequena marca d'água na string de versão do launcher (`Frontend_PU_Version`), acrescentando `\nLocalizations Enhanced with Smart Citizen v{VERSION}` em sua própria linha. É assim que você confirma no jogo que seu loc-pack está ativo: olhe o rótulo de versão no menu principal do Star Citizen. A marca é reescrita a cada aplicação, então nunca se acumula entre versões.

## 8. Restaurar um Backup

Abra o menu **Mais** na barra de ferramentas e escolha **Restaurar Backup** para voltar a uma versão anterior. O Smart Citizen mantém até **5 backups automáticos**; o mais antigo é removido conforme novos são criados.

## 9. Limpar a Localização

Abra o menu **Mais** e escolha **Limpar Localização** para excluir o `global.ini` personalizado do diretório do jogo, fazendo o jogo voltar ao texto padrão (original). Suas alterações salvas em `<pasta de dados>\<canal>\user.ini` ficam intactas e podem ser reaplicadas a qualquer momento.

## 10. Importar INI

Use **Importar INI** na aba **Config** (também disponível no menu **Mais** da barra de ferramentas) para incorporar um arquivo INI existente às suas alterações. Uma caixa de resolução de conflitos permite decidir, chave por chave: **manter o atual**, **usar o importado**, **anexar**, **inserir antes**, ou informar um valor **personalizado**.

## 11. Exportar Loc-Pack

Abra o menu **Mais** e escolha **Exportar INI…** para empacotar o `global.ini` atualmente aplicado em um único zip, `SmartCitizen-LocPack-{canal}-{AAAAMMDD}.zip`, que qualquer pessoa pode soltar em `StarCitizen\<canal>\data\Localization\english\` para usar o mesmo loc-pack sem instalar o Smart Citizen. Útil para compartilhar configurações com amigos ou com sua org.

## 12. Redefinir user.ini

Use **Resetar user.ini** na aba **Config** para apagar todas as suas edições pessoais do canal ativo. Uma confirmação evita cliques acidentais, e um backup automático do `user.ini` atual é feito antes em `<pasta de dados>\<canal>\backups\`: a redefinição é recuperável se você mudar de ideia.

## 13. Exportar / Importar Configurações

Use **Exportar Configurações…** e **Importar Configurações…** na aba **Config** para mover toda a sua configuração do Smart Citizen entre PCs, ou fazer um backup antes de uma reinstalação. A exportação empacota as configurações do app e as alterações do `user.ini` de todos os canais em um único zip pequeno, incluindo o caminho de instalação do Star Citizen; caminhos específicos da máquina que não fariam sentido em outro PC (sua pasta de dados, o local do cache, a geometria da janela, as larguras das colunas do editor de strings) ficam de fora. O backup registra todas as configurações, inclusive as que você deixou no valor padrão: restaurá-lo devolve o seu setup exatamente como estava, e uma configuração alterada *depois* do backup volta ao padrão em vez de manter o valor mais recente. A importação sobrepõe esse backup às suas configurações atuais e substitui o `user.ini` dos canais que ele contém: seus arquivos `user.ini` atuais são salvos antes via **Restaurar user.ini**, então uma importação é reversível. O caminho do Star Citizen só é mantido se ainda existir no PC de destino; caso contrário, o Smart Citizen o detecta automaticamente. O Smart Citizen reinicia após uma importação para carregar as novas configurações, e então oferece regenerar e aplicar seus aprimoramentos.

## 14. Após Atualizações do Jogo

Quando o Star Citizen é atualizado, suas edições ficam preservadas em `<pasta de dados>\<canal>\user.ini`. Execute novamente **Extrair do Data.p4k** para puxar as strings originais do jogo atualizado: a tabela recarrega automaticamente e suas personalizações se reaplicam por cima.

## 15. Trocar de Idioma

Escolha um idioma no menu **Idioma** da aba **Config** (ao lado de Canal). A troca muda tanto a interface do app quanto as strings do jogo na tabela:

- **Inglês** (o padrão) usa as strings originais extraídas do seu próprio `Data.p4k`.
- **Outros idiomas** baixam o `global.ini` traduzido pela comunidade para aquele idioma e o sobrepõem à base em inglês: qualquer string que a tradução não cobre cai de volta para o inglês em vez de sumir. O download fica em cache por idioma; voltar a um idioma já usado reaproveita o cache.
- **Os aprimoramentos continuam em inglês.** Blocos de estatísticas, tags e detalhes de missão são gerados a partir dos dados do jogo e mantêm a forma em inglês sobre a prosa traduzida. Uma linha mista (digamos, um nome de função em português dentro de um bloco de estatísticas em inglês) é esperada, não é um bug.
- **Mapear Arquivo de Idioma** (aba Config) permite apontar um idioma para outra URL de `global.ini`, por exemplo o seu próprio fork de uma tradução da comunidade. A sua URL vence o padrão incluído.
- Alguns textos da interface só atualizam após reiniciar o app. As strings da tabela recarregam imediatamente.

Ao aplicar, o app grava na pasta de idioma correspondente da instalação do jogo e define `g_language` no `user.cfg`, para que o jogo carregue o arquivo certo.

Quer ajudar a traduzir? O status das traduções por idioma fica em `languages/TRANSLATIONS.md` no repositório, e preferimos muito mais as suas palavras do que as de uma máquina. Fale com a gente no Discord.

## 16. Atualizações do App

O Smart Citizen verifica se há uma versão nova a cada inicialização. Quando há, as notas da versão aparecem em uma janela rolável com duas opções:

- **Atualizar Agora** baixa o novo instalador, o Windows pede permissão, e o Smart Citizen fecha, atualiza e reabre na versão nova. Suas edições, backups e configurações ficam intactos.
- **Depois** mantém você na versão atual; a pergunta volta na próxima inicialização.

Você também pode verificar manualmente a qualquer momento com **Verificar por atualizações** na aba Config. Builds portáteis mostram um botão **Abrir Página da Versão** no lugar, já que não há instalador para executar: baixe o zip novo e descompacte por cima da pasta antiga.

## Aba Aprimoramentos

- Ative sobreposições de estatísticas que acrescentam dados numéricos às descrições: velocidade SCM, HP de escudo, DPS, capacidade de carga, estatísticas de feixe de lasers de mineração (Fratura / Extração), rendimento de ferramentas de salvamento portáteis, listas de blueprints, XP de missão e mais. O XP de missão também indica qual trilha de reputação ele alimenta (ex.: `750 XP (Hauling)`), os contratos de scan/mineração da Battaglia levam uma tag `[RS ####]` com a assinatura de recurso base do minério alvo, e o diário Mining Compendium lista a RS base de cada minério ao lado dos locais de mineração.
- **Consumíveis Médicos**: adiciona uma linha de efeito em linguagem clara às canetas CureLife básicas (MedPen, OxyPen, AdrenaPen e companhia), para que a descrição diga o que a caneta realmente faz em vez de só contar a história dela.
- **Mostrar estatísticas acima da descrição**: coloque o bloco de estatísticas no topo da descrição em vez do final, para que os números sejam a primeira coisa lida no jogo.
- **Mostrar Assinaturas de Recursos (RS) ao lado dos nomes dos minérios**: acrescenta a Assinatura de Recurso base de cada minério minerável ao próprio nome de exibição (ex.: "Aluminium (RS 4285)"), para que apareça em todos os lugares onde o jogo mostra esse nome, incluindo o rastreador de missões. Independente da linha Assinaturas de Recursos nos Campos dos Detalhes de Missão abaixo.
- Ative ou desative cada categoria de aprimoramento de forma independente.
- Configure o caractere de prefixo das naves favoritas.
- **O controle de blueprints adquiridos** mudou para a própria aba **Rastreador de Blueprints**; veja a próxima seção.
- **Criador de Tags**: personalize as tags entre colchetes colocadas nos nomes de componentes, mísseis, armas de nave e commodities. Reordene elementos com ▲/▼, desative elementos individuais, mude o tamanho da abreviação (`M` / `MIL` / `Military`), escolha o separador (nenhum, hífen, espaço etc.) e os colchetes (quadrados, redondos, nenhum etc.), e escolha se a tag aparece antes ou depois do nome. Componentes também têm um elemento **Type** opcional (Escudo, Refrigerador, Usina etc.), desativado por padrão. Commodities têm os elementos **Label**, **Usage** (para onde vão os materiais de fabricação de uma commodity) e **Collection**, todos desativados por padrão; ative os que quiser no Criador de Tags. Clique em **Aplicar alterações nas tags** para salvar e regenerar. (**Gerar Aprimoramentos** também salva antes qualquer edição de tag pendente, para que um ajuste não salvo nunca escape de uma regeneração.)
- **Títulos de Missão** (aba Criador de Tags): comece os títulos das missões de transporte pela rota. Escolha o posicionamento (antes, depois, ou substituindo o título), a seta da rota (`>`, `->`, `to`, ou as formas `->-`/`->=`/`=>-`/`=>=` que distinguem um ponto único de vários em cada lado), o separador de título e o nível de detalhe do local (endereço completo por padrão; o nome curto pode não aparecer em missões raras), com pré-visualização ao vivo. Uma entrega passa a se ler `Area18 > Lorville - <título original>`, para ver o trajeto de relance na lista de contratos, e transportes com várias paradas listam os destinos (`Area18 > Lorville, New Babbage`). Duas opções independentes encurtam o título original: **Encurtar títulos originais** aplica abreviações de frases selecionadas (ex.: "Opportunity for Independent Cargo Hauler" → "Intro", "Local Shipment Route" → "Route", além do tratamento de prefixos de rank e da família Ling), e **Encurtar tamanhos de carga** abrevia os tamanhos ("Extra Small" → "XS"). Caixas individuais dão controle fino — remover "Cargo" ou "Haul", tirar "Rank", ou sublinhar transportes "Direct" para dar ênfase — para que a rota e as tags caibam mesmo em títulos longos. As caixas de **Tags gerais** na mesma página mostram ou ocultam as tags exclusivas do título: a recompensa de reputação, a tag de blueprint, `[ACE]`, a tag `[RS ####]` da Battaglia e o nome da trilha de reputação. A tag de blueprint aparece como `[BP]` quando toda versão de uma missão paga um blueprint, e como `[BP?]` quando não é garantido (só algumas versões trazem um, ou os dados do jogo marcam a recompensa como um sorteio).
- **Rótulos de Missão**: personalize os cabeçalhos de seção dos blocos de aprimoramento de missão (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), o rótulo de XP exibido em missões sem rank de reputação específico (padrão "Rep") e a tag de ênfase (EM3 = sublinhado, EM4 = cor) usada nos cabeçalhos.
- **Campos dos Detalhes de Missão**: mostre ou oculte individualmente cada linha do bloco MISSION DETAILS (tipo de missão, dificuldade, spawns, reputação, blueprints, piloto ace e assinaturas de recursos), para que suas descrições de missão carreguem só os dados que importam para você. **Assinaturas de Recursos** adiciona aos contratos de scan/mineração da Recco Battaglia um detalhamento com a progressão completa de valores de RS de cada minério alvo, separado da tag `[RS ####]` do título da missão e da anotação nos nomes de minérios acima.
- Clique em **Gerar Aprimoramentos** para extrair os dados do DataForge do `Data.p4k` e reconstruir os arquivos INI de aprimoramento. Os patches declarativos em `patches/` são reaplicados de forma idempotente a cada regeneração, para que os bugs de dados conhecidos da CIG continuem corrigidos sem esperar um patch do jogo.

## Aba Rastreador de Blueprints

Acompanhe quais blueprints de fabricação você já possui, e veja isso refletido no jogo: itens adquiridos recebem uma tag azul `[Owned]` nas listas POTENTIAL BLUEPRINTS das missões, para um contrato mostrar de relance o que ainda falta caçar.

- **Duas listas, um transporte.** Blueprints disponíveis à esquerda, sua coleção à direita. Selecione itens e mova-os com os botões de seta. A coleção persiste entre sessões.
- **Encontre rápido.** Uma caixa de busca filtra as duas listas, e os filtros **Missão / Tipo / Classe / Tamanho / Grau** reduzem a lista de disponíveis pela missão de origem do blueprint e pelo tipo de item (armadura, munição, arma FPS, item de nave etc.).
- **Escanear Logs por Blueprints Adquiridos** preenche a coleção automaticamente: a função lê os arquivos de log do Star Citizen atrás dos blueprints recebidos no jogo e os marca como adquiridos. Só os blueprints recebidos desde o último escaneamento são importados, então repetir a operação a qualquer momento é barato. O escaneamento precisa do caminho de instalação do Star Citizen definido na aba Config.
- **Também escanear LIVE/HOTFIX (o que não estiver ativo)** verifica também qual desses dois não é o seu canal atual, já que eles compartilham a mesma progressão de conta: um blueprint obtido no LIVE aparece nos logs do HOTFIX e vice-versa. Ativado por padrão. PTU, EPTU e TECH-PREVIEW são builds de teste separadas com progressão própria e nunca são escaneadas, independentemente desta opção.
- **Reescanear todos os registros (ignorar a última verificação)** força o próximo escaneamento a reler todas as entradas de log do zero, em vez de só o que é novo desde o último escaneamento. Use se a sua coleção parecer errada e um escaneamento normal não resolver. A opção desmarca a si mesma quando o escaneamento termina.
- **Exportar Blueprints Adquiridos… / Importar Blueprints Adquiridos…** movem sua lista de adquiridos entre PCs, ou a compartilham com um amigo. A exportação grava tudo o que você possui em um arquivo JSON ou CSV; a importação lê um arquivo desses e adiciona o que encontrar, sem nunca remover nada que você já possui. Exportações do scmdb.net também importam. O resumo da importação diz quantos blueprints eram novos e lista os nomes do arquivo que o Smart Citizen não rastreia.
- **Aplicar Tags [Owned]** retece as tags `[Owned]` nas suas strings carregadas depois de mudar a coleção. Como os outros botões de ação, ele fica **vermelho** quando a coleção tem mudanças que a tabela ainda não incorporou e **verde** quando tudo está sincronizado.
- A coluna **Adquirido** da tabela de strings ainda mostra uma estrela e ordena os adquiridos primeiro, mas agora é somente leitura; a coleção é gerenciada nesta aba.

## Aba Config

- **Aparência**: escolha o tema do app (veja abaixo).
- **Instalação do Star Citizen**: caminho para o seu diretório LIVE; detectado automaticamente na instalação, editável aqui. O menu **Canal** escolhe qual canal o app lê e grava, e o menu **Idioma** troca o app e as strings do jogo (veja *Trocar de Idioma* acima).
- **Dados do Smart Citizen**: pasta para `user.ini`, caches, extração do DataForge, INIs de aprimoramento gerados e backups. Padrão `Documents\Smart Citizen`; mova para fora do OneDrive se a extração ou a limpeza do cache estiver lenta.
- **Localização Base (Extração do P4K)**: clique em **Extrair do Data.p4k** para descompactar a localização original e os dados de entidades do DataForge diretamente do jogo instalado. Esta é a única fonte das strings base e dos dados de aprimoramento.
- **Importar INI**: incorpore um arquivo INI existente às suas alterações pela caixa de resolução de conflitos.
- **Resetar user.ini**: apague todas as suas edições pessoais do canal ativo. Pede confirmação e faz backup automático do `user.ini` atual antes de limpar.
- **Restaurar user.ini**: volte suas edições pessoais para um snapshot anterior. O Smart Citizen mantém backups rotativos do `user.ini` (até 5, tirados automaticamente antes de cada mudança): se uma importação ou edição der errado, escolha uma versão anterior e recupere suas strings. A restauração é reversível: o arquivo atual é salvo primeiro.
- **Exportar Configurações… / Importar Configurações…**: faça backup de toda a sua configuração (as configurações mais o `user.ini` de todos os canais) em um único zip pequeno, ou restaure em um PC novo. Veja *Exportar / Importar Configurações* acima.

## Aba Log

- Log da aplicação em tempo real.
- Filtre por nível, ative a rolagem automática e **exporte** o log para diagnóstico ou relatórios de bug.

## Temas

Escolha um tema em **Config → Aparência**:

- **Padrão**: SCLE, um tema cyber azul-marinho inspirado na interface mobiGlas do Star Citizen.
- **Claro / Escuro**: temas de interface clássicos.
- **ODW**: assinatura Osiris DevWorks, grafite marinho com dourado antigo.

## Layout da janela

O Smart Citizen lembra o tamanho da sua janela, o layout do editor de strings acoplado e as larguras das suas colunas entre as execuções. Cada aba rola o próprio conteúdo, então você pode reduzir a janela o quanto quiser e alcançar tudo rolando, em vez de ver os controles comprimidos ou cortados.

Se o seu layout acabar em um estado incômodo (uma coluna reduzida a uma tira, ou um tamanho de janela que não serve mais para a sua tela), use **Mais → Redefinir proporções da janela**. Isso restaura o tamanho da janela, o layout dos painéis e as larguras das colunas para os padrões. Suas configurações, edições e dados de localização não são afetados.

## Barra de Status

Mostra a contagem de entradas carregadas / modificadas e o estado de qualquer tarefa em segundo plano (extração, geração, aplicação).

## Tour Guiado

Clique no botão **Tutorial** da barra de ferramentas a qualquer momento para repetir o tour guiado: um passo a passo do fluxo principal com balões apontando cada controle. O tour também roda automaticamente na primeira vez que você inicia uma nova versão, para que uma instalação nova nunca comece no escuro. Clique em **Pular** a qualquer momento para fechá-lo.

## Aba FAQ

A aba **FAQ** responde às perguntas que mais recebemos, direto no app: quais arquivos o Smart Citizen toca, se dá para ser banido por usá-lo, por que o Windows sinaliza o instalador, e como desfazer as alterações. Confira lá primeiro; se a sua pergunta não estiver coberta, o Discord está a um clique.

## Atalhos de Teclado

- **Ctrl+Shift+C**: copiar as linhas filtradas para a área de transferência (formato chave=valor).

## Solução de Problemas

- **Nada na tabela**: confira se **Extrair do Data.p4k** terminou e se o recarregamento pós-extração concluiu, depois verifique a aba **Log** em busca de erros de leitura.
- **Aprimoramentos vazios ou com itens faltando**: execute **Gerar Aprimoramentos** na aba Aprimoramentos; é preciso ter um cache do DataForge (clique antes em **Extrair do Data.p4k** se ainda não fez).
- **Falha ao Aplicar Aprimoramentos**: confirme o caminho de instalação do Star Citizen na aba **Config** e que o jogo não está em execução.
- **A extração diz que o Data.p4k está bloqueado**: o RSI Launcher está baixando ou verificando uma atualização. Espere ele terminar (ou feche o launcher) e clique de novo em **Extrair do Data.p4k**.
- **Dados desatualizados após um patch do jogo**: execute novamente **Extrair do Data.p4k** e depois regenere os aprimoramentos.

## Problemas Conhecidos

Algumas anomalias de texto têm origem nos próprios dados do Star Citizen: uma referência errada de chave de localização num registro de contrato da CIG, ou uma recompensa de blueprint cujos dados não remetem a nenhum nome de exibição real. O jogo lê contratos e recompensas de blueprint do próprio `Data.p4k` em tempo de execução, então o Smart Citizen não pode corrigir isso na origem; só pode corrigir o *texto* que ele gera e aplica. Quando dá, contornamos esses bugs no nível dos dados ou da geração para que o resultado no jogo apareça correto mesmo assim.

- **Dossiê Jorrit, "Updated Power Usage Data" mostra o texto de Energy Anomaly**: CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). O contrato `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` da CIG aponta o parâmetro `Description` para `@Hockrow_FacilityDelve_P2M1_Repeat_desc` em vez do próprio `P2M4_Repeat_desc`, então os jogadores veem no jogo o texto de ambientação de Energy Anomaly do P2M1 numa missão chamada "Power Usage Data". O Smart Citizen contorna isso em dois passos, ambos declarados em `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. Uma edição do XML do DataForge para que nosso gerador de aprimoramentos anexe a lista correta de blueprints do P2M4 (Corbel Smolder, Geist Rogue/Whiteout) ao `P2M4_Repeat_desc`, em vez de recair na do P2M1.
  2. Um contorno de texto que acrescenta o conteúdo completo do `P2M4_Repeat_desc` (o texto de ambientação mais a própria lista de blueprints) ao final do `P2M1_Repeat_desc`, separado por um divisor rotulado. Como o jogo lê o ponteiro bugado e consulta `P2M1_Repeat_desc` para os dois contratos, o contrato P2M4 agora exibe o conteúdo pretendido. Jogadores do P2M1 veem o bloco do P2M4 como um apêndice rotulado após a própria descrição: mais ruidoso, mas os dois contratos agora mostram a lista de blueprints certa e o texto de ambientação certo.

  Quando a CIG corrigir o STARC-176797, o arquivo de patch inteiro pode ser excluído e a próxima regeneração volta a produzir descrições separadas e limpas.

- **Missões de reabastecimento mostrando nomes de bicos corrompidos** (ex.: "Nozzle Fuelgiver Grin Nozzlefast" em vez de "Norfield") na lista POTENTIAL BLUEPRINTS de uma missão. As recompensas de blueprint dos bicos de combustível não remetem a um nome de entidade resolvível nos dados da CIG como os outros itens fabricáveis, então nosso gerador de aprimoramentos caía de volta para uma versão "desmontada" do nome de arquivo interno em vez do nome real do produto. Corrigido para as 8 variantes de bico conhecidas (Marlin, Lindstrom, Bendix, Torrez, Ezra, Norfield, Harkin, RN-7s) por meio de uma correção de nomes conhecidos em `scripts/generate_enhancements_ini.py`; rode **Gerar Aprimoramentos** e **Aplicar ao Jogo** novamente para aplicar a correção em missões que você já viu.

## Feedback, Bugs e Votação de Recursos

- **Relate bugs, compartilhe configurações personalizadas e vote nos próximos recursos** no canal dedicado do Smart Citizen no Discord: [Discord da Osiris DevWorks, feedback e votação #smart-citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) (é preciso entrar antes no servidor da Osiris DevWorks: [convite](https://discord.gg/BNzRegKZ7k)). A priorização de recursos é guiada pelas reações e votos nesse canal, então quanto mais demanda um pedido tem, mais cedo ele chega.
- Ao relatar um bug, anexe o log (aba Log → **Exportar**) e mencione a versão do Star Citizen que você está usando, para distinguirmos problemas originais de mudanças do jogo.
