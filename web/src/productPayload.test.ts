import { describe, expect, it } from "vitest";
import { buildProductCreatePayload, type ProductPayloadValues } from "./productPayload";

const baseValues: ProductPayloadValues = {
  name: "智枫蓝牙耳机",
  brand: "智枫",
  model: "",
  category: "",
  material: "",
  color: "",
  description: "",
};

describe("product payload", () => {
  it("omits optional product fields when the user leaves them blank", () => {
    const payload = buildProductCreatePayload(baseValues);

    expect(payload).toEqual({
      name: "智枫蓝牙耳机",
      brand: "智枫",
    });
    expect(payload).not.toHaveProperty("specs");
  });

  it("never sends specifications to the backend", () => {
    const payload = buildProductCreatePayload({
      ...baseValues,
      specificationKey: "阻抗",
      specificationValue: "32",
      specificationUnit: "Ω",
    } as ProductPayloadValues);

    expect(payload).not.toHaveProperty("specs");
  });

  it("sends only user-entered optional product fields", () => {
    const payload = buildProductCreatePayload({
      ...baseValues,
      model: "ZF-CUP-800",
      material: "聚乙烯",
    });

    expect(payload).toEqual({
      name: "智枫蓝牙耳机",
      brand: "智枫",
      model: "ZF-CUP-800",
      material: "聚乙烯",
    });
  });
});
