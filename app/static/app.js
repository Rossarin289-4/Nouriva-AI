
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

    panel.innerHTML = `
      <h3>${escapeHTML(foodName)}</h3>
      <p class="subtext">
        ข้อมูลต่อ ${escapeHTML(basis?.basis_quantity ?? "—")}
        ${escapeHTML(basis?.basis_unit ?? "")}
      </p>
      ${table}
      <p class="notice">
        สถานะข้อมูล: ${escapeHTML(
          basis?.verification_status ?? "ไม่ระบุ"
        )} — โปรดตรวจสอบกับแหล่งข้อมูลก่อนใช้งานจริง
      </p>
    `;

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

window.addEventListener("beforeunload", stopBarcodeScanner);

loadDashboard();
