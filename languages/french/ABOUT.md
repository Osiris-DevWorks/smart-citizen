# Smart Citizen

*Smarter Strings for Star Citizen*

> Cette page est une traduction fournie pour votre confort. En cas de divergence, la version anglaise fait foi.

## À propos de ce projet

**Smart Citizen** est un outil puissant et convivial qui permet aux joueurs de Star Citizen de personnaliser les textes de localisation de leur jeu. Chargez, modifiez et appliquez des changements de localisation avec persistance complète, sauvegardes automatiques et prise en charge transparente des mises à jour du jeu.

Développé par **Osiris DevWorks**, un studio individuel dédié à la création d'outils utiles pour la communauté des joueurs.

## La promesse Osiris DevWorks

Tous les outils Osiris DevWorks seront soit **entièrement gratuits**, soit dotés d'un **niveau gratuit**. Nous croyons en la création de valeur pour les joueurs, sans murs payants ni abonnements obligatoires.

## Équipe ODW

- **Osiris_x**
- **Tichro**

## Contributeurs

Merci à celles et ceux qui ont contribué au code de Smart Citizen :

- **Stealrull**
- **Ishikudeska**
- **jonigirl**
- **Coerwyn**
- **denis-coach** (h0use)
- **scubamount**
- **hkstrongside**
- **odw-okano**

## Traducteurs

Merci à celles et ceux qui ont traduit l'interface de Smart Citizen :

- **Akwa** (Français)
- **Nxzzin** (Português brasileiro)
- **Thord82** (Español)

## Remerciements

Merci aux testeurs qui ont façonné Smart Citizen par leurs retours :

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

### Soutiens

Merci à celles et ceux qui ont soutenu le projet financièrement : vos contributions aident à garder Smart Citizen gratuit pour tout le monde :

- **Dimwit the Wise**

Smart Citizen embarque aussi des outils en amont :

- [**Osiris-DevWorks/odw-fast-unp4k**](https://github.com/Osiris-DevWorks/odw-fast-unp4k) : `unp4k.exe` et `unforge.exe`, utilisés pour décompresser `Data.p4k` et convertir DataForge en XML. C'est notre fork du projet original [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k), avec extraction parallèle et autres améliorations de performance.

Les textes du jeu en langues autres que l'anglais sont des traductions communautaires :

- [**Dymerz/StarCitizen-Localization**](https://github.com/Dymerz/StarCitizen-Localization) : les traductions communautaires de `global.ini` qui alimentent les options de langue française, portugaise du Brésil et italienne. Leurs traducteurs font le vrai travail ici ; nous ne faisons que le livrer.
- [**Thord82/Star_citizen_ES**](https://github.com/Thord82/Star_citizen_ES) : la traduction communautaire de `global.ini` qui alimente l'option de langue espagnole.
- [**stdblue/StarCitizenJapaneseResources**](https://github.com/stdblue/StarCitizenJapaneseResources) : la traduction communautaire de `global.ini` qui alimente l'option de langue japonaise.
- [**42Kit**](https://ini.42kit.com/) : la traduction communautaire de `global.ini` qui alimente l'option de langue chinoise.
- [**rjcncpt/StarCitizen-Deutsch-INI**](https://github.com/rjcncpt/StarCitizen-Deutsch-INI) : la traduction communautaire de `global.ini` qui alimente l'option de langue allemande.
- **[스타 시티즌 유저 한국어 프로젝트](https://sc.galaxyhub.kr)** (les guildes Shatagon, MGM Star Fleet et Falco Rescue) : l'équipe communautaire derrière la localisation coréenne. Leur fichier n'est pas fourni avec Smart Citizen (leur licence n'autorise pas la redistribution) ; le coréen est une langue « apportez votre propre fichier », associée via *Mapper le fichier de langue* à une copie locale que vous obtenez directement auprès d'eux.

## Fonctionnalités clés

### 🎯 Fonctionnalités principales
- **Charger et modifier** : chargez le `global.ini` de votre installation Star Citizen et personnalisez les textes dans une vue en tableau intuitive
- **Multi-canaux** : LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW ont chacun leur `user.ini`, cache, sauvegardes et extraction DataForge isolés ; changez de canal depuis l'onglet Paramètres sans redémarrer
- **Multilingue** : basculez l'application et les textes du jeu entre anglais, français, espagnol, portugais du Brésil, japonais, chinois, italien, allemand et coréen (fichier personnel) depuis l'onglet Paramètres. Les langues autres que l'anglais superposent un `global.ini` traduit par la communauté à la base anglaise, avec repli sur l'anglais pour tout texte non traduit. D'autres langues seront proposées à mesure que les traductions communautaires arrivent (voir `languages/TRANSLATIONS.md`)
- **Contrats de mission** : modifiez les textes de contrats et de briefings depuis la catégorie Missions dédiée
- **Filtrage intelligent** : recherchez des textes, filtrez par catégorie (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other) ou par statut de modification
- **Filtres par colonne** : tapez directement dans les champs de filtre sous chaque en-tête de colonne pour une recherche fine
- **Aperçu en direct** : un panneau latéral affiche le rendu du texte de la ligne sélectionnée avec les jetons de localisation du jeu (sauts de ligne, emphases EM3/EM4, libellés de mission) traduits en HTML stylisé, pour un aperçu proche du rendu en jeu
- **Panneau d'édition latéral** : un canevas activable depuis la barre d'outils, redimensionnable et détachable, pour modifier les valeurs longues (entrées de journal, briefings de mission, descriptions de vaisseaux) avec boutons Souligner/Surligner et synchronisation en direct entre panneaux
- **Application sûre** : l'application écrit dans `global.ini` avec une sauvegarde horodatée automatique préalable, valide le résultat par rapport au jeu de clés d'origine, et revient automatiquement en arrière en cas d'anomalie
- **Restauration de sauvegardes** : conservez jusqu'à 5 versions de sauvegarde par canal ; revenez en arrière à tout moment en un clic
- **Effacer la localisation** : ramenez votre jeu au texte d'origine sans perdre vos modifications enregistrées
- **Importer un INI** : importez un fichier INI existant et résolvez les conflits clé par clé avec la boîte de dialogue intégrée
- **Mode Simple et mode Avancé** : ouvrez sur un écran Simple à deux boutons (l'un applique les enrichissements avec vos réglages enregistrés, l'autre bascule en mode Avancé), ou utilisez l'interface Avancée complète (tableau, filtres, Enrichissements, Paramètres) dès que vous voulez retoucher à la main. Choisissez votre mode par défaut à l'installation et basculez dans l'application
- **Onglet FAQ** : les questions qu'on nous pose le plus, répondues directement dans l'application — quels fichiers sont touchés, le risque de bannissement, l'avertissement Windows « application non reconnue », et comment annuler ses modifications
- **Fenêtre et colonnes flexibles** : redimensionnez la fenêtre à votre guise — chaque onglet fait défiler son propre contenu au lieu de comprimer ou de tronquer les contrôles. Les colonnes de l'Éditeur de textes se redimensionnent par glissement (double-cliquez sur un séparateur pour l'ajuster au contenu) et vos largeurs comme la disposition de la fenêtre sont conservées d'un lancement à l'autre, avec **Plus → Réinitialiser les proportions de la fenêtre** pour rétablir les valeurs par défaut
- **Tutoriel guidé** : une visite à info-bulles accompagne les nouveaux utilisateurs au premier lancement de chaque version, rejouable à tout moment depuis le bouton Tutoriel

### 🔄 Données et persistance
- **Source : Data.p4k** : toutes les données de localisation et d'entités DataForge sont décompressées directement depuis votre `Data.p4k` installé ; aucun téléchargement, aucun miroir communautaire, toujours en phase avec votre version du jeu
- **Modifications persistantes** : vos personnalisations sont enregistrées automatiquement et rechargées à chaque session
- **Migration transparente** : quand Star Citizen est mis à jour, réextrayez depuis le `Data.p4k` patché ; vos modifications enregistrées se réappliquent automatiquement aux nouveaux textes de base
- **Interface soignée** : tableau performant avec filtres, édition en ligne, raccourcis clavier et interface moderne

### 📊 Enrichissements
- **Stats de vaisseaux** : vitesse SCM, carburant hydrogène/quantique, capacité de soute, armement complet et multiplicateurs d'armure (physique / énergie / distorsion / thermique) ajoutés aux descriptions de vaisseaux
- **Stats de composants** : PV de bouclier, consommation, refroidissement, régénération et autres stats pour boucliers, refroidisseurs, générateurs, moteurs quantiques et radars, avec balises de nom de type `[MIL-S2-A]` par défaut (entièrement personnalisables dans le Générateur d'étiquettes)
- **Stats d'armes** : DPS, cadence, portée et dégâts des canons et tourelles de vaisseau, de S1 au capital. Les armes de vaisseau reçoivent une balise dégâts+taille de type `[E-S2]`, les missiles `[IR-S1] Arrester III`, et les bombes `[S5] 500SCB Cluster`
- **Annotations de mission** : balises de récompense de plans `[BP]` / `[BP?]` sur les titres, plus des blocs structurés *MISSION DETAILS*, *POTENTIAL BLUEPRINTS* et *ITEM REWARDS* dans les descriptions. Les lignes de palier de réputation affichent les vrais noms de rangs (Rookie, Jr. Contractor, etc.) au lieu d'une numérotation générique. L'XP de mission nomme la voie de réputation qu'elle alimente, et les titres de scan/minage de Battaglia portent des balises de signature de ressource `[RS ####]`, rejointes par un détail « Resource Signatures » dans MISSION DETAILS pour chaque minerai ciblé et une annotation des noms de minerais affichée partout où le jeu montre ce nom, y compris le suivi de mission (deux options indépendantes, toutes deux activées par défaut)
- **Renvois de journal** : les entrées du Compendium minier reçoivent des renvois de fabrication et la signature de ressource de base de chaque minerai ; les marchandises utilisées en fabrication reçoivent une balise de nom `[CF]` personnalisable et la liste de tous les plans qui les demandent
- **Effets des consommables médicaux** : les injecteurs CureLife de base (MedPen, OxyPen, AdrenaPen et compagnie) reçoivent une ligne d'effet en langage clair, pour que la description dise ce que fait l'injecteur au lieu de se limiter à son texte d'ambiance
- **Vaisseaux favoris** : étoilez un vaisseau pour préfixer son nom d'un caractère configurable (par défaut `*`) et le faire remonter en tête du terminal ASOP en jeu
- **Générateur d'étiquettes** : personnalisez les balises entre crochets des composants, missiles, armes de vaisseau et marchandises ; réordonnez les éléments, changez la longueur des abréviations (M / MIL / Military), choisissez séparateurs et crochets, ou placez la balise après le nom. Les composants disposent d'un élément Type optionnel (Bouclier, Refroidisseur, etc.) ; les marchandises ont un élément Usage qui montre à quoi servent leurs matériaux de fabrication
- **Titres de mission** : faites précéder les titres de transport par leur itinéraire (par ex. `Area18 > Lorville`) — placement, flèche, séparateur et niveau de détail du lieu configurables, plus un raccourcissement optionnel des titres d'origine, avec aperçu en direct
- **Stats en haut ou en bas** : choisissez si le bloc de stats se place en tête ou en pied de description
- **Suivi des plans** : un onglet dédié pour marquer les plans de fabrication que vous possédez déjà. Déplacez les éléments entre Disponibles et Possédés, filtrez par Mission / Type / Classe / Taille / Grade, et les objets possédés reçoivent une balise bleue `[Owned]` dans les listes de plans des missions. **Rechercher les plans possédés dans les journaux** remplit la collection automatiquement depuis vos fichiers journaux Star Citizen, en n'important que les nouveautés depuis la dernière recherche, et **Exporter / Importer les plans possédés** déplace la collection d'un PC à l'autre (JSON ou CSV ; les imports ne font qu'ajouter, et les exports de scmdb.net fonctionnent aussi)
- **Étiquettes de mission** : renommez les en-têtes de section (MISSION DETAILS, POTENTIAL BLUEPRINTS, etc.), le libellé d'XP et la balise d'emphase des en-têtes
- **Correctifs déclaratifs des bugs de données CIG** : un système de correctifs applique à l'extraction des corrections aux bugs DataForge connus, pour que le texte en jeu soit correct sans attendre CIG
- **Catégories sélectives** : activez ou désactivez chaque catégorie d'enrichissements indépendamment depuis l'onglet Enrichissements

### 🎨 Thèmes
- **Défaut** : thème cyber bleu nuit inspiré de l'interface mobiGlas de Star Citizen
- **Clair / Sombre** : thèmes d'interface classiques
- **ODW** : thème signature Osiris DevWorks, anthracite marine et or antique

### 🛡️ Gestion des données
- **Sauvegardes automatiques** : sauvegardes horodatées créées avant chaque application au jeu (jusqu'à 5 par canal)
- **Persistance via le registre** : tous les chemins et préférences sont enregistrés dans le registre Windows
- **Stockage configurable** : vos modifications sont stockées sous `<dossier de données>\<canal>\` (par défaut `Documents\Smart Citizen`, un sous-arbre isolé par canal Star Citizen) pour une persistance sûre entre les sessions
- **Sauvegarde des paramètres** : exportez toute votre configuration (préférences, configurations d'étiquettes et les modifications de textes de chaque canal) dans un petit zip unique, puis importez-la sur un nouveau PC ou après une nouvelle décompression portable. Les imports prennent d'abord un instantané de vos fichiers actuels, ils sont donc réversibles
- **Journal intégré** : journal d'application en temps réel avec filtre de niveau, défilement automatique et bouton d'export pour les rapports de bug
- **Mise à jour automatique** : Smart Citizen consulte les versions GitHub au lancement et affiche les notes de version dans l'application ; un clic (plus une demande d'autorisation Windows) télécharge la mise à jour, l'installe et rouvre l'application

## Démarrage rapide

1. **Premier lancement** : l'application détecte automatiquement votre installation Star Citizen (modifiable dans l'onglet **Paramètres**)
2. **Extraire** : cliquez sur **Extraire depuis Data.p4k** dans l'onglet Paramètres pour décompresser la localisation d'origine et les données d'entités DataForge depuis votre jeu installé ; les textes se chargent automatiquement dans le tableau à la fin de l'extraction
3. **Modifier les textes** : utilisez la recherche et les filtres, puis double-cliquez sur une cellule Valeur personnalisée pour personnaliser le texte
4. **Appliquer** : cliquez sur **Appliquer les enrichissements** ; vos changements sont enregistrés et appliqués avec une sauvegarde automatique
5. **Enrichissements (optionnel)** : ouvrez l'onglet Enrichissements pour activer les surcouches de stats des vaisseaux, composants, armes et récompenses de mission
6. **Après les mises à jour du jeu** : relancez Extraire depuis Data.p4k ; vos modifications se réappliquent automatiquement

## Communauté et support

### Rejoignez-nous
- 💬 [Communauté Discord](https://discord.gg/BNzRegKZ7k) : obtenez de l'aide, partagez vos configurations, demandez des fonctionnalités
- 🐛 [Retours, bugs et vote des fonctionnalités Smart Citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) : canal dédié aux rapports de bug, retours et votes sur les prochaines fonctionnalités (rejoignez d'abord le serveur via l'invitation ci-dessus)

### Guides vidéo
- 🎥 [Star Citizen Hides Important Mission Info – This Tool Shows It In-Game & More!](https://www.youtube.com/watch?v=Xo1t404gsgs) par **Karolinger** : une présentation communautaire des fonctionnalités de Smart Citizen

### Soutenir ce projet
Smart Citizen est entièrement gratuit. Si vous le trouvez utile :
- 💳 [Don via PayPal](https://www.paypal.com/ncp/payment/YAWXHMGZH8T76)
- 💰 [Don via Venmo](https://venmo.com/u/Amr-Abouelleil)

## Autres outils d'Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)** : gérez et partagez vos configurations de hangar Star Citizen
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)** : importez, modifiez et exportez vos profils de contrôles Star Citizen
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)** : outil AFK pour éviter les déconnexions d'inactivité

## Construit avec

Construit avec **PyQt6** et inspiré du travail de localisation de la communauté Star Citizen.

**GitHub** : https://github.com/Osiris-DevWorks/smart-citizen

## Licence et mentions légales

Smart Citizen est sous licence **Apache, version 2.0**.

Consultez l'onglet **Juridique** pour le résumé complet de la licence, les attributions des logiciels tiers embarqués (unp4k / PyQt6 / lxml), les mentions « Made by the Community » de Cloud Imperium, la déclaration de confidentialité et de gestion des données, et la déclaration d'usage de l'IA.
