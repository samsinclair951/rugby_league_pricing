FIXTURE_DATE_CORRECTIONS = {
    "38787": "2019-05-03",
    "38786": "2019-05-03",
    "38840": "2019-07-19",
    "44917": "2020-10-01",
    "45356": "2021-05-29",
    "54329": "2023-07-27",
    "58410": "2023-09-01",
}


def apply_fixture_date_corrections(
    matches: list[dict],
) -> list[dict]:
    for match in matches:
        source_match_id = match.get(
            "source_match_id"
        )

        if source_match_id is None:
            continue

        corrected_date = (
            FIXTURE_DATE_CORRECTIONS.get(
                str(source_match_id)
            )
        )

        if corrected_date is not None:
            match["match_date"] = corrected_date

    return matches