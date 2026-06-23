import type { Element, Root, Text } from "hast";
import { SKIP, visit } from "unist-util-visit";

import { buildReplacements, type RefIndex } from "@/lib/legal-refs";

const SKIP_PARENTS = new Set(["a", "code", "pre"]);

/**
 * Plugin rehype : remplace les références juridiques résolues par des liens
 * `<a href="#src-<document_id>">`, interceptés au rendu par LegalRefAnchor.
 *
 * Placé AVANT rehype-sanitize : les liens générés sont donc eux-mêmes
 * sanitizés (href fragment et className passent le schema par défaut).
 * Ignore le texte déjà dans un lien, du code inline ou un bloc.
 */
export function rehypeLegalRefs(options: { index: RefIndex }) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (index === undefined || !parent) return;
      if (
        parent.type === "element" &&
        SKIP_PARENTS.has((parent as Element).tagName)
      ) {
        return;
      }
      const replacements = buildReplacements(node.value, options.index);
      if (!replacements) return;
      parent.children.splice(index, 1, ...replacements);
      // Ne pas re-visiter les nœuds insérés (les liens sont skippés de toute façon).
      return [SKIP, index + replacements.length];
    });
  };
}
