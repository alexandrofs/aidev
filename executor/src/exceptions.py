class ContextError(Exception):
    """Base exception for context-related errors in the executor."""
    pass


class PromptTemplateNotFoundError(ContextError):
    """Raised when a required prompt template is missing or empty."""
    pass


class InvalidMCPConfigError(ContextError):
    """Raised when the MCP configuration file is invalid or cannot be parsed."""
    pass
