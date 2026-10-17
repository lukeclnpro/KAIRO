# KAIRO

**Assistant personnel avec modèles locaux ou OpenRouter.** Version actuelle : **0.2.0.21 (bêta 21)**.

## Installer KAIRO sur Windows

La méthode recommandée est l’installateur Windows. Python n’est pas nécessaire : l’application et son runtime sont inclus dans le paquet.

1. Ouvrez la page [Releases de KAIRO](https://github.com/lukeclnpro/KAIRO/releases).
2. Dans les fichiers de la version souhaitée, téléchargez `KAIRO-Setup-<version>.exe`.
3. Lancez le fichier téléchargé et choisissez le dossier d’installation. Le chemin proposé par défaut est `%LOCALAPPDATA%\Programs\KAIRO`.
4. À la fin, démarrez KAIRO depuis le menu Démarrer ou le raccourci créé par l’installateur.

Le programme installé s’ouvre dans son interface graphique. Gardez l’ensemble du dossier d’installation : l’exécutable s’appuie sur les fichiers qui l’accompagnent.

> **Installateur indisponible ?** Si aucun fichier `KAIRO-Setup-<version>.exe` n’apparaît dans les assets de la release, utilisez la méthode depuis les sources décrite plus bas. Les exécutables Windows doivent être construits sous Windows.

## Premier démarrage

Choisissez l’accès qui correspond à votre configuration :

- **OpenRouter** : connectez-vous ou créez un compte KAIRO, puis autorisez la création d’une clé dans le navigateur. La clé est conservée dans le coffre-fort sécurisé du système.
- **Ollama** : choisissez de continuer sans compte. Ollama doit être installé et démarré séparément; aucun modèle n’est inclus avec KAIRO.

Une connexion Internet est requise pour OpenRouter, la recherche Web et les mises à jour. Les modèles Ollama locaux peuvent être utilisés sans connexion après leur installation.

## Fonctionnalités

- Conversations avec des modèles locaux Ollama ou des modèles OpenRouter.
- Gestion des conversations, projets de code et fichiers.
- Détection, ajout et lancement d’applications installées.
- Installation d’applications depuis le catalogue avec confirmation.
- Gestion des habitudes et notifications en arrière-plan.
- Assistant `iahelp` dans le terminal, qui fournit uniquement les commandes demandées pour Linux, Windows ou macOS.

## Linux et macOS

L’installateur `.exe` est destiné à Windows. Sous Linux ou macOS, utilisez les sources du dépôt avec Python. Le démarrage graphique fonctionne avec `python3 main.py` sous Linux/macOS et `python main.py` sous Windows.

## Alternative : installer depuis les sources

Cette méthode est destinée aux personnes qui n’utilisent pas l’installateur ou souhaitent lancer le code source. Elle requiert Git et Python 3.10 ou plus récent.

Linux/macOS :

```bash
git clone https://github.com/lukeclnpro/KAIRO.git
cd KAIRO
python3 setup.py
```

Windows PowerShell :

```powershell
git clone https://github.com/lukeclnpro/KAIRO.git
cd KAIRO
python setup.py
```

Pour démarrer directement depuis le dépôt, utilisez `python3 main.py` sous Linux/macOS ou `python main.py` sous Windows.

## Licence et versions

KAIRO est distribué sous licence MIT : [LICENSE](LICENSE). Les licences des dépendances sont indiquées dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Consultez [Releases](https://github.com/lukeclnpro/KAIRO/releases) pour les versions et leurs fichiers d’installation, [version.json](version.json) pour la version actuelle et [update.json](update.json) pour l’historique des changements.
