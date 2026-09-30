# Smart Citizen

*Smarter Strings for Star Citizen*

> Esta página é uma tradução fornecida para sua conveniência. Em caso de divergência, a versão em inglês prevalece.

## Sobre Este Projeto

O **Smart Citizen** é uma ferramenta poderosa e fácil de usar para jogadores de Star Citizen personalizarem as strings de localização do jogo. Carregue, edite e aplique mudanças de localização com persistência completa, backups automáticos e suporte transparente a atualizações do jogo.

Desenvolvido pela **Osiris DevWorks**, um estúdio de uma pessoa só dedicado a criar ferramentas valiosas para a comunidade gamer.

## A Promessa da Osiris DevWorks

Todas as ferramentas da Osiris DevWorks serão **totalmente gratuitas** ou terão um **nível gratuito**. Acreditamos em criar valor para os jogadores sem paywalls nem assinaturas obrigatórias.

## Equipe ODW

- **Osiris_x**
- **Tichro**

## Contribuidores

Obrigado a quem contribuiu com código para o Smart Citizen:

- **Stealrull**
- **Ishikudeska**
- **jonigirl**
- **Coerwyn**
- **denis-coach** (h0use)
- **scubamount**
- **hkstrongside**
- **odw-okano**

## Tradutores

Obrigado a quem traduziu a interface do Smart Citizen:

- **Akwa** (Francês)
- **Nxzzin** (Português brasileiro)
- **Thord82** (Espanhol)

## Agradecimentos

Obrigado aos testadores que ajudaram a moldar o Smart Citizen com seu feedback:

- **Boogie Man**
- **Perseuscz**
- **Flat Earth**
- **Lord Valium**
- **Zero**
- **Apolleon Phoibos**
- **Epiq**
- **Narull**
- **XaileiShiv**
- **Mindbulletz**

### Apoiadores

Obrigado a quem apoiou o projeto financeiramente: suas contribuições ajudam a manter o Smart Citizen gratuito para todos:

- **Dimwit the Wise**

O Smart Citizen também embarca ferramentas de terceiros:

- [**Osiris-DevWorks/odw-fast-unp4k**](https://github.com/Osiris-DevWorks/odw-fast-unp4k): `unp4k.exe` e `unforge.exe`, usados para descompactar o `Data.p4k` e converter o DataForge em XML. É o nosso fork do projeto original [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k), com extração paralela e outras melhorias de desempenho.

As strings do jogo em idiomas diferentes do inglês são traduções da comunidade:

- [**Dymerz/StarCitizen-Localization**](https://github.com/Dymerz/StarCitizen-Localization): as traduções comunitárias do `global.ini` que alimentam as opções de idioma francês, português do Brasil e italiano. Os tradutores deles fazem o trabalho de verdade aqui; nós só entregamos.
- [**Thord82/Star_citizen_ES**](https://github.com/Thord82/Star_citizen_ES): a tradução comunitária do `global.ini` que alimenta a opção de idioma espanhol.
- [**stdblue/StarCitizenJapaneseResources**](https://github.com/stdblue/StarCitizenJapaneseResources): a tradução comunitária do `global.ini` que alimenta a opção de idioma japonês.
- [**42Kit**](https://ini.42kit.com/): a tradução comunitária do `global.ini` que alimenta a opção de idioma chinês.
- [**rjcncpt/StarCitizen-Deutsch-INI**](https://github.com/rjcncpt/StarCitizen-Deutsch-INI): a tradução comunitária do `global.ini` que alimenta a opção de idioma alemão.

## Principais Recursos

### 🎯 Recursos Centrais
- **Carregar e Editar**: carregue o `global.ini` da sua instalação do Star Citizen e personalize strings em uma tabela intuitiva
- **Suporte Multicanal**: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW têm cada um seu próprio `user.ini`, cache, backups e extração do DataForge isolados; troque de canal na aba Config sem reiniciar
- **Suporte a Vários Idiomas**: alterne o app e as strings do jogo entre inglês, francês, espanhol, português do Brasil, japonês, chinês, italiano e alemão na aba Config. Idiomas diferentes do inglês sobrepõem um `global.ini` traduzido pela comunidade à base em inglês, com fallback para o inglês no que não estiver traduzido. Mais idiomas serão expostos conforme as traduções da comunidade chegarem (veja `languages/TRANSLATIONS.md`)
- **Contratos de Missão**: edite textos de contratos e briefings na categoria Missions dedicada
- **Filtragem Inteligente**: busque strings, filtre por categoria (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other) ou por status de modificação
- **Filtros por Coluna**: digite direto nas caixas de filtro sob cada cabeçalho de coluna para buscas refinadas
- **Pré-visualização ao Vivo**: um painel lateral renderiza o texto da linha selecionada com os tokens de localização do jogo (quebras de linha, ênfases EM3/EM4, marcadores de missão) convertidos em HTML estilizado, mostrando mais ou menos como a string aparecerá no jogo
- **Painel Editor Lateral**: área de edição acionável pela barra de ferramentas, redimensionável e desacoplável, para editar valores longos (entradas de diário, briefings de missão, descrições de naves) com botões Sublinhar/Destacar e sincronização ao vivo entre painéis
- **Aplicação Segura**: a aplicação grava no `global.ini` com backup automático com data e hora antes, valida a saída contra o conjunto de chaves original e desfaz automaticamente em caso de divergência
- **Restauração de Backups**: mantenha até 5 versões de backup por canal; reverta mudanças a qualquer momento com um clique
- **Limpar Localização**: faça o jogo voltar ao texto original sem perder suas alterações salvas
- **Importar INI**: importe um arquivo INI existente e resolva conflitos chave por chave com a caixa de diálogo integrada
- **Modo Simples e Modo Avançado**: abra em uma tela Simples de dois botões (um aplica os aprimoramentos com suas configurações salvas, o outro muda para o Avançado), ou use a interface Avançada completa (tabela, filtros, Aprimoramentos, Config) sempre que quiser editar à mão. Escolha o padrão na instalação e alterne dentro do app
- **Aba FAQ**: as perguntas que mais recebemos, respondidas direto no app — quais arquivos são tocados, risco de banimento, o aviso de app não reconhecido do Windows, e como desfazer as alterações
- **Janela e colunas flexíveis**: redimensione a janela como quiser — cada aba rola o próprio conteúdo em vez de espremer ou cortar os controles. As colunas do Editor de Strings são redimensionáveis arrastando (clique duplo em um divisor para ajustá-la ao conteúdo) e suas larguras e o layout da janela são mantidos entre inicializações, com **Mais → Redefinir proporções da janela** para restaurar os padrões
- **Tutorial Guiado**: um tour com balões orienta novos usuários pelo fluxo de trabalho no primeiro uso de cada versão, repetível a qualquer momento pelo botão Tutorial

### 🔄 Origem dos Dados e Persistência
- **Origem: Data.p4k**: toda a localização original e os dados de entidades do DataForge são descompactados diretamente do seu `Data.p4k` instalado; sem downloads, sem espelhos da comunidade, sempre em sincronia com a versão real do seu jogo
- **Edições Persistentes**: suas personalizações são salvas automaticamente e recarregadas em cada sessão
- **Migração Transparente**: quando o Star Citizen atualiza, reextraia do `Data.p4k` atualizado; suas edições salvas se reaplicam automaticamente às novas strings base
- **Interface Limpa**: tabela de alto desempenho com filtros, edição em linha, atalhos de teclado e visual moderno

### 📊 Aprimoramentos
- **Estatísticas de Naves**: velocidade SCM, combustível de hidrogênio/quântico, capacidade de carga, armamento completo e multiplicadores de armadura (físico / energia / distorção / térmico) anexados às descrições das naves
- **Estatísticas de Componentes**: HP de escudo, consumo de energia, taxa de refrigeração, regeneração e afins para escudos, refrigeradores, usinas, motores quânticos e radares, com tags de nome no estilo `[MIL-S2-A]` por padrão (totalmente personalizáveis no Criador de Tags)
- **Estatísticas de Armas**: DPS, cadência, alcance e dano de canhões e torretas de nave, de S1 a capital. Armas de nave recebem uma tag dano+tamanho no estilo `[E-S2]`, mísseis `[IR-S1] Arrester III` e bombas `[S5] 500SCB Cluster`
- **Anotações de Missão**: tags de recompensa de blueprint `[BP]` / `[BP?]` nos títulos, além de blocos estruturados *MISSION DETAILS*, *POTENTIAL BLUEPRINTS* e *ITEM REWARDS* nas descrições. Linhas de nível de reputação mostram nomes reais de ranks (Rookie, Jr. Contractor etc.) em vez de numeração genérica. O XP de missão indica a trilha de reputação que alimenta, e títulos de scan/mineração da Battaglia levam tags de assinatura de recurso `[RS ####]`, acompanhadas por um detalhamento "Resource Signatures" no MISSION DETAILS para cada minério alvo e por uma anotação nos nomes dos minérios exibida em todo lugar onde o jogo mostra esse nome, incluindo o rastreador de missões (duas opções independentes, ambas ativadas por padrão)
- **Referências Cruzadas no Diário**: entradas do Compêndio de Mineração ganham referências de fabricação e a assinatura de recurso base de cada minério; commodities usadas em fabricação ganham uma tag de nome `[CF]` personalizável e a lista de todos os blueprints que as exigem
- **Efeitos de Consumíveis Médicos**: as canetas CureLife básicas (MedPen, OxyPen, AdrenaPen e companhia) ganham uma linha de efeito em linguagem clara, para a descrição dizer o que a caneta faz em vez de só contar a história dela
- **Naves Favoritas**: marque uma nave com estrela para prefixar o nome com um caractere configurável (padrão `*`) e fazê-la subir ao topo do terminal ASOP no jogo
- **Criador de Tags**: personalize as tags entre colchetes de componentes, mísseis, armas de nave e commodities; reordene elementos, mude o tamanho da abreviação (M / MIL / Military), escolha separadores e colchetes, ou coloque a tag depois do nome. Componentes têm um elemento Type opcional (Escudo, Refrigerador etc.); commodities têm um elemento Usage que mostra para onde vão seus materiais de fabricação
- **Títulos de Missão**: comece títulos de transporte pela rota (ex.: `Area18 > Lorville`) — posicionamento, seta, separador e nível de detalhe do local configuráveis, além do encurtamento opcional dos títulos originais, com pré-visualização ao vivo
- **Estatísticas Acima ou Abaixo**: escolha se o bloco de estatísticas fica no topo ou no final da descrição
- **Rastreador de Blueprints**: uma aba dedicada para marcar os blueprints de fabricação que você já possui. Mova itens entre Disponíveis e Adquiridos, filtre por Missão / Tipo / Classe / Tamanho / Grau, e itens adquiridos ganham uma tag azul `[Owned]` nas listas de blueprints das missões. **Escanear Logs por Blueprints Adquiridos** preenche a coleção automaticamente a partir dos seus arquivos de log do Star Citizen, importando só o que é novo desde o último escaneamento, e **Exportar / Importar Blueprints Adquiridos** move a lista de adquiridos entre PCs (JSON ou CSV; a importação só adiciona, e exportações do scmdb.net também funcionam)
- **Rótulos de Missão**: renomeie os cabeçalhos de seção (MISSION DETAILS, POTENTIAL BLUEPRINTS etc.), o rótulo de XP e a tag de ênfase dos cabeçalhos
- **Patches Declarativos para Bugs de Dados da CIG**: um sistema de patches aplica correções a bugs conhecidos do DataForge no momento da extração, para o texto no jogo sair certo sem esperar a CIG
- **Categorias Seletivas**: ative ou desative cada categoria de aprimoramento de forma independente na aba Aprimoramentos

### 🎨 Temas
- **Padrão**: tema cyber azul-marinho inspirado na interface mobiGlas do Star Citizen
- **Claro / Escuro**: temas de interface clássicos
- **ODW**: tema assinatura da Osiris DevWorks, grafite marinho com dourado antigo

### 🛡️ Gestão de Dados
- **Backups Automáticos**: backups com data e hora criados antes de aplicar mudanças ao jogo (até 5 por canal)
- **Persistência no Registro**: todos os caminhos e preferências salvos com segurança no Registro do Windows
- **Armazenamento Configurável**: suas edições ficam em `<pasta de dados>\<canal>\` (padrão `Documents\Smart Citizen`, uma subárvore isolada por canal do Star Citizen) para persistência segura entre sessões
- **Backup de Configurações**: exporte toda a sua configuração (preferências, configurações de tags e as alterações de strings de todos os canais) para um único zip pequeno, depois importe em um PC novo ou após descompactar uma nova versão portátil. As importações salvam seus arquivos atuais primeiro, então são reversíveis
- **Visualizador de Log Integrado**: log da aplicação em tempo real com filtro de nível, rolagem automática e botão Exportar para relatórios de bug
- **Atualizador Automático**: o Smart Citizen consulta os releases do GitHub ao iniciar e mostra as notas da versão no app; um clique (mais uma permissão do Windows) baixa a atualização, instala e reabre o app

## Início Rápido

1. **Primeiro Uso**: o app detecta automaticamente sua instalação do Star Citizen (editável na aba **Config**)
2. **Extrair**: clique em **Extrair do Data.p4k** na aba Config para descompactar a localização original e os dados de entidades do DataForge do jogo instalado; as strings carregam na tabela automaticamente quando a extração termina
3. **Editar Strings**: use a busca e os filtros, depois dê um duplo clique em qualquer célula de Valor Personalizado para personalizar o texto
4. **Aplicar**: clique em **Aplicar Aprimoramentos**; suas mudanças são salvas e aplicadas com backup automático
5. **Aprimoramentos (Opcional)**: abra a aba Aprimoramentos para ativar sobreposições de estatísticas de naves, componentes, armas e recompensas de missão
6. **Após Atualizações do Jogo**: execute novamente Extrair do Data.p4k; suas edições se reaplicam automaticamente

## Comunidade e Suporte

### Junte-se a Nós
- 💬 [Comunidade no Discord](https://discord.gg/BNzRegKZ7k): suporte, compartilhamento de configurações, pedidos de recursos
- 🐛 [Feedback, Bugs e Votação de Recursos do Smart Citizen](https://discord.com/channels/1438175448420057323/1472394204347895890): canal dedicado a relatos de bug, feedback e votação dos próximos recursos (entre antes no servidor pelo convite acima)

### Guias em Vídeo
- 🎥 [Star Citizen Hides Important Mission Info – This Tool Shows It In-Game & More!](https://www.youtube.com/watch?v=Xo1t404gsgs) por **Karolinger**: uma visão geral do Smart Citizen feita pela comunidade

### Apoie Este Projeto
O Smart Citizen é totalmente gratuito. Se ele é útil para você:
- 💳 [Doe via PayPal](https://www.paypal.com/ncp/payment/YAWXHMGZH8T76)
- 💰 [Doe via Venmo](https://venmo.com/u/Amr-Abouelleil)

## Outras Ferramentas da Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)**: gerencie e compartilhe builds de battlestation de hangar do Star Citizen
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)**: importe, edite e exporte perfis de controles do Star Citizen
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)**: ferramenta AFK para evitar desconexões por inatividade

## Construído Com

Construído com **PyQt6** e inspirado no trabalho de localização da comunidade Star Citizen.

**GitHub**: https://github.com/Osiris-DevWorks/smart-citizen

## Licença e Aspectos Legais

O Smart Citizen é licenciado sob a **Licença Apache, Versão 2.0**.

Veja a aba **Legal** para o resumo completo da licença, as atribuições de software de terceiros embarcado (unp4k / PyQt6 / lxml), os reconhecimentos "Made by the Community" da Cloud Imperium, a declaração de privacidade e tratamento de dados, e a declaração de uso de IA.
