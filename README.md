# Widget iPhone d'événements culturels

Affiche sur l'écran d'accueil iPhone les prochaines séances et événements de lieux prédéfinis (La Scala à Thionville, L'Arsenal à Metz, etc.). Les données viennent d'un fichier JSON hébergé sur GitHub Pages ; le widget est un script [Scriptable](https://scriptable.app). Aucun Google Calendar impliqué.

Cette première version (étape 1 du plan) contient :

- `data/events.json` : la programmation de La Scala du 7 au 13 octobre 2026 (+ les événements à venir du PDF) et celle de L'Arsenal (Metz) ;
- `widget/EventsWidget.js` : le widget (tailles petit / moyen / grand, filtre par lieu, cache hors ligne) ;
- `scripts/` + `.github/workflows/refresh-scrape.yml` : mise à jour automatique de L'Arsenal et purge des événements passés (voir « Mise à jour automatique ») ;
- `pdf/` + `.github/workflows/import-pdf.yml` : import du programme hebdomadaire PDF de La Scala (voir « Importer le PDF de La Scala »).

## Installation

### 1. Publier le JSON sur GitHub Pages

1. Crée un dépôt **public** sur GitHub (par exemple `culture-widget`) et envoie-y le contenu de ce dossier.
2. Dans le dépôt : **Settings > Pages > Build and deployment**, source **Deploy from a branch**, branche `main`, dossier `/ (root)`, puis **Save**.
3. Après une ou deux minutes, le fichier est disponible à l'adresse :
   `https://<ton-pseudo>.github.io/<nom-du-depot>/data/events.json`
   Ouvre-la dans Safari pour vérifier qu'elle affiche bien le JSON.

### 2. Installer le widget sur l'iPhone

1. Installe **Scriptable** depuis l'App Store.
2. Dans Scriptable, appuie sur **+** pour créer un script, nomme-le `EventsWidget`, et colle le contenu de `widget/EventsWidget.js`.
3. Modifie la ligne `JSON_URL` en haut du script avec l'adresse de l'étape précédente.
4. Appuie sur le bouton lecture : un aperçu moyen s'affiche. Si tu vois les séances, c'est bon.

### 3. Ajouter le widget à l'écran d'accueil

1. Appui long sur l'écran d'accueil, bouton **+**, cherche **Scriptable**, choisis la taille (petit, moyen ou grand) et **Ajouter le widget**.
2. Appuie sur le widget pour le modifier :
   - **Script** : `EventsWidget`
   - **Paramètre** : voir ci-dessous (facultatif)

### Paramètre du widget (filtre)

Le paramètre est une liste séparée par des virgules, comparée au lieu, à la ville ou à la catégorie (sans tenir compte des majuscules ni des accents) :

| Paramètre | Résultat |
|---|---|
| *(vide)* | tous les événements |
| `La Scala` | uniquement La Scala |
| `Metz` | uniquement les événements à Metz |
| `concert,spectacle` | uniquement ces catégories |
| `La Scala,L'Arsenal` | ces deux lieux |

Astuce : tu peux ajouter plusieurs widgets avec des paramètres différents (un « Cinéma », un « Concerts »).

## Comportement

- Les séances du jour s'affichent d'abord, puis celles des jours suivants. Un même film est regroupé sur une ligne avec toutes ses heures de la journée.
- Une séance reste affichée 10 minutes après son début.
- Hors ligne, le widget affiche la dernière version reçue (cache local) avec la mention « Hors ligne ».
- Le widget demande un rafraîchissement toutes les 15 minutes environ, mais c'est iOS qui décide du rythme réel (de 15 minutes à plusieurs heures).

## Mise à jour automatique

Le workflow **Rafraîchir les événements** (`.github/workflows/refresh-scrape.yml`) tourne deux fois par jour (vers 5 h et 15 h, heure de Paris) et peut aussi être lancé à la main : onglet **Actions > Rafraîchir les événements > Run workflow**.

À chaque passage il :

1. récupère la programmation de L'Arsenal sur le site de la Cité musicale-Metz (toutes les pages, 1 requête par seconde, `robots.txt` respecté) et remplace les événements de L'Arsenal ;
2. **supprime les événements passés** : tout ce qui s'est terminé avant le début de la journée en cours (heure de Paris) disparaît, donc les événements de la veille sont retirés le matin. Une exposition ou un événement sur plusieurs jours reste jusqu'à son dernier jour ;
3. vérifie que le JSON est valide (jamais de fichier cassé publié), puis le commit si quelque chose a changé.

Si le site de L'Arsenal est inaccessible ou que sa mise en page change au point que plus rien n'est lu, les anciennes données de L'Arsenal sont conservées, la purge a quand même lieu, et le workflow passe en **échec** : GitHub t'envoie alors un e-mail. La Scala n'est pas touchée par ce workflow (ses données viendront de l'étape PDF).

Tester en local (Python 3.11+) :

```
pip install -r requirements.txt
python -m unittest discover -s scripts/tests -v     # tests sans réseau
python scripts/merge.py                              # purge seule
python scripts/scrape_sources.py                     # scraping de L'Arsenal + purge
python scripts/extract_pdf.py --dry-run pdf/x.pdf    # test d'un PDF de La Scala
```

Pour ajouter un lieu : créer `scripts/sources/<nom>.py` (constante `LIEU`, fonction `fetch_events()`) et l'ajouter à la liste `SOURCES` de `scripts/scrape_sources.py`.

Pour inclure aussi la BAM et les Trinitaires (autres salles de la Cité musicale), il faut modifier `scripts/sources/arsenal.py` : pour l'instant seuls les événements de L'Arsenal sont retenus.

## Importer le PDF de La Scala

Chaque semaine, La Scala publie une grille horaire en PDF (« Horaires du mercredi 30 septembre au mardi 6 octobre 2026 »).

1. Dépose le PDF dans le dossier `pdf/` du dépôt (nom libre, par exemple `scala-2026-10-07.pdf`). Depuis l'iPhone, le plus simple est Safari sur github.com : dépôt > **Add file > Upload files**, puis **Commit changes**.
2. Le workflow **Importer le programme PDF de La Scala** se lance tout seul (ou à la main : onglet **Actions**, **Run workflow**).
3. Il lit la grille avec `pdfplumber`, remplace toutes les séances de La Scala de cette semaine-là, ajoute les « Événements à venir » du bas du PDF (ciné-débats, avant-premières...), purge le passé, valide le JSON et le commit.

Ce qui est repris : titre, horaires par jour, durée, version (VOST/VF), et les mentions des bandeaux (« Dernière semaine », « Jeune public », « Avant-première », ciné-club, festival...) dans le champ `note`. Les anciens PDF restent dans `pdf/` sans effet : leurs séances sont passées donc purgées.

Si la mise en page du PDF change au point de ne plus être reconnue, le workflow échoue (e-mail GitHub) et `events.json` n'est pas modifié. Pour vérifier un PDF sans rien écrire : `python scripts/extract_pdf.py --dry-run pdf/mon-fichier.pdf`.

## Format du JSON

```json
{
  "updated_at": "2026-10-04T18:00:00+02:00",
  "events": [
    {
      "id": "la-scala-2026-10-07-2020-her-private-hell",
      "lieu": "La Scala",
      "ville": "Thionville",
      "categorie": "cinema",
      "titre": "Her Private Hell",
      "debut": "2026-10-07T20:20:00+02:00",
      "duree_min": 110,
      "version": "VOST",
      "note": "texte libre facultatif",
      "url": "https://www.thionville.fr/scala/programmation-cinema"
    }
  ]
}
```

Catégories prévues : `cinema`, `concert`, `spectacle`, `expo`, `festival`. Les champs `duree_min`, `version`, `note`, `fin` et `jour_entier` sont facultatifs.

Événements sans heure précise ou sur plusieurs jours (exposition, spectacle sur trois jours) : `jour_entier: true`, `debut` à minuit et `fin` à 23:59:59 du dernier jour. Le widget les affiche sous « Aujourd'hui » tant qu'ils sont en cours, avec « → 15 nov. » (ou « journée » pour un seul jour). Dates en ISO 8601 avec fuseau (`+02:00` en heure d'été, `+01:00` à partir du 25 octobre 2026).

## Prochaines étapes

3. Scraping automatique de La Scala (L'Arsenal est déjà en place) : le PDF reste le moyen fiable en attendant.
4. Lignes cliquables dans le widget pour déclencher une Action GitHub (token fine-grained dans le Keychain).
