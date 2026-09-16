import { conventionDisplayStatus } from "@/lib/convention-status";

test("a ready convention with a failed document is displayed as failed", () => {
  expect(conventionDisplayStatus("ready", [{ name: "CCN Syntec", indexation_status: "error" }])).toBe("error");
});

test("a convention stays in progress until its consolidated documents are indexed", () => {
  expect(conventionDisplayStatus("ready", [{ name: "CCN Syntec", indexation_status: "pending" }])).toBe("indexing");
  expect(conventionDisplayStatus("ready", [])).toBe("indexing");
});

test("BOCC reserve does not block an indexed convention", () => {
  expect(conventionDisplayStatus("ready", [
    { name: "CCN Syntec", indexation_status: "indexed" },
    { name: "BOCC Syntec", indexation_status: "pending" },
  ])).toBe("ready");
});

test("an installation error remains visible even with existing indexed documents", () => {
  expect(conventionDisplayStatus("error", [{ name: "CCN Syntec", indexation_status: "indexed" }])).toBe("error");
});
