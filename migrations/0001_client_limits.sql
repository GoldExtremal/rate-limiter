CREATE TABLE client_limits (
    client_id text PRIMARY KEY CHECK (char_length(client_id) BETWEEN 1 AND 256),
    rate_limit integer NOT NULL CHECK (rate_limit >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
