# Instructions du projet AORIA RH

## Sorties LLM : transparence, sans correction automatique

Ces règles concernent les fonctionnalités LLM des applications développées ou modifiées, pas l'interdiction de tester leur code.

- Par défaut, ne pas ajouter de mécanisme automatique qui juge la qualité sémantique, l'intention, le style ou la pertinence d'une génération, notamment par mots-clés, regex, heuristiques ou un autre LLM.
- Conserver et afficher toute génération non vide intégralement, sans nettoyage, troncature, réécriture, reconstruction ni complément. Placer les contraintes de contenu et de format dans les prompts, pas dans un post-traitement.
- Ne pas masquer les défauts par un fallback, un contenu de remplacement ou des relances destinées à obtenir une sortie jugée satisfaisante. Ne pas boucler sur des appels LLM pour satisfaire un validateur.
- Laisser l'utilisateur examiner et juger le contenu original. Ne mettre en place ni lancer d'évaluation de qualité des générations sans demande explicite ; une évaluation demandée reste séparée du rendu et ne le conditionne pas.
- Maintenir les contrôles techniques et de sécurité : droits d'accès, isolation des données, protection des secrets, validation des paramètres d'actions et affichage sûr. Afficher du texte ne signifie pas exécuter son HTML, son code ou ses commandes.
- Si une sortie structurée est inexécutable, signaler l'erreur séparément, sans réparer la génération ni exécuter l'opération de force. Sa sortie brute reste consultable dans le respect des autorisations et de la confidentialité.
- Signaler les sorties vides, erreurs de transport et délais expirés comme des erreurs techniques. Toute politique de relance technique doit être explicite, bornée et ne jamais servir à corriger le contenu.
- Les tests du code, des contrats techniques et des contrôles de sécurité restent autorisés et nécessaires ; ils ne doivent pas devenir des validateurs éditoriaux des générations.

## Audits de code

- Une demande d’audit seule n’autorise pas à modifier les fichiers.
- Pour chaque constat, préciser l’emplacement, les conditions de déclenchement et la conséquence concrète. Examiner les appelants et les protections existantes avant de conclure.
- Distinguer les défauts établis, les risques à confirmer et les améliorations facultatives. Justifier la priorité par l’impact et les conditions réelles.
- Éviter les recommandations génériques ou disproportionnées. L’absence de test et les préférences de style ne suffisent pas à établir un défaut.
- Ne pas chercher un nombre minimum de problèmes. Préciser le périmètre réellement examiné et les limites des conclusions.

## Documentation commune

- La documentation courante est dans le dépôt voisin [aoriarh-docs](../aoriarh-docs/README.md).
- La documentation est reconstruite progressivement avec l’utilisateur. Pour les faits actuels, consulter le code de l’application et du site ; ne pas recréer automatiquement des guides.
- Ne pas recréer de documentation concurrente ni d’archives dans ce dépôt. Les contenus applicatifs, données et preuves privées nécessaires restent dans leurs emplacements techniques.

## Déploiement en production

- Avant toute livraison, lire intégralement [la procédure centrale de livraison](../aoriarh-docs/LIVRAISON.md) et le fichier privé non versionné `../aoriarh-docs/.prive/application/ACCES_PROD.md`.
- Suivre exclusivement la procédure et les accès indiqués dans ces deux fichiers.
- Une demande explicite de déploiement vaut autorisation pour le commit, le push et les commandes de livraison prévues par la procédure. Ne pas redemander une confirmation déjà donnée.
- Ne reconstruire que les services concernés et toujours employer `--no-deps` pour un déploiement isolé.
- Ne déclarer le déploiement terminé qu'après les contrôles post-déploiement prévus par la procédure.
