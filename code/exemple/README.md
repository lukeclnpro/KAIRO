# Bibliothèque d'exemples réutilisables

Ces exemples sont des fonctions autonomes, sans dépendance externe. Local IA peut les consulter pendant une tâche `/code`, puis reprendre uniquement les fonctions pertinentes dans le projet actif.

## Python

- `text.py` : nettoyage, normalisation, slug, troncature et masquage de texte.
- `collection_helpers.py` : découpage en lots, déduplication, regroupement, pagination et recherche.
- `files.py` : lecture/écriture JSON, écriture atomique, parcours de fichiers et empreinte SHA-256.
- `validation.py` : limites numériques, validation d'adresse e-mail/URL, mot de passe et entier.
- `dates.py` : dates ISO, différence de jours et durées lisibles.
- `url_helpers.py` : construction d'URL, paramètres de requête et extraction de paramètres.

## JavaScript

- `javascript.js` : fonctions utilitaires pour chaînes, nombres, tableaux, HTML, URL, dates et temporisation d'événements.

L'IA doit lire les fonctions et leurs docstrings avant de les adapter. Elle doit vérifier les entrées et conserver les exemples d'origine intacts, sauf demande explicite de modification.
