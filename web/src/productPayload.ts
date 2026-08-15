export type ProductPayloadValues = {
  name: string;
  brand: string;
  model: string;
  category: string;
  material: string;
  color: string;
  description: string;
};

type ProductCreatePayload = {
  name: string;
  brand: string;
  model?: string;
  category?: string;
  material?: string;
  color?: string;
  description?: string;
};

function text(value: string | undefined): string {
  return String(value ?? "").trim();
}

function assignIfPresent(payload: ProductCreatePayload, key: keyof ProductCreatePayload, value: string) {
  const cleaned = text(value);
  if (cleaned) {
    Object.assign(payload, { [key]: cleaned });
  }
}

export function buildProductCreatePayload(values: ProductPayloadValues): ProductCreatePayload {
  const payload: ProductCreatePayload = {
    name: text(values.name),
    brand: text(values.brand),
  };

  assignIfPresent(payload, "model", values.model);
  assignIfPresent(payload, "category", values.category);
  assignIfPresent(payload, "material", values.material);
  assignIfPresent(payload, "color", values.color);
  assignIfPresent(payload, "description", values.description);

  return payload;
}
