"""
OMNIX Visual Physics Engine — Image Analysis Pipeline (v2)

Multi-pass analysis that extracts deep features from device photos:
  Pass 1: Segmentation — isolate device from background
  Pass 2: Geometry — shape, contour, convex hull analysis
  Pass 3: Texture — surface roughness, reflectance, patterns
  Pass 4: Color — dominant colors, material estimation, gradient analysis
  Pass 5: Structure — component detection (rotors, arms, wheels, LEDs, panels)
  Pass 6: Spatial — component layout, symmetry axes, density mapping
  Pass 7: Size — relative and absolute estimation
  Pass 8: Annotation — visual overlay of all findings
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
import base64
import math
import time


@dataclass
class DetectedComponent:
    """A structural component found in the image."""
    name: str
    confidence: float
    bounding_box: tuple     # (x, y, w, h)
    area: float
    centroid: tuple          # (cx, cy)
    shape: str = "circle"    # circle, rectangle, line
    angle: float = 0         # orientation in degrees
    color_rgb: tuple = (128, 128, 128)


@dataclass
class ImageAnalysis:
    """Full analysis results from the image pipeline."""
    # Basic
    image_size: tuple = (0, 0)
    main_object_bbox: Optional[tuple] = None
    main_object_area: float = 0
    main_object_contour: Optional[np.ndarray] = None

    # Shape features (Pass 2)
    aspect_ratio: float = 0
    solidity: float = 0
    circularity: float = 0
    extent: float = 0
    symmetry_score: float = 0
    complexity: float = 0
    num_corners: int = 0
    num_edges: int = 0
    convex_defects_count: int = 0   # indentations in hull
    elongation: float = 0           # min_dim / max_dim of bounding ellipse
    contour_roughness: float = 0    # how jagged the outline is
    hull_ratio: float = 0           # convex hull perimeter / contour perimeter

    # Texture features (Pass 3)
    texture_energy: float = 0       # Laplacian variance — sharp edges
    texture_contrast: float = 0     # local contrast measure
    texture_homogeneity: float = 0  # how uniform the surface is
    specular_ratio: float = 0       # fraction of specular highlights
    edge_density: float = 0         # edges per unit area

    # Color profile (Pass 4)
    dominant_colors: list = field(default_factory=list)
    avg_brightness: float = 0
    color_variance: float = 0
    saturation_mean: float = 0
    saturation_std: float = 0
    hue_diversity: float = 0        # how many distinct hue clusters
    estimated_material: str = "unknown"
    has_bright_spots: bool = False   # LEDs, screens, etc.
    dark_ratio: float = 0           # fraction of very dark pixels

    # Structural (Pass 5)
    components: list = field(default_factory=list)
    has_rotary_elements: bool = False
    has_linear_elements: bool = False
    has_light_elements: bool = False
    has_panel_elements: bool = False
    estimated_axes_of_motion: int = 0
    rotary_count: int = 0
    linear_count: int = 0
    circle_count: int = 0
    strong_line_count: int = 0

    # Spatial layout (Pass 6)
    component_symmetry: float = 0   # how symmetric component placement is
    component_density: float = 0    # components per unit area
    vertical_bias: float = 0.5      # 0=bottom-heavy, 1=top-heavy, 0.5=balanced
    radial_symmetry: float = 0      # for round objects (wheels, vacuums)

    # Size (Pass 7)
    estimated_size_category: str = "medium"
    estimated_dimensions_cm: tuple = (30, 20, 15)
    object_fill_ratio: float = 0    # how much of the image the object fills

    # Timing
    pass_times_ms: dict = field(default_factory=dict)

    # Annotated image
    annotated_image_b64: str = ""

    def to_dict(self):
        return {
            "image_size": self.image_size,
            "main_object_bbox": self.main_object_bbox,
            "main_object_area": round(self.main_object_area, 1),
            "shape_features": {
                "aspect_ratio": round(self.aspect_ratio, 3),
                "solidity": round(self.solidity, 3),
                "circularity": round(self.circularity, 3),
                "extent": round(self.extent, 3),
                "symmetry_score": round(self.symmetry_score, 3),
                "complexity": round(self.complexity, 1),
                "num_corners": self.num_corners,
                "num_edges": self.num_edges,
                "convex_defects": self.convex_defects_count,
                "elongation": round(self.elongation, 3),
                "contour_roughness": round(self.contour_roughness, 3),
                "hull_ratio": round(self.hull_ratio, 3),
            },
            "texture_features": {
                "energy": round(self.texture_energy, 1),
                "contrast": round(self.texture_contrast, 1),
                "homogeneity": round(self.texture_homogeneity, 3),
                "specular_ratio": round(self.specular_ratio, 4),
                "edge_density": round(self.edge_density, 4),
            },
            "color_profile": {
                "dominant_colors": [
                    {"rgb": list(c), "hex": f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"}
                    for c in self.dominant_colors[:5]
                ],
                "avg_brightness": round(self.avg_brightness, 1),
                "color_variance": round(self.color_variance, 1),
                "saturation_mean": round(self.saturation_mean, 1),
                "hue_diversity": round(self.hue_diversity, 2),
                "estimated_material": self.estimated_material,
                "dark_ratio": round(self.dark_ratio, 3),
            },
            "structural": {
                "components": [
                    {"name": c.name, "confidence": round(c.confidence, 2),
                     "area": round(c.area, 1), "centroid": c.centroid,
                     "shape": c.shape, "angle": round(c.angle, 1)}
                    for c in self.components
                ],
                "has_rotary_elements": self.has_rotary_elements,
                "has_linear_elements": self.has_linear_elements,
                "has_light_elements": self.has_light_elements,
                "has_panel_elements": self.has_panel_elements,
                "estimated_axes_of_motion": self.estimated_axes_of_motion,
                "rotary_count": self.rotary_count,
                "linear_count": self.linear_count,
                "circle_count": self.circle_count,
                "strong_line_count": self.strong_line_count,
            },
            "spatial_layout": {
                "component_symmetry": round(self.component_symmetry, 3),
                "component_density": round(self.component_density, 4),
                "vertical_bias": round(self.vertical_bias, 3),
                "radial_symmetry": round(self.radial_symmetry, 3),
            },
            "size": {
                "category": self.estimated_size_category,
                "estimated_dimensions_cm": self.estimated_dimensions_cm,
                "object_fill_ratio": round(self.object_fill_ratio, 3),
            },
            "annotated_image": self.annotated_image_b64,
            "pass_times_ms": self.pass_times_ms,
        }


class ImageAnalyzer:
    """Multi-pass image analysis pipeline."""

    def analyze(self, image_data: bytes) -> ImageAnalysis:
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")

        analysis = ImageAnalysis(image_size=(img.shape[1], img.shape[0]))

        # Pass 1: Segmentation
        t = time.time()
        mask, main_contour = self._pass1_segment(img)
        analysis.pass_times_ms["segmentation"] = round((time.time() - t) * 1000, 1)

        if main_contour is not None:
            analysis.main_object_contour = main_contour

            # Pass 2: Geometry
            t = time.time()
            self._pass2_geometry(main_contour, img.shape, analysis)
            analysis.pass_times_ms["geometry"] = round((time.time() - t) * 1000, 1)

        # Pass 3: Texture
        t = time.time()
        self._pass3_texture(img, mask, analysis)
        analysis.pass_times_ms["texture"] = round((time.time() - t) * 1000, 1)

        # Pass 4: Color
        t = time.time()
        self._pass4_color(img, mask, analysis)
        analysis.pass_times_ms["color"] = round((time.time() - t) * 1000, 1)

        # Pass 5: Structure
        t = time.time()
        self._pass5_structure(img, mask, analysis)
        analysis.pass_times_ms["structure"] = round((time.time() - t) * 1000, 1)

        # Pass 6: Spatial layout
        t = time.time()
        self._pass6_spatial(img, analysis)
        analysis.pass_times_ms["spatial"] = round((time.time() - t) * 1000, 1)

        # Pass 7: Size
        t = time.time()
        self._pass7_size(img, main_contour, analysis)
        analysis.pass_times_ms["size"] = round((time.time() - t) * 1000, 1)

        # Pass 8: Annotation
        t = time.time()
        self._pass8_annotate(img, main_contour, analysis)
        analysis.pass_times_ms["annotation"] = round((time.time() - t) * 1000, 1)

        return analysis

    def analyze_from_base64(self, b64_string: str) -> ImageAnalysis:
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]
        return self.analyze(base64.b64decode(b64_string))

    def analyze_from_file(self, filepath: str) -> ImageAnalysis:
        with open(filepath, "rb") as f:
            return self.analyze(f.read())

    # ─── Pass 1: Segmentation ───

    def _pass1_segment(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        h, w = img.shape[:2]

        strategies = []

        # Strategy 1: Otsu
        _, t1 = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        strategies.append(t1)

        # Strategy 2: Adaptive
        t2 = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 11, 2)
        strategies.append(t2)

        # Strategy 3: Canny edge fill
        edges = cv2.Canny(blurred, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        t3 = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=3)
        strategies.append(t3)

        # Strategy 4: Center bias
        center_mask = np.zeros((h, w), dtype=np.uint8)
        mx, my = w // 6, h // 6
        center_mask[my:h - my, mx:w - mx] = 255
        strategies.append(center_mask)

        # Strategy 5: Color distance from border (background subtraction)
        border_pixels = np.concatenate([
            img[0, :], img[-1, :], img[:, 0], img[:, -1]
        ]).reshape(-1, 3).astype(np.float32)
        bg_color = np.median(border_pixels, axis=0)
        diff = np.sqrt(np.sum((img.astype(np.float32) - bg_color) ** 2, axis=2))
        # Try multiple thresholds — pick the one that gives best contour
        for thresh_val in [15, 25, 40, 60]:
            _, t5 = cv2.threshold(diff.astype(np.uint8), thresh_val, 255, cv2.THRESH_BINARY)
            strategies.append(t5.astype(np.uint8))

        # Strategy 6: Multi-threshold combination — AND of Otsu + background sub
        combined = cv2.bitwise_and(t1, strategies[-2]) if len(strategies) > 5 else t1
        strategies.append(combined)

        best_contour = None
        best_score = 0
        best_mask = strategies[0]

        for mask in strategies:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
            contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            ratio = area / (h * w)
            if 0.03 < ratio < 0.9:
                score = ratio * (1 - abs(ratio - 0.35)) * 2
                if score > best_score:
                    best_score = score
                    best_contour = largest
                    best_mask = cleaned

        if best_contour is None:
            for mask in strategies:
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    best_contour = max(contours, key=cv2.contourArea)
                    best_mask = mask
                    break

        return best_mask, best_contour

    # ─── Pass 2: Geometry ───

    def _pass2_geometry(self, contour, img_shape, a: ImageAnalysis):
        h, w = img_shape[:2]
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)

        x, y, bw, bh = cv2.boundingRect(contour)
        a.main_object_bbox = (x, y, bw, bh)
        a.main_object_area = area

        a.aspect_ratio = bw / max(bh, 1)

        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        hull_perim = cv2.arcLength(hull, True)
        a.solidity = area / max(hull_area, 1)

        if perimeter > 0:
            a.circularity = (4 * np.pi * area) / (perimeter ** 2)
            a.hull_ratio = hull_perim / perimeter

        a.extent = area / max(bw * bh, 1)

        if area > 0:
            a.complexity = (perimeter ** 2) / area

        # Corners
        epsilon = 0.015 * perimeter
        approx = cv2.approxPolyDP(contour, epsilon, True)
        a.num_corners = len(approx)
        a.num_edges = max(0, len(approx) - 1)

        # Convex defects — how many concavities
        hull_indices = cv2.convexHull(contour, returnPoints=False)
        try:
            defects = cv2.convexityDefects(contour, hull_indices)
            if defects is not None:
                significant = [d for d in defects if d[0][3] > 1000]
                a.convex_defects_count = len(significant)
        except Exception:
            a.convex_defects_count = 0

        # Elongation via fitted ellipse
        if len(contour) >= 5:
            (_, _), (ma, MA), _ = cv2.fitEllipse(contour)
            a.elongation = min(ma, MA) / max(ma, MA, 1)
        else:
            a.elongation = min(bw, bh) / max(bw, bh, 1)

        # Contour roughness: ratio of actual perimeter to smoothed perimeter
        smooth_eps = 0.05 * perimeter
        smooth_approx = cv2.approxPolyDP(contour, smooth_eps, True)
        smooth_perim = cv2.arcLength(smooth_approx, True)
        a.contour_roughness = perimeter / max(smooth_perim, 1) - 1

        # Symmetry
        a.symmetry_score = self._symmetry(contour, x, y, bw, bh)

    def _symmetry(self, contour, x, y, w, h):
        mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
        shifted = contour - np.array([x, y])
        cv2.drawContours(mask, [shifted], -1, 255, -1)
        flipped = cv2.flip(mask, 1)
        overlap = np.count_nonzero(cv2.bitwise_and(mask, flipped))
        union = max(np.count_nonzero(cv2.bitwise_or(mask, flipped)), 1)
        return overlap / union

    # ─── Pass 3: Texture ───

    def _pass3_texture(self, img, mask, a: ImageAnalysis):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Laplacian energy (edge sharpness)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        a.texture_energy = float(lap.var())

        # Local contrast: std dev in sliding windows
        blur = cv2.GaussianBlur(gray.astype(np.float64), (15, 15), 0)
        sqblur = cv2.GaussianBlur((gray.astype(np.float64)) ** 2, (15, 15), 0)
        local_std = np.sqrt(np.maximum(sqblur - blur ** 2, 0))
        a.texture_contrast = float(np.mean(local_std))

        # Homogeneity: inverse of local std
        a.texture_homogeneity = 1.0 / (1.0 + a.texture_contrast / 30)

        # Specular highlights
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        specular = np.sum((gray > 230) & (hsv[:, :, 1] < 30))
        a.specular_ratio = specular / max(h * w, 1)

        # Edge density (Canny edges per pixel in object area)
        edges = cv2.Canny(gray, 50, 150)
        obj_area = max(a.main_object_area, h * w * 0.1)
        a.edge_density = float(np.count_nonzero(edges)) / max(obj_area, 1)

    # ─── Pass 4: Color ───

    def _pass4_color(self, img, mask, a: ImageAnalysis):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        a.avg_brightness = float(np.mean(gray))

        pixels = img.reshape(-1, 3).astype(np.float32)
        a.dominant_colors = self._dominant_colors(pixels, k=5)
        a.color_variance = float(np.std(pixels))

        # Saturation stats
        sat = hsv[:, :, 1].astype(np.float32)
        a.saturation_mean = float(np.mean(sat))
        a.saturation_std = float(np.std(sat))

        # Hue diversity: count distinct hue bins with significant representation
        hue = hsv[:, :, 0].flatten()
        sat_flat = sat.flatten()
        # Only count pixels with enough saturation to have meaningful hue
        chromatic = hue[sat_flat > 30]
        if len(chromatic) > 100:
            hist, _ = np.histogram(chromatic, bins=18, range=(0, 180))
            threshold = len(chromatic) * 0.03
            a.hue_diversity = float(np.sum(hist > threshold)) / 18.0
        else:
            a.hue_diversity = 0.0

        # Dark pixel ratio
        a.dark_ratio = float(np.sum(gray < 50)) / max(gray.size, 1)

        # Bright spots (LEDs, screens)
        bright = (gray > 220) & (sat < 40)
        a.has_bright_spots = float(np.sum(bright)) / max(gray.size, 1) > 0.005

        # Material
        a.estimated_material = self._estimate_material(img, gray, hsv, a)

    def _dominant_colors(self, pixels, k=5):
        bin_size = 32
        quantized = (pixels // bin_size * bin_size + bin_size // 2).astype(np.uint8)
        sample_n = min(len(quantized), 15000)
        indices = np.random.choice(len(quantized), sample_n, replace=False)
        sampled = quantized[indices]
        unique = {}
        for px in sampled:
            key = tuple(px)
            unique[key] = unique.get(key, 0) + 1
        top = sorted(unique.items(), key=lambda x: -x[1])
        return [(int(c[2]), int(c[1]), int(c[0])) for c, _ in top[:k]]

    def _estimate_material(self, img, gray, hsv, a: ImageAnalysis) -> str:
        sat_mean = a.saturation_mean
        tex_e = a.texture_energy
        spec = a.specular_ratio
        dark = a.dark_ratio

        # Multi-factor material classification
        if spec > 0.05 and tex_e > 400:
            return "polished_metal"
        if spec > 0.02 and tex_e > 200 and sat_mean < 50:
            return "brushed_metal"
        if dark > 0.4 and tex_e < 150:
            return "carbon_fiber"
        if sat_mean > 100 and tex_e < 200:
            return "glossy_plastic"
        if sat_mean > 50 and tex_e < 300:
            return "matte_plastic"
        if tex_e < 80 and sat_mean < 40 and a.avg_brightness > 150:
            return "fabric_or_soft"
        if tex_e > 300 and sat_mean < 50:
            return "textured_metal"
        if sat_mean < 30 and a.avg_brightness < 100:
            return "dark_composite"
        if a.avg_brightness > 200 and sat_mean < 20:
            return "white_plastic"
        return "composite"

    # ─── Pass 5: Structure ───

    def _pass5_structure(self, img, mask, a: ImageAnalysis):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h_img, w_img = img.shape[:2]

        # ── Circles ──
        # Try multiple sensitivity levels to catch different sized circles
        all_circles = []
        for dp, p2, min_r, max_r in [
            (1.2, 50, 8, w_img // 5),
            (1.5, 35, 15, w_img // 3),
            (1.0, 60, 5, w_img // 8),
        ]:
            circles = cv2.HoughCircles(
                gray, cv2.HOUGH_GRADIENT, dp=dp, minDist=25,
                param1=100, param2=p2, minRadius=min_r, maxRadius=max_r
            )
            if circles is not None:
                for c in np.uint16(np.around(circles[0])):
                    # De-duplicate (don't add if too close to existing)
                    cx, cy, r = int(c[0]), int(c[1]), int(c[2])
                    dupe = any(abs(cx - ec[0]) < r and abs(cy - ec[1]) < r
                              for ec in all_circles)
                    if not dupe:
                        all_circles.append((cx, cy, r))

        a.circle_count = len(all_circles)

        for cx, cy, r in all_circles:
            area = np.pi * r * r
            rel_size = r / max(w_img, h_img)
            roi = img[max(0, cy - r):min(h_img, cy + r),
                      max(0, cx - r):min(w_img, cx + r)]
            if roi.size == 0:
                continue

            brightness = float(np.mean(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)))
            avg_color = tuple(int(x) for x in np.mean(roi, axis=(0, 1)))
            # Check for ring structure (hollow = rotor/wheel, solid = joint/LED)
            inner_r = max(1, r // 2)
            inner_roi = img[max(0, cy - inner_r):min(h_img, cy + inner_r),
                           max(0, cx - inner_r):min(w_img, cx + inner_r)]
            inner_bright = float(np.mean(inner_roi)) if inner_roi.size > 0 else brightness
            is_hollow = abs(brightness - inner_bright) > 20

            if rel_size > 0.1 and is_hollow:
                name = "rotor_assembly"
                a.has_rotary_elements = True
                a.rotary_count += 1
            elif rel_size > 0.06:
                name = "wheel_or_joint"
                a.has_rotary_elements = True
                a.rotary_count += 1
            elif brightness > 210 and a.saturation_mean < 50:
                name = "led_indicator"
                a.has_light_elements = True
            elif rel_size < 0.025:
                name = "sensor_or_button"
            else:
                name = "circular_component"

            conf = min(0.95, 0.5 + rel_size * 3)
            a.components.append(DetectedComponent(
                name=name, confidence=conf,
                bounding_box=(cx - r, cy - r, 2 * r, 2 * r),
                area=area, centroid=(cx, cy), shape="circle",
                color_rgb=(avg_color[2], avg_color[1], avg_color[0])
            ))

        # ── Lines ──
        edges = cv2.Canny(gray, 40, 130)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                                minLineLength=max(30, min(h_img, w_img) // 10),
                                maxLineGap=12)

        horiz, vert, diag = 0, 0, 0
        line_lengths = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
                length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                if length < 25:
                    continue
                line_lengths.append(length)
                if angle < 20 or angle > 160:
                    horiz += 1
                elif 70 < angle < 110:
                    vert += 1
                else:
                    diag += 1

        a.strong_line_count = horiz + vert + diag
        if a.strong_line_count > 2:
            a.has_linear_elements = True
            a.linear_count = a.strong_line_count

        # Add structural components for strong line clusters
        if horiz > 5:
            a.components.append(DetectedComponent(
                name="horizontal_frame", confidence=min(0.9, horiz / 15),
                bounding_box=(0, 0, 0, 0), area=0,
                centroid=(w_img // 2, h_img // 2), shape="line", angle=0
            ))
        if vert > 5:
            a.components.append(DetectedComponent(
                name="vertical_structure", confidence=min(0.9, vert / 15),
                bounding_box=(0, 0, 0, 0), area=0,
                centroid=(w_img // 2, h_img // 2), shape="line", angle=90
            ))
        if diag > 4:
            a.components.append(DetectedComponent(
                name="diagonal_strut", confidence=min(0.9, diag / 10),
                bounding_box=(0, 0, 0, 0), area=0,
                centroid=(w_img // 2, h_img // 2), shape="line", angle=45
            ))

        # ── Rectangular panels ──
        contours_all, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        rect_count = 0
        for cnt in contours_all:
            ca = cv2.contourArea(cnt)
            if ca < (h_img * w_img * 0.005) or ca > (h_img * w_img * 0.5):
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)
            if len(approx) == 4:
                x, y, rw, rh = cv2.boundingRect(approx)
                ar = rw / max(rh, 1)
                if 0.3 < ar < 3.0:
                    rect_count += 1
                    if rect_count <= 5:
                        a.components.append(DetectedComponent(
                            name="panel_or_plate", confidence=0.6,
                            bounding_box=(x, y, rw, rh), area=float(ca),
                            centroid=(x + rw // 2, y + rh // 2),
                            shape="rectangle", angle=0
                        ))
        if rect_count > 2:
            a.has_panel_elements = True

        # ── Axes of motion ──
        if a.has_rotary_elements and a.has_linear_elements:
            a.estimated_axes_of_motion = min(6, a.rotary_count + 1)
        elif a.has_rotary_elements:
            a.estimated_axes_of_motion = min(6, a.rotary_count)
        elif a.has_linear_elements:
            a.estimated_axes_of_motion = max(1, min(3, a.linear_count // 5))

    # ─── Pass 6: Spatial Layout ───

    def _pass6_spatial(self, img, a: ImageAnalysis):
        h, w = img.shape[:2]
        cx_img, cy_img = w / 2, h / 2

        comps = [c for c in a.components if c.area > 0]
        if len(comps) < 2:
            a.component_symmetry = a.symmetry_score
            return

        # Component symmetry: mirror component positions
        centroids = [(c.centroid[0], c.centroid[1]) for c in comps]
        mirror_score = 0
        for (px, py) in centroids:
            mx = w - px
            # Find closest component to mirrored position
            min_dist = min(math.sqrt((mx - qx) ** 2 + (py - qy) ** 2)
                          for (qx, qy) in centroids)
            rel_dist = min_dist / max(w, 1)
            mirror_score += max(0, 1 - rel_dist * 5)
        a.component_symmetry = mirror_score / max(len(centroids), 1)

        # Density
        bbox = a.main_object_bbox
        obj_area = (bbox[2] * bbox[3]) if bbox else (w * h)
        a.component_density = len(comps) / max(obj_area, 1)

        # Vertical bias
        if centroids:
            avg_y = np.mean([cy for _, cy in centroids])
            a.vertical_bias = avg_y / max(h, 1)

        # Radial symmetry: variance of distances from center
        if len(centroids) >= 3:
            dists = [math.sqrt((px - cx_img) ** 2 + (py - cy_img) ** 2)
                     for (px, py) in centroids]
            mean_d = np.mean(dists)
            if mean_d > 0:
                a.radial_symmetry = 1 - min(1, np.std(dists) / mean_d)

    # ─── Pass 7: Size ───

    def _pass7_size(self, img, contour, a: ImageAnalysis):
        h, w = img.shape[:2]
        if contour is None:
            return

        bbox = a.main_object_bbox or (0, 0, w, h)
        fill_ratio = (bbox[2] * bbox[3]) / max(w * h, 1)
        a.object_fill_ratio = fill_ratio

        nc = len(a.components)
        cpx = a.complexity
        rotary = a.rotary_count
        linear = a.linear_count
        defects = a.convex_defects_count

        # Multi-factor size estimation
        if nc > 10 and cpx > 50:
            a.estimated_size_category = "large"
            base = (80, 60, 40)
        elif nc > 6 or (cpx > 35 and defects > 3):
            a.estimated_size_category = "medium"
            base = (40, 30, 25)
        elif a.has_light_elements and nc < 3 and not a.has_rotary_elements:
            a.estimated_size_category = "small"
            base = (8, 8, 14)
        elif rotary >= 4:
            a.estimated_size_category = "medium"
            base = (35, 35, 15)
        elif cpx > 25:
            a.estimated_size_category = "small"
            base = (20, 15, 10)
        else:
            a.estimated_size_category = "medium"
            base = (25, 20, 15)

        # Adjust by aspect ratio
        ar = a.aspect_ratio
        a.estimated_dimensions_cm = (
            round(base[0] * max(ar, 0.5), 1),
            round(base[1] / max(ar, 0.5), 1),
            round(base[2], 1)
        )

    # ─── Pass 8: Annotation ───

    def _pass8_annotate(self, img, contour, a: ImageAnalysis):
        ann = img.copy()

        if contour is not None:
            cv2.drawContours(ann, [contour], -1, (0, 180, 216), 2)
            if a.main_object_bbox:
                x, y, bw, bh = a.main_object_bbox
                cv2.rectangle(ann, (x, y), (x + bw, y + bh), (0, 255, 200), 2)

        color_map = {
            "rotor_assembly": (0, 165, 255),
            "wheel_or_joint": (255, 165, 0),
            "led_indicator": (0, 255, 255),
            "sensor_or_button": (255, 0, 255),
            "circular_component": (200, 200, 0),
            "panel_or_plate": (100, 255, 100),
            "horizontal_frame": (255, 100, 100),
            "vertical_structure": (100, 100, 255),
            "diagonal_strut": (255, 255, 100),
        }

        for comp in a.components:
            color = color_map.get(comp.name, (128, 128, 128))
            cx, cy = comp.centroid
            if comp.shape == "circle":
                bx, by, bw, bh = comp.bounding_box
                r = bw // 2
                cv2.circle(ann, (cx, cy), r, color, 2)
            elif comp.shape == "rectangle":
                bx, by, bw, bh = comp.bounding_box
                cv2.rectangle(ann, (bx, by), (bx + bw, by + bh), color, 2)
            label = f"{comp.name} ({comp.confidence:.0%})"
            cv2.putText(ann, label, (cx - 40, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

        y_off = 20
        for line in [
            f"AR:{a.aspect_ratio:.2f} Circ:{a.circularity:.2f} Sol:{a.solidity:.2f} Sym:{a.symmetry_score:.2f}",
            f"Mat:{a.estimated_material} Size:{a.estimated_size_category} Comps:{len(a.components)}",
            f"Rotary:{a.rotary_count} Linear:{a.linear_count} Defects:{a.convex_defects_count}",
        ]:
            cv2.putText(ann, line, (10, y_off),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 180, 216), 1)
            y_off += 18

        _, buf = cv2.imencode(".jpg", ann, [cv2.IMWRITE_JPEG_QUALITY, 85])
        a.annotated_image_b64 = base64.b64encode(buf).decode("utf-8")
