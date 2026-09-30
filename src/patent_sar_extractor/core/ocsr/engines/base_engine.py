"""
Base OCSR Engine abstract interface.

All OCSR (Optical Chemical Structure Recognition) engines must implement
this interface to ensure uniform predict() output format.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseOCSREngine(ABC):
    """Abstract base class for OCSR engines."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the engine is properly installed and ready to use.

        Returns:
            True if the engine can be used for prediction, False otherwise.
        """
        pass

    @abstractmethod
    def predict(self, image_path: str, timeout: int = 120) -> dict:
        """Run OCSR prediction on a single structure image.

        Args:
            image_path: Path to the structure crop image file.
            timeout: Maximum time in seconds for a single prediction.

        Returns:
            dict with the following keys:
                - engine (str): Engine name
                - status (str): "success" | "failed" | "timeout" | "unavailable"
                - raw_smiles (str|None): Predicted SMILES string
                - molblock (str|None): MOL block if available
                - sdf_path (str|None): Path to SDF file if generated
                - confidence (float|None): Prediction confidence score
                - error (str|None): Error message if failed
                - elapsed_sec (float): Time taken for prediction
        """
        pass

    def _make_result(
        self,
        status: str,
        raw_smiles: Optional[str] = None,
        molblock: Optional[str] = None,
        sdf_path: Optional[str] = None,
        confidence: Optional[float] = None,
        error: Optional[str] = None,
        elapsed_sec: float = 0.0,
        **extra,
    ) -> dict:
        """Helper to construct a standardized result dict."""
        result = {
            "engine": self.name,
            "status": status,
            "raw_smiles": raw_smiles,
            "molblock": molblock,
            "sdf_path": sdf_path,
            "confidence": confidence,
            "error": error,
            "elapsed_sec": round(elapsed_sec, 3),
        }
        result.update(extra)
        return result

    def _make_unavailable_result(self, error: str) -> dict:
        """Construct an unavailable result dict."""
        return self._make_result(status="unavailable", error=error)

    def _make_timeout_result(self, timeout: int) -> dict:
        """Construct a timeout result dict."""
        return self._make_result(
            status="timeout", error=f"Prediction timed out after {timeout}s"
        )

    def _make_failed_result(self, error: str) -> dict:
        """Construct a failed result dict."""
        return self._make_result(status="failed", error=error)
