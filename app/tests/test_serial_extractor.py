from ygc.extractors.serial import (
    EXTRACTION_VERSION,
    extract_serial_candidates,
    select_serial,
)


def test_version_is_v3():
    assert (
        EXTRACTION_VERSION
        == "serial-v3"
    )


def test_serial_number_label():
    candidate = select_serial(
        "Vintage Fender. "
        "Serial number N056062. "
        "Excellent condition."
    )

    assert candidate
    assert (
        candidate.value
        == "N056062"
    )
    assert (
        candidate.confidence
        >= 0.9
    )


def test_s_n_label():
    candidate = select_serial(
        "Fender Telecaster "
        "S/N: 729321, "
        "original finish."
    )

    assert candidate
    assert (
        candidate.value
        == "729321"
    )


def test_sn_label():
    candidate = select_serial(
        "1965 Jaguar "
        "SN: L01372 "
        "Original case."
    )

    assert candidate
    assert (
        candidate.value
        == "L01372"
    )


def test_ser_abbreviation():
    candidate = select_serial(
        "Fender Jazzmaster "
        "ser. #54866, "
        "original case."
    )

    assert candidate
    assert (
        candidate.value
        == "54866"
    )


def test_serial_and_fon_do_not_confuse():
    candidate = select_serial(
        "Gibson Nick Lucas. "
        "Serial #83509; "
        "FON #9009."
    )

    assert candidate
    assert (
        candidate.value
        == "83509"
    )


def test_pot_code_not_selected_without_serial_label():
    assert (
        select_serial(
            "Pot code 1377612, "
            "neck date 3 MAY 76."
        )
        is None
    )


def test_year_alone_not_serial():
    assert (
        select_serial(
            "Serial: 1976"
        )
        is None
    )


def test_multiple_candidates():
    candidates = (
        extract_serial_candidates(
            "S/N: 123456. "
            "Serial number ABC999."
        )
    )

    assert (
        len(candidates)
        >= 2
    )


def test_trailing_weight_is_trimmed():
    candidate = select_serial(
        "Serial: 524436WEIGHT "
        "10LB 3oz"
    )

    assert candidate
    assert (
        candidate.value
        == "524436"
    )


def test_spaced_prefix_is_normalized():
    candidate = select_serial(
        "Serial number "
        "L 75650 "
        "Weight: 3.5kg"
    )

    assert candidate
    assert (
        candidate.value
        == "L75650"
    )


def test_prose_after_serial_number_is_rejected():
    assert (
        select_serial(
            "This Jazzmaster has "
            "a serial number "
            "that dates to 1964."
        )
        is None
    )

    assert (
        select_serial(
            "The serial number "
            "dates it at 1959."
        )
        is None
    )

    assert (
        select_serial(
            "The serial number "
            "dates it to 1969."
        )
        is None
    )


def test_masked_serial_is_rejected():
    assert (
        select_serial(
            "Serial number 31xxx"
        )
        is None
    )

    assert (
        select_serial(
            "Serial: L6XXXX"
        )
        is None
    )


def test_double_dash_prose_suffix_is_trimmed():
    candidate = select_serial(
        "Serial: "
        "73178142--YOUR "
        "guitar includes a case."
    )

    assert candidate
    assert (
        candidate.value
        == "73178142"
    )


def test_headstock_suffix_is_trimmed():
    candidate = select_serial(
        "The neck plate bears "
        "serial number: "
        "L53450.HEADSTOCK"
    )

    assert candidate
    assert (
        candidate.value
        == "L53450"
    )


def test_later_valid_serial_beats_earlier_prose():
    candidate = select_serial(
        "Serial Number: 269566. "
        "The serial number "
        "dates to 1965."
    )

    assert candidate
    assert (
        candidate.value
        == "269566"
    )


def test_real_serial_hash_format():
    candidate = select_serial(
        "YEAR: 1966 "
        "SERIAL #: 145635 "
        "BODY WOOD: ALDER"
    )

    assert candidate
    assert (
        candidate.value
        == "145635"
    )
