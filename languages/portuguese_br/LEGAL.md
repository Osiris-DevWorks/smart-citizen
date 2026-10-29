# Smart Citizen: Aspectos Legais e Conformidade

> Esta página é uma tradução fornecida apenas para fins informativos. **A versão em inglês prevalece**; em caso de divergência, o texto em inglês (e os arquivos `LICENSE` e `NOTICE` distribuídos ao lado do executável) tem precedência.

Esta página reúne em um só lugar todas as informações legais, de licenciamento e de tratamento de dados do Smart Citizen. Se algo aqui conflitar com os arquivos `LICENSE` ou `NOTICE` distribuídos ao lado do executável, esses arquivos são a fonte autoritativa.

## Reconhecimento Star Citizen / Cloud Imperium

O Smart Citizen é uma **ferramenta comunitária não oficial** para Star Citizen. Não é desenvolvido, endossado, patrocinado nem afiliado à Cloud Imperium Games (CIG) ou à Roberts Space Industries (RSI) de forma alguma. O Smart Citizen se enquadra nas diretrizes "Made by the Community" da CIG para conteúdos e ferramentas feitos por fãs.

**Star Citizen®**, **Roberts Space Industries®** e **Cloud Imperium®** são marcas registradas da Cloud Imperium Rights LLC e da Cloud Imperium Rights Ltd. Todos os dados do jogo Star Citizen, incluindo o conteúdo do `Data.p4k`, modelos de naves e componentes, nomes de itens, textos de missão e lore, são propriedade intelectual da Cloud Imperium Rights LLC.

O Smart Citizen não redistribui nenhum conteúdo da CIG ou da RSI. O app lê arquivos da **sua própria instalação licenciada do Star Citizen** na sua máquina local e grava strings personalizadas pelo usuário de volta nessa mesma instalação. Nenhum conteúdo da CIG sai do seu computador por meio do Smart Citizen.

## Licença do Smart Citizen

O Smart Citizen é software de código aberto licenciado sob a **Licença Apache, Versão 2.0**. Você pode obter uma cópia da Licença em [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0). O texto completo da licença acompanha o executável no arquivo `LICENSE`, e o código-fonte está disponível no [repositório GitHub](https://github.com/Osiris-DevWorks/smart-citizen).

Salvo quando exigido pela lei aplicável ou acordado por escrito, o software distribuído sob a Licença é distribuído **"NO ESTADO EM QUE SE ENCONTRA", sem garantias ou condições de qualquer tipo**, expressas ou implícitas. Consulte a Licença para o texto específico que rege permissões e limitações.

## Software de Terceiros Embarcado

O Smart Citizen distribui no instalador os softwares de terceiros abaixo. O texto completo de atribuição de cada um está no arquivo `NOTICE` ao lado do executável.

- **unp4k / unforge**: embarcados em `assets/unp4k/` como `unp4k.exe` e `unforge.exe`. A Osiris DevWorks distribui o próprio fork ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) do projeto original [dolkensp/unp4k](https://github.com/dolkensp/unp4k), com extração paralela e melhorias de desempenho. Usados para descompactar o `Data.p4k` e converter arquivos de entidades do DataForge em XML. Licenciados sob a **Licença MIT**.
- **PyQt6**: framework de interface gráfica, da Riverbank Computing. Usado sob a **GNU General Public License v3 (GPL-3.0)** para distribuição não comercial; licenciamento comercial também está disponível na Riverbank. O Smart Citizen é uma ferramenta comunitária gratuita e de código aberto e se qualifica nos termos da GPL-3.0.
- **lxml**: biblioteca de análise XML, de lxml.de. Usada sob a **Licença BSD-3-Clause**.

A biblioteca padrão do Python e as demais dependências empacotadas pelo PyInstaller têm suas próprias licenças; veja a licença da Python Software Foundation em [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Privacidade e Tratamento de Dados

O Smart Citizen é um **aplicativo de desktop local**. Ele não transmite suas edições, seu `user.ini`, seu `base.ini`, suas personalizações nem qualquer outro conteúdo do seu computador para nenhum servidor operado pela Osiris DevWorks ou por terceiros.

### O que fica no seu computador

Tudo. Suas edições de localização, backups, configurações do app e cache do DataForge residem exclusivamente no seu disco local:

- **Configurações**: Registro do Windows em `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` na instalação padrão, ou `config.json` ao lado do executável na versão portátil.
- **Edições do usuário + backups**: `Documents\Smart Citizen\{canal}\` por padrão (configurável na aba Config; a versão portátil usa `<pasta-do-exe>\data\`).
- **Cache XML do DataForge**: `%LOCALAPPDATA%\Smart Citizen\{canal}\cache\dataforge\`.
- **Relatórios de travamento + exportações manuais de log**: `Documents\Smart Citizen\logs\` (ou equivalente portátil), gravados somente quando o app trava ou quando você clica em *Exportar* na aba Log.

### O que passa pela rede

O Smart Citizen faz requisições de rede de saída em apenas três circunstâncias:

- **Verificação de atualização**: uma pequena requisição não autenticada para `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest`, aproximadamente a cada 6 horas, para comparar a versão instalada com o release mais recente do GitHub. Retorna apenas metadados do release (nome da tag, URL); nenhum estado do Smart Citizen é enviado.
- **Download de idiomas**: quando você troca para um idioma diferente do inglês, o Smart Citizen baixa o `global.ini` traduzido pela comunidade para aquele idioma a partir da URL configurada (por padrão, o repositório GitHub [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization)). O download fica em cache local; nada da sua máquina é enviado.
- **Fontes remotas configuradas pelo usuário**: se você configurou uma fonte de dados apontando para uma URL `http(s)://` na aba Config, o Smart Citizen consulta essa URL ao atualizar os arquivos de fontes. De fábrica, isso só se aplica à forma de URL GitHub-raw da fonte `global`; a configuração padrão desde a v1.0 lê o `base.ini` da sua extração local do Data.p4k.

### O que o Smart Citizen **não** faz

- Nenhuma telemetria, análise ou relatório de uso de qualquer tipo.
- Nenhuma informação pessoalmente identificável coletada, armazenada ou transmitida.
- Nenhum envio de dados em segundo plano.
- Nenhum relatório automático de travamento para servidor remoto: os relatórios de travamento são gravados **somente localmente** em `Documents\Smart Citizen\logs\`. Se quiser compartilhar um em um relatório de bug, é você quem copia e cola o arquivo.
- Nenhuma conta, nenhum login, nenhuma identidade remota.

Se você descobrir um comportamento que contrarie o que está acima, registre um bug em [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues).

## Declaração de Uso de IA

Partes do código-fonte do Smart Citizen foram escritas com a ajuda do **Claude**, o assistente de programação com IA da Anthropic. O código gerado é **revisado e aprovado por um mantenedor humano antes do merge**: a IA não commita diretamente e é tratada como qualquer outra contribuição de código, lida, testada e aceita apenas pelos próprios méritos.

Especificamente:

- A assistência de IA acelera o desenvolvimento de geradores, classificadores, refatorações e testes; commits feitos com ajuda de IA carregam um trailer `Co-Authored-By: Claude` na mensagem, para que o histórico seja auditável.
- Toda a lógica de leitura dos dados do jogo, a classificação de missões e as regras de tratamento de strings são projetadas pelos mantenedores humanos e validadas com amostras reais do cache do DataForge.
- Algumas traduções da interface e da documentação do Smart Citizen são geradas por IA como provisórias, até que traduções humanas cheguem. Elas são registradas, por idioma e por string, em `languages/TRANSLATIONS.md`, e substituídas conforme as traduções humanas chegam. Traduções humanas existentes nunca são modificadas pela IA.
- **O aplicativo em si não contém nenhum recurso de IA ou aprendizado de máquina.** O Smart Citizen não embarca nenhum modelo, não chama nenhum serviço de IA em tempo de execução e não transmite suas edições nem os dados do jogo Star Citizen a nenhum provedor de IA.

## Relatar Questões Legais

Se você acredita que o Smart Citizen infringe direitos autorais, marcas ou outro direito que você detém, ou se tem uma pergunta sobre como o app trata seus dados, abra uma issue ou contate os mantenedores pelo [Discord da Osiris DevWorks](https://discord.gg/BNzRegKZ7k).
