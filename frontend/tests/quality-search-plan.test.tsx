import { render, screen } from "@testing-library/react";

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => null }));
jest.mock("rehype-sanitize", () => ({ __esModule: true, default: () => null }));

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { access_token: "test-token" } }),
}));

import {
  InspectorBody,
  type InspectorPayload,
} from "@/app/(admin)/admin/quality/InspectorBody";

function payload(): InspectorPayload {
  return {
    question: "Et pour un cadre ?",
    answer: null,
    sources: [],
    cost_usd: 0.001,
    latency_ms: 1200,
    rag_trace: {
      query_original: "Et pour un cadre ?",
      query_condensed: null,
      variants: [],
      identifiers_detected: {},
      boost_injected: 0,
      hybrid_results: [],
      rerank_results: [],
      parent_groups: [],
      perf_ms: {},
      model: "test-model",
      out_of_scope: false,
      no_results: false,
      error: null,
      search_plan_usage: {
        prompt_tokens: 321,
        completion_tokens: 87,
        latency_ms: 450,
        cost_usd: 0.0002,
      },
      search_plan: {
        version: "deterministic-shadow-v1",
        query_original: "Et pour un cadre ?",
        standalone_question: "Quel est le préavis applicable à un cadre ?",
        mode: "follow_up",
        answer_intent: "factual_rule",
        answer_format: "direct_then_cases",
        needs_llm_planner: true,
        needs_condensation: true,
        explicit_identifiers: {},
        requested_source_types: [],
        applicable_idccs: ["1486"],
        time_scope: null,
        legislation: "required",
        ccn: "safety_floor",
        jurisprudence: "optional",
        internal_documents: "optional",
        planner_status: "ok",
        legal_topics: ["préavis", "cadre"],
        search_queries: ["préavis cadre convention collective"],
        hypothesized_articles: [{ reference: "L1234-1", confidence: "medium" }],
        missing_facts: ["ancienneté"],
        planner_source_hints: ["legislation", "ccn"],
        planner_jurisprudence: "optional",
        planner_answer_intent: "factual_rule",
        reasons: ["anaphoric_follow_up"],
        warnings: [],
      },
    },
  };
}

describe("Quality search plan", () => {
  it("renders the shadow plan without presenting guessed articles as used", () => {
    render(<InspectorBody data={payload()} />);

    expect(
      screen.getByText("Plan de recherche (observation)")
    ).toBeInTheDocument();
    expect(screen.getByText("Relance conversationnelle")).toBeInTheDocument();
    expect(screen.getByText("Simulation compacte réussie")).toBeInTheDocument();
    expect(
      screen.getByText("Articles supposés — non utilisés")
    ).toBeInTheDocument();
    expect(screen.getByText(/L1234-1 \(medium\)/)).toBeInTheDocument();
    expect(screen.getByText(/321 tokens entrée/)).toBeInTheDocument();
  });

  it("clearly identifies a plan that actually drove a sandbox run", () => {
    const data = payload();
    if (data.rag_trace?.search_plan_usage) {
      data.rag_trace.search_plan_usage.execution = "adaptive_shadow";
    }
    if (data.rag_trace?.search_plan) {
      data.rag_trace.search_plan.query_budget = 1;
    }
    if (data.rag_trace) {
      data.rag_trace.search_plan_validation = {
        status: "ok",
        hypotheses_proposed: ["L1234-1"],
        hypotheses_requested: ["L1234-1"],
        hypotheses_skipped_low_confidence: [],
        corpus_matches: ["L1234-1"],
        candidate_chunks_fetched: 2,
        candidate_chunks_added: 2,
        rejected_below_confidence_floor: [],
        retained_after_rerank: ["L1234-1"],
        retained_in_final_sources: ["L1234-1"],
      };
    }

    render(<InspectorBody data={data} />);

    expect(
      screen.getByText("Plan de recherche (exécuté dans le sandbox)")
    ).toBeInTheDocument();
    expect(screen.getByText("Exécuté dans ce sandbox")).toBeInTheDocument();
    expect(screen.getByText("1 requête enrichie")).toBeInTheDocument();
    expect(
      screen.getByText("Articles suggérés — validation dans le corpus")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/L1234-1 \(medium\) — retenu dans les sources finales/)
    ).toBeInTheDocument();
  });

  it("shows that low-confidence articles were not searched", () => {
    const data = payload();
    if (data.rag_trace?.search_plan_usage) {
      data.rag_trace.search_plan_usage.execution = "adaptive_shadow";
    }
    if (data.rag_trace?.search_plan) {
      data.rag_trace.search_plan.hypothesized_articles = [
        { reference: "L1226-9", confidence: "low" },
      ];
    }
    if (data.rag_trace) {
      data.rag_trace.search_plan_validation = {
        status: "ok",
        hypotheses_proposed: ["L1226-9"],
        hypotheses_requested: [],
        hypotheses_skipped_low_confidence: ["L1226-9"],
        corpus_matches: [],
        candidate_chunks_fetched: 0,
        candidate_chunks_added: 0,
        rejected_below_confidence_floor: [],
        retained_after_rerank: [],
        retained_in_final_sources: [],
      };
    }

    render(<InspectorBody data={data} />);

    expect(
      screen.getByText(
        /L1226-9 \(low\) — écarté avant recherche \(confiance faible\)/
      )
    ).toBeInTheDocument();
  });
});
