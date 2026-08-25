# Déploiement en production — application AORIA RH

Cette procédure concerne le dépôt `Waibly/aoriarh`, qui alimente l'application
et l'API AORIA RH.

Les identifiants, l'hôte, le port SSH et les autres informations sensibles sont
conservés dans `ACCES_PROD.md`, à la racine du projet. Ce fichier est local,
ignoré par Git et ne doit jamais être affiché dans une réponse, commité ou copié
dans un journal.

## Principes

- Une demande explicite telle que « déploie en prod » autorise la livraison de
  la modification demandée. Ne pas demander une seconde confirmation.
- Si un déploiement est annoncé comme étant en cours, attendre sa fin avant d'en
  commencer un autre. Vérifier l'activité sur le serveur AORIA RH ; une CI GitHub
  terminée n'est pas, à elle seule, la preuve d'un déploiement terminé.
- Préserver les modifications locales sans rapport avec la livraison.
- Ajouter au commit uniquement les fichiers concernés, avec des chemins
  explicites. Ne jamais utiliser `git add .`.
- Utiliser `git pull --ff-only` sur le serveur.
- Reconstruire uniquement les services concernés, avec `--no-deps`.
- Aucun secret ne doit apparaître dans les commandes journalisées ou les sorties
  adressées à l'utilisateur.

## 1. Contrôles locaux

Depuis la racine du dépôt :

```bash
git status -sb
git diff --check
git diff -- <fichiers concernés>
```

Exécuter les tests proportionnés au changement. Pour une modification de la
fiche pratique :

```bash
python3 -m pytest backend/tests/test_fiche_service.py -q
```

Les échecs préexistants hors périmètre doivent être signalés, mais ne doivent ni
être corrigés ni ajoutés au commit sans demande explicite.

## 2. Commit et publication

Vérifier que la branche locale est alignée avec `origin/main` :

```bash
git fetch origin
git status -sb
```

Ajouter seulement les fichiers de la livraison, puis contrôler l'index :

```bash
git add <fichier-1> <fichier-2>
git diff --cached --check
git diff --cached --stat
git status --short
git commit -m "<message précis>"
git push origin main
```

Si le commit demandé est déjà présent sur `origin/main`, ne pas créer de commit
vide et passer à l'étape suivante.

## 3. Préparation du serveur

Utiliser exclusivement la connexion indiquée dans `ACCES_PROD.md`, puis :

```bash
cd ~/aoriarh
git status -sb
git rev-parse HEAD
docker compose -f docker-compose.prod.yml ps
```

S'assurer qu'aucun build ou redémarrage du projet n'est en cours. Les fichiers
locaux non versionnés attendus sur le serveur ne doivent pas être supprimés.

Récupérer ensuite le commit publié :

```bash
git pull --ff-only
git log -1 --oneline
```

Le hash affiché doit correspondre au commit livré.

## 4. Reconstruction ciblée

Choisir uniquement les services réellement concernés :

- routes API, services backend ou génération de PDF : `backend` ;
- interface Next.js : `frontend` ;
- tâches asynchrones : `worker` ;
- code backend partagé par l'API et le worker : `backend worker`.

Exemple pour le backend :

```bash
docker compose -f docker-compose.prod.yml up -d --build --no-deps backend
```

Exemple pour le frontend :

```bash
docker compose -f docker-compose.prod.yml up -d --build --no-deps frontend
```

Ne pas reconstruire l'ensemble de la stack pour une modification isolée. Les
migrations, changements de variables d'environnement, de Caddy ou
d'infrastructure nécessitent un plan spécifique avant exécution.

## 5. Contrôles post-déploiement

Pour une livraison backend :

```bash
docker compose -f docker-compose.prod.yml ps backend
docker logs --tail 100 aoriarh-backend-1
curl -sS https://api.aoriarh.fr/health
docker inspect aoriarh-backend-1 --format \
  'status={{.State.Status}} running={{.State.Running}} restart_count={{.RestartCount}}'
```

Le déploiement est réussi uniquement si :

- le conteneur concerné est démarré et reste stable ;
- `restart_count` reste à `0` après le démarrage ;
- l'endpoint de santé retourne `status: ok` et ses dépendances sont disponibles ;
- les logs récents ne contiennent ni traceback ni erreur applicative liée au
  changement ;
- le commit et, lorsque c'est pertinent, le contenu attendu sont présents dans
  le conteneur.

En cas d'échec, consulter les logs avant toute action. Ne pas lancer de rollback
destructif ou de restauration de données sans accord explicite.
