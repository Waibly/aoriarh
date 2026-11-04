import { redirect } from "next/navigation";

// Le middleware redirige déjà "/" selon la session. Pas d'appel à auth() ici :
// un refresh déclenché dans un Server Component ne peut pas réécrire le cookie,
// le nouveau refresh token serait perdu.
export default function HomePage() {
  redirect("/chat");
}
