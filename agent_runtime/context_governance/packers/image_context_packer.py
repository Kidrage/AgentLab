from __future__ import annotations
from pathlib import Path
from ..schemas import ContextBudget, ContextProfile
from .base import evidence, external, make_pack, omitted, section, source_ref


class ImageContextPacker:
    def pack(self, profile: ContextProfile, budget: ContextBudget, request_text: str = "", run_dir: Path | None = None):
        mock = source_ref(run_dir, "image_ocr_mock.json")
        sections = [section("image_metadata", "Image metadata placeholder", "Image size/type/source metadata placeholder.", [mock]), section("ocr_layout", "OCR/layout placeholder", "Uses mock OCR/layout only; no real OCR/model in P2-G.", [mock]), section("crop_candidates", "Crop candidates placeholder", f"At most {budget.max_crops} crop refs are planned.", [mock])]
        return make_pack(profile, budget, sections, omitted_sections=[omitted("Raw pixels not embedded in context.", mock)], externalized=[external(mock, "raw_input", "Image/OCR mock remains externalized.")], evidence_refs=[evidence(mock, "image_ocr_mock")], warnings=["No real OCR or image model is invoked in P2-G."])