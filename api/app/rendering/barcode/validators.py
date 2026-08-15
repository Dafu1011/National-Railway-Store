from dataclasses import dataclass
from enum import StrEnum


class BarcodeType(StrEnum):
    EAN_13 = "EAN_13"
    EAN_8 = "EAN_8"
    UPC_A = "UPC_A"
    CODE_128 = "CODE_128"


@dataclass(frozen=True)
class BarcodeValidationResult:
    barcode_type: BarcodeType
    raw_value: str
    normalized_value: str
    character_valid: bool
    length_valid: bool
    check_digit_valid: bool | None
    calculated_check_digit: str | None
    suggested_full_value: str | None
    can_confirm: bool
    error_code: str | None


def validate_barcode_value(barcode_type: BarcodeType, raw_value: str) -> BarcodeValidationResult:
    normalized = _normalize(raw_value)
    character_valid = normalized.isascii() and normalized.isdigit() and len(normalized) > 0

    if not character_valid:
        return _result(
            barcode_type,
            raw_value,
            normalized,
            character_valid=False,
            length_valid=False,
            check_digit_valid=None,
            calculated_check_digit=None,
            suggested_full_value=None,
            can_confirm=False,
            error_code="BARCODE_VALUE_INVALID",
        )

    if barcode_type == BarcodeType.EAN_13:
        return _validate_ean13(raw_value, normalized)
    if barcode_type == BarcodeType.EAN_8:
        return _validate_fixed_check_digit(barcode_type, raw_value, normalized, 8, _ean8_check_digit)
    if barcode_type == BarcodeType.UPC_A:
        return _validate_fixed_check_digit(barcode_type, raw_value, normalized, 12, _upca_check_digit)
    if barcode_type == BarcodeType.CODE_128:
        return _validate_code128(raw_value, normalized)

    return _result(
        barcode_type,
        raw_value,
        normalized,
        character_valid=True,
        length_valid=False,
        check_digit_valid=None,
        calculated_check_digit=None,
        suggested_full_value=None,
        can_confirm=False,
        error_code="BARCODE_TYPE_REQUIRED",
    )


def _validate_ean13(raw_value: str, normalized: str) -> BarcodeValidationResult:
    if len(normalized) == 12:
        check_digit = _ean13_check_digit(normalized)
        return _result(
            BarcodeType.EAN_13,
            raw_value,
            normalized,
            character_valid=True,
            length_valid=True,
            check_digit_valid=None,
            calculated_check_digit=check_digit,
            suggested_full_value=f"{normalized}{check_digit}",
            can_confirm=False,
            error_code="BARCODE_CHECK_DIGIT_SUGGESTED",
        )
    if len(normalized) != 13:
        return _length_error(BarcodeType.EAN_13, raw_value, normalized)

    expected = _ean13_check_digit(normalized[:12])
    valid = normalized[-1] == expected
    return _result(
        BarcodeType.EAN_13,
        raw_value,
        normalized,
        character_valid=True,
        length_valid=True,
        check_digit_valid=valid,
        calculated_check_digit=expected,
        suggested_full_value=None,
        can_confirm=valid,
        error_code=None if valid else "BARCODE_CHECK_DIGIT_INVALID",
    )


def _validate_fixed_check_digit(
    barcode_type: BarcodeType,
    raw_value: str,
    normalized: str,
    required_length: int,
    calculator,
) -> BarcodeValidationResult:
    if len(normalized) != required_length:
        return _length_error(barcode_type, raw_value, normalized)

    expected = calculator(normalized[:-1])
    valid = normalized[-1] == expected
    return _result(
        barcode_type,
        raw_value,
        normalized,
        character_valid=True,
        length_valid=True,
        check_digit_valid=valid,
        calculated_check_digit=expected,
        suggested_full_value=None,
        can_confirm=valid,
        error_code=None if valid else "BARCODE_CHECK_DIGIT_INVALID",
    )


def _validate_code128(raw_value: str, normalized: str) -> BarcodeValidationResult:
    max_digits = 32
    length_valid = 1 <= len(normalized) <= max_digits
    return _result(
        BarcodeType.CODE_128,
        raw_value,
        normalized,
        character_valid=True,
        length_valid=length_valid,
        check_digit_valid=None,
        calculated_check_digit=None,
        suggested_full_value=None,
        can_confirm=length_valid,
        error_code=None if length_valid else "BARCODE_LENGTH_INVALID",
    )


def _normalize(value: str) -> str:
    return value.replace(" ", "").replace("-", "")


def _ean13_check_digit(first_12_digits: str) -> str:
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(first_12_digits))
    return str((10 - (total % 10)) % 10)


def _ean8_check_digit(first_7_digits: str) -> str:
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(first_7_digits))
    return str((10 - (total % 10)) % 10)


def _upca_check_digit(first_11_digits: str) -> str:
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(first_11_digits))
    return str((10 - (total % 10)) % 10)


def _length_error(barcode_type: BarcodeType, raw_value: str, normalized: str) -> BarcodeValidationResult:
    return _result(
        barcode_type,
        raw_value,
        normalized,
        character_valid=True,
        length_valid=False,
        check_digit_valid=None,
        calculated_check_digit=None,
        suggested_full_value=None,
        can_confirm=False,
        error_code="BARCODE_LENGTH_INVALID",
    )


def _result(
    barcode_type: BarcodeType,
    raw_value: str,
    normalized_value: str,
    *,
    character_valid: bool,
    length_valid: bool,
    check_digit_valid: bool | None,
    calculated_check_digit: str | None,
    suggested_full_value: str | None,
    can_confirm: bool,
    error_code: str | None,
) -> BarcodeValidationResult:
    return BarcodeValidationResult(
        barcode_type=barcode_type,
        raw_value=raw_value,
        normalized_value=normalized_value,
        character_valid=character_valid,
        length_valid=length_valid,
        check_digit_valid=check_digit_valid,
        calculated_check_digit=calculated_check_digit,
        suggested_full_value=suggested_full_value,
        can_confirm=can_confirm,
        error_code=error_code,
    )
