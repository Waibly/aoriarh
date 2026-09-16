/** An installed convention is usable only when its documents are indexed. */
export function conventionDisplayStatus(
  status: string,
  docs: { indexation_status: string; name: string }[],
): string {
  if (status !== "ready") return status;
  // BOCC reserve documents are intentionally pending and do not block the CCN.
  const consolidated = docs.filter((doc) => !doc.name.includes("BOCC"));
  if (consolidated.some((doc) => doc.indexation_status === "error")) return "error";
  if (consolidated.length === 0 || consolidated.some((doc) => doc.indexation_status !== "indexed")) {
    return "indexing";
  }
  return "ready";
}
