# Widget iPhone d'événements culturels

Affiche sur l'écran d'accueil iPhone les prochaines séances et événements de lieux prédéfinis (La Scala à Thionville, L'Arsenal à Metz, etc.). Les données viennent d'un fichier JSON hébergé sur GitHub Pages ; le widget est un script [Scriptable](https://scriptable.app). Aucun Google Calendar impliqué.

Cette première version (étape 1 du plan) contient :

- `data/events.json` : la vraie programmation de La Scala du 7 au 13 octobre 2026 (+ les événements à venir du PDF) et quelques événements **fictifs** pour L'Arsenal (titres préfixés `[Exemple]`, à remplacer à l'étape 3) ;
- `widget/EventsWidget.js` : le widget (tailles petit / moyen / grand, filtre par lieu, cache hors ligne).

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

Catégories prévues : `cinema`, `concert`, `spectacle`, `expo`, `festival`. Les champs `duree_min`, `version` et `note` sont facultatifs. Dates en ISO 8601 avec fuseau (`+02:00` en heure d'été, `+01:00` à partir du 25 octobre 2026).

## Prochaines étapes

2. Chaîne PDF vers JSON (extraction avec `pdfplumber`, GitHub Action déclenchée par un dépôt dans `pdf/`).
3. Scraping automatique de La Scala et de L'Arsenal.
4. Lignes cliquables dans le widget pour déclencher une Action GitHub (token fine-grained dans le Keychain).
