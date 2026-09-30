export type ProjectPayloadValues = {
  name: string;
  companyName: string;
  manufacturerName: string;
  manufacturerAddress: string;
  productionDate: string;
  inspector: string;
  barcodeType: "EAN_13" | "EAN_8" | "UPC_A" | "CODE_128";
  productLogoEnabled?: boolean;
  productVolume?: "large" | "small";
};

export function buildProjectCreatePayload(values: ProjectPayloadValues, productId: string, normalizedBarcode: string) {
  return {
    product_id: productId,
    name: `${values.name} 五图项目`,
    style_config: {
      tone: "clean",
      provider: "configured-image-provider",
      product_logo_enabled: Boolean(values.productLogoEnabled),
    },
    certificate_config: {
      standard: "GB/T 29606",
      inspector: values.inspector,
      production_date: values.productionDate,
      company_name: values.companyName,
      manufacturer_name: values.manufacturerName,
      manufacturer_address: values.manufacturerAddress,
      product_volume: values.productVolume === "large" ? "large" : "small",
    },
    package_config: {
      box_material: "kraft",
      company_name: values.companyName,
      manufacturer_name: values.manufacturerName,
      manufacturer_address: values.manufacturerAddress,
    },
    detail_config: {},
    barcode: { barcode_type: values.barcodeType, raw_value: normalizedBarcode, confirmed: true },
  };
}
