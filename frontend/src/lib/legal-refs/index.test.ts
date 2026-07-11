import { buildRefIndex, buildReplacements } from "./index";
import type { MessageSource } from "@/types/api";

function src(partial: Partial<MessageSource>): MessageSource {
  return {
    document_id: "d",
    document_name: "",
    source_type: "decret",
    source_type_label: "",
    norme_niveau: 5,
    excerpt: "",
    ...partial,
  };
}

// Renvoie [texte, href] pour chaque lien produit.
function links(text: string, sources: MessageSource[]): [string, string][] {
  const out = buildReplacements(text, buildRefIndex(sources));
  if (!out) return [];
  return out
    .filter((n): n is import("hast").Element => (n as { type: string }).type === "element")
    .map((el) => [
      (el.children[0] as { value: string }).value,
      String(el.properties?.href ?? ""),
    ]);
}

describe("liens juridiques", () => {
  test("numéro de décret → lien vers son document", () => {
    const sources = [
      src({ document_id: "d887", document_name: "Décret n° 2025-887 du 4 septembre 2025 relatif aux modalités…", source_type: "decret" }),
    ];
    expect(links("Voir le décret n° 2025-887 pour la formule.", sources)).toEqual([
      ["décret n° 2025-887", "#src-d887"],
    ]);
  });

  test("numéro de loi → lien", () => {
    const sources = [src({ document_id: "l1403", document_name: "LOI n° 2025-1403 du 30 décembre 2025 de financement…", source_type: "loi" })];
    expect(links("prévu par la loi n° 2025-1403", sources)).toEqual([
      ["loi n° 2025-1403", "#src-l1403"],
    ]);
  });

  test("pas de lien si le décret cité n'est pas une source", () => {
    expect(links("le décret n° 2025-887", [])).toEqual([]);
  });

  test("non-régression : article de code toujours lié", () => {
    const sources = [src({ document_id: "css", document_name: "Code de la sécurité sociale", source_type: "code_securite_sociale_reglementaire", article_nums: ["D241-7"] })];
    expect(links("selon l'art. D. 241-7", sources)).toEqual([["art. D. 241-7", "#src-css"]]);
  });

  test("non-régression : pourvoi toujours lié", () => {
    const sources = [src({ document_id: "ca", document_name: "Cour d'appel de Bordeaux", source_type: "arret_cour_appel", numero_pourvoi: "24/05597" })];
    expect(links("CA Bordeaux, n° 24/05597", sources)).toEqual([["n° 24/05597", "#src-ca"]]);
  });

  test("décret prioritaire sur le pourvoi pour le même numéro", () => {
    const sources = [src({ document_id: "d887", document_name: "Décret n° 2025-887 du 4 septembre 2025", source_type: "decret" })];
    // « n° 2025-887 » ne doit pas être traité comme un pourvoi orphelin.
    expect(links("décret n° 2025-887", sources)).toEqual([["décret n° 2025-887", "#src-d887"]]);
  });

  test("arrêté cité par date numérique (JJ/MM/AAAA) → lien", () => {
    const sources = [src({ document_id: "arr", document_name: "Arrêté du 22 mai 2026 relatif au relèvement du salaire minimum de croissance", source_type: "arrete" })];
    expect(links("cf. Arrêté du 22/05/2026, art. 1-1°", sources)).toEqual([
      ["Arrêté du 22/05/2026", "#src-arr"],
    ]);
  });

  test("arrêté cité par date française → lien", () => {
    const sources = [src({ document_id: "arr", document_name: "Arrêté du 22 mai 2026 relatif au relèvement du SMIC", source_type: "arrete" })];
    expect(links("selon l'arrêté du 22 mai 2026", sources)).toEqual([
      ["arrêté du 22 mai 2026", "#src-arr"],
    ]);
  });

  test("pas de lien si l'arrêté cité n'est pas une source", () => {
    expect(links("Arrêté du 22/05/2026", [])).toEqual([]);
  });

  test("pas de faux lien : date du texte ≠ date de la source", () => {
    const sources = [src({ document_id: "arr", document_name: "Arrêté du 8 juin 2026 relatif au SMIC agricole", source_type: "arrete" })];
    expect(links("Arrêté du 22/05/2026", sources)).toEqual([]);
  });
});
