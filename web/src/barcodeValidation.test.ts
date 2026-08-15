import { describe, expect, it } from "vitest";
import { barcodeValidationMessage, suggestedBarcodeValue } from "./barcodeValidation";

describe("barcode validation UX", () => {
  it("formats EAN-13 check digit suggestions as a human readable confirmation message", () => {
    const result = {
      can_confirm: false,
      error_code: "BARCODE_CHECK_DIGIT_SUGGESTED",
      normalized_value: "400638133393",
      calculated_check_digit: "1",
      suggested_full_value: "4006381333931",
    };

    expect(barcodeValidationMessage(result)).toContain("EAN-13 缺少校验位");
    expect(barcodeValidationMessage(result)).toContain("4006381333931");
    expect(suggestedBarcodeValue(result)).toBe("4006381333931");
  });
});
