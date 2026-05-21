"""Config dataclasses and validation."""
import dataclasses


@dataclasses.dataclass
class ValidatedConfig:
    desired_gics: list[int]
    rejected_gics: list[int]
    reject_words: list[str]
    ai_endpoint: str
    ai_api_key: str
    no_ai: bool


def validate_config(config: dict, no_ai: bool) -> ValidatedConfig:
    """Validate config. Raises ValueError if config is invalid."""
    desired_gics = [int(g) for g in config.get("desired_gics", []) if g]
    rejected_gics = [int(g) for g in config.get("rejected_gics", []) if g]
    reject_words = config.get("reject_words", [])
    ai_endpoint = config.get("ai", {}).get("endpoint", "")
    ai_api_key = config.get("ai", {}).get("api_key", "")

    if desired_gics:
        if not no_ai:
            # GICS filtering is requested but --no-ai flag not set
            # AI is needed for GICS classification
            if not ai_endpoint:
                raise ValueError("desired_gics is set but ai.endpoint is empty — cannot classify GICS")
        # else: --no-ai flag means skip GICS filter entirely, so no error even if AI is missing
    # if desired_gics is empty: don't filter by GICS, don't care about AI
    # if desired_gics is not empty and no_ai is True: skip GICS filter, no error

    return ValidatedConfig(
        desired_gics=desired_gics,
        rejected_gics=rejected_gics,
        reject_words=reject_words,
        ai_endpoint=ai_endpoint,
        ai_api_key=ai_api_key,
        no_ai=no_ai,
    )

