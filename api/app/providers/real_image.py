from __future__ import annotations

from collections import deque
from datetime import date
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.rendering.barcode.images import render_barcode_image
from app.rendering.barcode.validators import BarcodeType
from app.providers.kele import KeleGptImage2Provider


OUTPUT_SPECS: tuple[tuple[str, int, int], ...] = (
    ("main", 800, 800),
    ("certificate", 800, 800),
    ("package", 800, 800),
    ("detail", 800, 2400),
    ("scene", 800, 800),
)
DEFAULT_EDIT_SIZE = "1024x1024"


@dataclass(frozen=True)
class GeneratedImage:
    output_type: str
    width: int
    height: int
    path: Path


class KeleFiveImagePipeline:
    name = "kele-gpt-image-2"

    def __init__(self, provider: KeleGptImage2Provider, font_path: str = "", edit_size: str = DEFAULT_EDIT_SIZE):
        self.provider = provider
        self.font_path = font_path
        self.edit_size = edit_size.strip() or DEFAULT_EDIT_SIZE

    def generate_five_images(
        self,
        *,
        output_dir: Path,
        job_id: str,
        product: dict[str, Any],
        project: dict[str, Any],
        source_image_path: Path,
        reference_image_paths: dict[str, Path] | None = None,
    ) -> list[GeneratedImage]:
        job_dir = output_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        generated: list[GeneratedImage] = []
        reference_image_paths = reference_image_paths or {}

        for output_type, width, height in OUTPUT_SPECS:
            if output_type == "detail":
                module_images: list[Image.Image] = []
                for prompt in _detail_module_prompts(product):
                    raw = self.provider.edit_image(
                        prompt=prompt,
                        size=self.edit_size,
                        image_paths=[source_image_path],
                    )
                    module_images.append(_open_provider_image(raw))
                image = _build_detail_page(module_images, product, project, self.font_path)
                path = job_dir / f"{output_type}.png"
                image.save(path, format="PNG")
                generated.append(GeneratedImage(output_type=output_type, width=image.width, height=image.height, path=path))
                continue

            image_paths = [source_image_path]
            if output_type in {"certificate", "package"} and reference_image_paths.get(output_type):
                image_paths.append(reference_image_paths[output_type])
            raw = self.provider.edit_image(
                prompt=_prompt_for(
                    output_type,
                    product,
                    {
                        **project,
                        "has_certificate_reference": output_type == "certificate" and len(image_paths) > 1,
                        "has_package_reference": output_type == "package" and len(image_paths) > 1,
                    },
                ),
                size=self.edit_size,
                image_paths=image_paths,
            )
            image = _open_provider_image(raw)
            image = _normalize_size(image, width, height, background="white" if output_type in {"main", "certificate", "package"} else "#f3f4f6")
            if output_type == "certificate":
                image = _overlay_certificate_qc_stamp(image, project, self.font_path)
            path = job_dir / f"{output_type}.png"
            image.save(path, format="PNG")
            generated.append(GeneratedImage(output_type=output_type, width=image.width, height=image.height, path=path))

        return generated


def _prompt_for(output_type: str, product: dict[str, Any], project: dict[str, Any] | None = None) -> str:
    name = product.get("name", "the uploaded product")
    category = str(product.get("category", "") or "")
    project = project or {}
    package_config = project.get("package_config", {}) if isinstance(project.get("package_config", {}), dict) else {}
    certificate_config = project.get("certificate_config", {}) if isinstance(project.get("certificate_config", {}), dict) else {}
    package_manufacturer = (
        package_config.get("manufacturer_name")
        or package_config.get("company_name")
        or _company_name(product, certificate_config)
    )
    package_address = package_config.get("manufacturer_address") or package_config.get("address") or ""
    package_rows = _package_information_rows(product, package_manufacturer, package_address)
    package_brand = _clean_text(product.get("brand", ""))
    package_brand_wordmark = (
        "Package brand rendering rule: render the brand value only as a large standalone brand wordmark on the package front; "
        "brand value only, never render the field label Brand, brand, 品牌, or 品牌： before it. "
        "Render it as large standard printed Chinese brand text, plain regular-weight Songti/Heiti-style characters, not artistic typography, not calligraphy, not brush style, not decorative typography, not a stylized logo redesign. "
        "The standalone brand wordmark must be much larger than the ordinary information rows and occupy more pixels. character correctness and complete stroke structure are more important than sharpness; slight softness or mild ink blur is acceptable. "
        "Do not squeeze, merge, simplify, substitute, pseudo-render, split, connect, warp, or decorate any brand character. Preserve every radical, stroke order impression, inner gap, and complete Chinese stroke structure as faithfully as possible. "
        f"Standalone package brand wordmark text: {package_brand}. "
        if package_brand
        else "No standalone package brand wordmark is needed because the user did not enter a brand. "
    )
    package_fact_rows = [
        ("product name", product.get("name", "")),
        ("specification model", product.get("model", "")),
        ("manufacturer", package_manufacturer),
        ("address", package_address),
        ("barcode type", project.get("barcode_type", "")),
        ("barcode digits", project.get("barcode_value", "")),
    ]
    package_text_layout = (
        "Candidate package side information area, printed directly by the image model as native ink on the visible package side panel only, "
        "using only non-empty user-entered ordinary information rows in this Chinese label order, excluding the brand row because the brand is rendered separately as the large wordmark: "
        f"{_format_chinese_rows(package_rows)} "
    )
    package_facts = (
        f"Candidate package information to print directly on the package surface, from non-empty user-entered fields only: "
        f"{_format_fact_rows(package_fact_rows)} "
    )
    certificate_manufacturer = certificate_config.get("manufacturer_name") or _company_name(product, certificate_config)
    certificate_address = certificate_config.get("manufacturer_address") or certificate_config.get("address") or package_address
    certificate_facts = (
        "Candidate certificate information to print directly on the certificate card, from user-entered fields where available: "
        f"brand: {product.get('brand', '')}; "
        f"product name: {product.get('name', '')}; "
        f"model/specification: {product.get('model', '')}; "
        f"production date: {certificate_config.get('production_date', '')}; "
        f"manufacturer: {certificate_manufacturer}; "
        f"factory address: {certificate_address}; "
        f"barcode type: {project.get('barcode_type', '')}; "
        f"barcode digits: {project.get('barcode_value', '')}. "
    )
    certificate_reference_instruction = (
        "A certificate reference image is provided as an additional reference image. Use the certificate reference only for certificate card style, border style, card material, field layout rhythm, and inspector-area layout style; do not copy its old product data, old barcode digits, old date, old inspector value, camera composition, or product pose. "
        if project.get("has_certificate_reference")
        else "No certificate reference image is provided; generate a simple realistic certificate style based on the product and user-entered certificate fields. "
    )
    has_package_reference = bool(project.get("has_package_reference"))
    package_reference_instruction = (
        "A package reference image is provided as an additional reference image. The package reference image is the highest-priority packaging-style reference. The current uploaded product and user-entered specification are higher priority than copying the reference package literally. Use the package reference only for packaging style: box type, form factor, handle or carry strap, color palette, graphic density, panel decoration, material finish, flap or lid construction, surface texture, and print-layout rhythm; do not copy its old product data, old barcode digits, old brand, old size, background, camera composition, or product pose. Keep the generated scene on the required pure white background even if the package reference image has a colored environment. Adapt the referenced package style to the current product category, product volume, product count, storage needs, and realistic retail packaging logic. If the reference package belongs to a different product category, borrow only its broad visual language and construction cues, then adjust package proportions, handle/carry structure, panel graphics, and decoration intensity so the final package looks designed for the current product itself; do not copy a packaging proportion, carry structure, visual motif, or premium/cartoon/fresh-food style that would make the final package look mismatched to the current product. "
        if has_package_reference
        else "No package reference image is provided; design a product-appropriate retail package based on the uploaded product structure and user-entered specification model. Choose the package box shape, material feel, color system, and graphic style from the product's real category and retail packing logic. Do not default to a generic brown package, tall narrow bottle box, high box, or plain shipping box unless that is the realistic package for this product. "
    )
    package_style_instruction = (
        "Follow the uploaded package reference for the package's visual style only. If the reference package has a colored printed surface, product illustration, logo zone, decorative panels, carry handle, glossy finish, matte printed finish, folded gift-box structure, or angled retail-box form, the generated package should visibly inherit those style traits while adapting them to the current product's realistic retail package shape, size, category, and specification, and while replacing all written product information with the current user's fields. "
        if has_package_reference
        else "Use a normal product-appropriate retail package style with realistic structure, lid or flap seams, subtle material texture, and proportions that fit the uploaded product. Make it designed retail packaging, not an oversized shipping package, not an appliance package, and not a decorative poster. "
    )
    package_front_geometry_instruction = (
        "Keep the package side information area and barcode readable on the visible package side panel. If the package reference uses an angled box perspective, preserve a similar natural retail-product perspective while keeping the side information area upright on its side panel and avoiding unreadable distortion. Do not force the package into a square-on brown-box layout when a reference package is provided. "
        if has_package_reference
        else "The package side panel must be clearly visible and stable enough for readable package printing. Keep the side information zone reasonably visible to the camera, with level side-panel text baselines and no excessive convergence, twisted panels, or unreadable perspective. "
    )
    package_side_instruction = (
        "Visible package side faces should follow the reference package's side style. If the reference has colored side panels, decorative graphics, side logos, pattern blocks, QR/barcode zones, or illustration continuation, keep that kind of side-panel design style while replacing old readable data with current user fields. "
        if has_package_reference
        else "The visible package side face should stay visually simple and consistent with the generated retail package style, with no random unrelated side icons, side logos, warning marks, or duplicate barcode blocks. "
    )
    package_barcode_position_instruction = (
        "The barcode must be directly below the side information area on the same visible package side panel, following normal retail package layout logic. The barcode and all information rows must remain fully visible, uncropped, unobstructed, and inside the same side panel. The package barcode must not be centered high, placed near the brand wordmark, placed on the front display area, or floating outside the package; it must sit on a real visible package side surface with enough quiet space around it. "
        if has_package_reference
        else "The barcode must be directly below the side information area on the same visible package side panel, following normal retail package layout logic. The barcode and all information rows must remain fully visible, uncropped, unobstructed, and inside the same side panel. The package barcode must not be centered high, placed near the brand wordmark, placed on the front display area, or floating outside the package; it must sit on a real visible package side surface with enough quiet space around it. "
    )
    package_physical_capacity_instruction = (
        "The package must be physically large enough to contain the uploaded product and every unit implied by the user-entered specification model. "
        "Treat quantity expressions in the specification model, such as 6 bottles, 6 pcs, x6, ×6, 500ml×6瓶, or one box of multiple units, as hard packing capacity requirements. "
        "Do not generate a package sized for only one unit when the specification model says multiple units. "
        "Package dimensions, internal volume, divider/spacing allowance, and external proportions must obey real packing physics: enough inner length, width, height, padding, grouping space, and closure clearance for the full quantity. "
        "The visible package must look larger than the product in every required loading direction, not merely taller in the image composition. "
        "For bottle, cup, can, jar, and drink products, the package internal height must be greater than the product height when packed upright, and its internal width and depth must also be large enough for the product diameter or body width plus realistic padding. "
        "If the product is shown standing beside the package, the package must not appear shorter, thinner, or too narrow to contain that product; the visible scale relationship must make it obvious that the product can fit inside the package. "
        "Package physical capacity has higher priority than reference package style, composition, beauty, and front display completeness. "
        "If the reference package is too small, too thin, too narrow, or shaped for a different quantity, keep only its broad visual style and scale the final package to the current product and specification quantity. "
    )
    package_capacity_plan = _package_capacity_plan(product)
    package_product_pose_instruction = _package_product_pose_instruction(product)
    reference_base = (
        "Use the uploaded product photo as the exact product reference. "
        "The uploaded product photo may be an angled, side, top-down, or non-front view; preserve the real visible product appearance from that view, including visible side geometry, foreshortening, label perspective, seam direction, cap/lid ellipse, logo position, and any occluded or partially visible surfaces. Do not force the product into a generic front-facing, perfectly symmetrical, or redesigned catalog view. When a new scene camera angle is required, re-project the same real product structure into that camera angle while keeping the uploaded-view identity and perspective clues consistent. "
        "All five generated image types must depict the same single uploaded product and preserve the same product style identity across marketplace main photo, certificate co-photo, package co-photo, detail page, and scene photo. Do not switch to a different SKU, package variant, colorway, flavor, label design, logo layout, cap shape, bottle shape, accessory set, or material finish between image types. "
        "User-entered product information is the source of truth for all readable product facts. For generated readable labels, package printing, certificate rows, and detail-page fact text, do not preserve or copy conflicting readable product facts from the uploaded product photo or package reference. If the visual source contains old or conflicting text, keep only the product appearance or package style and replace readable facts with the current user-entered information. "
        "Keep the product structure, color, material, proportions, wear, and surface texture consistent. "
        "Identify and keep only the actual sellable product body from the uploaded photo. Exclude display stands, support poles, bases, hooks, hangers, risers, background props, and any non-product objects even if they touch or hold the product in the source image. For headphones or earphones, the product body means only the headband, earcups, hinges, cushions, cable, controls, and other headphone parts; never include a mannequin head, stand, rack, pole, or base as part of the product. "
        "preserve existing physical markings: the exact visible logo, brand lettering, small badges, and surface markings from the uploaded product when visible, but do not invent new readable text. "
        "If the source product includes an R mark, circled R, or tiny registered trademark symbol beside the logo, that same tiny registered trademark symbol must appear in every generated product view where that side is visible. "
        "do not add parts, accessories, packaging, labels, or quantities that are not visible in the uploaded image. "
        "Do not add new machine-readable codes, watermarks, certificate-like words, or random labels. "
    )
    clean_product_surface = (
        "Keep the product surface clean, continuous, and materially plausible. The white marks to avoid are not acceptable texture: they are clipped specular highlights, blown-out pure-white patches, and mask-like cutout residue. No white speckles, no white noise dots, no salt-and-pepper artifacts, no paint-chip-like white patches, no masking residue, no cutout scars, no random bright flecks, no broken highlights, no large pure-white holes inside the product body, and no white halo along the product edge. For light gray or white products, preserve soft gray tonal detail and separation from the white background; do not clip the surface to pure #ffffff. Real photographic highlights are allowed only when smooth, coherent, feathered, low-to-moderate contrast, and following the product material and lighting direction. "
    )
    catalog_exposure_control = (
        "Use the same restrained exposure discipline as the certificate co-photo: soft natural daylight from the left and upper-left, one consistent light source, no harsh studio flash, no high-key overexposure, no blown-out glossy bands, and no pure-white clipping on the product surface. The product may be light gray or white, but it must still show continuous midtone detail, cushion texture, seams, bevels, rim edges, hinge transitions, and material curvature. Keep highlights controlled and soft; do not let any product surface, edge, cable, headband, earcup, or microphone turn into a pure #ffffff patch or merge into the white background. A very light natural contact shadow is allowed because product shape fidelity and readable edges are more important than removing every shadow. "
    )
    real_photo = (
        "The output must look like a real camera photograph, not CGI, not a 3D render, not illustration, not a flat mockup. "
        "Use believable lens perspective, realistic contact with the surface, real material texture, slight photographic imperfections, and normal depth of field. "
        "Use clean product-catalog lighting with minimal or no visible floor shadow under the product. "
    )
    prompts = {
        "main": (
            reference_base
            + real_photo
            + clean_product_surface
            + catalog_exposure_control
            + f"Create a marketplace product main photo for {name}. White sweep or white tabletop background, only the sellable product itself visible, full product visible, product fills most of the frame, natural studio photo lighting, minimal or no visible floor shadow. Do not show source-photo display hardware or auxiliary objects; if the uploaded product is photographed on a stand, remove the stand and reconstruct only the product body in a natural standalone product pose."
        ),
        "certificate": (
            reference_base
            + real_photo
            + clean_product_surface
            + "Photograph the product as a realistic phone-style angled top-down snapshot. Use the uploaded product image as the only product reference, 以用户上传的商品图片作为唯一商品参考, and create a 真实自然的手机随手拍 product co-photo. Output must be exactly 800x800 pixels, 1:1 square, 800x800, 1:1 square, exactly 800x800. "
            "The scene is a pure seamless #ffffff white background plus a pure white matte support surface, using the support as a single flat, level, uncurved horizontal plane and horizontal tabletop plane. The background and tabletop should visually merge naturally, with no visible horizon line, no horizon line, no wall, no window curtain, no visible table edge, no floor, no table edge, no curved sweep backdrop, no bent paper, no studio cove, no grey wall, no floor, and no environmental clutter. The white area should occupy most of the frame with large pure white negative space across the lower half; the lower half must keep a large clean pure-white negative-space area. The whole scene must feel like a product casually photographed on a clean white tabletop, not like a cutout pasted onto a background. keep a pure-white background while allowing one realistic soft contact shadow that follows the product base and one consistent light source; a very light natural contact shadow is allowed when it looks physically correct. "
            "Keep the white plane truly clean and bright pure white: no gray gradient, no off-white texture, no speckled background noise, no dirty texture, no mottled paper grain, no beige stains, no dirty shadow patches, no gray or beige shadow patch around the product, no concave or convex support surface, and no studio sweep shading. A very light and soft natural contact shadow is allowed only where needed to anchor the product physically to the white tabletop. Do not create any fake floating-cutout look. product shape fidelity is more important than shadow removal; clean natural product edges are more important than aggressively removing all shadows. "
            "Strictly restore only the uploaded product's real visible category, structure, shape, proportions, color, material, texture, surface finish, logo, seams, edges, labels, ports, parts, and all visible product details. Do not replace the product, do not recolor it, do not redesign it, do not change its structure, count, scale, or proportions, and do not add accessories, decorative blocks, pads, plates, caps, labels, parts, packaging, or quantities that are not visible in the uploaded image. For headphones, the headband must remain the same continuous uploaded headband surface; do not add any black rectangular pad, black top block, extra cushion, sticker, label, logo plate, or foreign object on the headband unless that exact object is clearly visible in the uploaded product. "
            "Preserve the exact original product silhouette; preserve the exact original product silhouette and keep every outer contour smooth, continuous, anti-aliased, clean, and physically plausible. Product edges must look like real photographic edges, not AI masking or digital cutout edges. No jagged stair-step edges, no pixelated cutout edge, no pixelated edge, no serrated contour, no jagged stair-step edges, no pixelated cutout edge, no serrated contour, no ragged AI mask edge, no broken outline, no white halo, no bright fringe, no dark fringe, no fuzzy cutout edge, no aliasing, and no pasted-object appearance. Every product edge, corner, rim, lip, seam, bevel, top boundary, bottom edge, and brand-side contour must remain completely visible and naturally resolved. No product edge, corner, rim, lip, seam, or silhouette detail may be covered; no product edge, corner, rim, lip, seam, or silhouette detail may be covered; the complete outer boundary must remain visible. "
            "Use the uploaded image geometry as a locked reference; use the uploaded image geometry as a locked reference. Do not smooth, redraw, stylize, reinterpret, simplify, or invent a cleaner or more symmetrical replacement product shape; do not smooth, redraw, stylize, or reinterpret the product body. There must be no deformation, no warping, no squeezing, no stretching, no melted edges, no perspective exaggeration, and no artificial symmetry correction; no product deformation, no warping, no squeezing, no stretching. Cylindrical products must keep straight parallel body sides, cylindrical products must keep straight parallel sides, aligned top and bottom ellipses, correct lid proportions, and the same tall body proportions as the uploaded reference. Do not turn a tall cylinder into a tapered, swollen, barrel-shaped, or hourglass-shaped object; do not turn a tall cylinder into a tapered or swollen shape. "
            "Preserve only brand marks, logos, and small markings that are actually visible in the uploaded product reference, including their original proportions and any tiny registered trademark mark when present. Do not invent, redraw, enlarge, relocate, stylize, distort, or replace logos or add unrelated brand marks. Preserve all small shape transitions, bevels, seams, contours, and surface texture clearly without adding non-product objects. "
            "Place the uploaded product in the upper-right area; place the uploaded product naturally in the upper-right area with visual center around 68% to 72% of image width and 32% to 38% of image height. Do not center it, do not push it against the frame edge, and keep the entire product visible with comfortable white breathing room around the top, sides, and bottom. The placement should feel casually composed by a person using a phone, not mathematically rigid or mechanically positioned. "
            "Choose the product's orientation from its real structure, center of gravity, and normal display logic; do not mechanically force every product to stand upright. Bottles, thermos cups, cans, boxes, and stable flat-bottom products may stand upright. Drill bits, knife rods, screwdrivers, pen-shaped tools, long accessories, pipes, and other slender unstable products must lie flat or slightly diagonal rather than stand vertically against gravity. Power tools, hardware tools, mechanical parts, and irregular products should contact the support surface on their most stable display face. Soft or flexible products should fall naturally with mild folds. Preserve the source count and relationship for multi-piece sets. "
            "For the uploaded product, choose a natural catalog-safe orientation for its real category after removing any non-product support hardware. Headphones should appear as the headphones alone, with the headband and earcups naturally arranged on the tabletop or in a stable product-only display pose; no black stand, pole, base, rack, mannequin, hook, or hanger may appear. Do not make the product lean unnaturally, tip, float, hover, or balance impossibly. Give it only a very subtle natural rotational angle if needed so the placement feels like a casual real phone snapshot rather than a perfectly staged catalog pose. "
            "The product must physically contact the support surface with a believable contact point: no floating, no tipping, no impossible balance, no intersection, and no detached cutout appearance. Preserve real material details, mild natural highlights, realistic black surface reflections, and one consistent reflection and lighting direction. "
            "Directly generate both the product and the certificate in one natural photo, directly generate both the product and the certificate in one natural photo; do not reserve a large empty card area for backend compositing, do not create a cutout, do not paste a later card, and do not make the certificate look like a separate overlay layer. The only allowed reserved area is the normal inspector-value area on the certificate; keep that area clean, blank, and free of red ink graphics for backend inspector-value rendering. The certificate must be generated by the image model as part of the same camera shot, with the same lens perspective, same white tabletop plane, same lighting direction, and same natural photo texture as the product. "
            + certificate_reference_instruction
            + certificate_facts
            + "Required certificate rows: 品牌, 名称, 规格型号, 生产日期, 生产厂家, 厂址, 检验员 value area left blank for backend inspector rendering, and a barcode centered horizontally. Do not render category, material, color, detail copy, company-name-only rows, inspection-result text, or any unentered/old reference-image facts. "
            + "On the certificate, print only user-entered fields that match the visible uploaded product. If a user-entered value conflicts with the visible product category, structure, or appearance, omit that row rather than printing incorrect product information. Do not write capacity, volume, material, model, product name, brand, or specification values that belong to another product type; do not invent replacement values. "
            + "Place the certificate in the same current lower-left area and keep the current reference-like lower-left placement. The certificate should have a lower-left to upper-right diagonal relationship with the product and should sit reasonably close to the product base without touching it. Its visual center should stay around 31% to 35% of image width and 62% to 66% of image height; visual center should be around 31% to 35% of image width and 62% to 66% of image height. "
            "The certificate is a single small horizontal rectangular white hard card or slightly thick paper card, laid flat on the same horizontal tabletop plane as the product. It is not tissue, not folded paper, not stacked sheets, not a standing card, not a portrait sheet, and not a floating overlay; not tissue, not folded, not stacked, not diamond-patterned. The card may have only extremely slight natural paper waviness while retaining clean sharply cut edges and corners; may show only very slight natural paper waviness or tiny surface wrinkles. Its card edges must have no frayed, furry, torn, ragged, or fuzzy edges. Its long edge should remain nearly horizontal with only a slight 3 to 5 degree rotation and share exactly the same tabletop perspective as the product, not a perfectly front-facing rectangle; long edge nearly horizontal with only a slight 3 to 5 degree rotation; not a vertical standing card, not a portrait paper sheet, not a floating overlay. "
            f"The certificate face must be clear and readable. It should show a clean normal product inspection certificate layout with the title 产品合格证 or 合格证, only the compatible user-entered information rows, the normal inspector-value area reserved for backend inspector rendering, and one small barcode using the entered barcode digits. Do not print 检验结果：合格, 结果：合格, or a standalone 合格 result row as plain text. Do not print the inspector parameter value as ordinary black text; do not show a normal 检验员：QC-01 row, and do not place QC-01 after a 检验员 label as typed table text. No red circular mark, red oval mark, red ring, red seal, or red ink graphic may appear in the model-generated certificate. Do not render 检验, 合格, PASS, QC, inspection-result text, {_clean_text(certificate_config.get('inspector') or 'QC-01')}, inspector digits, pseudo text, or random characters inside the inspector value area. The backend will render the inspector value after image generation, so the model should only leave the normal inspector-value area clean and blank. The backend-applied inspector mark remains half the previous visual size; it may be slightly soft like real ink, but must not contain garbled, substituted, pseudo, or random characters. The inspector value area must stay safely above the barcode and must never touch the barcode, barcode quiet zone, or barcode numerals. For the certificate barcode, render a realistic EAN-style retail barcode centered horizontally on the certificate: the first digit printed outside the barcode bars on the left, the remaining digits printed below the bars in two groups, and a clear center guard before the eighth digit. The start guard, center guard before the eighth digit, and end guard bars must be the longest. Use thin and thick vertical bars with varied bar heights, clean white gaps, realistic quiet zones, and no decorative simplification. barcode numerals must exactly match the entered barcode digits, keep the digits separated and readable below the bars, use regular-weight numerals only, and avoid any scrambled, merged, missing, repeated, invented, or substituted digits; no malformed barcode numerals, no random barcode digits, no pseudo barcode numbers, no distorted barcode numbers, and no barcode-number gibberish. The certificate printing must be black or dark gray ink with a simple blue border if needed; no red triangle mark, no QR code, no red ink graphic, no garbled characters, no pseudo text, no random English replacement words, no duplicate text blocks, and no invented unrelated fields. "
            "Keep a clear lower-left to upper-right diagonal relationship between the certificate and the product. The certificate and product must have a clear white gap, must leave a clear white gap from the product and never slide underneath or cover the product, must never touch or overlap, and the certificate must never slide underneath or cover any portion of the product; do not overlap. Keep both subject areas away from the exact image center. The visual mass should remain mainly in the upper and middle-upper part of the frame while the lower half remains mostly clean pure white negative space. "
            "Use only the referenced product's sellable body on the pure white plane: no props, no desk accessories, no plants, no laptop, no books, no pens, no hands, no packaging box, no extra bottle, no decorative objects, no display stand, no support pole, no base, and no unrelated objects. "
            "Use a high front-left angled top-down phone viewpoint: camera above and slightly in front-left of the horizontal tabletop plane, lens angled downward about 50 to 55 degrees. This is not a full top-down flat-lay and not a straight front view. Use an equivalent 28 to 35 mm phone wide-angle smartphone lens with mild natural near-large/far-small perspective, but no obvious wide-angle stretching, barrel distortion, edge deformation, or exaggerated perspective. "
            "The camera perspective must make the product look naturally photographed rather than digitally inserted. Maintain consistent perspective between the product body, its top ellipse, bottom contact, and the horizontal tabletop. Do not create an unnaturally oversized top, tiny lower body, or distorted cylindrical silhouette. "
            "Use soft natural daylight from the left and upper-left. The product top and left side may have soft believable highlights, but keep all highlights controlled and preserve black surface detail. Do not overexpose the top cap, do not clip black surfaces into white or gray, and do not let the product edge disappear into the background. Maintain clear separation between the dark product contour and the white background. "
            "A very light natural contact shadow is allowed directly below and immediately beside the product so it sits physically on the tabletop, but avoid heavy cast shadows, broad gray patches, beige shadow stains, dirty shadow halos, and any shadow shape that visually changes or damages the true product silhouette. "
            "The final feeling must be an ordinary indoor natural-light phone snapshot and ordinary indoor natural-light smartphone snapshot: photorealistic, natural, restrained, believable, casually composed, with slight phone-lens perspective, clean anti-aliased product edges, and clear real material texture. Avoid polished commercial advertising style, perfect CGI symmetry, strong studio lighting, exaggerated reflections, mirror reflections, floating display effects, fake cutout shadows, digital compositing artifacts, over-sharpened edges, or CGI rendering."
        ),
        "package": (
            reference_base
            + real_photo
            + clean_product_surface
            + catalog_exposure_control
            + "Create a pure white background product-and-package co-photo with an appropriately sized retail package on the left and the uploaded product placed near the package on the right-side tabletop when physically possible. The product may occupy more horizontal space, sit lower in the frame, appear as a flatter top or side view, or be less visually prominent if that is required by its natural resting pose. Use the uploaded product image as the only visual reference for the product's real outer shape, appearance, visible parts, proportions, material, color, surface texture, markings, and structural relationships; do not copy any pose that depends on a stand, hook, rack, hanger, pole, base, mannequin, or other display support. Output must be exactly 800x800 pixels, 1:1 square, 800x800, 1:1 square. "
            + package_reference_instruction
            + "The scene must keep a clean seamless pure #ffffff white background and a pure white matte tabletop surface. The background and tabletop should visually merge naturally with no visible horizon line, no wall, no table edge, no floor, no colored background, no environmental objects, and no clutter. "
            "Package size must be chosen from the real product volume and the user-entered 规格型号/model value. Packaging shape and size must adapt to the uploaded product's visible real structure, outer dimensions, folded or storage volume, specification model, and realistic retail packing logic. Hard size rule: the visible package must be taller than the nearby individual product's highest point and its overall outer volume must be clearly larger than the product, so the product can realistically fit inside the package. If the model/specification indicates multiple units, the package must be large enough to hold that full quantity, not just one visible product. Do not make the package lower, smaller, flatter, or visually unable to contain the product just for a prettier composition. Do not default to a tall narrow bottle package, high box, or vertical box shape. For headphones or earphones, use a medium-small headphone retail box that is wider and shallower than a bottle package, sized to fit folded or nested earcups and headband; never use a thermos-style package or oversized shipping box for headphones. "
            + package_physical_capacity_instruction
            + package_capacity_plan
            + package_style_instruction
            + "The package must be structurally complete and fully visible in the final frame. Do not crop, truncate, erase, melt, overexpose, or hide the package top, bottom, top flaps, lid seam, handle, front corners, side corners, lower edge, or any outer packaging boundary when that structure exists. The complete packaging silhouette must remain visible and physically plausible. "
            + package_product_pose_instruction
            + package_front_geometry_instruction
            + package_side_instruction
            + "The package front must have no unnecessary artificial printed border unless that border style comes from the package reference. The ordinary package information area must be on the visible package side panel only. Do not create a front information area; the package front may carry the large brand wordmark, product image, product illustration, or decorative visual design, but ordinary information rows and barcode must stay on the side panel. The model must directly print the package text and barcode on the package surface as native ink or printed packaging graphics, not as a floating sticker, not as an overlay, and not as a separate label. "
            + package_brand_wordmark
            + package_facts
            + package_text_layout
            + "On the package, print user-entered fields as the authoritative product facts. Do not show capacity, volume, material, product name, model, brand, or specification values that were not entered by the user or that come from another product, another package reference, or old source-image text; do not invent replacement values. Render only the selected compatible Chinese and Latin characters from the package information. no garbled characters, no pseudo text, no random English replacement words, no hallucinated brand, no duplicate text blocks, no unrelated product facts, and no invented labels. Keep all package text upright, level, evenly spaced, and aligned like normal package printing. The text must read upright relative to the visible package panel; it should share the package panel's vertical axis and horizontal baseline, with no diagonal drift and no perspective mismatch. "
            + package_barcode_position_instruction
            + "The barcode must be drawn directly on the visible package surface from the barcode type and barcode digits above, like a real EAN retail barcode. The first digit outside the barcode bars on the left, then the remaining digits sit below the bars in two groups with a center guard before the right group; start guard two bars, center guard two bars before the eighth digit, and end guard two bars are the longest. The bars must vary naturally in width and height like a real EAN retail barcode, with thin and thick vertical bars, clean white gaps, realistic quiet zones, and no decorative simplification. barcode digits must be clear, regular weight, and not bold; not bold, not blurry, not thickened, not smeared, and not fused into the vertical code bars. Use one barcode block only, with readable digits below the bars, sized realistically for the package. "
            "Do not add handling marks, up arrows, moisture marks, random extra labels, unrelated code graphics, unrelated QR codes, warning triangles, stickers, badges, unrelated certification symbols, or duplicate barcode blocks; avoid unrelated warning symbols. "
            "Preserve the uploaded product's visible product type, main structure, proportions, seams, surface finish, material texture, edges, visible logo, and recognizable appearance after excluding non-product support hardware. Do not redesign, recolor, deform, squeeze, stretch, taper, swell, or replace the product. Do not preserve the uploaded source image's exact 2D silhouette, source camera angle, source canvas orientation, or supported display posture. Re-project the product into its physically natural tabletop pose even if this makes the product look flatter, lower, foreshortened, side-facing, or less complete than the source reference. For cylindrical products, preserve the cylindrical form accurately with straight body sides and properly aligned top and bottom ellipses; for headphones, preserve the headband arc, earcup shapes, hinge geometry, cushions, and left-right relationship without adding the source display stand. "
            "Keep product edges smooth, continuous, anti-aliased, and photographic in the final natural resting pose. No jagged stair-step edges, no pixelated contour, no fuzzy AI mask, no white fringe, no broken outline, no melted edge, and no cutout halo. "
            "The package must remain fully inside the image with comfortable white breathing room around its complete packaging silhouette. Avoid unnecessary product cropping, but product physical resting pose is more important than showing every product outline or feature. Do not rotate the product upright just to keep the product outline complete. 商品包装必须完整，包装顶部、底部、四角、折边、封口线和箱体轮廓都必须完整可见. "
            "Use soft natural light from the left and upper-left with restrained realistic highlights and mild clean contact shadows. Lighting direction must remain consistent across the package, the product, and tabletop. Avoid harsh studio lighting and avoid conflicting highlight directions. "
            "Critical exposure requirement: prevent overexposure on the top of the product and the top of the packaging. 商品顶部严禁过度曝光，包装顶部也严禁过曝. Preserve visible tonal detail, lid contour, rim, edge transitions, package material texture, and top flap geometry. No part of the black product top may become a blown-out white or pale gray patch. "
            "The final feeling must be a realistic retail product photograph: clean, believable, restrained, with complete packaging geometry, accurate product structure, a clean product-and-package co-photo, controlled highlights, and no overexposure on the product or package top. Avoid CGI rendering, exaggerated advertising gloss, distorted packaging, crooked typography, warped retail codes, bold retail-code numerals, incomplete packaging, floating print layers, and blown-out highlights."
        ),
        "detail": (
            reference_base
            + "Create finished visual sections for a modular ecommerce detail page, not one long poster. "
            "The backend will only stitch four finished generated sections vertically and will not add titles, labels, parameter tables, or other text afterward. "
            "Each section may include integrated ecommerce graphic text when needed, but do not create machine-readable codes, watermarks, or random certificate-like labels."
        ),
        "scene": (
            reference_base
            + real_photo
            + _scene_instruction(category)
        ),
    }
    return prompts[output_type]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _package_capacity_plan(product: dict[str, Any]) -> str:
    model = _clean_text(product.get("model", ""))
    name = _clean_text(product.get("name", ""))
    category = _clean_text(product.get("category", ""))
    quantity = _extract_package_quantity(model)
    if quantity < 2:
        return ""

    product_hint = f"{name} {category} {model}".lower()
    bottle_like = any(
        token in product_hint
        for token in ("瓶", "饮", "茶", "乳", "奶", "juice", "drink", "bottle", "beverage", "ml")
    )
    if not bottle_like:
        return (
            f"Detected multi-unit product specification: {quantity} units. "
            "Use a multi-unit retail carton structure, not a single-unit gift box. "
            "The package must visibly fit all units plus dividers, padding, grouping space, and closure clearance. "
        )

    if quantity == 6:
        return (
            "Detected multi-unit bottle specification: 6 bottles. "
            "Use a six-bottle carton packing structure, not a single-bottle gift box. "
            "Arrange the internal capacity as 3 bottles by 2 bottles upright, with realistic divider and padding allowance. "
            "The package width must visibly fit three bottle diameters plus dividers, the package depth must visibly fit two bottle diameters plus dividers, and the package height must exceed the full bottle height including cap. "
            "In the final co-photo, the package's visible top edge must sit higher than the top of the adjacent single bottle, and the package must look large enough to physically contain all 6 bottles. "
            "The shown package may be wider and deeper than a simple front display box; physical fit is more important than making the package compact or elegant. "
        )

    return (
        f"Detected multi-unit bottle specification: {quantity} bottles. "
        "Use a multi-bottle retail carton packing structure, not a single-bottle gift box. "
        "Choose an upright internal bottle grid that visibly fits the full quantity plus dividers, padding, and closure clearance. "
    )


def _package_product_pose_instruction(product: dict[str, Any]) -> str:
    product_hint = " ".join(
        _clean_text(product.get(key, ""))
        for key in ("name", "brand", "model", "category")
    ).lower()
    stable_container = any(
        token in product_hint
        for token in ("瓶", "罐", "杯", "饮", "茶", "乳", "奶", "juice", "drink", "bottle", "beverage", "can", "cup", "jar", "ml")
    )
    unstable_tabletop_product = any(
        token in product_hint
        for token in (
            "鼠标",
            "耳机",
            "键盘",
            "遥控",
            "手柄",
            "工具",
            "电钻",
            "螺丝刀",
            "mouse",
            "headphone",
            "earphone",
            "keyboard",
            "remote",
            "controller",
            "tool",
        )
    )

    package_intro = (
        "Place the appropriately sized package on the left and the product resting area nearby with natural retail-photo spacing. "
        "The package may stand upright or sit at the natural package angle required by its referenced or product-appropriate structure. "
        "This package orientation rule applies only to the package, never to the product. "
        "For product placement only, preserve the uploaded product's identity, appearance, visible parts, materials, proportions, and structural relationships, not its original supported display position, camera viewpoint, or canvas orientation. "
        "First remove every non-product object from the source reference, including stands, poles, bases, hooks, hangers, racks, mannequins, and invisible support; then choose the product pose from its real-world normal use orientation, normal resting orientation, designed functional contact surface, actual stable contact points, and center of gravity. "
    )
    stable_container_rule = (
        "For bottles, cans, cups, jars, and stable flat-bottom containers, the product should stand upright beside the package by default. "
        "Do not lay a bottle, can, cup, jar, or stable flat-bottom container horizontally unless the uploaded product is visibly damaged, has no stable bottom, or the user explicitly requests a lying pose. "
        "The container bottom must naturally contact the tabletop, the cap or lid should remain above the body, and the product should look like a normal retail bottle display. "
        "This upright-container rule has higher priority than the general natural resting pose rule, product visibility rule, and package composition rule. "
    )
    tabletop_rule = (
        "Physical realism has absolute priority over product visibility, product attractiveness, front-facing display, and showing product features for products without a stable standing base. "
        "Do not rotate, stand, lean, prop up, or balance the product just to show more of the product. "
        "It is acceptable if the product looks lower, flatter, less prominent, less complete, less front-facing, partially less informative, or visually less impressive, as long as it rests naturally according to physics. "
        "A broad surface alone is not permission to stand the product upright. "
        "For desktop-use products, handheld devices, controllers, remotes, mice, keyboards, chargers, power banks, small electronics, tools, and any product with a designed bottom or underside, place the product in its real tabletop resting pose. "
        "The designed bottom, underside, feet, pads, base, or normal contact surface must be on the tabletop. "
        "The product top should face upward relative to the tabletop, not forward toward the camera. "
        "The top/use side may be visible only through a natural camera angle, not by rotating the product upright toward the camera. "
        "Do not rotate the product onto its front, tail, side, edge, cable, connector, rounded end, or decorative face just to satisfy a vertical composition. "
        "If the normal resting/use pose is horizontal, low, flat, side-lying, or slightly diagonal, keep that pose. "
        "The product may occupy more horizontal tabletop area when that is the physically natural resting pose; do not compress, crop, or stand the product to fit a narrow right-side silhouette. "
        "Forbidden: standing a normally flat tabletop product vertically on its tail, front, side, edge, curved end, cable, connector, or any narrow contact point. "
        "Forbidden: showing a normally flat tabletop product as an upright front-facing object beside the package. "
        "Forbidden: using a small contact shadow to fake physical contact while the product is actually vertical. "
        "For products that need an external stand, hook, rack, hanger, pole, base, or mannequin to remain upright, unsupported vertical placement is forbidden after those supports are removed. "
        "Hard rule for headphones and earphones: when no visible stand or support fixture is included, vertical or upright placement is forbidden. "
        "The entire headphones must lie flat, side-lying, or low diagonal on the tabletop; the headband, both earcups, cable, inline control, and microphone must all rest on or visibly contact the tabletop. "
        "Do not support headphones only on one earcup edge or a narrow earcup rim, and do not let the headband rise as a free-standing arch. "
        "Do not let headphones balance upright on one edge, float, hover, lean without support, stand on a cable, or hang in the air. "
    )
    contact_shadow_rule = (
        "For this package co-photo, realistic consistent contact shadows directly beneath all tabletop contact points are required so the product and package feel photographed together rather than composited separately. "
    )

    if stable_container and not unstable_tabletop_product:
        return package_intro + stable_container_rule + contact_shadow_rule
    return package_intro + tabletop_rule + contact_shadow_rule


def _extract_package_quantity(model: str) -> int:
    candidates: list[int] = []
    for pattern in (
        r"[xX×*]\s*(\d{1,3})",
        r"(\d{1,3})\s*(?:瓶|罐|杯|支|个|件|pcs?|PCS?)",
    ):
        candidates.extend(int(match) for match in re.findall(pattern, model))

    return max(candidates) if candidates else 1


def _package_information_rows(
    product: dict[str, Any],
    manufacturer_name: object,
    manufacturer_address: object,
) -> list[tuple[str, str]]:
    return [
        ("品名", _clean_text(product.get("name", ""))),
        ("规格型号", _clean_text(product.get("model", ""))),
        ("生产厂家", _clean_text(manufacturer_name)),
        ("地址", _clean_text(manufacturer_address)),
    ]


def _format_chinese_rows(rows: list[tuple[str, object]]) -> str:
    parts = [f"{label}：{text}" for label, value in rows if (text := _clean_text(value))]
    return "; ".join(parts) + ("." if parts else "no package text rows except barcode.")


def _format_fact_rows(rows: list[tuple[str, object]]) -> str:
    parts = [f"{label}: {text}" for label, value in rows if (text := _clean_text(value))]
    return "; ".join(parts) + ("." if parts else "no text facts.")


def _detail_module_prompts(product: dict[str, Any]) -> list[str]:
    name = product.get("name", "the uploaded product")
    brand = _clean_text(product.get("brand", ""))
    fact_text = _format_fact_rows(
        [
            ("product", name),
            ("specification model", product.get("model", "")),
        ]
    )
    base = (
        "Use the uploaded product photo as the exact product reference. "
        "The uploaded product photo may not be a front view; preserve the real visible product appearance from the uploaded view, including actual perspective, visible side surfaces, foreshortening, label angle, seam direction, logo placement, cap/lid ellipse, and any naturally hidden surfaces. Do not force a generic front-facing or perfectly symmetrical product view when the uploaded product is angled, side-facing, top-down, or partially turned. "
        "Match the marketplace main image product style exactly: keep the same product identity, outer appearance, color, material, scale, silhouette, visible parts, seams, finish, exact same visible product logo, and every visible marking consistent across all detail sections. "
        "The detail page modules must match the same product style identity used by the main photo, certificate co-photo, package co-photo, and scene photo. Do not switch to a different SKU, package variant, colorway, flavor, label design, logo layout, cap shape, bottle shape, accessory set, or material finish inside any detail module. "
        "All rendered product appearances must come from the same single uploaded product reference. "
        "For every close-up, bottom view, top view, side view, macro crop, inset, and full-product view, the product must share the same structure, geometry, proportions, material, texture, color, seams, edges, bevels, labels, logo position, and visible markings as the main product image. "
        "Do not invent a different bottom, underside, lid, cap, base, anti-slip pad, connector, label, badge, logo placement, surface pattern, display stand, support pole, base, hanger, rack, mannequin, or non-product support hardware in any module. "
        "If a part of the product is not visible in the uploaded reference, infer only a physically plausible continuation without adding readable logos, brand marks, labels, icons, decorative rings, or new surface features. "
        "A partial detail view must never conflict with a full-product view or the marketplace main image: no extra logo on a bottom or underside unless the uploaded reference clearly shows that exact logo in that exact position, no missing visible logo when the source-facing side is shown, and no changed base shape, rim shape, seam count, texture direction, product posture logic, or material finish. "
        "If the source product includes an R mark, circled R, or tiny registered trademark symbol beside the logo, preserve that same tiny registered trademark symbol in every product view where the logo side is visible. "
        "Keep the product on a plain white or very light neutral background and avoid scene props: no laptop, no books, no pen, no plant, no hands, no other containers, and no unrelated objects. "
        "Create one finished ecommerce detail section image with integrated layout and any needed Chinese text inside the generated image itself. "
        f"Use exact non-empty user-entered product facts where relevant: {fact_text} "
        "Do not render rows, table entries, labels, or placeholder text for absent fields; avoid missing-field placeholders in any language, empty-value markers, blank-value markers, placeholder dashes, or invented parameter values. "
        "If a fact was not entered by the user, omit that label completely; the model may infer visual feature illustrations from the real uploaded product appearance, but must not present inferred values as structured specifications. "
        "Do not add logos that are not on the product, machine-readable codes, watermarks, or certificate-like labels. "
    )
    first_brand_instruction = (
        f"Use the brand only in this first detail module as large standard printed Chinese brand text, brand: {brand}. "
        "Use plain regular-weight Songti/Heiti-style characters, not artistic typography, not calligraphy, not brush style, not decorative typography, and not a stylized logo redesign. "
        "The brand text should be large enough to occupy many pixels. character correctness and complete stroke structure are more important than sharpness; slight softness or mild ink blur is acceptable. "
        "Do not distort, simplify, merge, substitute, pseudo-render, split, connect, warp, or decorate any brand character. Preserve every radical, stroke order impression, inner gap, and complete Chinese stroke structure as faithfully as possible. "
        if brand
        else "Do not add a brand wordmark because the user did not enter a brand. "
    )
    no_repeat_brand_instruction = (
        "Do not repeat the brand name or brand wordmark as readable text in this section; only preserve visible product logos or markings that physically exist on the uploaded product. "
    )
    return [
        base + first_brand_instruction + f"detail module: product hero finished ecommerce detail section for {name}. Strong opening banner, complete product facing the same branded side as the source image, clean premium ecommerce style.",
        base + no_repeat_brand_instruction + f"detail module: product-only feature section for {name}. Show the same product on a white or light neutral surface, with the branded side and exact logo markings still visible, no lifestyle environment.",
        base + no_repeat_brand_instruction + f"detail module: close-up detail finished ecommerce detail section for {name}. Macro-style product details showing material, opening, lid, finish, texture, bottom, seam, or key feature, plus a small full-product view with the exact logo and registered mark visible.",
        base + no_repeat_brand_instruction + f"detail module: structure and scale visual reference finished ecommerce detail section for {name}. Product angles and visual scale cues may be integrated when they come from the uploaded product appearance, while preserving the exact logo and registered mark on every visible product.",
    ]


def _scene_instruction(category: str) -> str:
    lowered = category.lower()
    if any(token in lowered for token in ("tool", "wrench", "hardware", "electric", "power")) or any(
        token in category for token in ("工具", "扳手", "五金", "电动")
    ):
        return (
            "Show the product in a real worksite or workshop as a natural casual phone snapshot, with no hands, no fingers, no gloves, and no human body parts visible. "
            "Use real-world placement details: the product must sit, lie, lean, or rest according to its actual support area, center of gravity, cable direction, and contact points; no floating, impossible balance, staged perfect upright pose, or unsupported vertical placement. "
            "Use ordinary practical lighting, slight handheld composition, believable scale, natural background clutter appropriate to the environment, and no readable new text."
        )
    return (
        "Show a realistic product-in-use scene in a real environment matching the product category, like a natural casual phone snapshot rather than a staged catalog render. "
        "The product must stand, lie, lean, or rest naturally according to its actual support area, center of gravity, cable direction, and contact points, with no hands, no fingers, no gloves, and no human body parts visible. "
        "For headphones or earphones without a visible stand, make them rest naturally on the desk or surface with believable contact points for the headband, earcups, cable, inline control, or microphone; do not make them float, balance on one edge, or stand vertically without support. "
        "Use believable scale, ordinary practical lighting, slight handheld framing, natural everyday placement details, and no readable new text."
    )


def _open_provider_image(raw: bytes) -> Image.Image:
    with Image.open(BytesIO(raw)) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _normalize_size(image: Image.Image, width: int, height: int, *, background: str) -> Image.Image:
    canvas = Image.new("RGB", (width, height), background)
    contained = ImageOps.contain(image, (width, height))
    canvas.paste(contained, ((width - contained.width) // 2, (height - contained.height) // 2))
    return canvas


def _replace_neutral_background_with_white(image: Image.Image) -> Image.Image:
    result = image.convert("RGB")
    pixels = result.load()
    for y in range(result.height):
        for x in range(result.width):
            r, g, b = pixels[x, y]
            if r >= 205 and g >= 205 and b >= 205 and max(r, g, b) - min(r, g, b) <= 34:
                pixels[x, y] = (255, 255, 255)
    return result


def _suppress_white_background_shadows(image: Image.Image) -> Image.Image:
    result = image.convert("RGB")
    pixels = result.load()
    for y in range(result.height):
        for x in range(result.width):
            r, g, b = pixels[x, y]
            if r >= 205 and g >= 205 and b >= 205 and max(r, g, b) - min(r, g, b) <= 42:
                pixels[x, y] = (255, 255, 255)
    return result


def _normalize_certificate_tabletop_background(image: Image.Image) -> Image.Image:
    result = image.convert("RGB")
    pixels = result.load()
    width, height = result.size
    visited = bytearray(width * height)
    protected = _dark_product_protection_mask(pixels, width, height)
    queue: deque[tuple[int, int]] = deque()

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(1, height - 1):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        index = y * width + x
        if visited[index]:
            continue
        visited[index] = 1
        if not _is_certificate_background_pixel(pixels[x, y]):
            continue
        if protected[index]:
            continue

        pixels[x, y] = (255, 255, 255)
        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    return result


def _is_certificate_background_pixel(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return r >= 205 and g >= 205 and b >= 205 and max(r, g, b) - min(r, g, b) <= 42


def _dark_product_protection_mask(pixels: Any, width: int, height: int) -> bytearray:
    protected = bytearray(width * height)
    radius = 8
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if max(r, g, b) > 95:
                continue
            for yy in range(max(0, y - radius), min(height, y + radius + 1)):
                row = yy * width
                for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                    protected[row + xx] = 1
    return protected


def _apply_used_photo_finish(image: Image.Image) -> Image.Image:
    softened = image.filter(ImageFilter.GaussianBlur(0.18))
    return Image.blend(image, softened, 0.16)


def _build_detail_page(sources: list[Image.Image], product: dict[str, Any], project: dict[str, Any], font_path: str) -> Image.Image:
    module_images = sources or [Image.new("RGB", (800, 800), "white")]
    while len(module_images) < 4:
        module_images.append(module_images[-1])

    sections = [_fit_width(source, 800) for source in module_images[:4]]
    total_height = sum(section.height for section in sections)
    canvas = Image.new("RGB", (800, total_height), "white")
    y = 0
    for section in sections:
        canvas.paste(section, (0, y))
        y += section.height

    return canvas


def _certificate_rows(product: dict[str, Any], project: dict[str, Any]) -> list[tuple[str, str]]:
    config = project.get("certificate_config", {}) if isinstance(project.get("certificate_config", {}), dict) else {}
    manufacturer_name = config.get("manufacturer_name") or _company_name(product, config)
    manufacturer_address = config.get("manufacturer_address") or config.get("address") or ""
    return [
        ("品牌", _clip(product.get("brand", ""), 16)),
        ("名称", _clip(product.get("name", ""), 18)),
        ("规格型号", _clip(_spec_model_text(product), 20)),
        ("生产日期", _clip(config.get("production_date") or _date_text(project.get("created_at")), 16)),
        ("生产厂家", _clip(manufacturer_name, 18)),
        ("厂址", _clip(manufacturer_address, 24)),
    ]


def _compose_certificate(image: Image.Image, product: dict[str, Any], project: dict[str, Any], font_path: str) -> None:
    card = Image.new("RGBA", (360, 190), (250, 249, 244, 255))
    draw = ImageDraw.Draw(card)
    draw.rectangle((7, 7, 353, 183), outline=(37, 99, 172, 255), width=3)
    title = _font(24, font_path)
    body = _font(9, font_path)
    stamp_font = _font(11, font_path)
    stamp_value_font = _font(10, font_path)
    draw.text((68, 20), "合 格 证", fill=(31, 41, 55, 255), font=title)
    draw.line((34, 58, 202, 58), fill=(37, 99, 172, 255), width=2)
    y = 64
    for label, value in _certificate_rows(product, project):
        draw.text((24, y), f"{label}: {value}", fill=(31, 41, 55, 255), font=body)
        y += 14
    config = project.get("certificate_config", {}) if isinstance(project.get("certificate_config", {}), dict) else {}
    draw.text((205, 103), "检验员:", fill=(31, 41, 55, 255), font=body)
    _draw_qc_stamp(card, (252, 91), _clip(config.get("inspector") or "QC-01", 10), stamp_font, stamp_value_font)
    barcode = render_barcode_image(
        BarcodeType(project["barcode_type"]),
        project["barcode_value"],
        width=150,
        height=44,
        draw_border=False,
    ).convert("RGBA")
    card.alpha_composite(barcode, ((card.width - barcode.width) // 2, 137))
    tabletop_card = _flatten_certificate_for_tabletop(card)
    _paste_tabletop_paper(image, tabletop_card, (95, 410))


def _draw_qc_stamp(card: Image.Image, xy: tuple[int, int], inspector: str, stamp_font: ImageFont.ImageFont, value_font: ImageFont.ImageFont) -> None:
    draw = ImageDraw.Draw(card)
    x, y = xy
    red = (198, 45, 45, 220)
    stamp_width = 50
    stamp_height = 34
    center_y = y + stamp_height // 2
    value = _qc_stamp_value(inspector)

    draw.ellipse((x, y, x + stamp_width, y + stamp_height), outline=red, width=2)
    draw.line((x + 5, center_y, x + stamp_width - 5, center_y), fill=red, width=2)
    label_bbox = draw.textbbox((0, 0), "检验", font=stamp_font)
    label_width = label_bbox[2] - label_bbox[0]
    value_bbox = draw.textbbox((0, 0), value, font=value_font)
    value_width = value_bbox[2] - value_bbox[0]
    value_height = value_bbox[3] - value_bbox[1]
    draw.text((x + (stamp_width - label_width) / 2, y + 3), "检验", fill=red, font=stamp_font)
    draw.text((x + (stamp_width - value_width) / 2, center_y + (stamp_height // 2 - value_height) / 2 - 1), value, fill=red, font=value_font)


def _qc_stamp_value(inspector: str) -> str:
    text = str(inspector or "").strip()
    digit_groups = re.findall(r"\d+", text)
    if digit_groups:
        digits = digit_groups[-1]
        if len(digits) == 1:
            return f"0{digits}"
        return digits[-3:] if len(digits) > 3 else digits
    return _clip(text, 4) or "01"


def _flatten_certificate_for_tabletop(card: Image.Image) -> Image.Image:
    source = card.resize((360, 190), resample=Image.Resampling.LANCZOS)
    output_size = (334, 220)
    destination = [(44, 24), (293, 38), (328, 198), (7, 186)]
    source_corners = [(0, 0), (source.width, 0), (source.width, source.height), (0, source.height)]
    coefficients = _perspective_coefficients(destination, source_corners)
    return source.transform(
        output_size,
        Image.Transform.PERSPECTIVE,
        coefficients,
        Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )


def _paste_tabletop_paper(base: Image.Image, overlay: Image.Image, xy: tuple[int, int]) -> None:
    _paste_rgba_plain(base, overlay, xy)


def _detect_certificate_barcode_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    grayscale = image.convert("L")
    width, height = grayscale.size
    x_limit = int(width * 0.62)
    y_start = int(height * 0.58)
    dark_columns: list[int] = []

    for x in range(x_limit):
        dark_count = 0
        for y in range(y_start, height):
            if grayscale.getpixel((x, y)) < 75:
                dark_count += 1
        if dark_count >= 24:
            dark_columns.append(x)

    if not dark_columns:
        return None

    runs: list[tuple[int, int]] = []
    run_start = dark_columns[0]
    previous = dark_columns[0]
    for x in dark_columns[1:]:
        if x - previous <= 8:
            previous = x
            continue
        runs.append((run_start, previous))
        run_start = x
        previous = x
    runs.append((run_start, previous))

    candidates = [(x0, x1) for x0, x1 in runs if x1 - x0 >= 40]
    if not candidates:
        return None

    x0, x1 = max(candidates, key=lambda item: item[1] - item[0])
    y_values = [
        y
        for y in range(y_start, height)
        for x in range(x0, x1 + 1)
        if grayscale.getpixel((x, y)) < 75
    ]
    if not y_values:
        return None

    return x0, min(y_values), x1, max(y_values)


def _detect_certificate_card_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    source = image.convert("RGB")
    width, height = source.size
    x_limit = int(width * 0.68)
    y_start = int(height * 0.34)
    blue_pixels: list[tuple[int, int]] = []
    ink_pixels: list[tuple[int, int]] = []

    for y in range(y_start, height):
        for x in range(x_limit):
            red, green, blue = source.getpixel((x, y))
            if blue > 105 and blue > red + 25 and blue > green + 12 and red < 170:
                blue_pixels.append((x, y))
            if min(red, green, blue) < 205 and not _is_red_artifact_pixel((red, green, blue)):
                ink_pixels.append((x, y))

    for pixels, padding, min_width_ratio, min_height_ratio in (
        (blue_pixels, 16, 0.18, 0.11),
        (ink_pixels, 28, 0.24, 0.18),
    ):
        if len(pixels) < 40:
            continue
        xs = [x for x, _ in pixels]
        ys = [y for _, y in pixels]
        left = max(0, min(xs) - padding)
        top = max(0, min(ys) - padding)
        right = min(width - 1, max(xs) + padding)
        bottom = min(height - 1, max(ys) + padding)
        if right - left >= int(width * min_width_ratio) and bottom - top >= int(height * min_height_ratio):
            return left, top, right, bottom

    return None


def _is_red_artifact_pixel(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > 105 and green < 155 and blue < 155 and red - max(green, blue) > 18


def _bbox_contains(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
    left, top, right, bottom = bbox
    return left <= x <= right and top <= y <= bottom


def _expand_bbox(
    bbox: tuple[int, int, int, int],
    padding: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(width - 1, right + padding),
        min(height - 1, bottom + padding),
    )


def _local_non_red_surface_color(source: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    width, height = source.size
    for radius in (4, 8, 12, 18):
        samples: list[tuple[int, int, int]] = []
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                pixel = source.getpixel((xx, yy))
                if _is_red_artifact_pixel(pixel):
                    continue
                samples.append(pixel)
        if samples:
            return tuple(sum(pixel[channel] for pixel in samples) // len(samples) for channel in range(3))
    return 255, 255, 255


def _remove_certificate_red_artifacts(image: Image.Image) -> Image.Image:
    cleaned = image.convert("RGB")
    width, height = cleaned.size
    barcode_bbox = _detect_certificate_barcode_bbox(cleaned)
    barcode_guard = _expand_bbox(barcode_bbox, 14, width, height) if barcode_bbox else None
    x_limit = int(width * 0.66)
    y_start = int(height * 0.42)
    red_pixels: set[tuple[int, int]] = set()

    for y in range(y_start, height):
        for x in range(x_limit):
            if barcode_guard and _bbox_contains(barcode_guard, x, y):
                continue
            if _is_red_artifact_pixel(cleaned.getpixel((x, y))):
                red_pixels.add((x, y))

    source = cleaned.copy()
    pixels = cleaned.load()
    visited: set[tuple[int, int]] = set()
    for pixel in list(red_pixels):
        if pixel in visited:
            continue
        stack = [pixel]
        visited.add(pixel)
        component: list[tuple[int, int]] = []
        while stack:
            x, y = stack.pop()
            component.append((x, y))
            for neighbor_x in (x - 1, x, x + 1):
                for neighbor_y in (y - 1, y, y + 1):
                    neighbor = (neighbor_x, neighbor_y)
                    if neighbor in red_pixels and neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)

        if len(component) < 8:
            continue
        xs = [x for x, _ in component]
        ys = [y for _, y in component]
        component_width = max(xs) - min(xs) + 1
        component_height = max(ys) - min(ys) + 1
        if component_width > 140 or component_height > 100:
            continue

        for x, y in component:
            pixels[x, y] = _local_non_red_surface_color(source, x, y)

    return cleaned.convert(image.mode)


def _certificate_qc_stamp_position(base: Image.Image, stamp_size: tuple[int, int]) -> tuple[int, int]:
    width, height = base.size
    stamp_width, stamp_height = stamp_size
    barcode_bbox = _detect_certificate_barcode_bbox(base)
    card_bbox = _detect_certificate_card_bbox(base)
    if card_bbox is not None:
        card_left, card_top, card_right, card_bottom = card_bbox
        card_width = card_right - card_left + 1
        card_height = card_bottom - card_top + 1
        x = card_left + int(card_width * 0.58) - stamp_width // 2
        y = card_top + int(card_height * 0.74) - int(stamp_height * 0.58)
        x = max(card_left + 4, min(x, card_right - stamp_width - 4))
        y = max(card_top + int(card_height * 0.52), min(y, card_bottom - stamp_height - 4))

        barcode_guard = _certificate_barcode_guard_bbox(barcode_bbox, card_bbox, width, height)
        stamp_bbox = (x, y, x + stamp_width, y + stamp_height)
        if _bbox_intersects(stamp_bbox, barcode_guard):
            y = barcode_guard[1] - stamp_height - 4
            y = max(card_top + int(card_height * 0.52), min(y, barcode_guard[1] - stamp_height - 4))
        return x, y

    if barcode_bbox is None:
        safe_bottom = int(height * 0.72)
        return int(width * 0.29), min(int(height * 0.76), safe_bottom - stamp_height)

    barcode_x0, barcode_y0, barcode_x1, _ = barcode_bbox
    x = barcode_x0 - int(stamp_width * 0.35)
    x = max(int(width * 0.12), min(x, barcode_x1 - stamp_width))
    y = barcode_y0 - stamp_height - 4
    y = max(int(height * 0.50), min(y, barcode_y0 - stamp_height - 4))
    return x, y


def _bbox_intersects(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return first[0] <= second[2] and first[2] >= second[0] and first[1] <= second[3] and first[3] >= second[1]


def _certificate_barcode_guard_bbox(
    barcode_bbox: tuple[int, int, int, int] | None,
    card_bbox: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    if barcode_bbox is not None:
        return _expand_bbox(barcode_bbox, 14, width, height)

    card_left, card_top, card_right, card_bottom = card_bbox
    card_height = card_bottom - card_top + 1
    guard_top = card_top + int(card_height * 0.70)
    return card_left, guard_top, card_right, card_bottom


def _overlay_certificate_qc_stamp(image: Image.Image, project: dict[str, Any], font_path: str) -> Image.Image:
    config = project.get("certificate_config", {}) if isinstance(project.get("certificate_config", {}), dict) else {}
    inspector = _clip(config.get("inspector") or "QC-01", 10)
    base = _remove_certificate_red_artifacts(image).convert("RGBA")
    stamp = Image.new("RGBA", (70, 52), (0, 0, 0, 0))
    _draw_qc_stamp(stamp, (10, 9), inspector, _font(10, font_path), _font(11, font_path))
    stamp = stamp.rotate(-2.5, resample=Image.Resampling.BICUBIC, expand=True)
    stamp = stamp.filter(ImageFilter.GaussianBlur(0.25))
    base.alpha_composite(stamp, _certificate_qc_stamp_position(base, stamp.size))
    return base.convert(image.mode)


def _perspective_coefficients(
    destination_points: list[tuple[int, int]],
    source_points: list[tuple[int, int]],
) -> list[float]:
    matrix: list[list[float]] = []
    for (x, y), (source_x, source_y) in zip(destination_points, source_points):
        matrix.append([x, y, 1, 0, 0, 0, -source_x * x, -source_x * y, source_x])
        matrix.append([0, 0, 0, x, y, 1, -source_y * x, -source_y * y, source_y])

    for column in range(8):
        pivot = max(range(column, 8), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-9:
            raise ValueError("certificate perspective transform is singular")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]

        for row in range(8):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(matrix[row], matrix[column])
            ]

    return [matrix[row][8] for row in range(8)]


def _compose_package_label(image: Image.Image, product: dict[str, Any], project: dict[str, Any], font_path: str) -> None:
    label_image = Image.new("RGBA", (236, 390), (0, 0, 0, 0))
    draw = ImageDraw.Draw(label_image)
    ink = (28, 32, 30, 225)
    brand_font = _font(21, font_path)
    body = _font(12, font_path)
    draw.text((18, 8), _clip(product.get("brand", ""), 14), fill=ink, font=brand_font)
    package_config = project.get("package_config", {}) if isinstance(project.get("package_config", {}), dict) else {}
    certificate_config = project.get("certificate_config", {}) if isinstance(project.get("certificate_config", {}), dict) else {}
    manufacturer_name = (
        package_config.get("manufacturer_name")
        or package_config.get("company_name")
        or _company_name(product, certificate_config)
    )
    manufacturer_address = package_config.get("manufacturer_address") or package_config.get("address") or ""
    rows = [
        ("品名", product.get("name", "")),
        ("规格型号", product.get("model", "")),
        ("生产厂家", manufacturer_name),
        ("地址", manufacturer_address),
    ]
    y = 64
    for field_label, value in rows:
        if value:
            max_chars = 12 if field_label == "地址" else 14
            draw.text((18, y), f"{field_label}: {_clip(value, max_chars)}", fill=ink, font=body)
            y += 26
    barcode = render_barcode_image(
        BarcodeType(project["barcode_type"]),
        project["barcode_value"],
        width=236,
        height=104,
        draw_border=False,
        transparent=True,
    )
    _tint_barcode_for_box(barcode)
    label_image.alpha_composite(barcode, (0, max(y + 10, 278)))
    _paste_printed_label(image, label_image, (194, 150))


def _paste_printed_label(image: Image.Image, label: Image.Image, xy: tuple[int, int]) -> None:
    base = image.convert("RGB")
    printed = label.convert("RGBA")
    base_pixels = base.load()
    printed_pixels = printed.load()
    offset_x, offset_y = xy

    for y in range(printed.height):
        base_y = offset_y + y
        if base_y < 0 or base_y >= base.height:
            continue
        for x in range(printed.width):
            base_x = offset_x + x
            if base_x < 0 or base_x >= base.width:
                continue

            ink_r, ink_g, ink_b, ink_alpha = printed_pixels[x, y]
            if ink_alpha <= 0:
                continue

            paper_r, paper_g, paper_b = base_pixels[base_x, base_y]
            coverage = ink_alpha / 255
            strength = min(0.72, coverage * 0.68)
            fiber = (((base_x * 17 + base_y * 31) & 7) - 3) * coverage

            multiplied = (
                paper_r * ink_r / 255,
                paper_g * ink_g / 255,
                paper_b * ink_b / 255,
            )
            base_pixels[base_x, base_y] = (
                _clamp_channel(paper_r * (1 - strength) + multiplied[0] * strength + fiber),
                _clamp_channel(paper_g * (1 - strength) + multiplied[1] * strength + fiber),
                _clamp_channel(paper_b * (1 - strength) + multiplied[2] * strength + fiber),
            )

    image.paste(base)


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _paste_rgba_plain(base: Image.Image, overlay: Image.Image, xy: tuple[int, int]) -> None:
    base_rgba = base.convert("RGBA")
    base_rgba.alpha_composite(overlay, xy)
    base.paste(base_rgba.convert("RGB"))


def _draw_section_header(draw: ImageDraw.ImageDraw, y: int, text: str) -> None:
    draw.rectangle((0, y, 800, y + 44), fill=(255, 255, 255))
    draw.rectangle((48, y + 10, 56, y + 34), fill=(14, 116, 144))
    draw.text((70, y + 4), text, fill=(15, 23, 42), font=_font(28))


def _draw_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill: tuple[int, int, int]) -> None:
    draw.rectangle(box, fill=fill)


def _draw_tag(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    draw.rounded_rectangle((x, y, 750, y + 48), radius=8, fill=(255, 255, 255), outline=(203, 213, 225), width=1)
    draw.text((x + 18, y + 11), text, fill=(51, 65, 85), font=font)


def _draw_specs_table(
    draw: ImageDraw.ImageDraw,
    product: dict[str, Any],
    box: tuple[int, int, int, int],
    body: ImageFont.ImageFont,
    small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=8, fill="white", outline=(203, 213, 225), width=1)
    draw.text((x0 + 20, y0 + 18), "确认规格", fill=(15, 23, 42), font=body)
    rows = [("产品名称", product.get("name", "")), ("品牌", product.get("brand", "")), ("型号", product.get("model", ""))]
    for item in product.get("specs", []):
        rows.append((str(item.get("key", "")), f"{item.get('value', '')}{item.get('unit', '')}"))
    y = y0 + 64
    for label, value in rows[:7]:
        draw.line((x0, y - 8, x1, y - 8), fill=(226, 232, 240), width=1)
        draw.text((x0 + 18, y), _clip(label, 8), fill=(71, 85, 105), font=small)
        draw.text((x0 + 128, y), _clip(value, 16), fill=(30, 41, 59), font=small)
        y += 52


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int,
    line_height: int,
    max_lines: int,
) -> None:
    x, y = xy
    for line in _wrap_text(draw, str(text), font, max_width, max_lines):
        draw.text((x, y), line, fill=fill, font=font)
        y += line_height


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = char
            if len(lines) == max_lines:
                return lines
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _paste_cover(canvas: Image.Image, source: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    fitted = ImageOps.fit(source.convert("RGB"), (x1 - x0, y1 - y0), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    canvas.paste(fitted, (x0, y0))


def _fit_width(source: Image.Image, width: int) -> Image.Image:
    image = source.convert("RGB")
    if image.width == width:
        return image.copy()
    height = max(1, round(image.height * (width / image.width)))
    return image.resize((width, height), resample=Image.Resampling.LANCZOS)


def _sales_points(product: dict[str, Any], project: dict[str, Any], limit: int) -> list[str]:
    config = project.get("detail_config", {}) if isinstance(project.get("detail_config", {}), dict) else {}
    points = [str(point) for point in config.get("selling_points", []) if str(point).strip()]
    if not points:
        points = [product.get("material", ""), product.get("color", "")]
    return [point for point in points if point][:limit]


def _paste_rgba_with_shadow(base: Image.Image, overlay: Image.Image, xy: tuple[int, int]) -> None:
    base_rgba = base.convert("RGBA")
    alpha = overlay.getchannel("A")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(8))
    shadow = Image.new("RGBA", overlay.size, (0, 0, 0, 90))
    shadow.putalpha(shadow_alpha)
    base_rgba.alpha_composite(shadow, (xy[0] + 9, xy[1] + 12))
    base_rgba.alpha_composite(overlay, xy)
    base.paste(base_rgba.convert("RGB"))


def _tint_barcode_for_box(barcode: Image.Image) -> None:
    pixels = barcode.load()
    for y in range(barcode.height):
        for x in range(barcode.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if r < 80 and g < 80 and b < 80:
                pixels[x, y] = (24, 24, 20, 210)
            else:
                pixels[x, y] = (192, 151, 101, 42)


def _font(size: int, font_path: str = "") -> ImageFont.ImageFont:
    candidates = [
        font_path,
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _clip(value: object, length: int) -> str:
    text = str(value or "")
    return text[:length]


def _spec_model_text(product: dict[str, Any]) -> str:
    model = str(product.get("model", "") or "")
    specs = _spec_text(product)
    if not specs:
        return model
    return f"{model} / {specs}" if model else specs


def _spec_text(product: dict[str, Any]) -> str:
    specs = product.get("specs", [])
    if not specs:
        return ""
    return " / ".join(f"{item.get('key', '')}: {item.get('value', '')}{item.get('unit', '')}" for item in specs)


def _date_text(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return date.today().isoformat()


def _company_name(product: dict[str, Any], certificate_config: dict[str, Any]) -> str:
    return str(
        certificate_config.get("company_name")
        or product.get("company_name")
        or product.get("manufacturer")
        or product.get("manufacturer_name")
        or product.get("brand")
        or ""
    )
