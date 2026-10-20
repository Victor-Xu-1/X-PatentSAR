"""Actual printed-adapter output boundary with controlled tensors, not model inference."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
from PIL import Image

from patent_sar_extractor.core.ocsr.printed_model import PrintedDecimerModel


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)

    def numpy(self):
        return self.value

    def __getitem__(self, key):
        return Tensor(self.value[key])


class PrintedGenerationTests(unittest.TestCase):
    def predict(self, words, probabilities=None):
        # Construct only the adapter boundary, without importing TensorFlow,
        # initializing a runtime, opening weights or processing any patent crop.
        vocabulary = dict(enumerate(dict.fromkeys(words), start=1))
        indexes = {word: index for index, word in vocabulary.items()}
        tokens = Tensor([[indexes[word] for word in words]])
        scores = Tensor(
            probabilities if probabilities is not None else [0.99] * len(words)
        )
        model = PrintedDecimerModel.__new__(PrintedDecimerModel)
        model.tokenizer = SimpleNamespace(index_word=vocabulary)
        model.preprocess = SimpleNamespace(
            decode_image=lambda _path: np.ones((1, 1, 3))
        )
        model.codec = SimpleNamespace(decoder=lambda value: value)
        model.tf = SimpleNamespace(
            constant=lambda value: value, convert_to_tensor=lambda value: value
        )
        model.model = lambda _image: (tokens, scores)
        model.identity = {
            "fingerprint": "a" * 64,
            "versions": {"DECIMER": "controlled"},
        }
        model.device = "cpu"
        with TemporaryDirectory(prefix="printed-generation-") as temporary:
            image = Path(temporary) / "generated.png"
            Image.new("RGB", (2, 2), "white").save(image)
            return model.predict(str(image))

    def test_complete_output_preserves_tokens_and_same_raw_smiles(self):
        words = ["<start>", "C", "C", "O", "<end>"]
        result = self.predict(words)
        self.assertEqual(result["smiles"], "CCO")
        self.assertEqual(result["generation"]["tokens"], words)
        self.assertEqual(result["generation"]["status"], "complete")
        self.assertIsNone(result["generation"]["reason"])

    def test_parseable_but_unterminated_prediction_is_not_complete(self):
        words = ["<start>", "C", "C", "O"]
        result = self.predict(words)
        self.assertEqual(
            result["smiles"], "CCO", "Do not lose or repair the raw prediction"
        )
        self.assertEqual(result["generation"]["tokens"], words)
        self.assertEqual(result["generation"]["status"], "incomplete")
        self.assertEqual(result["generation"]["reason"], "missing_end")

    def test_unterminated_last_content_score_is_not_dropped_as_an_end_token(self):
        result = self.predict(["<start>", "C", "C", "O"], [0, 0.99, 0.98, 0.01])
        self.assertEqual(result["token_confidence"]["minimum"], 0.01)
        self.assertAlmostEqual(
            result["token_confidence"]["mean"], (0.99 + 0.98 + 0.01) / 3
        )

    def test_end_token_confidence_is_not_a_chemical_token_score(self):
        result = self.predict(["<start>", "C", "O", "<end>"], [0, 0.99, 0.98, 0.01])
        self.assertEqual(result["token_confidence"]["minimum"], 0.98)

    def test_confidence_alignment_failure_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "align"):
            self.predict(["<start>", "C", "O", "<end>"], [0.8, 0.9])

    def test_missing_start_or_embedded_special_tokens_cannot_be_erased_into_success(
        self,
    ):
        for words in (
            ["C", "O", "<end>"],
            ["<start>", "C", "<end>", "O", "<end>"],
            ["<start>", "C", "<start>", "O", "<end>"],
        ):
            with self.subTest(words=words):
                result = self.predict(words)
                self.assertEqual(result["generation"]["tokens"], words)
                self.assertEqual(result["generation"]["status"], "incomplete")

    def test_empty_content_is_not_a_complete_prediction(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.predict(["<start>", "<end>"])
