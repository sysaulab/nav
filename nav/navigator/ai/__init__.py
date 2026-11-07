"""Model backends and registry.

Module names in a ModelSpec's `module` field resolve to a ChatClient
implementation here. Adding a backend means adding a module here and
a ModelSpec with the matching `module` value.
"""