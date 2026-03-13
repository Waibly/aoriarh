# AORIA RH — Contexte projet pour Claude Code

## Description

Application web SaaS multi-tenant d'assistance juridique RH par IA. Les utilisateurs posent des questions juridiques RH via un chat et obtiennent des réponses sourcées générées par RAG.

## Stack technique

- **Frontend** : Next.js + React + Tailwind CSS
- **Backend** : Python FastAPI
- **RAG Framework** : LlamaIndex
- **Base de données** : PostgreSQL
- **Vector Store** : Qdrant
- **Embeddings** : Voyage AI `voyage-law-2`
- **LLM** : OpenAI `gpt-5-mini`
- **Auth** : NextAuth.js v5 (Credentials provider + JWT backend)
- **UI Kit** : shadcn/ui (composants Radix UI + Tailwind)
- **Paiement** : Stripe
- **Stockage docs** : MinIO (compatible S3)
- **Déploiement** : Docker + Vercel (front) + Railway/Fly.io (back)

## Architecture

- Multi-tenant strict : chaque donnée est associée à un `organisation_id`
- Cloisonnement des données entre organisations (applicatif + vectoriel dans Qdrant)
- Pipeline RAG avec agent structuré 7 étapes (reformulation → recherche hybride → reranking → références croisées → génération)
- Hiérarchie des normes du droit social français : 26 types de documents, 9 niveaux de priorité avec poids (1.0 → 0.5)

## Rôles utilisateurs

- **Admin** : personnel interne AORIA RH (back-office, documents communs)
- **Manager** : souscripteur (crée des organisations, invite des membres, gère l'abonnement)
- **Utilisateur** : membre invité (chat, upload de documents dans ses organisations)

## Conventions de code

### Backend (Python / FastAPI)
- Python 3.12+
- Formateur : `ruff`
- Tests : `pytest` — couverture cible > 80%
- Typage strict avec type hints
- Async/await pour les endpoints FastAPI
- Docstrings uniquement sur les fonctions publiques complexes

### Frontend (Next.js / React)
- TypeScript strict
- Formateur : `prettier` + `eslint`
- Tests : `Jest` + `React Testing Library`
- Composants fonctionnels uniquement (pas de class components)
- Tailwind CSS pour le styling (pas de CSS modules ni styled-components)
- **shadcn/ui** pour tous les composants d'interface (boutons, inputs, cards, dialogs, selects, tables, etc.). Ne pas créer de composants UI custom quand un équivalent shadcn/ui existe.
- Utiliser les tokens sémantiques shadcn/ui (`bg-background`, `bg-muted`, `text-muted-foreground`, `border-border`, etc.) au lieu des classes Tailwind brutes (`bg-gray-50 dark:bg-gray-900`)
- Thème light/dark géré via les CSS custom properties shadcn/ui (`:root` / `.dark`)

## Structure du projet

```
aoriarh/
├── frontend/          # Next.js app
│   ├── src/
│   │   ├── app/       # App Router (pages)
│   │   ├── components/
│   │   ├── lib/       # Utilitaires, API client
│   │   └── types/
│   └── tests/
├── backend/           # FastAPI app
│   ├── app/
│   │   ├── api/       # Routes / endpoints
│   │   ├── core/      # Config, sécurité, dépendances
│   │   ├── models/    # Modèles SQLAlchemy
│   │   ├── schemas/   # Schémas Pydantic
│   │   ├── services/  # Logique métier
│   │   └── rag/       # Pipeline RAG (ingestion, recherche, agent)
│   └── tests/
├── docker-compose.yml
├── CAHIER_DES_CHARGES.md
└── CLAUDE.md
```

## Règles importantes

- **JAMAIS push ni déployer sans accord explicite** : ne JAMAIS exécuter `git push`, `docker compose up`, ou toute commande de déploiement en production sans avoir demandé et obtenu la confirmation de l'utilisateur. Cela s'applique à CHAQUE fois, sans exception.
- **Demander avant de modifier des composants critiques** : ne pas se lancer dans des corrections sur le pipeline RAG, l'ingestion, les embeddings, ou tout composant qui impacte tous les documents/utilisateurs sans en discuter d'abord. Préférer ajouter du logging pour diagnostiquer avant de corriger.
- **Cloisonnement** : toute requête Qdrant ou PostgreSQL doit filtrer par `organisation_id`. Ne jamais exposer des données cross-tenant.
- **Hiérarchie des normes** : lors de contradictions entre sources, appliquer la priorité (1 = plus fort). Voir la table complète dans CAHIER_DES_CHARGES.md section 5.3.
- **Performance RAG** : max 2 itérations de re-recherche, timeout global 15s, timeout par étape 3s, pas de boucle ouverte.
- **Tests** : écrire des tests unitaires pour toute nouvelle fonctionnalité. Tester systématiquement le cloisonnement multi-tenant.
- **Sécurité** : ne jamais stocker de secrets dans le code. Utiliser des variables d'environnement (.env).

## Commandes courantes

```bash
# Backend
cd backend && uvicorn app.main:app --reload
pytest

# Frontend
cd frontend && npm run dev
npm test

# Docker
docker-compose up -d
```

## Cahier des charges

Le fichier `CAHIER_DES_CHARGES.md` à la racine contient toutes les spécifications détaillées du projet. S'y référer pour toute question fonctionnelle.
