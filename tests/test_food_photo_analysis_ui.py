from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_food_photo_capture_requires_consent_and_uses_real_analysis_endpoint():
    page = (ROOT / "app/static/index.html").read_text()
    script = (ROOT / "app/static/app.js").read_text()

    assert 'id="foodImageInput"' in page
    assert 'accept="image/jpeg,image/png,image/webp"' in page
    assert 'id="foodImageConsent"' in page
    assert 'id="analyzeFoodImageBtn"' in page
    assert 'fetch("/foods/image-analysis"' in script
    assert '"X-Food-Image-Consent": "true"' in script
    assert 'if (!$("foodImageConsent").checked)' in script
    assert 'credentials: "same-origin"' in script


def test_food_photo_output_is_a_proposal_and_does_not_render_nutrition_values():
    script = (ROOT / "app/static/app.js").read_text()
    assert 'data.status !== "proposed"' in script
    assert 'data.food_identification' in script
    assert 'textContent = value' in script
    assert 'สารอาหาร: ยังไม่คำนวณ' in script
    assert 'weight_g: unit.value === "g" ? amount : null' in script
    assert 'volume_ml: unit.value === "ml" ? amount : null' in script


def test_food_photo_confirmation_saves_to_selected_meal_with_review_source():
    script = (ROOT / "app/static/app.js").read_text()
    assert 'fetch(`/meals/${encodeURIComponent(selectedMealId)}/items`' in script
    assert 'entry_source: "food_image"' in script
    assert 'if (!confirm.checked)' in script
    assert 'if (saving || saved) return' in script
    assert 'result.item.meal_log_id !== selectedMealId' in script
    assert 'result.item.quantity_unit !== selectedUnit' in script
    assert 'สถานะ needs_review' in script
