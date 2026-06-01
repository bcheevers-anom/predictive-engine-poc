export interface ForecastResponse {
  status: 'ok' | 'no_model' | 'insufficient_coverage' | 'not_supported';
  finding?: {
    title: string;
    type_name: string;
    confidence: number;
    viz_type: 'timeseries' | 'classification' | 'anomaly' | 'cluster';
  };
  prediction?: { tool?: string; count?: number }[];
  feature_contributions?: { feature: string; importance: number; normalised: number }[];
  coverage?: Record<string, number>;
  baselines?: Record<string, number>;
  message?: string;
  reason?: string;
  hint?: string;
  aql_port_idiom?: string;
  batch_id?: string;
}

export interface BatchInfo {
  batch_id: string;
  from_date: string;
  to_date: string;
  total_deduplicated: number;
}
