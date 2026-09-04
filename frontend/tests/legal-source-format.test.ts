import { formatLegalSourceMarkdown } from "@/lib/legal-source-format";

describe("formatLegalSourceMarkdown", () => {
  it("met en forme les titres des anciens textes JORF sans toucher au contenu", () => {
    const source =
      "Article 3\n\nI.-Le code du travail est modifié :\n1° Première règle ;\n2° Seconde règle.";

    expect(formatLegalSourceMarkdown(source, "loi")).toBe(
      "### Article 3\n\nI.-Le code du travail est modifié :\n1° Première règle ;\n2° Seconde règle."
    );
  });

  it("reconnaît les continuations et laisse les autres sources inchangées", () => {
    expect(formatLegalSourceMarkdown("Article 11 (suite)\nTexte", "decret")).toBe(
      "### Article 11 (suite)\nTexte"
    );
    expect(formatLegalSourceMarkdown("Article 11\nTexte", "code_travail")).toBe(
      "Article 11\nTexte"
    );
  });
});
