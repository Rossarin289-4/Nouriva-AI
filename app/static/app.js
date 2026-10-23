
const $ = (id) => document.getElementById(id);

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"
  })[char]);
}

function setStatus(id, message, ok) {
  $(id).textContent = message;
  $(id).style.color = ok ? "#076653" : "#B4533C";
}

function ruleStatusClass(status) {
  if (status === "active") return "good";
  if (["draft", "reviewed", "needs_review",
       "needs_expert_review", "needs_design"].includes(status)) {
    return "review";
  }
  return "neutral";
}

async function loadDashboard() {
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "…";

  setStatus("apiStatus", "กำลังตรวจสอบ", true);
  setStatus("dbStatus", "กำลังตรวจสอบ", true);

  const results = await Promise.allSettled([
    getJSON("/health/db"),
    getJSON("/rules"),
    getJSON("/foods?limit=100"),
    getJSON("/rules/NUT-001")
  ]);

  // หน้าเว็บโหลดจาก FastAPI อยู่ จึงเข้าถึง Backend ได้
  setStatus("apiStatus", "Online", true);

  const [dbResult, rulesResult, foodsResult, nutResult] = results;

  if (dbResult.status === "fulfilled" &&
      dbResult.value.database === "connected") {
    setStatus("dbStatus", "Connected", true);
  } else {
    setStatus("dbStatus", "Disconnected", false);
  }

  if (rulesResult.status === "fulfilled") {
    const data = rulesResult.value;
    const count = data.count ??
      data.items?.length ??
      data.rules?.length;

    $("ruleCount").textContent = count ?? "—";
  } else {
    $("ruleCount").textContent = "โหลดไม่ได้";
  }

  if (foodsResult.status === "fulfilled") {
    const data = foodsResult.value;
    $("foodCount").textContent = data.count ?? 0;
    renderFoods(data.items ?? []);
  } else {
    $("foodCount").textContent = "โหลดไม่ได้";
    $("foodMessage").textContent = "โหลดรายการอาหารไม่สำเร็จ";
  }

  if (nutResult.status === "fulfilled") {
    const data = nutResult.value;
    const rule = data.item ?? data.rule ?? data;
    const status = rule.lifecycle_status ?? "ไม่พบสถานะ";

    $("nutRuleStatus").textContent = status;
    $("nutRuleStatus").className =
      `pill ${ruleStatusClass(status)}`;
  } else {
    $("nutRuleStatus").textContent = "โหลดไม่ได้";
    $("nutRuleStatus").className = "pill neutral";
  }

  $("refreshBtn").disabled = false;
  $("refreshBtn").textContent = "↻";
}

function renderFoods(items) {
  const results = $("foodResults");
  results.innerHTML = "";

  if (!items.length) {
    $("foodMessage").textContent =
      "ไม่พบอาหาร ลองค้นหาด้วยชื่ออื่น";
    return;
  }

  $("foodMessage").textContent = `พบ ${items.length} รายการ`;

  items.forEach((food) => {
    const name = food.name_th || food.name_en || "ไม่ระบุชื่อ";
    const status = food.verification_status || "unverified";
    const isVerified = ["reviewed", "source_verified",
      "user_confirmed"].includes(status);

    const row = document.createElement("article");
    row.className = "food-item";

    row.innerHTML = `
      <div class="food-info">
        <div class="food-thumb">🥑</div>
        <div>
          <strong>${escapeHTML(name)}</strong>
          <p>${escapeHTML(food.brand_name || food.item_type || "อาหาร")}</p>
          <span class="pill ${isVerified ? "good" : "review"}">
            ${escapeHTML(status)}
          </span>
        </div>
      </div>
      <button type="button">ดูสารอาหาร →</button>
    `;

    row.querySelector("button").addEventListener("click", () => {
      loadNutrition(food.food_id, name);
    });

    results.appendChild(row);
  });
}

async function searchFoods(search) {
  $("foodMessage").textContent = "กำลังค้นหา...";
  $("foodResults").innerHTML = "";
  $("nutritionPanel").classList.add("hidden");

  try {
    const params = new URLSearchParams({ limit: "100" });
    if (search.trim()) params.set("search", search.trim());

    const data = await getJSON(`/foods?${params}`);
    $("foodCount").textContent = data.count ?? 0;
    renderFoods(data.items ?? []);
  } catch (error) {
    $("foodMessage").textContent =
      `ค้นหาไม่สำเร็จ: ${error.message}`;
  }
}

async function calculateFoodNutrition(foodId, foodName) {
  const panel = $("nutritionPanel");
  const weightInput = $("eatenWeightInput");
  const message = $("calculationMessage");
  const button = $("calculateNutritionBtn");

  // ล้างผลคำนวณเก่าก่อนตรวจเงื่อนไข เพื่อไม่ให้ผลเดิมค้าง
  const oldResult = $("consumedNutritionResult");
  if (oldResult) oldResult.remove();

  // ป้องกันการเรียก API หากกฎหรือข้อมูลยังไม่ผ่านเงื่อนไข
  if (!button || button.dataset.canCalculate !== "true") {
    if (message) {
      message.textContent =
        "ยังคำนวณไม่ได้: กฎหรือข้อมูลโภชนาการยังไม่ผ่านเงื่อนไขการตรวจสอบ";
    }
    return;
  }

  const weight = Number(weightInput?.value);

  if (!Number.isFinite(weight) || weight <= 0) {
    message.textContent = "กรุณากรอกน้ำหนักที่มากกว่า 0 กรัม";
    return;
  }

  button.disabled = true;
  message.textContent = "กำลังตรวจสอบข้อมูลและคำนวณ...";

  try {
    const response = await fetch("/nutrition/calculate-from-food", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        food_id: foodId,
        eaten_weight_g: weight
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }

    if (data.status === "rule_not_active") {
      message.textContent =
        `ยังคำนวณไม่ได้: กฎ ${data.rule_code || "NUT-001"} ` +
        `ยังมีสถานะ ${data.lifecycle_status || "ไม่เปิดใช้งาน"} ` +
        "จึงยังไม่แสดงผลสารอาหารที่ได้รับ";
      return;
    }

    if (data.status === "data_needs_review") {
      message.textContent =
        "ยังคำนวณไม่ได้: ข้อมูลอาหารหรือข้อมูลโภชนาการยังไม่ผ่านการตรวจสอบ";
      return;
    }

    if (data.status !== "calculated") {
      message.textContent = data.message || "ยังไม่สามารถคำนวณได้";
      return;
    }

    message.textContent = data.message || "คำนวณสารอาหารสำเร็จ";

    const nutrients = Array.isArray(data.nutrients) ? data.nutrients : [];

    if (!nutrients.length) {
      message.textContent = "ไม่พบรายการสารอาหารที่คำนวณได้";
      return;
    }

    const result = document.createElement("div");
    result.id = "consumedNutritionResult";

    const heading = document.createElement("h4");
    heading.textContent =
      `สารอาหารที่ได้รับจาก ${foodName} (${data.eaten_weight_g} กรัม)`;
    result.appendChild(heading);

    const wrapper = document.createElement("div");
    wrapper.style.overflowX = "auto";

    const table = document.createElement("table");
    table.className = "nutrition-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    ["สารอาหาร", "ปริมาณที่ได้รับ", "หน่วย"].forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);

    const tbody = document.createElement("tbody");

    nutrients.forEach((item) => {
      const row = document.createElement("tr");

      const nameCell = document.createElement("td");
      nameCell.textContent =
        item.name_th || item.name_en || item.nutrient_code || "ไม่ระบุ";

      const amountCell = document.createElement("td");
      amountCell.textContent = String(item.consumed);

      const unitCell = document.createElement("td");
      unitCell.textContent = item.unit || "";

      row.append(nameCell, amountCell, unitCell);
      tbody.appendChild(row);
    });

    table.append(thead, tbody);
    wrapper.appendChild(table);
    result.appendChild(wrapper);

    const ruleNote = document.createElement("p");
    ruleNote.className = "notice";
    ruleNote.textContent =
      `คำนวณตามกฎ ${data.rule?.rule_code || "ไม่ระบุ"} ` +
      `(${data.rule?.lifecycle_status || "ไม่ระบุ"}) ` +
      `โดยใช้ข้อมูลที่ระบบอนุญาตให้คำนวณ`;
    result.appendChild(ruleNote);

    message.insertAdjacentElement("afterend", result);
  } catch (error) {
    message.textContent = `คำนวณไม่สำเร็จ: ${error.message}`;
  } finally {
    // ไม่เปิดปุ่ม หากข้อมูลหรือกฎยังไม่ผ่านเงื่อนไข
    button.disabled = button.dataset.canCalculate !== "true";
  }
}

async function loadNutrition(foodId, foodName) {
  const panel = $("nutritionPanel");
  panel.classList.remove("hidden");
  panel.innerHTML = "<p>กำลังโหลดสารอาหาร...</p>";

  try {
    const data = await getJSON(
      `/foods/${encodeURIComponent(foodId)}/nutrition`
    );
    const rows = data.nutrition ?? [];

    const table = rows.length ? `
      <div style="overflow-x:auto">
        <table class="nutrition-table">
          <thead>
            <tr>
              <th>สารอาหาร</th>
              <th>ปริมาณ</th>
              <th>หน่วย</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((item) => `
              <tr>
                <td>${escapeHTML(
                  item.nutrient_name_th ||
                  item.nutrient_name_en ||
                  item.nutrient_code
                )}</td>
                <td>${escapeHTML(item.amount)}</td>
                <td>${escapeHTML(item.nutrient_unit)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    ` : "<p>ยังไม่มีข้อมูลสารอาหาร</p>";

    const basis = rows[0];
    const source = data.source || {};
    const sourceUrl = source.source_url || "";
    const safeSourceUrl = /^https:\/\//i.test(sourceUrl)
      ? sourceUrl
      : "";
    const sourceDetails = `
      <section class="notice" aria-label="แหล่งข้อมูลสารอาหาร">
        <h4>แหล่งข้อมูลและการตรวจสอบ</h4>
        <p>
          แหล่งข้อมูล:
          ${escapeHTML(source.source_name || source.source_code || "ไม่ระบุ")}
        </p>
        <p>
          รหัสระเบียน:
          ${escapeHTML(source.source_record_id || "ไม่ระบุ")}
        </p>
        <p>
          สถานะข้อมูลโภชนาการ:
          ${escapeHTML(source.verification_status || "ไม่ระบุ")}
        </p>
        ${
          safeSourceUrl
            ? `<p><a href="${escapeHTML(safeSourceUrl)}"
                 target="_blank" rel="noopener noreferrer">
                 เปิดเอกสารแหล่งข้อมูล
               </a></p>`
            : "<p>ยังไม่มี URL แหล่งข้อมูลสำหรับรายการนี้</p>"
        }
        ${
          source.license_or_attribution
            ? `<p>ข้อกำหนดการอ้างอิง: ${
                escapeHTML(source.license_or_attribution)
              }</p>`
            : ""
        }
        ${
          source.notes
            ? `<p>หมายเหตุ: ${escapeHTML(source.notes)}</p>`
            : ""
        }
      </section>
    `;

    const trustedStatuses = ["reviewed", "source_verified"];
    const basisStatus = basis?.verification_status || "ไม่ระบุ";
    const isTrustedBasis = trustedStatuses.includes(basisStatus);
    const foodStatus = data.food?.verification_status || "ไม่ระบุ";
    const trustedFood = trustedStatuses.includes(foodStatus);

    let nutritionRuleActive = false;
    let nutritionRuleStatus = "ตรวจสอบไม่ได้";

    try {
      const ruleData = await getJSON("/rules/NUT-001");
      nutritionRuleStatus = ruleData.lifecycle_status || "ไม่ระบุ";
      nutritionRuleActive = nutritionRuleStatus === "active";
    } catch (ruleError) {
      nutritionRuleActive = false;
    }

    const canCalculate =
      isTrustedBasis && trustedFood && nutritionRuleActive;

    const nutritionWarning = rows.length && (!isTrustedBasis || !trustedFood)
      ? `
        <div class="notice" role="alert">
          <strong>ข้อมูลอาหารหรือสารอาหารยังไม่ผ่านการตรวจสอบ</strong>
          <p>
            สถานะอาหาร: ${escapeHTML(foodStatus)}<br>
            สถานะฐานโภชนาการ: ${escapeHTML(basisStatus)}<br>
            ตัวเลขในตารางเป็นข้อมูลอ้างอิงจากฐานข้อมูล
            ไม่ใช่ผลคำนวณจากน้ำหนักอาหารที่รับประทาน
            โปรดตรวจสอบแหล่งอ้างอิงก่อนนำไปใช้งานจริง
          </p>
        </div>
      `
      : "";

    let portionItems = [];
    let portionLoadMessage = "กำลังโหลดหน่วยบริโภค...";

    try {
      const portionData = await getJSON(
        `/foods/${encodeURIComponent(foodId)}/portions`
      );
      portionItems = Array.isArray(portionData.items)
        ? portionData.items
        : [];
      portionLoadMessage = portionItems.length
        ? "เลือกหน่วยบริโภคเพื่อเติมน้ำหนักโดยประมาณ"
        : "ยังไม่มีหน่วยบริโภคที่ผ่านการตรวจสอบ คุณสามารถกรอกน้ำหนักเป็นกรัมได้";
    } catch (portionError) {
      portionLoadMessage =
        "โหลดหน่วยบริโภคไม่ได้ คุณยังสามารถกรอกน้ำหนักเป็นกรัมได้";
    }

    const portionOptions = portionItems.map((item) => {
      const label = [
        item.portion_name_th || item.portion_name_en || item.unit_name,
        `${item.weight_g} กรัม`
      ].filter(Boolean).join(" — ");

      return `
        <option value="${escapeHTML(item.weight_g)}">
          ${escapeHTML(label)}
        </option>
      `;
    }).join("");

    panel.innerHTML = `
      <h3>${escapeHTML(foodName)}</h3>
      ${nutritionWarning}
      <p class="subtext">
        ข้อมูลต่อ ${escapeHTML(basis?.basis_quantity ?? "—")}
        ${escapeHTML(basis?.basis_unit ?? "")}
      </p>
      ${table}
      ${sourceDetails}
      <div class="calculation-form">
        <label for="portionSelect">หน่วยบริโภคที่มีข้อมูลตรวจสอบแล้ว</label>
        <select id="portionSelect">
          <option value="">กรอกน้ำหนักเอง</option>
          ${portionOptions}
        </select>
        <p id="portionMessage" class="message" aria-live="polite">
          ${escapeHTML(portionLoadMessage)}
        </p>

        <label for="eatenWeightInput">น้ำหนักอาหารที่รับประทาน (กรัม)</label>
        <div class="barcode-input-row">
          <input
            id="eatenWeightInput"
            type="number"
            min="0.1"
            step="any"
            value="100"
            aria-label="น้ำหนักอาหารที่รับประทานเป็นกรัม"
          >
          <button
            id="calculateNutritionBtn"
            type="button"
            data-can-calculate="${String(canCalculate)}"
            ${canCalculate ? "" : "disabled"}
          >
            คำนวณสารอาหารที่ได้รับ
          </button>
        </div>
        <p id="calculationMessage" class="message" aria-live="polite">
          ${!nutritionRuleActive
            ? `ยังคำนวณไม่ได้: กฎ NUT-001 มีสถานะ ${escapeHTML(nutritionRuleStatus)}`
            : !trustedFood || !isTrustedBasis
              ? "ยังคำนวณไม่ได้: ข้อมูลอาหารหรือข้อมูลโภชนาการยังไม่ผ่านการตรวจสอบ"
              : "กรอกน้ำหนักแล้วกดคำนวณ"}
        </p>
      </div>
      <p class="notice">
        สถานะข้อมูล: ${escapeHTML(
          basis?.verification_status ?? "ไม่ระบุ"
        )} — โปรดตรวจสอบกับแหล่งข้อมูลก่อนใช้งานจริง
      </p>
    `;

    $("portionSelect").addEventListener("change", (event) => {
      const selectedWeight = Number(event.target.value);
      if (Number.isFinite(selectedWeight) && selectedWeight > 0) {
        $("eatenWeightInput").value = String(selectedWeight);
      }
    });

    $("calculateNutritionBtn").addEventListener("click", () => {
      calculateFoodNutrition(foodId, foodName);
    });

    $("eatenWeightInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (!canCalculate) {
          $("calculationMessage").textContent =
            "ยังคำนวณไม่ได้: โปรดตรวจสอบสถานะกฎและข้อมูลโภชนาการก่อน";
          return;
        }
        calculateFoodNutrition(foodId, foodName);
      }
    });

    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    panel.innerHTML =
      `<p>โหลดข้อมูลไม่สำเร็จ: ${escapeHTML(error.message)}</p>`;
  }
}

$("searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  searchFoods($("searchInput").value);
});

$("refreshBtn").addEventListener("click", loadDashboard);

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".nav-item")
      .forEach((nav) => nav.classList.remove("active"));
    item.classList.add("active");
  });
});



// Barcode lookup: query only existing, active foods in the backend.
async function lookupBarcode(rawCode) {
  const code = rawCode.trim();
  const result = $("barcodeResult");
  const message = $("scannerMessage");

  result.classList.add("hidden");
  result.textContent = "";

  if (!code) {
    message.textContent = "กรุณากรอกรหัส Barcode หรือ QR Code";
    return;
  }

  message.textContent = "กำลังค้นหารหัสในคลังอาหาร...";

  try {
    const response = await fetch(
      `/foods/barcode/${encodeURIComponent(code)}`
    );
    const data = await response.json().catch(() => ({}));

    if (response.status === 404) {
      message.textContent =
        "ยังไม่มีข้อมูลสินค้านี้ในคลังอาหาร ลองค้นหาชื่ออาหารหรือกรอกรหัสอื่น";
      return;
    }

    if (!response.ok) {
      message.textContent =
        data.detail || "ค้นหารหัสไม่สำเร็จ กรุณาลองอีกครั้ง";
      return;
    }

    const food = data.item || {};
    const name = food.name_th || food.name_en || "ไม่ระบุชื่อ";
    result.innerHTML = `
      <h3>${escapeHTML(name)}</h3>
      <p>แบรนด์: ${escapeHTML(food.brand_name || "ไม่ระบุ")}</p>
      <p>Barcode: ${escapeHTML(food.barcode || code)}</p>
      <p>ประเภท: ${escapeHTML(food.barcode_type || "ไม่ระบุ")}</p>
      <p>สถานะข้อมูล: ${escapeHTML(
        food.verification_status || "ไม่ระบุ"
      )}</p>
      <button id="barcodeNutritionBtn" type="button">
        ดูข้อมูลสารอาหาร
      </button>
    `;
    result.classList.remove("hidden");
    message.textContent = "พบอาหารในคลังข้อมูลแล้ว";

    $("barcodeNutritionBtn").addEventListener("click", () => {
      loadNutrition(food.food_id, name);
    });
  } catch (error) {
    message.textContent =
      `เชื่อมต่อ API ไม่สำเร็จ: ${error.message}`;
  }
}

$("barcodeForm").addEventListener("submit", (event) => {
  event.preventDefault();
  lookupBarcode($("barcodeInput").value);
});

let barcodeStream = null;
let barcodeAnimation = null;
let barcodeDetector = null;

function stopBarcodeScanner() {
  if (barcodeAnimation !== null) {
    cancelAnimationFrame(barcodeAnimation);
    barcodeAnimation = null;
  }

  if (barcodeStream) {
    barcodeStream.getTracks().forEach((track) => track.stop());
    barcodeStream = null;
  }

  const video = $("scannerVideo");
  video.pause();
  video.srcObject = null;
  video.classList.add("hidden");
  $("stopScannerBtn").disabled = true;
  $("startScannerBtn").disabled = false;
}

async function scanVideoFrame() {
  if (!barcodeStream || !barcodeDetector) return;

  const video = $("scannerVideo");
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    try {
      const detected = await barcodeDetector.detect(video);
      if (detected.length && detected[0].rawValue) {
        const code = detected[0].rawValue;
        $("barcodeInput").value = code;
        stopBarcodeScanner();
        await lookupBarcode(code);
        return;
      }
    } catch (error) {
      $("scannerMessage").textContent =
        "อ่านภาพจากกล้องไม่สำเร็จ ลองจัดตำแหน่งรหัสใหม่";
    }
  }

  if (barcodeStream) {
    barcodeAnimation = requestAnimationFrame(scanVideoFrame);
  }
}

$("startScannerBtn").addEventListener("click", async () => {
  const message = $("scannerMessage");

  if (!("BarcodeDetector" in window)) {
    message.textContent =
      "เบราว์เซอร์นี้ยังไม่รองรับตัวสแกนในตัว ลองกรอกรหัสเองก่อน";
    return;
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    message.textContent =
      "ไม่สามารถเปิดกล้องได้ กรุณาใช้ localhost หรือ HTTPS บนอุปกรณ์ที่รองรับ";
    return;
  }

  try {
    const supported = await BarcodeDetector.getSupportedFormats();
    const wanted = [
      "qr_code", "ean_13", "ean_8", "upc_a", "upc_e",
      "code_128", "code_39", "itf", "data_matrix", "pdf417"
    ];
    const formats = wanted.filter((format) => supported.includes(format));

    if (!formats.length) {
      message.textContent =
        "เบราว์เซอร์ไม่รองรับรูปแบบ Barcode/QR ที่ต้องการ";
      return;
    }

    barcodeDetector = new BarcodeDetector({ formats });
    barcodeStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false
    });

    const video = $("scannerVideo");
    video.srcObject = barcodeStream;
    video.classList.remove("hidden");
    await video.play();

    $("startScannerBtn").disabled = true;
    $("stopScannerBtn").disabled = false;
    message.textContent =
      "เปิดกล้องแล้ว วาง Barcode หรือ QR Code ให้ชัดในภาพ";

    scanVideoFrame();
  } catch (error) {
    stopBarcodeScanner();
    message.textContent =
      `เปิดกล้องไม่ได้: ${error.message}. ตรวจสิทธิ์กล้องของเบราว์เซอร์`;
  }
});

$("stopScannerBtn").addEventListener("click", () => {
  stopBarcodeScanner();
  $("scannerMessage").textContent = "ปิดกล้องแล้ว";
});

$("foodImageInput").addEventListener("change", () => {
  const file = $("foodImageInput").files?.[0];
  const preview = $("foodImagePreview");
  const message = $("imageMessage");

  if (!file) {
    preview.classList.add("hidden");
    preview.removeAttribute("src");
    message.textContent = "ยังไม่ได้เลือกภาพ";
    return;
  }

  if (!file.type.startsWith("image/")) {
    $("foodImageInput").value = "";
    preview.classList.add("hidden");
    message.textContent = "กรุณาเลือกไฟล์ภาพ";
    return;
  }

  if (file.size > 10 * 1024 * 1024) {
    $("foodImageInput").value = "";
    preview.classList.add("hidden");
    message.textContent = "ภาพใหญ่เกินไป กรุณาเลือกภาพขนาดไม่เกิน 10 MB";
    return;
  }

  preview.src = URL.createObjectURL(file);
  preview.classList.remove("hidden");
  message.textContent =
    `เลือกภาพแล้ว: ${file.name} — ยังไม่ได้ส่งภาพไป OCR หรือบันทึกลงระบบ`;
});


// Search foods by a name typed by the user in the photo section.
// This does not perform AI image recognition.
async function searchFoodsFromImage() {
  const input = $("imageFoodSearch");
  const message = $("imageFoodMessage");
  const results = $("imageFoodResults");

  if (!input || !message || !results) {
    console.error("ไม่พบองค์ประกอบค้นหาอาหารจากภาพใน index.html");
    return;
  }

  const query = input.value.trim();
  results.innerHTML = "";

  if (!query) {
    message.textContent = "กรุณาพิมพ์ชื่ออาหารก่อนค้นหา";
    return;
  }

  message.textContent = "กำลังค้นหาอาหารในคลัง...";
  results.innerHTML = "";

  try {
    const params = new URLSearchParams({
      search: query,
      limit: "100"
    });
    const data = await getJSON(`/foods?${params}`);
    const items = data.items ?? [];

    if (!items.length) {
      message.textContent =
        "ไม่พบอาหารชื่อนี้ในคลัง ลองใช้ชื่ออื่น";
      return;
    }

    message.textContent =
      `พบ ${items.length} รายการ — เลือกรายการที่ตรงกับอาหารของคุณ`;

    items.forEach((food) => {
      const name = food.name_th || food.name_en || "ไม่ระบุชื่อ";
      const status = food.verification_status || "unverified";

      const row = document.createElement("article");
      row.className = "food-item";

      const info = document.createElement("div");
      info.className = "food-info";

      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = name;

      const description = document.createElement("p");
      description.textContent =
        food.brand_name || food.item_type || "อาหาร";

      const statusText = document.createElement("p");
      statusText.textContent = `สถานะข้อมูล: ${status}`;

      details.append(title, description, statusText);
      info.appendChild(details);

      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "เลือกอาหารและดูสารอาหาร";

      button.addEventListener("click", async () => {
        message.textContent =
          `กำลังโหลดข้อมูลของ ${name}...`;

        await loadNutrition(food.food_id, name);
        message.textContent =
          `เลือก ${name} แล้ว โปรดตรวจสอบสถานะข้อมูลก่อนนำไปใช้`;
      });

      row.append(info, button);
      results.appendChild(row);
    });
  } catch (error) {
    message.textContent =
      `ค้นหาไม่สำเร็จ: ${error.message}`;
  }
}

const imageFoodSearchButton = $("imageFoodSearchBtn");
const imageFoodSearchInput = $("imageFoodSearch");

if (imageFoodSearchButton && imageFoodSearchInput) {
  imageFoodSearchButton.addEventListener(
    "click",
    searchFoodsFromImage
  );

  imageFoodSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchFoodsFromImage();
    }
  });
}

window.addEventListener("beforeunload", stopBarcodeScanner);

loadDashboard();
