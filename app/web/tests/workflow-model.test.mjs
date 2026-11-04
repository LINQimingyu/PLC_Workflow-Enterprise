import test from "node:test";
import assert from "node:assert/strict";
import { workflowGraph, statusMark } from "../src/cim/workflow-model.ts";

const stages = ["requirements", "baseline", "analysis", "proposal", "review", "verification", "archive"];
const snapshot = {
  nodes: [...stages.map(stage => ({ id: `stage:${stage}`, stage, kind: "stage" })),
    { id: "task:a", stage: "requirements", kind: "task" },
    { id: "task:b", stage: "baseline", kind: "task" },
    { id: "task:c", stage: "analysis", kind: "task" }],
  edges: [
    { id: "route", source: "stage:requirements", target: "stage:baseline", kind: "route" },
    { id: "a-b", source: "task:a", target: "task:b", kind: "dependency" },
    { id: "b-c", source: "task:b", target: "task:c", kind: "dependency" },
  ],
};
test("collapsed graph shows seven stages without an invented task relationship", () => {
  const graph = workflowGraph(snapshot, new Set(), "stage:requirements");
  assert.equal(graph.visible.length, 7);
  assert.equal(graph.edges.length, 1);
});
test("selected task keeps its real predecessor visible through a collapsed stage", () => {
  const graph = workflowGraph(snapshot, new Set(["baseline"]), "task:b");
  const edges = graph.edges.filter(e => e.kind === "dependency");
  assert.equal(edges.length, 2);
  assert.ok(edges.some(e => e.source === "stage:requirements" && e.target === "task:b"));
  assert.ok(edges.some(e => e.source === "task:b" && e.target === "stage:analysis"));
  assert.equal(new Set([...graph.positions.values()].map(p => `${p.x},${p.y}`)).size, graph.visible.length);
});
test("expanded groups keep underlying dependency endpoints and deterministic positions", () => {
  const graph = workflowGraph(snapshot, new Set(["requirements", "baseline"]), "stage:baseline");
  assert.ok(graph.edges.some(e => e.source === "task:a" && e.target === "task:b"));
  assert.ok(graph.visible.every(n => graph.positions.has(n.id)));
  assert.equal(graph.positions.get("stage:baseline").x, graph.positions.get("task:b").x);
});
test("exemption and cancellation have distinct markers from actual completion", () => {
  assert.equal(statusMark("passed"), "✓");
  assert.equal(statusMark("not_applicable"), "−");
  assert.equal(statusMark("cancelled"), "×");
  assert.equal(statusMark("stale"), "!");
});
