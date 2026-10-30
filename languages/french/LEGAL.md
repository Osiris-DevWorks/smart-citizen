# Smart Citizen : mentions légales et conformité

> Cette page est une traduction fournie à titre d'information. **La version anglaise fait foi** ; en cas de divergence, le texte anglais (et les fichiers `LICENSE` et `NOTICE` livrés à côté de l'exécutable) prévaut.

Cette page rassemble en un seul endroit toutes les informations juridiques, de licence et de gestion des données de Smart Citizen. Si quelque chose ici contredit les fichiers `LICENSE` ou `NOTICE` livrés à côté de l'exécutable, ces fichiers font autorité.

## Reconnaissance Star Citizen / Cloud Imperium

Smart Citizen est un **outil communautaire non officiel** pour Star Citizen. Il n'est ni développé, ni approuvé, ni sponsorisé, ni affilié à Cloud Imperium Games (CIG) ou Roberts Space Industries (RSI) de quelque manière que ce soit. Smart Citizen relève des directives « Made by the Community » de CIG pour les contenus et outils créés par les fans.

**Star Citizen®**, **Roberts Space Industries®** et **Cloud Imperium®** sont des marques déposées de Cloud Imperium Rights LLC et Cloud Imperium Rights Ltd. Toutes les données du jeu Star Citizen, y compris le contenu de `Data.p4k`, les modèles de vaisseaux et de composants, les noms d'objets, les textes de mission et le lore, sont la propriété intellectuelle de Cloud Imperium Rights LLC.

Smart Citizen ne redistribue aucun contenu de CIG ou RSI. L'application lit des fichiers depuis **votre propre installation licenciée de Star Citizen** sur votre machine locale et écrit des textes personnalisés par l'utilisateur dans cette même installation. Aucun contenu appartenant à CIG ne quitte votre ordinateur par l'intermédiaire de Smart Citizen.

## Licence de Smart Citizen

Smart Citizen est un logiciel open source sous licence **Apache, version 2.0**. Vous pouvez en obtenir une copie à [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0). Le texte complet de la licence est livré dans le fichier `LICENSE` à côté de l'exécutable, et le code source est disponible sur le [dépôt GitHub](https://github.com/Osiris-DevWorks/smart-citizen).

Sauf si la loi applicable l'exige ou si cela est convenu par écrit, le logiciel distribué sous la Licence est distribué **« EN L'ÉTAT », sans garanties ni conditions d'aucune sorte**, expresses ou implicites. Consultez la Licence pour le texte précis régissant les permissions et limitations.

## Logiciels tiers embarqués

Smart Citizen livre les logiciels tiers suivants dans son installateur. Le texte complet d'attribution de chacun se trouve dans le fichier `NOTICE` à côté de l'exécutable.

- **unp4k / unforge** : embarqués dans `assets/unp4k/` sous les noms `unp4k.exe` et `unforge.exe`. Osiris DevWorks livre son propre fork ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) du projet original [dolkensp/unp4k](https://github.com/dolkensp/unp4k), avec extraction parallèle et améliorations de performance. Utilisés pour décompresser `Data.p4k` et convertir les fichiers d'entités DataForge en XML. Sous licence **MIT**.
- **PyQt6** : framework d'interface graphique, par Riverbank Computing. Utilisé sous la **GNU General Public License v3 (GPL-3.0)** pour la distribution non commerciale ; une licence commerciale est aussi disponible auprès de Riverbank. Smart Citizen est un outil communautaire gratuit et open source et remplit les conditions de la GPL-3.0.
- **lxml** : bibliothèque d'analyse XML, par lxml.de. Utilisée sous licence **BSD-3-Clause**.

La bibliothèque standard Python et les autres dépendances embarquées par PyInstaller portent leurs propres licences ; voir la licence de la Python Software Foundation à [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Confidentialité et gestion des données

Smart Citizen est une **application de bureau locale**. Elle ne transmet ni vos modifications, ni votre `user.ini`, ni votre `base.ini`, ni vos personnalisations, ni aucun autre contenu de votre ordinateur à un serveur exploité par Osiris DevWorks ou un tiers.

### Ce qui reste sur votre ordinateur

Tout. Vos modifications de localisation, sauvegardes, réglages d'application et cache DataForge résident exclusivement sur votre disque local :

- **Réglages** : registre Windows sous `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` dans l'installation par défaut, ou `config.json` à côté de l'exécutable dans la version portable.
- **Modifications + sauvegardes** : `Documents\Smart Citizen\{canal}\` par défaut (configurable dans l'onglet Paramètres ; la version portable utilise `<dossier-exe>\data\` à la place).
- **Cache XML DataForge** : `%LOCALAPPDATA%\Smart Citizen\{canal}\cache\dataforge\`.
- **Rapports de plantage + exports manuels du journal** : `Documents\Smart Citizen\logs\` (ou équivalent portable), écrits uniquement quand l'application plante ou quand vous cliquez sur *Exporter* dans l'onglet Journal.

### Ce qui passe par le réseau

Smart Citizen n'effectue de requêtes réseau sortantes que dans trois cas :

- **Vérification de mise à jour** : une petite requête non authentifiée vers `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` environ toutes les 6 heures pour comparer la version installée à la dernière version GitHub. Ne renvoie que des métadonnées de version (nom du tag, URL) ; aucun état de Smart Citizen n'est envoyé.
- **Téléchargement des langues** : quand vous passez à une langue autre que l'anglais, Smart Citizen télécharge le `global.ini` traduit par la communauté pour cette langue depuis l'URL configurée (par défaut, le dépôt GitHub [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization)). Le téléchargement est mis en cache localement ; rien de votre machine n'est envoyé.
- **Sources distantes configurées par l'utilisateur** : si vous avez configuré une source de données pointant vers une URL `http(s)://` dans l'onglet Paramètres, Smart Citizen consulte cette URL lors de l'actualisation des fichiers sources. Par défaut, cela ne concerne que la forme URL GitHub-raw de la source `global` ; la configuration standard depuis la v1.0 lit `base.ini` depuis votre extraction locale de Data.p4k.

### Ce que Smart Citizen ne fait **pas**

- Aucune télémétrie, analyse d'usage ou rapport d'utilisation d'aucune sorte.
- Aucune information personnellement identifiable collectée, stockée ou transmise.
- Aucun envoi de données en arrière-plan.
- Aucun rapport de plantage automatique vers un serveur distant : les rapports de plantage sont écrits **localement uniquement** sous `Documents\Smart Citizen\logs\`. Si vous souhaitez en partager un pour un rapport de bug, c'est vous qui copiez et collez le fichier.
- Aucun compte, aucune connexion, aucune identité distante.

Si vous constatez un comportement en contradiction avec ce qui précède, merci de signaler un bug à [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues).

## Déclaration d'usage de l'IA

Des parties du code source de Smart Citizen ont été écrites avec l'aide de **Claude**, l'assistant de programmation IA d'Anthropic. Le code généré est **relu et approuvé par un mainteneur humain avant fusion** : l'IA ne commite pas directement et est traitée comme toute autre contribution de code, lue, testée et acceptée uniquement sur ses mérites.

En particulier :

- L'assistance IA accélère le développement des générateurs, classifieurs, refontes et tests ; les commits réalisés avec l'aide de l'IA portent un trailer `Co-Authored-By: Claude` dans leur message, pour que l'historique soit auditable.
- Toute la logique d'analyse des données du jeu Star Citizen, la classification des missions et les règles de traitement des textes sont conçues par les mainteneurs humains et validées sur de vrais échantillons de cache DataForge.
- Certaines traductions de l'interface et de la documentation de Smart Citizen sont générées par IA en attendant des traductions humaines. Elles sont recensées, langue par langue et clé par clé, dans `languages/TRANSLATIONS.md`, et sont remplacées par des traductions humaines dès qu'elles arrivent. Les traductions humaines existantes ne sont jamais modifiées par l'IA.
- **L'application elle-même ne contient aucune fonctionnalité d'IA ou d'apprentissage automatique.** Smart Citizen n'embarque aucun modèle, n'appelle aucun service d'IA à l'exécution, et ne transmet ni vos modifications ni les données du jeu Star Citizen à un fournisseur d'IA.

## Signaler un problème juridique

Si vous estimez que Smart Citizen porte atteinte à un droit d'auteur, une marque ou tout autre droit que vous détenez, ou si vous avez une question sur la façon dont l'application gère vos données, ouvrez un ticket ou contactez les mainteneurs via le [Discord Osiris DevWorks](https://discord.gg/BNzRegKZ7k).
