# Cahier des charges des dossiers AORIA RH

Version de travail du 7 octobre 2026, complétée avec les exigences d’architecture et de développement. Les parcours fonctionnels précèdent les exigences techniques. Les décisions confirmées sont distinguées des paramètres proposés et des arbitrages restant à résoudre avant livraison.

## 1. Objectif

Permettre à l’utilisateur de suivre un sujet RH dans la durée en réunissant son contexte, ses informations, ses documents et plusieurs conversations. Il doit pouvoir revenir sur un dossier sans repartir de zéro, compléter la situation et retrouver ses échanges précédents.

Mise à jour après recette du 7 octobre : le terme affiché est **Projets**. Le mot dossier reste utilisé ci-dessous pour le modèle fonctionnel et dans les noms techniques existants. Un dossier peut concerner une situation individuelle, une question collective ou un projet RH : « Situation de Mme Martin », « Élections CSE 2027 », « Accord télétravail ». Il n’est pas obligatoirement rattaché à un salarié.

La question libre reste un accès direct essentiel : créer un dossier n’est jamais obligatoire pour interroger AORIA RH.

## 2. Continuité avec AORIA RH

L’interface actuelle propose une sidebar avec le choix d’organisation, Nouvelle question, Fiches pratiques, Documents, Organisation et Équipe selon les droits, puis les conversations récentes. Les cinq premières conversations sont affichées avant une liste dépliable.

Le chat propose déjà un panneau Dossier à droite. Il présente les informations retenues, les éléments à vérifier, le profil de l’entreprise, les documents consultés et les anciennes informations. Une information peut notamment être corrigée, confirmée ou retirée. Ce dossier est actuellement associé à une seule conversation.

La nouvelle fonctionnalité fait du dossier nommé un espace autonome contenant plusieurs conversations. Le panneau existant devient le moyen de consulter et compléter cet espace pendant un échange. Les possibilités actuelles de lecture des sources, de consultation des messages et de travail documentaire sont conservées.

**Décision : mutualiser le chat existant.** Le chat libre et le chat dans un dossier utilisent la même interface de conversation et la même chaîne de traitement. Le contexte disponible varie selon le parcours ; aucune copie autonome du chat n’est créée. Une amélioration ou une correction des composants communs bénéficie aux deux parcours.

L’inspiration ChatGPT porte sur le regroupement de conversations et de documents autour d’un contexte commun, décrit dans la [documentation officielle OpenAI](https://learn.chatgpt.com/docs/projects). Les dispositions ci-dessous sont des choix propres à AORIA RH.

## 3. Principes fonctionnels

- Un dossier appartient à une organisation et, pour cette première version, reste personnel à son utilisateur dans les parcours ordinaires. Le rattachement à une organisation ne vaut pas partage avec toute l’équipe ; les accès administratifs existants restent à traiter selon les droits en vigueur.
- Le nom du dossier est obligatoire, libre et modifiable. Une description est facultative.
- Un dossier peut exister sans document ni conversation.
- Un dossier contient plusieurs conversations ; une conversation appartient au plus à un dossier.
- Une conversation libre peut servir à créer un nouveau dossier, mais ne peut pas être ajoutée à un dossier existant. Pour poursuivre un dossier existant, l’utilisateur démarre sa conversation depuis ce dossier.
- Les informations et documents du dossier sont disponibles pour ses conversations. L’historique de chaque conversation reste distinct.
- Aucun autre dossier n’est utilisé implicitement pour compléter la situation.
- Les informations saisies ou confirmées par l’utilisateur restent distinguées des propositions de l’IA et des déclarations rapportées.
- Une modification du dossier s’applique aux demandes suivantes. Elle ne réécrit pas les réponses déjà produites.

## 4. Sidebar de gauche

La navigation principale présente **Nouvelle question**, **Fiches pratiques**, puis **Organisation**. Cette dernière regroupe Documents, Informations générales et Équipe, avec les droits existants.

**Dossiers** forme une section distincte sous la navigation et avant **Conversations récentes**. Son titre discret porte un chevron accolé : cliquer sur le titre replie ou déplie la liste. Le bouton « + » reste à droite, visible au survol ou au focus sur ordinateur et toujours accessible sur écran tactile. Son emplacement réservé évite tout déplacement. Le focus clavier reste visible et discret.

Afficher au maximum quatre dossiers récemment modifiés, sans conversations imbriquées. Chaque ligne comporte une icône, le nom et le menu d’actions. **Voir tous les dossiers** ouvre la liste complète. L’historique propre au dossier reste accessible depuis sa page.

Dossiers et Conversations récentes partagent la zone défilante. **Administration** est placée en bas, près du compte, et demeure réservée aux administrateurs. Les sections sont distinguées par leurs titres et espacements, sans séparateurs supplémentaires.

## 5. Page de tous les dossiers

En-tête **Dossiers**, texte court « Retrouvez les documents et les échanges de vos sujets RH », bouton principal **Créer un dossier**.

Une recherche par nom et description permet de retrouver un dossier. Deux vues **Actifs** et **Archivés** séparent le travail en cours des dossiers rangés. Une liste sobre affiche, pour chaque dossier, son nom, sa description éventuelle, sa dernière activité, le nombre de conversations et le nombre de documents. Le tri par défaut suit l’activité récente ; les épingles sont signalées.

Cliquer une ligne ouvre l’accueil du dossier. Les actions secondaires sont regroupées dans un menu. Aucun résumé IA n’est généré lors de l’affichage de cette liste.

Un premier accès sans dossier explique l’usage en une phrase et propose **Créer mon premier dossier**. Une recherche sans résultat conserve la saisie et indique qu’aucun dossier ne correspond. Une erreur de chargement possède son propre état et un bouton Réessayer.

## 6. Création et identité du dossier

La création utilise une boîte de dialogue courte, dans le style des formulaires actuels, avec un seul champ à saisir :

| Élément | Comportement |
| --- | --- |
| Nom du dossier | Obligatoire, saisi par l’utilisateur, par exemple « Accord télétravail 2027 » |
| Organisation | Organisation courante affichée comme repère |
| Visibilité | Indication « Dossier personnel » avec explication de sa portée |
| Actions | Créer le dossier et Annuler |

Le champ Nom reçoit le focus à l’ouverture. Le bouton Créer le dossier reste désactivé tant que le nom est vide. Une phrase explique : « Un dossier rassemble les informations, documents et conversations d’un sujet RH. » Organisation et visibilité sont des repères discrets, pas des champs supplémentaires. La description se complète après création dans Informations ou depuis le menu de l’en-tête.

Après création, ouvrir l’accueil du dossier. Ne pas lancer d’analyse, générer une synthèse ou créer une conversation vide. L’utilisateur peut immédiatement poser une question, ajouter un document ou compléter les informations.

Le nom et la description se modifient depuis le menu de l’en-tête. Un dossier ne change pas d’organisation dans cette version. Les noms identiques sont autorisés ; la description et les dates aident à distinguer les dossiers.

## 7. Accueil du dossier

La page reprend l’enveloppe du chat AORIA : surface principale claire, angles arrondis, typographie et espacements existants. Elle contient un en-tête persistant avec le retour à Dossiers, le nom du dossier, sa description éventuelle et un menu d’actions.

Sous l’en-tête, la zone de saisie habituelle invite à **Poser une question dans ce dossier**. Elle reste présente au-dessus des onglets, y compris pendant la consultation des informations ou documents. Un repère discret indique que le contexte du dossier est disponible. Envoyer une question depuis cet accueil crée une nouvelle conversation et ouvre le chat correspondant ; pour poursuivre un échange existant, l’utilisateur l’ouvre dans l’historique. Le brouillon est conservé lors d’un changement d’onglet.

Trois onglets donnent ensuite accès à **Conversations**, **Informations** et **Documents**. L’ouverture depuis la sidebar arrive sur Conversations. Le nom du dossier et la saisie restent dans la même position dans les trois vues. Sur petit écran, la saisie appartient au flux de la page afin de ne pas réduire excessivement la place du contenu.

### Conversations

Sous les onglets, afficher l’historique des conversations du dossier, de la plus récente à la plus ancienne : titre, date du dernier échange et menu d’actions. Une recherche par titre permet de retrouver un échange ; l’intégralité de l’historique reste accessible avec un chargement progressif.

Cliquer un échange le reprend. Le menu permet de le renommer et de le supprimer selon les règles de la section 12. Un dossier vide affiche une invitation courte à décrire sa situation. Aucun titre de conversation vide n’est enregistré avant l’envoi d’un message.

### Informations

Afficher le contexte descriptif puis les rubriques déjà familières : **Informations retenues**, **À vérifier**, **Profil de l’entreprise** et **Anciennes informations**. Le profil d’entreprise reste identifié comme une information issue de l’organisation ; sa modification relève de la rubrique Organisation.

Un bouton **Ajouter une information** permet de saisir un intitulé et un texte libre, sans formulaire métier long. L’utilisateur peut décrire une date, une personne, un événement, une contrainte ou un objectif sans devoir choisir une catégorie.

Chaque information présente son contenu complet, sa provenance disponible et ses actions : modifier, confirmer lorsque pertinent, signaler comme à vérifier, retirer. L’édition utilise **Enregistrer** et **Annuler**. En cas d’échec, la saisie est conservée et l’échec est visible. Quitter une modification non enregistrée permet de la conserver en restant sur place ou de l’abandonner explicitement.

Retirer une information la sort du contexte actif. Elle reste consultable dans Anciennes informations avec sa provenance. Le libellé **Retirer du dossier** indique cette conséquence ; il ne promet pas un effacement définitif. Une information retirée ou corrigée ne doit pas être réintroduite implicitement depuis un ancien échange.

Les consignes facultatives adressées à AORIA disposent d’un champ distinct, par exemple « Préparer des réponses destinées aux managers ». Elles sont modifiables et effaçables. Elles ne sont pas présentées comme des faits sur la situation.

### Documents

Afficher les pièces rattachées au dossier, leur nom, leur format, leur date d’ajout et leur état de disponibilité. **Ajouter un document** propose **Importer un fichier** ou **Choisir dans les documents de l’entreprise**.

Sans pièce, afficher un encart léger : « Ajoutez des documents pour préciser votre situation », avec le bouton **Ajouter un document**. Ce bouton ouvre une fenêtre dédiée avec une zone de glisser-déposer et les deux choix d’ajout. L’import reste également possible par un sélecteur de fichiers au clavier ou au toucher. La fenêtre indique le dossier destinataire et la portée des pièces ajoutées. Après ajout, revenir à la liste avec les états de préparation visibles. Les connecteurs externes montrés dans ChatGPT ne font pas partie de cette version ; une note textuelle libre se saisit dans Informations.

L’utilisateur peut ouvrir ou télécharger une pièce selon les capacités et droits existants, modifier son intitulé dans le dossier, ajouter une description facultative et la retirer du dossier. Modifier l’intitulé local ne renomme pas silencieusement le document partagé de l’entreprise. Modifier le texte d’un fichier n’est pas une fonction de cette première version.

Une nouvelle version s’ajoute explicitement : l’utilisateur précise si elle remplace la version active ou constitue une pièce distincte. Les versions historiques citées restent identifiables dans les anciens échanges, sous réserve des droits et de leur disponibilité.

Un fichier en préparation, illisible ou en erreur n’est pas présenté comme lu. Une erreur sur une pièce n’empêche pas de consulter les autres éléments. Les formats, tailles et limites autorisés sont affichés avant l’import ; les valeurs commerciales restent à définir séparément.

## 8. Conversations dans un dossier

Le chat conserve les messages, la zone de saisie, les pièces jointes, les sources et les interactions actuelles. Son en-tête indique **Nom du dossier / Titre de la conversation**. Le nom du dossier permet de revenir à son accueil ; **Nouvelle conversation** démarre un nouvel échange dans ce même dossier.

Le bouton actuel Dossier devient **Voir le dossier** et ouvre le panneau à droite. Ce panneau donne accès aux mêmes informations et documents que les onglets de l’accueil, avec les mêmes actions essentielles d’ajout, de modification et de retrait. Il ne constitue pas un second dossier propre à la conversation.

Le panneau n’est pas ouvert en permanence. Sa fermeture rend sa largeur au chat et conserve le message en cours de saisie. Le retour depuis l’accueil du dossier vers une conversation ne doit pas faire perdre un brouillon en cours.

Une nouvelle conversation dispose du contexte actif et des documents du dossier. Les messages des autres conversations restent accessibles par l’historique, mais ne deviennent pas indistinctement des faits confirmés. L’utilisateur peut ajouter explicitement une information au contexte commun depuis un échange, avec un aperçu modifiable et sa provenance.

L’enrichissement issu des échanges conserve la distinction existante entre informations retenues, propositions ou hypothèses à confirmer et déclarations rapportées. Une correction manuelle ne doit pas être remplacée silencieusement par une proposition ultérieure. Des informations divergentes restent identifiables avec leurs sources, sans arbitrage automatique présenté comme certain.

L’utilisateur peut demander de travailler sur une ou plusieurs pièces déterminées. Les documents disponibles dans le dossier et les documents effectivement consultés pour une réponse sont distingués. L’ajout d’un fichier ne vaut pas promesse de lecture complète de tout le dossier à chaque question.

Les réponses générées demeurent intégralement consultables. Aucun contrôle éditorial automatique ne les masque, ne les réécrit ou ne les remplace. Une analyse ou une synthèse est produite à la demande, reste identifiée comme génération et ne remplace pas les informations originales du dossier.

## 9. Documents du dossier et documents de l’entreprise

La rubrique **Documents** existante continue de représenter les ressources de l’organisation. L’onglet Documents d’un dossier réunit les pièces utilisées pour ce sujet particulier.

Rattacher un document d’entreprise crée un accès depuis le dossier sans dupliquer le fichier ni modifier ses droits. Le retirer du dossier ne le supprime pas de la bibliothèque de l’entreprise et ne l’affecte pas dans les autres dossiers. Il peut rester une source d’entreprise accessible selon les règles existantes : retrait du dossier et suppression générale sont distincts.

**Règle retenue : un fichier importé directement dans un dossier reste réservé à ce dossier dans les parcours ordinaires.** Il n’apparaît pas dans les Documents de l’entreprise et n’est pas réutilisé pour un autre dossier. C’est une évolution fonctionnelle par rapport à l’import actuel depuis le chat, qui enregistre un document dans l’organisation. Cette différence doit être traitée avant de présenter le dossier comme personnel.

Dans le chat d’un dossier, un import propose une portée explicite : **Ajouter au dossier** par défaut, ou **Joindre uniquement à cette conversation**. Le rattachement d’une pièce déjà partagée ne réduit pas sa visibilité d’origine. Un repère distingue les pièces du dossier, celles de l’entreprise et les pièces limitées à la conversation.

Retirer une pièce privée du dossier la rend indisponible pour les prochaines demandes du dossier. Les anciens échanges ne sont pas réécrits et leurs références restent expliquées ; un retrait ne doit pas laisser un lien actif donnant accès à un fichier qui n’est plus autorisé. La suppression définitive et la conservation historique doivent être définies distinctement dans la politique de données.

## 10. Passage des conversations existantes aux dossiers

Les anciennes conversations restent consultables à leur emplacement actuel. Ne pas créer automatiquement un dossier nommé pour chacune d’elles.

Dans une conversation libre, l’actuel panneau est intitulé **Contexte de la conversation** afin de le distinguer des dossiers nommés. Ses informations, ses corrections et ses références restent disponibles.

Une action **Créer un dossier à partir de cet échange** permet uniquement de créer un nouveau dossier, avec un nom obligatoire. Un aperçu présente les informations et documents à reprendre ; l’utilisateur choisit ceux à conserver dans le contexte commun. Après validation, la conversation actuelle devient la première conversation du nouveau dossier, sans duplication. Les messages restent intacts, et les informations non retenues restent dans le contexte de la conversation d’origine.

**Décision : aucune action Ajouter à un dossier existant.** Un échange commencé hors dossier n’a pas disposé du contexte de ce dossier lors de ses premières réponses. L’y ajouter après coup pourrait faire croire que ces réponses en tenaient compte et compliquerait le parcours. Pour travailler sur un dossier existant, l’utilisateur l’ouvre puis y commence une nouvelle conversation, avec son contexte disponible dès la première question. Créer un dossier depuis un échange ne réévalue ni ne réécrit les réponses antérieures.

Ce rattachement ne constitue pas un partage à l’équipe. Une éventuelle différence de visibilité des documents est indiquée avant de confirmer. Une pièce d’entreprise reste une pièce d’entreprise, même si la conversation rejoint un dossier personnel.

Le transfert d’une conversation vers un autre dossier et son détachement ne sont pas proposés. Chaque échange conserve ainsi le lien avec le contexte dans lequel il a été commencé, ou avec le nouveau dossier créé à partir de cet échange.

## 11. Suppression du projet

Décision du 7 octobre 2026 : proposer uniquement **Supprimer**, sans action Archiver ni filtres Actifs/Archivés.

Une confirmation nomme le projet et annonce la suppression définitive de ses informations, de toutes ses conversations (y compris masquées) et de leurs pièces privées. Les documents d’entreprise simplement associés restent conservés. Annuler ne modifie rien. Une erreur laisse la confirmation ouverte avec son motif.

Les anciens projets archivés restent consultables et supprimables. Aucune restauration après suppression n’est proposée. Les fichiers et extractions font l’objet d’un effacement suivi par le journal technique de stockage, qui permet de reprendre un échec de nettoyage.

## 12. Historique et suppression des conversations

L’historique du dossier contient toutes ses conversations non supprimées, avec leurs messages et leurs sources disponibles. Il reste accessible même si un utilisateur a masqué ses raccourcis dans l’historique global.

L’action globale actuelle d’effacement de l’historique correspond à un masquage. Son libellé doit expliciter cette portée, par exemple **Masquer les conversations récentes**. Elle ne supprime aucun dossier et ne vide pas les historiques internes aux dossiers.

Supprimer individuellement une conversation d’un dossier exige une confirmation. Cela ne supprime ni le dossier ni les autres conversations. Les informations et pièces déjà ajoutées explicitement au dossier restent dans le dossier ; la confirmation l’annonce. Une référence à un message devenu indisponible le signale sans proposer un lien cassé. La suppression respecte la politique de conservation du produit et ne doit pas être décrite comme un effacement définitif si elle ne l’est pas.

## 13. Cohérence visuelle et mobile

Réutiliser la police Inter, le violet principal AORIA, les fonds neutres, les surfaces blanches ou leurs équivalents sombres, les bordures discrètes, les angles arrondis et les icônes de la famille actuelle. Conserver les styles de boutons, menus, formulaires et panneaux existants.

L’accueil du dossier privilégie une colonne de lecture et trois onglets sobres. Le chat reste la surface principale pendant un échange. Ne pas ajouter de tableau de bord chiffré, de grandes cartes décoratives, de couleurs par dossier ou de troisième colonne permanente dans cette version.

Sur mobile, conserver la navigation dans le volet gauche. Les raccourcis Dossiers sont repliables. Le panneau du dossier utilise la largeur disponible et revient au chat sans perdre la saisie. Les actions sont utilisables au toucher et au clavier, sans dépendre du survol. Les titres longs, le thème sombre et les états de focus sont pris en compte.

Une sauvegarde réussie, une opération en cours et une erreur sont distinguées. L’application ne donne pas l’impression d’avoir enregistré un changement qui a échoué. Un changement d’organisation remplace les dossiers et historiques affichés par ceux de l’organisation sélectionnée.

## 14. Parcours de référence

| Situation | Résultat attendu |
| --- | --- |
| Créer « Accord télétravail 2027 » | Le dossier apparaît dans la sidebar ; son accueil est ouvert, sans conversation vide |
| Ajouter une description et une date de négociation | Les informations sont enregistrées et consultables depuis l’accueil et le panneau du chat |
| Ajouter l’accord actuel | La pièce apparaît avec son état de préparation, puis devient consultable |
| Poser une première question | Une conversation est créée dans ce dossier |
| Ouvrir une nouvelle conversation pour préparer un courrier | Le même contexte de dossier est disponible ; l’échange précédent reste distinct |
| Revenir deux semaines plus tard | Les conversations, informations et documents sont retrouvés dans le dossier |
| Corriger une date pendant le chat | La prochaine demande utilise la situation actualisée ; la réponse précédente reste inchangée |
| Retirer une pièce privée | Elle ne sert plus aux nouvelles demandes ; les références historiques restent compréhensibles |
| Poser une question depuis Nouvelle question | Un échange libre démarre, sans rattachement implicite au dernier dossier |
| Créer un dossier depuis une conversation libre | L’utilisateur nomme un nouveau dossier et choisit les éléments à reprendre ; la conversation y est conservée sans duplication |
| Poursuivre un dossier existant | L’utilisateur ouvre le dossier et y démarre une conversation ; aucun ajout d’une conversation libre à ce dossier n’est proposé |
| Masquer les conversations récentes | Les dossiers et leurs historiques internes restent accessibles |
| Archiver puis réactiver | Le dossier est retrouvé dans Archivés puis redevient utilisable sans perte |
| Changer d’organisation | Aucun dossier ni document de l’organisation précédente ne reste utilisable dans le nouveau contexte |
| Échec d’import ou de sauvegarde | L’erreur est visible, les saisies récupérables et aucune réussite fictive n’est affichée |

## 15. Périmètre proposé et arbitrages

Le socle comprend la navigation, la liste des dossiers, la création avec nom, les trois onglets, l’édition manuelle des informations, l’ajout et le retrait des pièces, les conversations multiples, leur historique, le panneau dans le chat, la création d’un nouveau dossier depuis une conversation libre, les épingles et l’archivage. La confidentialité des pièces importées fait partie du socle. L’ajout d’une conversation à un dossier existant est exclu.

Le partage entre collègues, les rôles propres à chaque dossier, les sous-dossiers, les tâches, les rappels, les échéanciers, les modèles spécialisés de dossiers, les synthèses automatiques et les recherches sur plusieurs dossiers sont hors de cette première version. Une date peut néanmoins être enregistrée comme simple information et une synthèse demandée dans le chat.

Les décisions confirmées comprennent la mutualisation du chat, la confidentialité des fichiers importés dans un dossier, le maintien des droits des documents d’entreprise référencés et la création d’un nouveau dossier depuis un échange libre sans possibilité de l’ajouter à un dossier existant. Les paramètres proposés pour cette version restent : dossiers personnels pour le lancement ; cinq raccourcis dans la sidebar ; trois onglets avec ouverture sur Conversations ; maintien des échanges de dossiers dans l’historique récent transversal. La politique de suppression et de restauration ainsi que les quotas doivent être arrêtés avant livraison des actions concernées. Aucune offre commerciale nouvelle n’est présumée par ce document.

## 16. Repères examinés dans le projet

- Navigation : `frontend/src/components/sidebar.tsx`.
- Enveloppe desktop et mobile : `frontend/src/app/(dashboard)/layout.tsx`.
- Chat et accueil : `frontend/src/components/chat/conversation.tsx` et `welcome-screen.tsx`.
- Panneau actuel : `frontend/src/components/chat/case-file-panel.tsx`.
- Bibliothèque accessible depuis le chat : `frontend/src/components/chat/document-library.tsx`.
- Documents d’organisation : `frontend/src/app/(dashboard)/documents/page.tsx`.
- Identité visuelle : `frontend/src/app/globals.css`.
- Portée actuelle des dossiers et imports : `backend/app/models/case_file.py` et `backend/app/api/conversations.py`.

Ces repères servent à préserver la continuité du produit. Les sections suivantes fixent les exigences d’architecture ; le schéma détaillé des données et les contrats d’API seront établis lors de la conception technique.

Les cinq captures ChatGPT fournies le 7 octobre 2026 précisent le parcours visuel de référence : actions de section dans la sidebar, création par nom, accueil avec saisie au-dessus des onglets, état vide des sources et fenêtre d’ajout. L’apparition du « + » au survol est précisée par l’utilisateur. L’onglet Informations, les limites de raccourcis et l’adaptation aux composants AORIA sont des choix de cette proposition, pas des comportements déduits des captures.

## 17. Prérequis de conception technique

Avant l’implémentation, produire trois éléments courts dans la documentation du projet :

1. Un schéma des relations entre organisation, utilisateur, dossier, conversation, information, document, version et rattachement.
2. Une matrice des droits couvrant les actions de lecture, modification, recherche, téléchargement, archivage et suppression, y compris les accès administratifs.
3. Un plan de migration et de retour arrière accompagné des scénarios de vérification.

L’analyse préalable doit inventorier les points d’entrée documentaires : bibliothèque d’entreprise, pièces jointes, extraction, indexation, recherche, consultation des sources, téléchargement, traitements différés, caches, exports et traces administratives. Vérifier chaque sélection fondée uniquement sur l’organisation : elle ne suffit plus à autoriser l’accès aux pièces privées d’un dossier.

Les règles fonctionnelles de la section 3 sont des invariants imposés côté serveur et testables indépendamment de l’interface. L’interface ne constitue pas une barrière d’autorisation.

## 18. Mutualisation du chat et séparation des responsabilités

### Un seul fonctionnement de conversation

Réutiliser et faire évoluer les composants existants pour les messages, la saisie, les pièces jointes, les sources, le streaming, les erreurs et les actions sur les réponses. L’accueil du dossier utilise également la saisie commune. Il n’y a pas de second moteur conversationnel ni de chaîne documentaire spécifique copiée pour les dossiers.

Le contexte de travail constitue une entrée explicite du fonctionnement commun :

| Parcours | Contexte disponible |
| --- | --- |
| Chat libre | Contexte de la conversation, ses pièces et les ressources d’entreprise ou juridiques autorisées |
| Chat dans un dossier | Même socle, complété par les informations actives et les documents autorisés de ce dossier |

L’identité du dossier éventuel est contrôlée par le serveur à partir de la conversation. Une valeur fournie par l’interface ne suffit jamais à élargir le contexte autorisé.

### Des composants et services communs

L’onglet Informations et le panneau latéral utilisent les mêmes composants d’édition et les mêmes opérations métier. Il en va de même pour les listes et actions documentaires communes. Les dispositions peuvent varier entre page et panneau, mais les règles, validations techniques et mises à jour ne sont pas dupliquées.

Isoler les responsabilités de gestion des dossiers, d’autorisation, de gestion documentaire et de constitution du contexte dans des modules cohérents de l’application existante. Les vues orchestrent les interactions ; elles ne réimplémentent pas les règles métier. Des adaptations explicites selon le contexte sont préférables à des conditions dispersées dans tous les composants.

La fonctionnalité ne nécessite pas l’introduction de microservices. Les nouvelles vues propres aux dossiers sont la liste, l’accueil et la navigation associée ; elles s’appuient sur les capacités communes. Les tests doivent vérifier les deux parcours après toute modification d’un composant partagé.

## 19. Modèle métier et intégrité des données

Le dossier est une entité autonome portant son nom, son organisation, son propriétaire, son état et son contexte partagé. Son existence ne dépend pas d’une conversation particulière. Supprimer une conversation ne doit pas provoquer la suppression du dossier ou de ses autres conversations.

Le contexte local d’une conversation reste distinct du contexte commun. Une information conservée dans un échange n’est pas automatiquement un fait confirmé pour les autres. Les informations actives, anciennes, retirées et proposées conservent leur statut et leur provenance.

Séparer le fichier, ses versions, son périmètre d’accès et ses rattachements. Une référence à un document d’entreprise n’est pas une copie privée. Un intitulé local n’écrase pas les métadonnées partagées. Une déduplication de contenus identiques ne fusionne jamais leurs droits d’accès.

Les contraintes de base et les transactions doivent empêcher les rattachements entre organisations incompatibles, les conversations dans plusieurs dossiers et les états partiellement enregistrés. Les règles métier complètent les contraintes de base pour empêcher l’ajout d’une conversation libre à un dossier existant. Inventorier et adapter les suppressions en cascade existantes avant toute modification des relations.

## 20. Autorisations et isolation documentaire

Une politique d’autorisation commune détermine les ressources accessibles selon l’utilisateur, son appartenance actuelle à l’organisation, l’action et le périmètre du dossier ou de la conversation. Refuser par défaut les accès non explicitement autorisés et vérifier les permissions à chaque accès, conformément aux [principes OWASP d’autorisation](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

Cette politique s’applique aux métadonnées comme au contenu : listes, fichiers originaux, extractions, passages indexés, citations, téléchargements, exports et traces. Connaître un identifiant ou une ancienne URL ne donne aucun droit. Un lien de rattachement ne peut pas élargir les droits du document source.

L’indexation d’une pièce privée ne doit pas la rendre disponible dans la recherche générale de l’entreprise. Le serveur détermine le périmètre autorisé avant la recherche et avant l’envoi au modèle ; les lectures de documents revérifient les droits. Les tâches différées revérifient que la ressource est toujours disponible et que leur opération reste autorisée.

Le modèle peut demander à consulter une ressource ; l’exécuteur contrôle cette demande. Le contenu d’un fichier, d’un message ou d’une génération ne peut pas modifier les autorisations ni déclencher à lui seul une action non autorisée.

Les caches doivent distinguer les périmètres d’accès et les versions utiles. Un retrait, une révocation de droit ou un changement de version ne doit pas permettre de réutiliser un contenu devenu inaccessible. Le changement d’organisation dans l’interface annule ou ignore les réponses tardives de l’ancien contexte et écarte ses données affichées.

Les accès administratifs sont explicitement décrits dans la matrice des droits. Les journaux de fonctionnement évitent de recopier des contenus RH sensibles ; les traces contenant du contenu sont protégées et soumises à une politique de conservation définie.

## 21. Versionnement et traitements fiables

### Contexte et modifications concurrentes

Chaque demande utilise un état identifié du contexte actif. Conserver les références nécessaires pour retrouver la version du dossier et les versions documentaires utilisées, sans dupliquer inutilement les contenus sensibles. Une réponse en cours ne mélange pas silencieusement des corrections successives du dossier. Une révocation d’accès reste prioritaire sur cet état identifié : elle ne peut pas être contournée pour terminer une lecture.

Détecter les conflits lorsque deux onglets modifient la même information. Ne pas écraser une modification concurrente ; conserver la saisie et permettre de recharger l’état actuel. Une correction manuelle ne peut pas être écrasée silencieusement par un enrichissement issu du modèle.

### Création et import

La création d’un dossier à partir d’un échange est atomique pour ses données métier : création, rattachement de la conversation et reprise des éléments sélectionnés réussissent ensemble ou ne sont pas validés. Les doubles clics et répétitions d’une même requête après interruption ne créent pas plusieurs dossiers ou conversations.

Les imports et leur préparation ont des états explicites. Les traitements différés peuvent reprendre sans dupliquer les fichiers ou les résultats techniques et sans réactiver une pièce retirée. Prévoir la gestion des fichiers reçus dont l’enregistrement échoue et des tâches dont le dossier destinataire a été archivé ou supprimé.

Toute relance technique est explicite, bornée et limitée aux erreurs techniques. Une sortie vide, une erreur de transport ou un délai expiré est signalé. Une sortie structurée inexécutable produit une erreur séparée ; sa génération brute reste consultable selon les droits. Aucune réparation éditoriale, réécriture automatique ou boucle de génération destinée à satisfaire un validateur n’est introduite.

### Coûts et réactivité

La navigation, la création et les listes n’entraînent pas de génération LLM. Charger progressivement les historiques et les listes ; ne pas charger tous les messages ni lire toutes les pièces pour afficher la sidebar. Réutiliser les extractions disponibles lorsque leur version et leurs droits le permettent.

Le contexte envoyé au modèle respecte un budget explicite. La disponibilité de tous les documents d’un dossier n’implique pas leur lecture intégrale à chaque question. Les limites de lecture restent visibles ; aucune génération non vide n’est tronquée ou réécrite pour respecter un objectif de coût.

## 22. Migration et mise en production

Faire évoluer le schéma progressivement et préserver les identifiants, historiques, corrections et références des conversations existantes. Ne pas créer de dossiers nommés en masse et ne pas modifier implicitement la visibilité des documents historiques.

Vérifier la migration sur des données représentatives, de préférence synthétiques ou anonymisées : conversations libres, dossiers conversationnels actuels, pièces d’entreprise, références manquantes et contenus déjà masqués. Contrôler les relations, les volumes et les droits avant et après migration.

Prévoir une sauvegarde et un retour arrière qui prennent en compte les dossiers et pièces créés après la livraison. Revenir à une ancienne version du code ne doit pas exposer les nouveaux fichiers privés via une recherche limitée à l’organisation. Une compatibilité sûre ou une procédure de retour dédiée est requise avant livraison.

Suivre les erreurs techniques, les délais et les coûts avec des identifiants de suivi, sans journaliser systématiquement le contenu des pièces. Les modalités de suppression, de conservation et de restauration doivent être arrêtées avant l’activation des actions concernées.

Toute livraison suit exclusivement `docs/exploitation/DEPLOIEMENT_PRODUCTION.md` et le fichier local `ACCES_PROD.md`, lus intégralement avant intervention. Ne reconstruire que les services concernés, employer `--no-deps` pour un déploiement isolé et effectuer les contrôles post-déploiement prévus avant de déclarer la livraison terminée.

## 23. Vérifications requises avant livraison

Les tests portent sur les contrats techniques, les droits, les données et les parcours. Ils ne jugent pas la qualité éditoriale des générations et ne conditionnent pas leur affichage. Les tests de constitution du contexte et d’autorisation utilisent des entrées contrôlées et peuvent vérifier les ressources transmises sans appel LLM réel.

| Domaine | Vérification attendue |
| --- | --- |
| Isolation | Refus entre organisations, entre utilisateurs d’une même organisation et entre dossiers d’un même utilisateur hors ressources d’entreprise communes autorisées |
| Accès direct | Refus d’accès avec un identifiant connu, une référence forgée ou une ancienne URL après révocation |
| Bibliothèque et recherche | Une pièce privée ne figure ni dans Documents de l’entreprise ni dans le contexte d’une recherche hors de son dossier |
| Documents partagés | Rattachement sans élargissement des droits ; retrait sans suppression du document d’entreprise |
| Contexte | Nouvelle conversation dans un dossier avec son contexte actif ; chat libre sans héritage implicite du dernier dossier |
| Création depuis le chat | Nouveau dossier uniquement, conservation des messages et absence de duplication après double soumission |
| Restrictions métier | Ajout à un dossier existant et transfert entre dossiers refusés côté serveur, même sans passer par l’interface |
| Concurrence | Conflit détecté entre deux corrections ; génération utilisant un état identifié ; correction humaine préservée |
| Traitement différé | Import interrompu et reprise maîtrisés ; retrait ou révocation pendant une tâche respectés |
| Cache | Retrait et révocation effectifs malgré un résultat précédemment mis en cache |
| Historique | Masquage global sans perte de l’historique du dossier ; archivage et réactivation sans perte |
| Migration | Anciennes conversations, pièces et sources accessibles selon leurs droits initiaux, sans dossiers nommés créés automatiquement |
| Mutualisation | Parcours libre et dossier vérifiés sur les mêmes composants, opérations documentaires et chaîne de réponse |
| Interface | Brouillons conservés, sauvegardes échouées visibles, clavier, mobile, thème sombre et réponses tardives après changement d’organisation |
| Transparence LLM | Génération non vide rendue intégralement et sans transformation ; erreurs techniques séparées ; aucune relance éditoriale |

Exécuter les vérifications statiques et les suites de tests pertinentes du projet. Documenter les résultats et toute limite non résolue. Ne pas considérer la fonctionnalité livrable tant qu’un accès non autorisé, une exposition documentaire ou une perte de données identifiée reste possible dans les parcours couverts.

### Ajustement visuel après recette

Les écrans Projets reprennent les surfaces blanches, le fond gris, le violet primaire, les en-têtes et les espacements des écrans existants. Les onglets utilisent des fonds neutres et le violet AORIA pour la sélection, sans aplat rose secondaire. Les URL `/dossiers` et le modèle technique sont conservés.

Après comparaison avec les captures du chat, l’accueil d’un projet reprend sa composition
centrée dans une surface blanche, son titre, son champ de saisie et sa largeur de lecture.
La structure visuelle est mutualisée dans ChatWelcomeLayout avec l’accueil du chat libre.
Les onglets et contenus du projet restent dans cette même colonne ; la recherche de
conversations n’est pas affichée lorsqu’aucune conversation n’existe.
Dans un projet, la colonne est ancrée en haut avec un espacement constant : le titre,
la saisie et les onglets ne se déplacent pas lorsque le contenu de l’onglet change
de hauteur. Les contenus longs restent accessibles par défilement.


Vocabulaire retenu après recette : **Dossiers** dans toute l’interface (création, navigation, documents, conversations et suppression). Les anciens libellés « Projets » sont remplacés. Les chevrons des rubriques Dossiers et Entreprise sont alignés à droite ; le bouton + apparaît avant le chevron au survol ou au focus, sans déplacement.


Navigation simplifiée après recette : la sidebar affiche uniquement les quatre dossiers les plus récemment modifiés, sans sous-liste de conversations. Les conversations restent dans leur dossier et dans l’historique habituel. Le groupe « Organisation » rassemble Documents, Informations générales et Équipe.
