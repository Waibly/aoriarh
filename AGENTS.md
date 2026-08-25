# Instructions du projet AORIA RH

## Sorties des LLM

- Toute réponse non vide produite par un LLM doit être renvoyée et affichée à l'utilisateur.
- Ne jamais altérer, nettoyer, tronquer, réécrire ou compléter une génération après sa production.
- Ne jamais bloquer ou masquer une génération en raison d'un validateur éditorial, stylistique ou de format.
- Si un contrôle est utile, il peut uniquement produire un avertissement visible à côté de la réponse brute ; il ne doit ni modifier la réponse ni empêcher son affichage.
- Les contraintes de contenu et de format doivent être placées dans le prompt de génération, pas dans un post-traitement.
- Une sortie vide, une erreur de transport ou un délai expiré peuvent être retentés ou signalés comme des erreurs techniques.

## Déploiement en production

- Avant toute livraison, lire intégralement `docs/DEPLOIEMENT_PRODUCTION.md` et le fichier local non versionné `ACCES_PROD.md`.
- Suivre exclusivement la procédure et les accès indiqués dans ces deux fichiers.
- Une demande explicite de déploiement vaut autorisation pour le commit, le push et les commandes de livraison prévues par la procédure. Ne pas redemander une confirmation déjà donnée.
- Ne reconstruire que les services concernés et toujours employer `--no-deps` pour un déploiement isolé.
- Ne déclarer le déploiement terminé qu'après les contrôles post-déploiement prévus par la procédure.
