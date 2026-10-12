"""Current setup metadata, separate from captured scientific input/report DTOs."""

from pydantic import Field

from ..activity_rank_models import RankDirection
from ..dto import DTO
from .study_models import StudyProfile


class IndicatorDefault(DTO):
    direction: RankDirection
    rule: str = Field(min_length=1, max_length=64)


class IndicatorProfile(StudyProfile):
    policy_defaults: dict[str, IndicatorDefault] = Field(max_length=1000)
    metric_defaults: dict[str, IndicatorDefault] = Field(max_length=1000)
