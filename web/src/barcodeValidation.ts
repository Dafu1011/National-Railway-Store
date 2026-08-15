export type BarcodeValidationResponse = {
  can_confirm: boolean;
  error_code: string | null;
  normalized_value: string;
  calculated_check_digit: string | null;
  suggested_full_value: string | null;
};

export function barcodeValidationMessage(result: BarcodeValidationResponse): string {
  if (result.error_code === "BARCODE_CHECK_DIGIT_SUGGESTED" && result.suggested_full_value) {
    return `EAN-13 缺少校验位，已计算完整条码：${result.suggested_full_value}。请确认后再次点击生成。`;
  }
  if (result.error_code === "BARCODE_CHECK_DIGIT_INVALID" && result.calculated_check_digit) {
    return `条码校验位不正确，正确校验位应为：${result.calculated_check_digit}。`;
  }
  if (result.error_code === "BARCODE_LENGTH_INVALID") {
    return "条码长度不符合所选制式，请检查数字位数。";
  }
  if (result.error_code === "BARCODE_VALUE_INVALID") {
    return "条码只能填写数字，不能包含字母或其他符号。";
  }
  return result.error_code ?? "条码未通过确认。";
}

export function suggestedBarcodeValue(result: BarcodeValidationResponse): string | null {
  if (result.error_code === "BARCODE_CHECK_DIGIT_SUGGESTED" && result.suggested_full_value) {
    return result.suggested_full_value;
  }
  return null;
}
