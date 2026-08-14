import { partitionSources, sourceDate, sourceIdcc } from "./source-evidence";
import type { MessageSource } from "@/types/api";

function source(partial: Partial<MessageSource>): MessageSource {
  return {
    document_id: "doc",
    document_name: "Document juridique",
    source_type: "code_travail",
    source_type_label: "Code du travail",
    norme_niveau: 4,
    excerpt: "Passage pertinent",
    ...partial,
  };
}

describe("classement des fondements", () => {
  test("une référence d'article résolue devient un fondement", () => {
    const law = source({ document_id: "law", article_nums: ["L1234-1"] });
    const other = source({
      document_id: "other",
      document_name: "Autre document",
    });

    const result = partitionSources("Selon l'article L.1234-1, le préavis…", [
      law,
      other,
    ]);

    expect(result.foundations).toHaveLength(1);
    expect(result.foundations[0].source.document_id).toBe("law");
    expect(result.foundations[0].references).toEqual(["article L.1234-1"]);
    expect(result.consulted.map((item) => item.document_id)).toEqual(["other"]);
  });

  test("un article conventionnel n'est relié que s'il est non ambigu", () => {
    const ccn = source({
      document_id: "ccn",
      document_name: "CCN Exemple (IDCC 1234)",
      source_type: "convention_collective_nationale",
      article_nums: ["12"],
    });

    expect(
      partitionSources("L'article 12 fixe le délai.", [ccn]).foundations
    ).toHaveLength(1);

    const second = source({
      document_id: "accord",
      document_name: "Accord d'entreprise",
      source_type: "accord_entreprise",
      article_nums: ["12"],
    });
    expect(
      partitionSources("L'article 12 fixe le délai.", [ccn, second]).foundations
    ).toHaveLength(0);
  });

  test("le nom exact d'un document interne peut être relié", () => {
    const rules = source({
      document_id: "rules",
      document_name: "Règlement intérieur 2026",
      source_type: "reglement_interieur",
    });
    expect(
      partitionSources("Le Règlement intérieur 2026 interdit cet usage.", [
        rules,
      ]).foundations[0].source.document_id
    ).toBe("rules");
  });

  test("les métadonnées IDCC et date ont des fallbacks sûrs", () => {
    const ccn = source({
      document_name: "CCN Exemple (IDCC 42)",
      content_date: "2026-06-01",
    });
    expect(sourceIdcc(ccn)).toBe("0042");
    expect(sourceDate(ccn)).toBe("01/06/2026");
  });
});
