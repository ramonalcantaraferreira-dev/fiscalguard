import type { CriteriaNode } from "@/lib/types";

const OPS: Record<string, string> = {
  eq: "=", ne: "≠", in: "∈", not_in: "∉", gt: ">", gte: "≥", lt: "<", lte: "≤", between: "entre",
  exists: "existe", not_exists: "não existe", starts_with: "começa com", is_true: "é verdadeiro", is_false: "é falso",
};
const GROUPS = { all: "Todas as condições", any: "Ao menos uma condição", not: "Negação" };

/** Trilha de avaliação: mostra cada critério, o valor observado e o resultado. */
export function Criteria({ node }: { node: CriteriaNode }) {
  if (node.group) {
    return (
      <div className="space-y-1">
        <p className="text-xs font-medium text-ink-muted">{GROUPS[node.group]}</p>
        <ul className="space-y-1 border-l border-line pl-3">
          {node.children?.map((c, i) => <li key={i}><Criteria node={c} /></li>)}
        </ul>
      </div>
    );
  }
  const show = (v: unknown) => (v === undefined || v === null ? "—" : Array.isArray(v) ? v.join(", ") : String(v));
  return (
    <p className="text-sm">
      <span className={node.result ? "text-ok" : "text-danger"}>{node.result ? "✓" : "✗"}</span>{" "}
      <code className="text-xs">{node.fact}</code> {OPS[node.op ?? ""] ?? node.op} <strong>{show(node.expected)}</strong>
      <span className="text-ink-muted"> (observado: {show(node.actual)})</span>
    </p>
  );
}
