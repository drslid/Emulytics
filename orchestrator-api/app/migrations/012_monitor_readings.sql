CREATE INDEX executions_finished_monitor_idx
    ON executions (finished_at DESC, id DESC) WHERE finished_at IS NOT NULL;
CREATE INDEX executions_success_monitor_idx
    ON executions (finished_at DESC, id DESC)
    WHERE status = 'succeeded' AND finished_at IS NOT NULL;
