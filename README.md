# Widget iPhone d'événements culturels

Un widget pour l'écran d'accueil de l'iPhone qui affiche les **prochaines séances de cinéma, concerts et spectacles** de quelques lieux autour de Thionville, Metz et Luxembourg. Un tap sur le widget ouvre la liste complète, avec filtres et recherche.

Le principe : ce dépôt rassemble les programmes de chaque lieu dans un seul fichier, `data/events.json`, publié gratuitement par GitHub Pages et mis à jour automatiquement. Sur l'iPhone, un script [Scriptable](https://scriptable.app) lit ce fichier et dessine le widget. Pas de serveur, pas d'abonnement, pas de compte Google.

## Lieux suivis

| Lieu | Ville | Contenu | Mise à jour |
|---|---|---|---|
| La Scala | Thionville | cinéma | dépôt du PDF hebdomadaire dans `pdf/` |
| Kinepolis Thionville | Thionville | cinéma | script à lancer sur ton PC |
| Théâtre de Thionville, Adagio | Thionville | spectacles, concerts | programme de saison saisi dans `json/` |
| NEST (CDN) | Thionville et alentours | théâtre | automatique, chaque lundi |
| L'Arsenal | Metz | concerts, spectacles, expos | automatique, chaque lundi |
| Philharmonie Luxembourg | Luxembourg | concerts (sans le jeune public) | automatique, chaque lundi |

Le widget n'affiche jamais les événements passés ; ils sont retirés du fichier à chaque mise à jour.

## Installation

### 1. Publier les données sur GitHub Pages

1. Crée un dépôt **public** sur GitHub et envoie-y le contenu de ce dossier.
2. Dans le dépôt : **Settings > Pages > Build and deployment**, source **Deploy from a branch**, branche `main`, dossier `/ (root)`, puis **Save**.
3. Après une ou deux minutes, le fichier est en ligne à l'adresse
   `https://<ton-pseudo>.github.io/<nom-du-depot>/data/events.json`.
   Ouvre-la dans Safari pour vérifier.

### 2. Installer le widget sur l'iPhone

1. Installe **Scriptable** depuis l'App Store.
2. Dans Scriptable, appuie sur **+**, nomme le script `EventsWidget` et colle le contenu de `widget/EventsWidget.js`.
3. Remplace l'adresse de la ligne `JSON_URL`, en haut du script, par celle de l'étape 1.
4. Appuie sur le bouton lecture : si la liste des événements s'affiche, c'est bon.

Tu n'as à coller le script qu'une seule fois : il se met ensuite à jour tout seul à partir de la version publiée sur GitHub, au plus une fois par jour.

### 3. Ajouter le widget à l'écran d'accueil

1. Appui long sur l'écran d'accueil, bouton **+**, cherche **Scriptable**, choisis une taille (petit, moyen ou grand) puis **Ajouter le widget**.
2. Appuie sur le widget pour le configurer : **Script** `EventsWidget`, et éventuellement un **Paramètre** (voir ci-dessous).

## Utilisation

### Filtrer un widget

Le paramètre du widget est une liste séparée par des virgules, comparée au lieu, à la ville ou à la catégorie (majuscules et accents ignorés) :

| Paramètre | Résultat |
|---|---|
| *(vide)* | tous les événements |
| `La Scala` | uniquement La Scala |
| `Kinepolis` | uniquement le Kinepolis |
| `NEST` | le NEST, y compris ses tournées hors de Thionville |
| `Philharmonie` | uniquement la Philharmonie Luxembourg |
| `Metz` | tout ce qui se passe à Metz |
| `cinema` | toutes les séances de cinéma |
| `concert,spectacle` | ces deux catégories |
| `La Scala,Kinepolis` | ces deux cinémas |

Tu peux ajouter plusieurs widgets avec des paramètres différents, par exemple un « Cinéma » et un « Concerts ».

### Ce qu'affiche le widget

- Les événements du jour d'abord, puis ceux des jours suivants. Un même film est regroupé sur une ligne avec toutes ses heures de la journée.
- Une séance reste affichée 10 minutes après son début.
- Un tap ouvre la **liste complète** : défilement, filtres par lieu ou genre et par période (tout, aujourd'hui, 7 jours), recherche, et un tap sur un événement ouvre sa page.
- Hors connexion, le widget affiche la dernière version reçue, avec la mention « Hors ligne ».
- iOS rafraîchit le widget à son rythme, de toutes les 15 minutes à toutes les quelques heures.

## Tenir les programmes à jour

La plupart des lieux se mettent à jour seuls. Il reste deux gestes manuels :

- **La Scala, chaque semaine :** dépose le PDF des horaires dans le dossier `pdf/` du dépôt. Depuis l'iPhone : github.com dans Safari, dépôt > **Add file > Upload files** > **Commit changes**. L'import se fait tout seul en une minute.
- **Kinepolis, idéalement chaque mercredi :** le site bloque les robots, donc le script ouvre un vrai navigateur sur ton PC. La première fois, installe les outils :
  ```
  pip install -r requirements-kinepolis.txt
  python -m playwright install chromium
  ```
  Ensuite, à chaque mise à jour :
  ```
  python scripts/scrape_kinepolis.py
  git add data/events.json && git commit -m "Séances Kinepolis" && git push
  ```

Une nouvelle saison du Théâtre de Thionville ou de l'Adagio se saisit dans un fichier du dossier `json/`. Si une mise à jour automatique échoue (site en panne ou modifié), les anciennes données sont conservées et GitHub t'envoie un e-mail.

## Pour aller plus loin

Le fonctionnement interne (architecture, format des données, détail de chaque source, ajout d'un lieu, tests) est décrit dans [`docs/technique.md`](docs/technique.md).
