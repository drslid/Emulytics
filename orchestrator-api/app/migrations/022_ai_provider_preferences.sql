CREATE TABLE ai_provider_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    active_provider text NOT NULL DEFAULT 'openai' CHECK (active_provider IN ('openai', 'ollama', 'deepseek')),
    ollama_url text,
    ollama_model text,
    deepseek_model text,
    deepseek_key_ciphertext text
);
INSERT INTO ai_provider_settings(singleton) VALUES (true);
