"""Model loader abstractions and mock implementations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import joblib

from app.models.interfaces import AbstractModelLoader
from app.models.signal import HORIZONS


@dataclass(frozen=True)
class LoadedModelSpec:
    """Metadata describing a loaded horizon model."""

    horizon: str
    provider_name: str
    version: str
    model: Any = None
    classes: Tuple[str, ...] = ()


class MockModelLoader(AbstractModelLoader):
    """Mock model loader used until a real classifier is plugged in."""

    def load(self) -> Dict[str, LoadedModelSpec]:
        """Return mock model metadata for each horizon."""

        return {
            "5s": LoadedModelSpec(horizon="5s", provider_name="mock", version="0.1.0"),
            "10s": LoadedModelSpec(horizon="10s", provider_name="mock", version="0.1.0"),
            "30s": LoadedModelSpec(horizon="30s", provider_name="mock", version="0.1.0"),
            "1m": LoadedModelSpec(horizon="1m", provider_name="mock", version="0.1.0"),
        }


class JoblibModelLoader(AbstractModelLoader):
    """Load trained sklearn-compatible models from joblib files."""

    def __init__(self, model_dir: Path):
        self._model_dir = model_dir

    def load(self) -> Dict[str, LoadedModelSpec]:
        """Load one model artifact per horizon from the configured directory."""

        loaded: Dict[str, LoadedModelSpec] = {}
        for horizon in HORIZONS:
            artifact_path = self._model_dir / f"{horizon}.joblib"
            if not artifact_path.exists():
                raise FileNotFoundError(
                    f"Missing model artifact for {horizon}: {artifact_path}"
                )

            artifact = joblib.load(artifact_path)
            model = artifact
            version = "1.0.0"
            classes: Tuple[str, ...] = ()

            if isinstance(artifact, dict):
                model = artifact.get("model")
                version = str(artifact.get("version", version))
                classes = tuple(str(item).upper() for item in artifact.get("classes", ()))

            if model is None:
                raise ValueError(f"Model artifact {artifact_path} did not contain a usable model.")

            if not classes and hasattr(model, "classes_"):
                classes = tuple(str(item).upper() for item in model.classes_)

            loaded[horizon] = LoadedModelSpec(
                horizon=horizon,
                provider_name="sklearn",
                version=version,
                model=model,
                classes=classes,
            )

        return loaded
