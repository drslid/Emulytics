CREATE TABLE automation_publications (
    workflow_id text NOT NULL,
    version integer NOT NULL,
    name text NOT NULL,
    instructions text NOT NULL,
    PRIMARY KEY(workflow_id,version),
    FOREIGN KEY(workflow_id,version) REFERENCES workflows(workflow_id,version)
);
