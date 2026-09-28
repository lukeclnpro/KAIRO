# 🤖 Local IA

> Une interface locale pour utiliser des modèles d'IA directement depuis votre machine, avec une intégration **Ollama optionnelle**.

<!-- VERSION:START -->
**Version actuelle : `0.2.0.4`**
<!-- VERSION:END -->

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/github/license/lukeclnpro/local_ia)](https://github.com/lukeclnpro/local_ia)

## ✨ Fonctionnalités

- 🧠 Utilisation de modèles locaux via Ollama
- 💬 Gestion des conversations
- ⚙️ Configuration de l'IA
- 🌐 Serveur web local pour accéder à l'IA depuis le réseau
- 📦 Installation et gestion des modèles Ollama
- 🔄 Vérification et installation des mises à jour
- 🗑️ Script de désinstallation
- 🖥️ Compatible Linux et Windows

## 📋 Prérequis

- **Python 3.10 ou plus récent**
- Une connexion Internet est nécessaire pour l'installation et les mises à jour

> **Important :** l'installation de Local IA **n'installe pas Ollama automatiquement**. Si vous n'utilisez pas Ollama, aucune installation supplémentaire n'est nécessaire de ce côté.

## 🚀 Installation

### Linux

```bash
git clone https://github.com/lukeclnpro/local_ia.git
cd local_ia
python3 setup.py
```

> Le script d'installation configure Local IA

### Windows

```powershell
cd $HOME/Documents
git clone https://github.com/lukeclnpro/local_ia.git
cd local_ia
python setup.py
```

> Le script d'installation configure Local IA

## ▶️ Lancer Local IA

### Linux

```bash
cd local_ia
python3 main.py
```

### Windows

```powershell
cd $HOME/Documents/local_ia
python main.py
```

## 🧰 Commandes utiles

Afficher l'aide :

```bash
python main.py help
```

Forcer une mise à jour depuis GitHub :

```bash
python main.py force_update
```

Désinstaller Local IA :

```bash
python uninstall.py
```

> Le script de désinstallation est disponible à partir de la version `0.1.6`.

## 🌐 Serveur web

Local IA inclut un serveur web local permettant aux autres appareils du réseau d'accéder à l'IA.

Lancement :

```bash
python server.py
```

> Selon votre configuration réseau et votre pare-feu, il peut être nécessaire d'autoriser le port utilisé par le serveur.

## 🧪 Tests

Chaque test peut être exécuté seul :

```bash
python3 tests/test_files.py
python3 tests/test_commands.py
```

Pour lancer toute la suite :

```bash
for test_file in tests/test_*.py; do python3 "$test_file" || exit 1; done
```

## 🔄 Mises à jour

Les informations de version et le journal des changements sont centralisés dans :

- [`version.json`](version.json) — version actuelle du projet
- [`update.json`](update.json) — historique des versions et changements

Le contenu ci-dessous est **généré automatiquement** à partir de ces deux fichiers. Il est donc inutile de modifier manuellement les sections dynamiques du README.

### 📌 Version actuelle

<!-- VERSION:START -->
**Version actuelle : `0.1.7`**
<!-- VERSION:END -->

### 📝 Journal des mises à jour

<!-- UPDATES:START -->
<details>
<summary>Version `0.2.0.4` — 2026-09-28 · **Recherche web multi-catégories**</summary>

- Ajout de catégories de recherche : Web général, actualités, sites officiels, annonces et météo.
- Recherche Google tentée en premier, avec repli automatique sur DuckDuckGo si les résultats Google ne sont pas accessibles.
- Routage des demandes de recherche vers la catégorie adaptée et transmission du type de recherche à l'outil web.

</details>

<details>
<summary>Version `0.2.0.3(beta5)` — 2026-09-28 · **Recherche web, applications et conversations (beta5)**</summary>

- Ajout d'un outil de recherche web pour les informations récentes, dont la météo actuelle par ville via Open-Meteo.
- Ajout d'une réponse déterministe à la question sur la date du jour.
- Réparation du lancement d'applications, avec détection automatique et autorisation distincte de l'exécution de commandes.
- Mémorisation persistante des chemins et alias d'applications fournis dans la conversation, avec tolérance aux fautes de frappe courantes.
- Compréhension des corrections contextuelles comme « WhatsApp s'appelle ZapZap » après un lancement infructueux.
- Protection contre l'interprétation d'appels d'outils recopiés comme des chemins d'application.
- Génération et mise à jour automatiques du titre de conversation selon son sujet, affiché dans l'interface web et le CLI.
- Conservation des sujets de conversation définis manuellement.

</details>

<details>
<summary>Version `0.2.0.2(beta4)` — 2026-09-27 · **Utilisation de la nouvelle API OpenRouter (beta4)**</summary>

- Ajout de la possibilité d'utiliser l'API OpenRouter pour les modèles LLM.
- Ajout d'une option de configuration pour choisir entre Ollama et OpenRouter.
- Mise à jour de la documentation pour inclure les instructions d'utilisation d'OpenRouter.

</details>

<details>
<summary>Version `0.2.0.1(beta3)` — 2026-09-26 · **Refonte IA + validation de phases (beta3)**</summary>

- Phase 1 : centralisation du flux IA avec RequestRouter, ContextCompiler et ToolManager.
- Phase 2 : ajout du routeur et du fast path pour les actions simples et déterministes.
- Phase 3 : sélection dynamique des outils selon la route et réductions des outils envoyés au modèle.
- Phase 4 : compilation du contexte en blocs structurés pour les prompts.
- Phase 5 : historique compact avec résumé et fenêtre récente pour réduire le poids du contexte.
- Phase 6 : mémoire SQLite avec tri de pertinence et maintien de l'API historique.
- Phases 7 à 10 : recherche mémoire sémantique, compression des résultats outils, boucle de contrôle des outils, et écriture asynchrone.
- Phase 11 : cache des prompts et des blocs de contexte pour éviter les recalculs inutiles.
- Phase 12 : session Ollama centralisée avec gestion unique des appels LLM.
- Phase 13 : support du streaming optionnel sans surcharge sur les appels internes.
- Phase 14 : extraction mémoire filtrée et déduplication avant sauvegarde.
- Phase 15 : centralisation des conversations et réduction de la duplication du code.
- Phase 16 : validation de non-régression sur les flux critiques et correction du cache de prompt.
- Phase 17 : benchmark final avec scénarios critiques et métriques détaillées.
- Phase 18 : seuils de performance et validation automatique.
- Phase 19 : ordre de déploiement recommandé pour la structure finale.
- Phase 20 : architecture cible documentée et exposée sans réécriture complète du projet.
- Le projet est aujourd'hui cohérent, testé et stable : 116 tests passent.

</details>

<details>
<summary>Version `0.2.0.0(beta1+2)` — 2026-09-25 · **Lecture de fichier + lancement de programme (beta1+2)**</summary>

- Ajout de la possibilité de l'ia de lancer des programme via une demande simple, pas de commande necessaire.

</details>

<details>
<summary>Version `0.1.8` — 2026-09-24 · **Lecture de fichier**</summary>

- Ajout d'une commande dans le chat qui permet de donner a l'ia un fichier. (/fichier chemin/vers/le/fichier). Pour l'instant, lecture uniquement.

</details>

<details>
<summary>Version `0.1.7` — 2026-09-23 · **interface plein écran globale**</summary>

- Chaque commande interactive démarre sur un écran entièrement nettoyé.
- Les anciens messages, prompts et menus ne restent plus empilés dans le terminal.
- Le comportement est appliqué aux outils principaux, à l'agent IA, à la configuration, au désinstalleur et aux utilitaires interactifs.

</details>

<details>
<summary>Version `0.1.6` — 2026-09-23 · **script de desinstallation**</summary>

- Ajout d'un script de desinstallation de local-ai, et au choix, ollama et ses modeles.
- Ajout de deux nouveau argument de commande pour main.py --> ''help'' qui affiche une aide sur les commande possible ; ''force_update'' qui force la mise a jour depuis le depot github

</details>

<details>
<summary>Version `0.1.5` — 2026-09-23 · **serveur web**</summary>

- Ajout d'un serveur local qui permet a tout les membres du reseau de discuter avec l'ia.
- Correctif des premiers bug et test du server local
- debut de la creation d'un portage executable du programme
- IMPORTANT : un possible bug du programme sur le serveur est possible pour les personnes ayant deja telecharger les anciennes version du programme, nous vous conseillons donc de supprimer le programme et de refaire une installation propre depuis le depot github (https://github.com/lukeclnpro/local_ia)

</details>

<details>
<summary>Version `0.1.4` — 2026-09-22 · **0.1.4**</summary>

- Resolution du bug d'affichage des versions dans le journal de mise a jour
- Fichier concerné : main.py

</details>

<details>
<summary>Version `0.1.3` — 2026-09-22 · **0.1.3**</summary>

- Ajout d'une exception pour les fichier update.json et version.json lors du telechargement de la mise a jour
- Fichier concerné : main.py

</details>

<details>
<summary>Version `0.1.2` — 2026-09-21 · **Première version publique**</summary>

- Ajout du système de gestion des modèles Ollama.
- Ajout du lancement de l'IA locale.
- Ajout de la gestion des conversations.
- Ajout de la configuration de l'IA.

</details>

<!-- UPDATES:END -->

## ⚠️ Anciennes versions

Pour les mises à jour depuis une version **inférieure ou égale à `0.0.4`**, certains fichiers peuvent manquer à cause de l'ancien système de téléchargement.

Après la mise à jour, exécutez :

### Linux

```bash
cd local_ia
python3 main.py force_update
```

### Windows

```powershell
cd $HOME/Documents/local_ia
python main.py force_update
```

## 📁 Structure du projet

```text
local_ia/
├── main.py                 # Programme principal
├── server.py               # Serveur web local
├── local_ia/               # Package de l'agent IA
│   ├── core/               # Agent, contexte, mémoire, conversations
│   ├── llm/                # Client Ollama
│   ├── tools/              # Outils utilisés par l'agent
│   ├── web/                # Serveur et API web
│   └── cli/                # Interface terminal
├── ui.py                   # Interface terminal
├── setup.py                # Installation
├── uninstall.py            # Désinstallation
├── config.json             # Configuration
├── version.json            # Version actuelle
├── update.json             # Journal des mises à jour
├── list.json               # Modèles Ollama détectés
├── web/                    # Interface web
└── scripts/
    └── generate_readme.py  # Génération du README dynamique
```

## 🤝 Contribution

Les issues et pull requests sont les bienvenues.

1. Forkez le dépôt.
2. Créez une branche :

```bash
git checkout -b feature/ma-fonctionnalite
```

3. Effectuez vos modifications.
4. Vérifiez le fonctionnement du projet.
5. Ouvrez une pull request.

## 📄 Licence

Voir les fichiers du dépôt pour les informations de licence.

---

<p align="center">
  <sub>Local IA — exécution locale, vos modèles restent sur votre machine.</sub>
</p>

## 📁 Commandes `/fichier`

Le chat peut maintenant lire et créer/modifier des fichiers directement avec des commandes.

### Lire un fichier

Syntaxe exacte :

```text
/fichier-"extension"-"chemin"
```

Exemple :

```text
/fichier-"py"-"/chemin/vers/main.py"
```

Le contenu du fichier est chargé dans le contexte de l'IA sans être recopié dans l'affichage de la conversation.

Une syntaxe simplifiée est également disponible :

```text
/fichier "/chemin/vers/main.py"
```

### Créer un fichier

```text
/fichier-create-"md"-"./README_test.md"
# Mon fichier

Contenu généré ou fourni après la commande.
```

ou :

```text
/fichier create "./README_test.md"
# Mon fichier
```

### Modifier un fichier

```text
/fichier-edit-"txt"-"./notes.txt"
Nouveau contenu du fichier.
```

Par sécurité, le serveur limite par défaut les accès au dossier de Local IA. Des dossiers supplémentaires peuvent être autorisés avec `file_access_roots` dans `config.json` :

```json
{
  "file_access_roots": [
    ".",
    "~/Documents/mes-projets"
  ]
}
```

La taille maximale par défaut est de 2 Mo pour les fichiers texte et les écritures. Les archives ZIP sont lues sous forme de liste de contenu.

## ▶️ Exécuter un programme

Le chat peut lancer un programme local avec la commande suivante :

```text
/executer "./main.py" --help
```

Les arguments peuvent être placés entre guillemets. Les fichiers Python sont lancés avec l'interpréteur Python courant; les autres programmes doivent être exécutables par le système. Le programme et son répertoire de travail doivent se trouver dans une racine autorisée par `file_access_roots`.

Pour éviter les blocages, chaque exécution est limitée à 30 secondes et la sortie à 64 Ko. La commande `/execute` est également acceptée.

### Commandes système demandées à l'IA

L'IA peut demander l'exécution d'une commande selon le contexte lorsqu'un utilisateur le demande clairement. Une commande explicite comme « lance Firefox » ou `/commande "firefox"` est autorisée pour cette requête. Pour autoriser aussi les commandes contextuelles sans demande explicite, activez volontairement cette option dans `config.json` :

```json
{
  "command_execution": {
    "enabled": true,
    "timeout": 30
  }
}
```

Les commandes sont transmises sous forme d'arguments séparés et ne passent jamais par un shell : les pipes, redirections et enchaînements shell ne sont pas interprétés. Si l'IA propose une commande sans demande explicite, elle demande d'abord une confirmation; répondre « oui » exécute uniquement cette commande. La désactivation par défaut est recommandée lorsque le serveur est accessible sur le réseau.

Pour une application, l'IA recherche un nom exact dans les applications installées puis la lance. Elle ne lance pas une application dont le nom est seulement ressemblant. Sous Linux, les fichiers `.desktop` sont recherchés dans les dossiers d'applications utilisateur et système; « Word » peut utiliser LibreOffice comme alternative lorsqu'il est installé.
