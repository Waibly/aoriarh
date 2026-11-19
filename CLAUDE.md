# Aoria RH — application

Lire [AGENTS.md](AGENTS.md). La [documentation commune](../aoriarh-docs/README.md) est reconstruite progressivement ; consulter le code pour vérifier les faits actuels.
Pour une livraison demandée, suivre [la procédure centrale](../aoriarh-docs/LIVRAISON.md).

## Modifier le Caddyfile du VPS (partagé Aoria RH et Kowizo)

Un seul Caddy (`aoriarh-caddy-1`) sert aoriarh.fr et kowizo.com : une erreur coupe les deux. Le fichier de référence est `Caddyfile` du dépôt Aoria RH ; ne jamais le modifier directement sur le serveur.

1. Modifier `Caddyfile` dans le dépôt Aoria RH sur le Mac (`~/Documents/Projets/aoriarh`), commit, push sur `main`. Côté Kowizo, reporter aussi la règle dans `ops/caddy/Kowizo.caddy.example`.
2. Sur le serveur (`ssh -p 2222 aoriadmin@79.137.14.24`, `cd /home/aoriadmin/aoriarh`) : `git status` doit être propre pour `Caddyfile`, puis `git pull --ff-only`.
3. Valider le nouveau fichier **avant** de toucher au Caddy en service, avec un conteneur jetable :
   `docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` → doit afficher `Valid configuration`. Sinon : `git revert`, push, pull, et rien n'est rechargé.
4. Appliquer. Piège : `git pull` remplace le fichier (nouvel inode) et le montage de Caddy reste sur l'ancien. Comparer `sha256sum Caddyfile` et `docker exec aoriarh-caddy-1 sha256sum /etc/caddy/Caddyfile` :
   - identiques → `docker exec aoriarh-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile` (sans coupure) ;
   - différents → `docker restart aoriarh-caddy-1` (quelques secondes de coupure pour tous les sites, à faire hors heures de publication).
5. Vérifier : `curl -s -o /dev/null -w '%{http_code}'` sur https://aoriarh.fr/, https://app.aoriarh.fr/, https://kowizo.com/, https://app.kowizo.com/api/health, https://mcp.kowizo.com/.well-known/oauth-protected-resource (attendus : 200, 307, 200, 200, 200).
