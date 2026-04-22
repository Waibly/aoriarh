# Politique de confidentialité — AORIA RH

**Dernière mise à jour : {{DATE_DERNIERE_MAJ}}**
**Version : 1.0**

---

## 1. Préambule

La présente politique décrit la manière dont **{{RAISON_SOCIALE}}** (ci-après « AORIA RH » ou « nous ») collecte, utilise, conserve et protège les données à caractère personnel des utilisateurs de son Service, conformément au Règlement (UE) 2016/679 (**RGPD**) et à la loi n° 78-17 du 6 janvier 1978 modifiée (**Loi Informatique et Libertés**).

Elle complète les [Conditions Générales de Vente](/docs/CGV.md) et en fait partie intégrante.

---

## 2. Responsable de traitement

- **Responsable du traitement** : {{RAISON_SOCIALE}}, {{FORME_JURIDIQUE}}
- **Siège** : {{ADRESSE_SIEGE}}
- **SIRET** : {{SIRET}}
- **Contact protection des données** : **privacy@aoriarh.fr**
- **DPO / Référent RGPD** : {{NOM_DPO_OU_REFERENT}} — {{EMAIL_DPO}} *(laisser vide si pas de DPO désigné, la loi ne l'impose pas systématiquement)*

### 2.1. Rôles respectifs AORIA RH / Client

- Pour les données des **Utilisateurs** du Service (comptes, authentification, usage) : AORIA RH est **responsable du traitement**.
- Pour les **données personnelles contenues dans les documents importés par le Client** (par exemple données de salariés figurant dans un contrat de travail), AORIA RH agit en qualité de **sous-traitant** au sens de l'art. 28 RGPD, pour le compte du Client qui en est le responsable de traitement. Un **accord de sous-traitance (DPA)** est disponible sur demande à privacy@aoriarh.fr.

---

## 3. Données collectées

### 3.1. Données fournies directement

| Catégorie | Données | Origine |
|---|---|---|
| Identification compte | Nom, prénom, email professionnel, mot de passe (haché) | Formulaire d'inscription |
| Organisation | Raison sociale, secteur, taille, IDCC (convention collective), SIRET (optionnel) | Déclaratif Client |
| Facturation | Raison sociale, adresse, coordonnées CB (traitées par Stripe) | Souscription |
| Documents importés | Tout contenu RH importé par le Client (contrats, accords, PV, notes, fiches de paie, etc.) pouvant inclure des données personnelles de tiers | Import Client |
| Questions et historique | Questions posées, conversations, feedbacks éventuels | Utilisation du Service |

### 3.2. Données collectées automatiquement

| Catégorie | Données | Finalité |
|---|---|---|
| Techniques | Adresse IP, user-agent, logs d'accès | Sécurité, prévention des abus |
| Authentification | Tokens de session (JWT 30 min, refresh 3 j, cookie NextAuth 7 j) | Maintien de la session |
| Préférences | Thème (clair/sombre), stocké en `localStorage` | Confort d'utilisation |

### 3.3. Données non collectées

AORIA RH ne met en œuvre **aucun outil d'analytics tiers** (Google Analytics, Meta Pixel, etc.) ni de cookie de traçage publicitaire. Seul le stockage local nécessaire au fonctionnement (thème, session) est utilisé.

---

## 4. Finalités et bases légales

| Finalité | Base légale (RGPD art. 6) |
|---|---|
| Exécution du Service (création de compte, génération de réponses, indexation documents) | **Exécution d'un contrat** (art. 6.1.b) |
| Facturation et recouvrement | **Obligation légale** (art. 6.1.c) et **exécution contractuelle** (art. 6.1.b) |
| Support utilisateur | **Exécution contractuelle** (art. 6.1.b) |
| Sécurité du Service, prévention des abus, logs techniques | **Intérêt légitime** (art. 6.1.f) |
| Emails transactionnels (confirmation, renouvellement, alerte) | **Exécution contractuelle** (art. 6.1.b) |
| Communications marketing (newsletter, offres) | **Consentement** (art. 6.1.a), opt-in explicite, retrait à tout moment |
| Amélioration du Service (statistiques agrégées, sans PII) | **Intérêt légitime** (art. 6.1.f) |

---

## 5. Destinataires et sous-traitants

Les données sont accessibles uniquement aux personnes habilitées d'AORIA RH (équipe technique, support) et aux sous-traitants strictement nécessaires à l'exécution du Service.

### 5.1. Sous-traitants techniques

| Sous-traitant | Rôle | Données concernées | Localisation | Garanties |
|---|---|---|---|---|
| **OVHcloud** (France) | Hébergement (VPS, base de données, stockage) | Ensemble des données du Service | France (Roubaix) | ISO/IEC 27001, 27017, 27018, HDS pour l'hébergeur. Contrat de sous-traitance conforme RGPD. |
| **OpenAI, L.L.C.** (États-Unis) | Modèle de langage (LLM) `gpt-5-mini` pour la génération de réponses | Contexte documentaire extrait + question posée (peut contenir des données personnelles présentes dans les documents Client) | États-Unis | **Zero Data Retention activé** : les prompts ne sont ni stockés, ni utilisés pour l'entraînement des modèles. Clauses contractuelles types (CCT) de la Commission européenne. OpenAI figure au Data Privacy Framework UE-USA. |
| **Voyage AI, Inc.** (États-Unis) | Génération d'embeddings vectoriels pour la recherche sémantique (`voyage-law-2`) | Extraits de documents indexés | États-Unis | Clauses contractuelles types (CCT). Politique de non-rétention pour entraînement. |
| **Stripe Payments Europe, Ltd.** (Irlande) | Traitement des paiements par carte bancaire | Coordonnées CB, email, montant | Irlande (UE) + sous-traitants Stripe hors UE (CCT) | Certification PCI-DSS niveau 1. Addendum RGPD Stripe. |
| **Sendinblue SAS (Brevo)** (France) | Envoi des emails transactionnels | Email, nom, contenu de l'email | France | Addendum RGPD Brevo. |
| **Google LLC** (États-Unis) | Authentification optionnelle via Google OAuth (si Utilisateur choisit ce mode) | Email Google, identifiant `sub`, nom | États-Unis | CCT. Data Privacy Framework UE-USA. Utilisation uniquement si Utilisateur active ce mode de connexion. |

### 5.2. Transferts hors Union européenne

Certains sous-traitants (OpenAI, Voyage AI, Google) sont établis aux **États-Unis**. Ces transferts sont encadrés par :

- les **Clauses contractuelles types** (CCT) adoptées par la Commission européenne (décision 2021/914) ;
- le cas échéant, la participation de ces sous-traitants au **Data Privacy Framework** UE-USA ;
- des mesures de minimisation (notamment : *Zero Data Retention* avec OpenAI, qui garantit l'absence de stockage et d'entraînement sur les prompts).

Le Client est informé et accepte ces transferts dès lors qu'il utilise le Service. En cas d'opposition à un transfert hors UE, le Service ne peut techniquement pas être fourni.

---

## 6. Durées de conservation

| Donnée | Durée |
|---|---|
| Compte et données associées (utilisateurs, organisations, documents, conversations) | Durée de l'Abonnement + **30 jours** après résiliation |
| Compte suspendu pour impayé | **60 jours** à compter de la suspension, puis suppression |
| Données d'essai gratuit non converti | **30 jours** après la fin de l'essai |
| Factures et pièces comptables | **10 ans** (obligation légale, art. L.123-22 Code de commerce) |
| Logs techniques d'accès et de sécurité | **12 mois** maximum (recommandation CNIL) |
| Métriques de supervision (Prometheus) | **30 jours** |
| Emails de prospection (si consentement) | Jusqu'au retrait du consentement ou 3 ans d'inactivité |

À l'issue de ces durées, les données sont **supprimées** ou **anonymisées** de manière irréversible.

---

## 7. Droits des personnes concernées

Conformément aux articles 15 à 22 du RGPD, vous disposez des droits suivants sur vos données :

- **Droit d'accès** : obtenir confirmation et copie des données vous concernant.
- **Droit de rectification** : corriger des données inexactes ou incomplètes.
- **Droit à l'effacement** (« droit à l'oubli ») : obtenir la suppression de vos données, sous réserve des obligations légales de conservation.
- **Droit à la limitation** : bloquer temporairement le traitement en cas de contestation.
- **Droit à la portabilité** : récupérer vos données dans un format structuré, lisible par machine.
- **Droit d'opposition** : vous opposer au traitement fondé sur l'intérêt légitime ou à des fins de prospection.
- **Droit de retrait du consentement** à tout moment, sans remettre en cause les traitements antérieurs.
- **Droit de définir des directives** relatives au sort de vos données après votre décès.

### 7.1. Comment exercer vos droits

Envoyez votre demande à **privacy@aoriarh.fr**, accompagnée d'un justificatif d'identité si nécessaire. Nous répondons dans un délai maximum de **30 jours** (prolongeable de 2 mois pour les demandes complexes, avec information préalable).

Pour les données personnelles contenues dans les documents importés par un Client (par exemple, un salarié souhaitant accéder aux informations le concernant dans un contrat importé par son employeur), la demande doit être adressée directement au Client (employeur), qui agit en tant que responsable de traitement. AORIA RH transmet la demande au Client concerné s'il est sollicité directement.

### 7.2. Réclamation auprès de la CNIL

Vous pouvez introduire une réclamation auprès de la **Commission Nationale de l'Informatique et des Libertés (CNIL)** :
- 3 place de Fontenoy – TSA 80715 – 75334 Paris Cedex 07
- www.cnil.fr

---

## 8. Sécurité des données

### 8.1. Mesures en place

- **Chiffrement en transit** : l'ensemble des communications entre le navigateur, le frontend, le backend et les sous-traitants est chiffré via **TLS 1.2+**.
- **Hachage des mots de passe** : algorithme **bcrypt** avec sel aléatoire (les mots de passe ne sont jamais stockés ni transmis en clair).
- **Cloisonnement multi-tenant strict** : chaque donnée (PostgreSQL, Qdrant, MinIO) est associée à un identifiant d'organisation et filtrée systématiquement. Aucune donnée n'est accessible entre Clients.
- **Contrôle d'accès** : authentification par email/mot de passe ou Google OAuth, tokens JWT à durée limitée, sessions invalidables.
- **Hébergement** : serveurs physiques OVHcloud situés à **Roubaix (France)**, certifiés **ISO/IEC 27001**, 27017, 27018.
- **Journalisation** : logs d'accès et d'administration conservés pour détection d'incidents.

### 8.2. Mesures en cours de déploiement

Par souci de transparence, AORIA RH indique que les mesures suivantes **ne sont pas encore en place** et font partie de sa feuille de route sécurité :

- **Chiffrement au repos** des volumes de stockage (PostgreSQL, Qdrant, MinIO) : mise en place prévue.
- **Sauvegardes chiffrées externalisées** hors du VPS principal : en cours de spécification.
- **Pseudonymisation automatique** des données personnelles dans les documents avant envoi au LLM : étude en cours.

Le Client est invité à en tenir compte dans son analyse d'impact (AIPD) et à conserver des copies de sauvegarde de ses documents critiques.

### 8.3. Notification de violation

En cas de violation de données à caractère personnel susceptible d'engendrer un risque pour les droits et libertés des personnes concernées, AORIA RH notifie :
- la **CNIL** dans un délai de 72 heures après en avoir pris connaissance (art. 33 RGPD) ;
- le **Client concerné** dans les meilleurs délais (art. 34 RGPD).

---

## 9. Cookies et traceurs

AORIA RH n'utilise **aucun cookie publicitaire, aucun cookie tiers de suivi, ni aucun outil d'analytics externe**.

Les seuls mécanismes utilisés sont :

| Nom | Type | Finalité | Durée |
|---|---|---|---|
| Cookie de session NextAuth | Technique (strictement nécessaire) | Maintien de l'authentification | 7 jours |
| `localStorage` : `theme` | Technique (confort) | Mémoriser le thème clair/sombre choisi | Persistant, supprimable par l'utilisateur |

Ces traceurs étant **strictement nécessaires** au fonctionnement du Service, ils ne requièrent pas de consentement préalable (art. 82 LIL, lignes directrices CNIL).

---

## 10. Données des mineurs

Le Service est strictement destiné aux professionnels. Aucune donnée de mineur de moins de 15 ans n'est collectée sciemment. Si un Client importe par erreur des documents concernant des mineurs, il lui appartient de s'assurer de la conformité de ce traitement, en sa qualité de responsable.

---

## 11. Modification de la politique

AORIA RH se réserve le droit de modifier la présente politique pour se conformer à l'évolution de la réglementation ou à l'évolution du Service. Toute modification substantielle est notifiée aux Utilisateurs par email et/ou dans l'application, au moins **30 jours** avant son entrée en vigueur.

---

## 12. Contact

Pour toute question relative à la présente politique ou à vos données personnelles :

- **Email** : privacy@aoriarh.fr
- **Courrier** : {{RAISON_SOCIALE}} — Service Protection des Données — {{ADRESSE_SIEGE}}

---

*Fin de la Politique de confidentialité — AORIA RH — v1.0*
