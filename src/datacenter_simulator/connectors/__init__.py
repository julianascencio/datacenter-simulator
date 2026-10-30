"""External generation adapters; no network access is required by the simulator."""

from .generation import generation_from_csv, generation_from_series

__all__ = ["generation_from_csv", "generation_from_series"]
