from ygc.extractors.normalization import (
    normalize_manufacturer,
    normalize_model,
    normalize_serial,
)


def match_or_create(
    repo,
    manufacturer,
    model,
    serial_number,
    finish=None,
    year=None,
):
    normalized_maker = (
        normalize_manufacturer(
            manufacturer
        )
    )
    normalized_model = (
        normalize_model(
            model
        )
    )
    normalized_serial = (
        normalize_serial(
            serial_number
        )
    )

    if (
        not normalized_maker
        or not normalized_serial
    ):
        raise ValueError(
            "manufacturer and "
            "serial_number are required"
        )

    existing = (
        repo.find_individual(
            normalized_maker,
            normalized_model,
            normalized_serial,
        )
    )

    if existing:
        individual_id = int(
            existing["id"]
        )

        repo.update_individual_metadata(
            individual_id,
            model=model,
            finish=finish,
            year=year,
        )

        return individual_id

    return repo.create_individual(
        manufacturer,
        model,
        serial_number,
        normalized_maker,
        normalized_model,
        normalized_serial,
        finish=finish,
        year=year,
    )
