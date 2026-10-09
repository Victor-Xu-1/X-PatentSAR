"""One shared numeric domain and conserved molecule/observation chart counts."""

from __future__ import annotations

from decimal import Decimal, localcontext

from .errors import SARInputError
from .study_statistics import proven_strong, strength_band
from .values import Value, grade_ranks, parse_value


class DistributionContext:
    """Parse each source observation once; group charts reuse this exact scale.

    Observation bins preserve every raw repeat. Molecule bins form a disjoint
    partition: conflicting/partly missing repeats cannot count in two grades.
    Source-only molecules contribute to missing membership, not fake readings.
    """

    def __init__(self, observations: dict, policy: dict, assessments: dict):
        self.observations, self.policy, self.assessments = (
            observations,
            policy,
            assessments,
        )
        self.ranks = grade_ranks(policy.get("grade_order", []))
        self.values: dict[str, list[Value]] = {}
        scalars: list[Decimal] = []
        for identifier, records in observations.items():
            parsed = []
            for record in records:
                try:
                    value = parse_value(record["value"], self.ranks)
                except SARInputError:
                    value = Value("unsupported")
                parsed.append(value)
                if value.kind == "scalar":
                    scalars.append(value.numeric_bounds()[0])
            self.values[identifier] = parsed
        self.low: Decimal | None
        self.high: Decimal | None
        self.low, self.high = (min(scalars), max(scalars)) if scalars else (None, None)
        # Bound-preserving Decimal arithmetic, including very close supported
        # values. A 50-digit display precision cannot define scientific bins.
        self.precision = max(
            50,
            max((len(value.as_tuple().digits) for value in scalars), default=1)
            + max((value.adjusted() for value in scalars), default=0)
            - min((value.adjusted() for value in scalars), default=0)
            + 24,
        )
        self.width: Decimal | None = None
        self.numeric: list[str] = []
        with localcontext() as context:
            context.prec = self.precision
            if self.low is not None and self.high is not None:
                if self.low == self.high:
                    self.numeric = [str(self.low)]
                else:
                    self.width = (self.high - self.low) / 8
                    self.numeric = [
                        f"[{self.low + self.width * index},{self.low + self.width * (index + 1)}{']' if index == 7 else ')'}"
                        for index in range(8)
                    ]

    def matches(self, observations, policy, assessments):
        return (
            self.observations is observations
            and self.policy is policy
            and self.assessments is assessments
        )

    def _key(self, value: Value) -> tuple[str, str]:
        if (
            self.policy.get("strength_method") == "tenth_decade"
            and not self.ranks
            and value.kind in {"scalar", "interval"}
        ):
            return "strength", strength_band(value, self.policy, self.ranks)
        if value.kind == "ordinal":
            if value.grade is None:
                raise SARInputError("study_distribution_grade")
            return "ordinal", value.grade
        if value.kind == "scalar":
            if self.low is None or not self.numeric:
                raise SARInputError("study_distribution_domain")
            with localcontext() as context:
                context.prec = self.precision
                index = (
                    min(7, int((value.numeric_bounds()[0] - self.low) / self.width))
                    if self.width
                    else 0
                )
                return "numeric", self.numeric[index]
        if value.kind == "interval":
            strong = proven_strong(value, self.policy, self.ranks) is True
            return (
                "interval",
                "proved strong bound" if strong else "interval / censored",
            )
        return value.kind, value.kind

    def _member_key(self, values, state=None):
        if not values or all(value.kind == "missing" for value in values):
            return "missing", "missing"
        if (
            self.policy.get("strength_method") == "tenth_decade"
            and not self.ranks
            and state is not None
        ):
            return "strength", state.get("band", "unclassified")
        if len(set(values)) == 1:
            return self._key(values[0])
        if any(value.kind == "missing" for value in values):
            return "unresolved", "partial measurements"
        return "unresolved", "conflicting measurements"

    def _seeds(self):
        return [
            *(
                [
                    ("strength", tier)
                    for tier in ("strong", "medium", "weak", "unclassified")
                ]
                if self.policy.get("strength_method") == "tenth_decade"
                and not self.ranks
                else []
            ),
            *[("ordinal", grade) for grade in self.ranks],
            *(
                []
                if self.policy.get("strength_method") == "tenth_decade"
                and not self.ranks
                else [("numeric", label) for label in self.numeric]
            ),
            ("interval", "proved strong bound"),
            ("interval", "interval / censored"),
            ("missing", "missing"),
            ("unsupported", "unsupported"),
            ("unresolved", "partial measurements"),
            ("unresolved", "conflicting measurements"),
        ]

    def for_members(self, members: list[str]) -> dict:
        if len(set(members)) != len(members) or any(
            identifier not in self.values or identifier not in self.assessments
            for identifier in members
        ):
            raise SARInputError("study_distribution_membership")
        buckets = {
            key: {
                "label": key[1],
                "kind": key[0],
                "observations": 0,
                "molecules": 0,
                "strong": False,
            }
            for key in self._seeds()
        }
        all_strong: dict[tuple[str, str], bool] = {}
        for identifier in members:
            values = self.values[identifier]
            for value in values:
                key = self._key(value)
                buckets[key]["observations"] += 1
                supported = value.kind in {"ordinal", "scalar", "interval"}
                all_strong[key] = (
                    all_strong.get(key, True)
                    and supported
                    and proven_strong(value, self.policy, self.ranks) is True
                )
            key = self._member_key(values, self.assessments[identifier])
            buckets[key]["molecules"] += 1
        output = []
        for key, bucket in buckets.items():
            if (
                not bucket["observations"]
                and not bucket["molecules"]
                and key[0] not in {"ordinal", "numeric", "strength"}
            ):
                continue
            bucket["strong"] = (
                key[1] == "strong"
                if key[0] == "strength"
                else self.ranks.get(key[1]) == 0
                if key[0] == "ordinal"
                else all_strong.get(key, False)
            )
            output.append(bucket)
        missing = sum(
            self._member_key(self.values[identifier], self.assessments[identifier])[0]
            == "missing"
            for identifier in members
        )
        observation_count = sum(len(self.values[identifier]) for identifier in members)
        if (
            sum(bucket["molecules"] for bucket in output) != len(members)
            or sum(bucket["observations"] for bucket in output) != observation_count
        ):
            raise SARInputError("study_distribution_conservation")
        return {
            "context_id": self.policy["context_id"],
            "bins": output,
            "observed_molecules": len(members) - missing,
            "observations": observation_count,
            "missing_molecules": missing,
            "unresolved_molecules": sum(
                self.assessments[item]["status"]
                in {"indeterminate", "context_mismatch"}
                for item in members
            ),
            "strong_molecules": sum(
                self.assessments[item]["strong"] for item in members
            ),
        }
