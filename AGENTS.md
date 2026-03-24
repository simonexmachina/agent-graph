**IMPORTANT**: before you do anything else, run the `beans prime` command and heed its output.

## Development Standards

- **Write tests as you go.** Every feature bean gets tests in the same commit. Unit tests for pure logic; integration tests (marked `@pytest.mark.integration`) for anything touching the database or external APIs. Integration tests are skipped by default (`pytest -m "not integration"`).
- **Strongly typed Python.** All code uses type hints throughout — function signatures, return types, class attributes. Pydantic models at all data boundaries. Pyright in strict mode for static checking.