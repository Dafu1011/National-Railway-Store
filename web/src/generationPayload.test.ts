import { describe, expect, it } from "vitest";
import { buildProjectCreatePayload } from "./generationPayload";

describe("generation payload", () => {
  it("sends manufacturer and address to package config", () => {
    const payload = buildProjectCreatePayload(
      {
        name: "智枫保温杯",
        companyName: "智枫科技",
        manufacturerName: "智枫科技",
        manufacturerAddress: "浙江省杭州市西湖区智枫路88号",
        productionDate: "2026-07-27",
        inspector: "QC-01",
        barcodeType: "EAN_13",
      },
      "product-id",
      "6903244675147",
    );

    expect(payload.package_config).toMatchObject({
      box_material: "kraft",
      manufacturer_name: "智枫科技",
      manufacturer_address: "浙江省杭州市西湖区智枫路88号",
    });
  });

  it("sends production manufacturer and factory address to the certificate config", () => {
    const payload = buildProjectCreatePayload(
      {
        name: "智枫保温杯",
        companyName: "智枫科技",
        manufacturerName: "智枫生产厂家",
        manufacturerAddress: "浙江省杭州市西湖区智枫路88号",
        productionDate: "2026-07-27",
        inspector: "QC-01",
        barcodeType: "EAN_13",
      },
      "product-id",
      "6903244675147",
    );

    expect(payload.certificate_config).toMatchObject({
      manufacturer_name: "智枫生产厂家",
      manufacturer_address: "浙江省杭州市西湖区智枫路88号",
    });
  });

  it("does not send fixed detail selling points that the user did not enter", () => {
    const payload = buildProjectCreatePayload(
      {
        name: "智枫蓝牙鼠标",
        companyName: "智枫科技",
        manufacturerName: "智枫科技",
        manufacturerAddress: "吉林省长春市南关区幸福街888号",
        productionDate: "2026-08-15",
        inspector: "QC-01",
        barcodeType: "EAN_13",
      },
      "product-id",
      "6903244675147",
    );

    expect(payload.detail_config).toEqual({});
  });
});
