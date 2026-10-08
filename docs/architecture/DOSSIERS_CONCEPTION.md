# Conception des dossiers autonomes

## Relations et mutualisation

Un dossier possède une organisation, un propriétaire et un CaseFile autonome. Une conversation conserve son CaseFile local historique et peut désigner un dossier. Les accès au contexte partagé passent par le service CaseFile existant ; le chat, son rendu et son orchestration restent communs. Le dossier ne dépend pas de sa première conversation.

Un document conserve son organisation, mais porte éventuellement un dossier privé ou une conversation privée. Son rattachement au contexte commun utilise CaseDocumentLink. Un retrait rend le document privé indisponible sans changer les messages historiques. Les documents d’entreprise référencés conservent leur visibilité d’origine.

## Matrice des droits

| Ressource | Propriétaire membre actif | Autre membre | Autre organisation | Administration |
| --- | --- | --- | --- | --- |
| Dossier personnel | Lire et modifier si actif ; lire si archivé | Refus | Refus | Accès explicite existant, pas de découverte dans la liste personnelle |
| Document privé | Lecture dans le contexte autorisé et si non retiré | Refus | Refus | Autorisation explicite ; jamais corpus général |
| Document entreprise | Droits entreprise existants | Droits entreprise existants | Refus | Droits administratifs existants |
| Contexte et messages | Droits conversation et dossier | Refus | Refus | Droits d’audit existants |

La recherche générale exclut les documents privés. La lecture ciblée exige une autorisation en base avant la recherche par identifiants. Les listes et accès documentaires d’entreprise excluent les pièces privées. Les droits sont vérifiés à nouveau avant transmission du contenu.

## Migration et retour arrière

Migration additive : nouvelle table dossiers, références facultatives et marqueur distinct de masquage de l’historique ; le lien historique CaseFile vers une conversation devient facultatif. Aucun dossier nommé n’est créé automatiquement et aucun document historique ne change de visibilité.

Sauvegarder avant migration de production. Un retour au code ancien est interdit tant que des pièces privées restent dans la base et les index qu’il peut consulter. Le downgrade refuse donc les nouvelles données ; restaurer une sauvegarde ou appliquer une procédure de migration dédiée, sans effacer les nouvelles pièces pour faciliter le retour.

Décision du 7 octobre 2026 : suppression définitive depuis la page ou la sidebar, après confirmation. DELETE /dossiers/{id} contrôle les droits et la version, verrouille le projet, puis supprime ses contextes, conversations, messages et documents privés dans une transaction. Les documents d’entreprise associés restent conservés. Les suppressions des fichiers et extractions sont journalisées avant commit puis exécutées via le mécanisme de nettoyage existant. Les commandes d’archivage ne sont plus proposées dans l’interface ; les anciens projets archivés restent accessibles pour suppression.

## Vérifications

Tester les droits entre utilisateurs et dossiers, les pièces privées dans les listes et recherches, la création atomique et répétée depuis un chat, les conflits de versions, l’archivage, les corrections du contexte partagé et le masquage de l’historique. Vérifier les deux parcours avec les composants communs ; aucune évaluation éditoriale ni appel LLM réel n’est nécessaire pour ces contrats.

## Livraison locale du 7 octobre 2026

Branche : `feat/dossiers-autonomes`. Le chat libre et les conversations de dossier
partagent le composant Conversation, ChatInput et l’endpoint de streaming existants.
La page et le panneau latéral du dossier partagent DossierContent ; les informations
réutilisent EntryCard et les opérations de versionnement CaseFile.

Les pièces peuvent recevoir un intitulé et une description propres au rattachement.
Un remplacement explicite crée une nouvelle pièce et retire l’ancienne du contexte
actif, avec les identifiants conservés dans l’événement de versionnement. Le document
d’entreprise d’origine reste intact. Les messages historiques ne sont pas modifiés.
Les corrections manuelles du contexte partagé ne sont pas modifiables par une action
LLM : un refus d’autorisation de mutation est distinct de la sortie brute conservée.
Aucune évaluation éditoriale n’est ajoutée.

### Démarrage isolé

Une autre application utilise déjà les ports 3000 et 8000 sur ce poste. Les essais
AORIA sont donc accessibles sur `http://localhost:3001`, avec l’API sur 8001.
PostgreSQL (5544), Qdrant (6335), Redis (6382) et MinIO (9100) utilisent des volumes
propres au projet Docker `aoria-dossiers-local`, sans reprise des données de production.

Depuis la racine du dépôt, pour réinitialiser les services arrêtés sans effacer les données :

```sh
sh scripts/dev/dossiers-local.sh infra
sh scripts/dev/dossiers-local.sh migrate
sh scripts/dev/dossiers-local.sh seed
```

Puis lancer chaque commande dans un terminal distinct :

```sh
sh scripts/dev/dossiers-local.sh backend
sh scripts/dev/dossiers-local.sh worker
sh scripts/dev/dossiers-local.sh frontend
```

Compte local : `dossiers-local@example.com`, mot de passe `Local-Dossiers-2026!`.
Organisation : **AORIA — Essais locaux**. Ces identifiants sont réservés à cette
base locale. Le worker local ne lance aucun calendrier de synchronisation ; les
emails et Stripe sont désactivés par le lanceur.

Le corpus juridique de production n’est pas copié : tester d’abord le parcours,
les informations et ses propres pièces de démonstration. Les questions réelles
utilisent la configuration LLM existante du backend et peuvent consommer des appels
API. Les tests automatisés ne jugent pas la qualité des générations ; le contrôle
navigateur de transmission du premier message utilise un flux SSE témoin.

La création d’une base vierge a également révélé l’absence d’une ancienne migration
pour `messages.feedback_comment`. La migration de compatibilité `l1m2feedback03`
ajoute la colonne seulement si nécessaire et ne supprime pas les commentaires
existants lors d’un retour arrière.

### Recette

- Créer un dossier nommé ; compléter ses informations ; retrouver les mêmes
  informations depuis le panneau du chat.
- Importer une pièce privée ; la télécharger, décrire, remplacer et retirer ;
  vérifier son absence des Documents de l’entreprise.
- Ouvrir plusieurs conversations ; rechercher un titre ; masquer les conversations
  récentes et retrouver l’historique dans le dossier.
- Depuis un échange libre, créer un nouveau dossier après sélection des informations.
  Aucune action ne permet de l’ajouter à un dossier existant.
- Épingler, renommer et supprimer un dossier après confirmation ; vérifier que les
  anciens dossiers archivés restent consultables et supprimables.
- Vérifier les brouillons et les messages de conflit, ainsi que l’affichage mobile.

Vérifications réalisées : migrations appliquées à PostgreSQL local ; 141 tests backend
ciblés ; 33 tests frontend ; vérification TypeScript sans émission ; parcours navigateur
sur Chrome en bureau et en largeur 390 px. Le contrôle de confidentialité des recherches
s’exécute aussi avec un client Qdrant en mémoire, sans mock du filtre.

La suppression définitive est disponible conformément à la décision utilisateur du
7 octobre. Aucune livraison en production n’est effectuée.

### Incident local de quota constaté pendant la recette

Le 7 octobre à 13 h 27, le fournisseur IA a renvoyé `credit_balance_exhausted`
(`insufficient_quota`). Le compte API configuré doit être rechargé pour tester des
réponses réelles. Le code distingue désormais ce refus d’une limitation temporaire,
affiche un message persistant et conserve la question ainsi que tout texte déjà reçu.
Aucune relance automatique ni réponse de substitution n’est ajoutée.


Vocabulaire retenu après recette : **Dossiers** dans toute l’interface. La navigation
regroupe Documents, Informations générales et Équipe sous Organisation. Dossiers
constitue une section distincte avec son chevron près du titre, un bouton + au
survol ou au focus et les quatre derniers dossiers, sans conversations imbriquées.

### Audit technique du 7 octobre 2026

Corrections réalisées :

- Les références communes sont marquées comme appartenant au dossier. Les anciennes
  pièces privées retirées ou remplacées ne sont plus réinjectées depuis les messages.
  Une pièce indisponible ou non préparée déclenche une erreur explicite.
- Un conflit après import déclenche le nettoyage du nouveau fichier non associé.
  Les droits et les liens sont revérifiés après la préparation documentaire,
  qui peut libérer les verrous lors de ses transactions internes.
- Les états affichés distinguent préparation, erreur et indisponibilité, en contrôlant
  aussi la version du fichier. Un lien vers un document disparu peut être retiré.
  Un import partiellement réussi rafraîchit la liste et conserve son message d’erreur.
- La navigation entre dossiers réinitialise les états locaux. Un rafraîchissement du
  panneau, y compris en erreur, conserve le formulaire et les modifications en cours.
- La suppression utilise le client HTTP avec délai borné et bloque les doubles clics.
  Le message d’erreur est réinitialisé pour une nouvelle cible.
- Le serveur trie les dossiers récents avant pagination ; la sidebar demande quatre
  résumés et ne charge plus systématiquement le détail du dossier courant.
- Suppression d’un import inutilisé, correction des dépendances des effets React et
  de requêtes redondantes, validation des intitulés vides, maintien de l’identité des
  informations manuelles lors d’une correction.
- Le lanceur du worker local transmet réellement les paramètres ARQ hérités, tout
  en désactivant les tâches planifiées. Démarrage et indexation locale vérifiés.

Validation : 132 tests backend ciblés, 25 tests frontend, TypeScript, ESLint sur les
composants/pages/API frontend Dossiers et Ruff sur les nouveaux modules backend.
Après la dernière correction du chemin d’import depuis le chat, les tests backend
Dossiers, documents conversationnels et erreurs chat sont relancés séparément.
Le parcours Chrome crée un dossier temporaire avec un fichier et une conversation,
annule une première suppression puis confirme la suppression et vérifie les réponses
404 pour les ressources supprimées. Aucun appel de génération ni évaluation éditoriale.

Points de vigilance conservés :

- Les messages antérieurs au marquage des références communes ne permettent pas
  toujours de distinguer une ancienne pièce d’organisation d’une pièce explicitement
  jointe à la conversation. Les anciens documents privés du dossier sont filtrés par
  leur propriété en base ; aucune réécriture de l’historique n’est effectuée.
- La suppression des blobs dispose du journal de reprise existant. Le nettoyage des
  vecteurs Qdrant repose encore sur le mécanisme général du projet, qui journalise une
  panne sans file durable de reprise ; cette limite d’infrastructure reste à traiter.
- L’API historique d’archivage est conservée pour compatibilité avec les données et
  clients antérieurs ; l’interface ne propose que la suppression.
- Les tests techniques ne constituent pas une garantie de qualité juridique des
  réponses. Le corpus juridique de production n’est pas présent dans l’environnement local.

### Consultation ciblée intégrée — 8 octobre 2026

La décision est incluse dans le planificateur commun du chat (`requests_v3`), via
`document_checks` : zéro à deux questions précises, chacune limitée à un ensemble
explicite de pièces actives autorisées. Une liste vide ne déclenche aucun appel
supplémentaire. Le seul fait de posséder un dossier ou une pièce partiellement lue
ne déclenche pas une vérification. Les demandes sont compilées vers l’exécuteur de
recherche documentaire existant ; aucun second modèle n’évalue une réponse produite.

Les contrôles portent sur le format, le nombre d’opérations et les identifiants
accessibles. Les anciens plans à deux champs restent décodables ; les nouveaux
appels structurés demandent explicitement `document_checks`. Au passage de
continuation, cette liste doit rester vide. Les plafonds d’exécution existants
restent applicables, et aucune relance éditoriale n’est ajoutée.

La recherche ciblée conserve les références et les extraits des autres pièces.
Les nouveaux passages sont transmis avec les sources initiales à la rédaction.
Un retour vide est distingué d’un échec de consultation. Les erreurs de consultation
alimentent les avertissements techniques existants et les traces ; les générations
restent intégrales. Un échec de transaction SQL remonte comme erreur technique.

Recette réelle locale : `scripts/dev/check_dossier_evidence_live.py`, avec option
explicite `--run`. PostgreSQL, MinIO, indexation, recherche Qdrant et appels IA réels,
sans résultat documentaire simulé. Un règlement fictif de 152 955 octets (111 chunks)
et une note de frais ont été importés dans un dossier temporaire, puis supprimés.
Résultats originaux dans `docs/tests/dossier-evidence-live-2026-10-08-run2/` :

- Mail sans rapport avec les pièces : `document_checks=[]`, aucune consultation
  supplémentaire, réponse en 7,37 s.
- Question sur la prise en charge de la dépense : une consultation ciblée du règlement,
  clause réellement retrouvée (plafond de 65 euros, arrivée après 22 h, reçu sous
  30 jours), réponse en 11,50 s pour la dépense fictive de 52 euros.
- Délai du règlement déjà présent dans les premiers extraits : aucune consultation
  supplémentaire, réponse en 5,26 s.

Chaque question n’a utilisé qu’un passage du planificateur. Ces trois observations
ne constituent pas une garantie générale de pertinence ou de fiabilité juridique.
Les coûts imputés aux questions dans les traces ne couvrent pas nécessairement
l’indexation et toutes les opérations initiales non attribuées. Le premier lancement
HTTP a précédé la disponibilité du serveur et n’a produit aucun appel IA ; le second
lancement a achevé les trois scénarios sans erreur de chat.

Validation technique : 96 tests ciblés couvrant les contrats, l’orchestration, les
pièces conversationnelles, les dossiers et leurs informations. Les régressions
vérifient notamment les identifiants hors périmètre, les plafonds, la continuation,
la conservation des extraits, le signalement des erreurs sans relance et l’absence
de consultation quand le plan ne demande aucun complément.


### Plan de livraison en production — 8 octobre 2026

Livraison directe des dossiers et de la consultation ciblée, sans restriction
administrateur, conformément à la décision utilisateur. La branche part de
`11ab13b`, également présent en production avant livraison. Les modifications
locales étrangères à ce chantier restent hors du commit.

Séquence prévue : sauvegarde PostgreSQL au format custom et contrôle de son
catalogue ; construction des images backend, worker et frontend ; application
transactionnelle des trois migrations de `i8j9chronology01` vers
`l1m2feedback03` avec un conteneur ponctuel sans dépendances ; redémarrage ciblé
`--no-deps` des trois services. Les migrations sont additives et conservent les
données historiques. Aucun changement de configuration de production n'est requis.

Contrôles : tests des dossiers, du chat, de l'accès documentaire et de l'interface,
compilation de production, version Alembic, santé de l'API et de ses dépendances,
stabilité des conteneurs, absence d'erreurs applicatives nouvelles et présence des
routes Dossiers dans les conteneurs livrés. La sauvegarde ne doit pas être restaurée
automatiquement en cas d'incident ; la contrainte de retour arrière décrite plus
haut reste applicable après la création de pièces privées.
