def extraction_confidence(
    fields_extracted: list[str],
    fields_attempted: list[str],
    model_response_finishtype: str = "end_turn",
) -> float:
    if not fields_attempted:
        return 0.0
    coverage = len(fields_extracted) / len(fields_attempted)
    finish_penalty = 0.1 if model_response_finishtype != "end_turn" else 0.0
    return max(0.0, min(1.0, coverage - finish_penalty))
