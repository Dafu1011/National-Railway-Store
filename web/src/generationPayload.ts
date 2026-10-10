export const DETAIL_SCENE_FIELDS = [
  { name: "scene1", key: "scene_1", label: "场景1（选填）" },
  { name: "scene2", key: "scene_2", label: "场景2（选填）" },
  { name: "scene3", key: "scene_3", label: "场景3（选填）" },
  { name: "scene4", key: "scene_4", label: "场景4（选填）" },
] as const;

export type DetailSceneValues = Partial<Record<(typeof DETAIL_SCENE_FIELDS)[number]["name"], string>>;

export type ProjectPayloadValues = DetailSceneValues & {
  name: string;
  companyName: string;
  manufacturerName: string;
  manufacturerAddress?: string;
  productionDate: string;
  inspector: string;
  barcodeType: "EAN_13" | "EAN_8" | "UPC_A" | "CODE_128";
  productLogoEnabled?: boolean;
  productVolume?: "large" | "small" | "car";
};

export function buildProjectCreatePayload(values: ProjectPayloadValues, productId: string, normalizedBarcode: string) {
  const manufacturerAddress = values.manufacturerAddress?.trim();
  const sceneInputs = Object.fromEntries(
    DETAIL_SCENE_FIELDS.map(({ name, key }) => [key, values[name]?.trim() ?? ""]).filter(([, value]) => value),
  );
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
      ...(manufacturerAddress ? { manufacturer_address: manufacturerAddress } : {}),
      product_volume: values.productVolume === "large" || values.productVolume === "car" ? values.productVolume : "small",
    },
    package_config: {
      box_material: "kraft",
      company_name: values.companyName,
      manufacturer_name: values.manufacturerName,
      ...(manufacturerAddress ? { manufacturer_address: manufacturerAddress } : {}),
    },
    detail_config: Object.keys(sceneInputs).length ? { scene_inputs: sceneInputs } : {},
    barcode: { barcode_type: values.barcodeType, raw_value: normalizedBarcode, confirmed: true },
  };
}
