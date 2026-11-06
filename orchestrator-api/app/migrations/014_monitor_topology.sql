CREATE INDEX run_events_topology_recent_idx ON run_events(created_at DESC)
    WHERE type IN ('execution.started','action.done','execution.step_completed');
CREATE INDEX executions_updated_topology_idx ON executions(updated_at DESC,id DESC);
