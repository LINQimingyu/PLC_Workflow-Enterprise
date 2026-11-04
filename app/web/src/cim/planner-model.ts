export interface CreationAgentDefinition { id: string; name: string; responsibility: string; skills: string[]; outputs: string[]; restrictions: string[] }
export interface PlannerSettings {
  provider: "deepseek" | "compatible";
  base_url: string;
  model: string;
  destination: "external" | "internal";
  internal_confirmed: boolean;
  has_key: boolean;
  key_read_only?: boolean;
  agent: CreationAgentDefinition;
}
export interface CreationFields { name: string; scenario: string; area: string; cpu: string; equipment: string; requirements: string; classification: string }
export interface CreationCatalog {
  agents: { id: string; name: string; responsibility: string; skills: string[]; category: string; areas: string[] }[];
  process_packs: { id: string; area: string; status: string; unknowns: string[]; agents: string[]; version: string; field_validated: boolean }[];
}
export interface SetupPreview {
  fingerprint: string;
  fields: CreationFields;
  agents: { id: string; name: string; skills: string[]; responsibility: string; stage: string }[];
  skills: { id: string; name: string; version: string }[];
  process_packs: CreationCatalog["process_packs"];
  missing: string[];
  stages: { id: string; name: string; agents: string[]; depends_on: string[]; completion: string }[];
  automatic_execution: false;
}
export interface CreationDraft {
  id: string;
  status: "running" | "completed" | "failed" | "uncertain";
  error?: string;
  input_classification: string;
  created_project_id: string | null;
  proposal?: {
    summary: string;
    fields: Record<Exclude<keyof CreationFields, "classification">, string | null>;
    questions: string[];
    agent_ids: string[];
    pack_ids: string[];
  };
}
export async function plannerApi<T>(csrf: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/cim/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || `请求未完成 (${response.status})`);
  return result as T;
}
