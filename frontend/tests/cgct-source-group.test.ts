import { getSourceGroup, groupSources } from "@/lib/source-groups";
import type { MessageSource } from "@/types/api";

describe("CGCT sources", () => {
  it("groups common legislative and regulatory articles as legal sources", () => {
    const kinds = [
      "code_general_collectivites_territoriales",
      "code_general_collectivites_territoriales_reglementaire",
    ];
    for (const kind of kinds) expect(getSourceGroup(kind)).toBe("legal");
    const sources = kinds.map((source_type) => ({ source_type }) as MessageSource);
    const groups = groupSources(sources);
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe("legal");
    expect(groups[0].sources).toEqual(sources);
  });
});
