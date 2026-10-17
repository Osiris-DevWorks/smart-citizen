# Foire aux questions

Des réponses rapides aux questions les plus fréquentes. Si votre question n'est pas ici, cliquez sur le lien **Retours** en bas de la fenêtre et posez-la sur notre Discord.

## Comment annuler les modifications faites par Smart Citizen ?

Facilement, et à tout moment. Smart Citizen ne modifie jamais les fichiers originaux du jeu sur place, donc revenir à la version vanilla ne prend qu'un clic :

- **Barre d'outils → Plus → Effacer la localisation** supprime le `global.ini` personnalisé écrit par Smart Citizen. Le jeu revient immédiatement à son texte intégré. Vos modifications ne sont pas perdues, elles restent enregistrées dans l'application et vous pouvez les réappliquer quand vous le souhaitez.
- Vous préférez revenir en arrière d'une seule version plutôt que de tout effacer ? **Barre d'outils → Plus → Restaurer une sauvegarde** ramène le fichier du jeu à une sauvegarde horodatée (Smart Citizen conserve les 5 dernières, et en crée une nouvelle à chaque application).

Vos modifications personnelles se trouvent dans `user.ini`, dans votre dossier de données Smart Citizen, séparé du jeu, donc effacer le fichier du jeu ne les touche jamais.

## Vais-je être banni pour avoir utilisé Smart Citizen ?

Smart Citizen ne modifie que le texte de localisation (les mots affichés par le jeu) ; il ne touche pas à la logique du jeu, ne vous donne aucun avantage et ne communique pas avec les serveurs de CIG. Nos modifications **devraient** être sans risque.

La **Superposition Smart Citizen** optionnelle (onglet Superposition) fonctionne de la même façon, sans intervenir sur le jeu. Elle affiche des fenêtres ordinaires par-dessus le jeu, lit les pixels de votre écran comme le ferait un outil de capture d'écran, et lit le fichier `Game.log` du jeu. Elle n'injecte jamais rien dans le jeu et ne s'y accroche jamais (aucun hook), n'ouvre jamais le processus du jeu et ne lit jamais sa mémoire, et n'envoie jamais d'entrées clavier ou souris. CIG ne s'est pas prononcé sur ce type de superposition : la même mise en garde « à vos propres risques » ci-dessous s'applique donc.

CIG soutient publiquement la localisation communautaire. Leur billet [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) présente leur soutien officiel aux traductions faites par les joueurs, ce que nous comprenons comme autorisant explicitement le type de modification de localisation que fait Smart Citizen.

Des streamers très en vue mènent des projets de localisation similaires au grand jour, et aucun d'eux ne s'est vu demander d'arrêter.

Cela dit : la façon dont vous utilisez Smart Citizen est à vos propres risques. Nos modifications devraient être sans danger, mais pour tout ce que vous faites vous-même, vous et vos associés êtes responsables des dommages éventuels. En cas de doute sur la pertinence d'une modification, restez sur du cosmétique et gardez une sauvegarde.

## Quels fichiers Smart Citizen modifie-t-il ?

Un seul, et uniquement lorsque vous cliquez sur **Appliquer les enrichissements** :

- `StarCitizen\<canal>\data\Localization\<langue>\global.ini` — le fichier de localisation du jeu pour le canal (LIVE, PTU, etc.) et la langue que vous avez sélectionnés. Smart Citizen sauvegarde d'abord le fichier existant, puis écrit le résultat fusionné.
- Il s'assure également que `g_language` est bien défini dans votre `user.cfg` pour que le jeu charge la bonne localisation. Rien d'autre dans votre installation du jeu n'est touché.

Tout ce que Smart Citizen génère pour son propre usage (le cache source, les fichiers d'enrichissements, les sauvegardes, votre `user.ini`) se trouve dans votre dossier de données Smart Citizen, pas dans le jeu.

## Pourquoi Windows dit-il que cette application n'est pas reconnue ?

Parce que Smart Citizen n'est pas encore signé numériquement. Windows SmartScreen et Smart App Control signalent toute nouvelle application d'un éditeur pour lequel ils n'ont pas de certificat de signature enregistré, même si elle est totalement sûre. C'est un avertissement du type « nous ne connaissons pas ceci », pas « ceci est dangereux ».

Pour l'exécuter : sur l'invite SmartScreen, cliquez sur **Plus d'infos → Exécuter quand même**. Si Smart App Control le bloque complètement, vous pouvez autoriser l'application depuis son invite, ou désactiver temporairement Smart App Control, installer, puis le réactiver.

La signature de code est sur notre feuille de route, ce qui fera disparaître cet avertissement. En attendant, ne téléchargez Smart Citizen que depuis nos versions officielles sur GitHub, pour être sûr d'avoir la version authentique.
