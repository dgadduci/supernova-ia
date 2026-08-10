## MODIFIED Requirements

### Requirement: Configurable LLM settings

The system SHALL expose configurable values for `LLM_URL`, `LLM_MODEL`,
`LLM_TIMEOUT`, `LLM_KEEP_ALIVE`, `LLM_NUM_CTX`, `LLM_NUM_PREDICT`,
`LLM_LOG_CONTENT`, and `LLM_LOG_MAX_CHARS`, allowing environment variables to
override the local defaults and without depending on SQLAlchemy or Alembic.
The local defaults for the existing non-semantic LLM path SHALL be
`LLM_MODEL=qwen2.5-coder:7b-ctx8192` and `LLM_NUM_CTX=8192`.

#### Scenario: Settings use local defaults when no overrides are set

- **WHEN** the settings module is loaded without any `LLM_*` environment
  variables
- **THEN** each value matches its documented local default

#### Scenario: Non-semantic defaults select the controlled 7B model

- **WHEN** the settings module is loaded without `LLM_MODEL` or `LLM_NUM_CTX`
  environment overrides
- **THEN** it yields `qwen2.5-coder:7b-ctx8192` and `8192`, respectively

#### Scenario: Settings honor environment overrides

- **WHEN** the user exports `LLM_MODEL=custom-model`, `LLM_NUM_CTX=4096` and
  `LLM_URL=https://example/llm`
- **THEN** the loaded values are `custom-model`, `4096` and the configured URL
