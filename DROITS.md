# AORIA RH — Matrice des droits par rôle

## Rôles

| Rôle | Description |
|---|---|
| **Admin** | Personnel interne AORIA RH. Accès au back-office, gestion des documents communs, monitoring. |
| **Manager** | Souscripteur. Crée des organisations, invite des collaborateurs, gère les documents et les droits. |
| **User** | Membre invité. Accède au chat, uploade des documents dans son organisation. |

---

## Authentification

| Action | Admin | Manager | User | Non connecté |
|---|---|---|---|---|
| Inscription | — | oui | oui | oui |
| Connexion | oui | oui | oui | — |
| Rafraîchir le token | oui | oui | oui | — |

---

## Compte utilisateur

| Action | Admin | Manager | User |
|---|---|---|---|
| Voir son profil | oui | oui | oui |
| Modifier son nom / email | oui | oui | oui |
| Changer son mot de passe | oui | oui | oui |

---

## Organisations

| Action | Admin | Manager | User |
|---|---|---|---|
| Créer une organisation | oui | oui | non |
| Lister ses organisations | oui | oui | oui |
| Voir une organisation | oui | oui (membre) | oui (membre) |
| Modifier une organisation | oui | oui (manager de l'org) | non |

---

## Membres d'organisation

| Action | Admin | Manager de l'org | User de l'org | Non-membre |
|---|---|---|---|---|
| Voir les membres | oui | oui | oui | non |
| Inviter un membre | oui | oui | non | non |
| Changer le rôle d'un membre | oui | oui | non | non |
| Retirer un membre | oui | oui | non | non |

> Le dernier manager d'une organisation ne peut pas être retiré.

---

## Documents d'organisation

| Action | Admin | Manager de l'org | User de l'org | Non-membre |
|---|---|---|---|---|
| Lister les documents | oui | oui | oui | non |
| Uploader un document | oui | oui | oui | non |
| Voir un document | oui | oui | oui | non |
| Télécharger un document | oui | oui | oui | non |
| Supprimer un document | oui | oui | non | non |
| Réindexer un document | oui | oui | non | non |

---

## Documents communs (lecture)

| Action | Admin | Manager | User |
|---|---|---|---|
| Lister les documents communs | oui | oui | oui |

> Les documents communs sont accessibles en lecture par tous les utilisateurs connectés. Ils sont partagés avec toutes les organisations.

---

## Administration (back-office)

| Action | Admin | Manager | User |
|---|---|---|---|
| Voir tous les documents (communs + orgs) | oui | non | non |
| Voir les stats de stockage | oui | non | non |
| Uploader un document commun | oui | non | non |
| Supprimer un document commun | oui | non | non |
| Télécharger un document commun | oui | non | non |
| Réindexer un document commun | oui | non | non |
| Voir les collections Qdrant | oui | non | non |
| Explorer les points Qdrant | oui | non | non |

---

## Chat RAG

| Action | Admin | Manager | User |
|---|---|---|---|
| Créer une conversation | oui | oui | oui |
| Lister ses conversations | oui | oui | oui |
| Voir une conversation | oui | oui | oui |
| Envoyer un message (chat) | oui | oui | oui |

> Le chat RAG est en cours de développement (endpoints TODO).

---

## Résumé par rôle

### Admin
- Tout ce qu'un manager peut faire
- Gestion des documents communs (upload, suppression, réindexation)
- Vue globale de tous les documents (toutes organisations)
- Stats de stockage et monitoring
- Accès à l'index Qdrant

### Manager
- Tout ce qu'un user peut faire
- Crée des organisations
- Invite et gère les membres (rôles, suppression)
- Supprime et réindexe les documents de son organisation

### User
- Accède au chat RAG
- Uploade et consulte les documents de son organisation
- Voit les documents communs
- Gère son propre compte
