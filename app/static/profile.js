const $ = (id) => document.getElementById(id);
const message = $("profileMessage");

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.location.assign("/login");
      throw new Error("กรุณาเข้าสู่ระบบ");
    }
    throw new Error(
      typeof data.detail === "string" ? data.detail : "ดำเนินการไม่สำเร็จ"
    );
  }
  return data;
}

function showMessage(text, kind = "success") {
  message.textContent = text;
  message.className = kind;
}

async function loadProfile() {
  try {
    const data = await api("/profile");
    const p = data.profile;

    $("displayName").value = p.display_name || "";
    $("dateOfBirth").value = p.date_of_birth
      ? String(p.date_of_birth).slice(0, 10) : "";
    $("sex").value = p.sex_for_formula || "";
    $("activityLevel").value = p.activity_level || "";

    const measurement = data.latest_body_measurement;
    if (measurement) {
      $("latestMeasurement").textContent =
        `ข้อมูลล่าสุด: น้ำหนัก ${measurement.weight_kg ?? "—"} กก. · ` +
        `ส่วนสูง ${measurement.height_cm ?? "—"} ซม.`;
    } else {
      $("latestMeasurement").textContent = "ยังไม่มีข้อมูลร่างกาย";
    }
  } catch (error) {
    showMessage(error.message || "โหลดโปรไฟล์ไม่สำเร็จ", "error");
  }
}

$("profileForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    display_name: $("displayName").value.trim() || null,
    date_of_birth: $("dateOfBirth").value || null,
    sex_for_formula: $("sex").value || null,
    activity_level: $("activityLevel").value || null,
  };

  try {
    await api("/profile", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    showMessage("บันทึกโปรไฟล์แล้ว");
  } catch (error) {
    showMessage(error.message || "บันทึกโปรไฟล์ไม่สำเร็จ", "error");
  }
});

$("measurementForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const weight = $("weight").value;
  const height = $("height").value;
  if (!weight && !height) {
    showMessage("กรุณากรอกน้ำหนักหรือส่วนสูงอย่างน้อยหนึ่งรายการ", "error");
    return;
  }

  const body = {};
  if (weight) body.weight_kg = Number(weight);
  if (height) body.height_cm = Number(height);

  try {
    await api("/profile/body-measurements", {
      method: "POST",
      body: JSON.stringify(body),
    });
    $("weight").value = "";
    $("height").value = "";
    showMessage("บันทึกข้อมูลร่างกายแล้ว");
    await loadProfile();
  } catch (error) {
    showMessage(error.message || "บันทึกข้อมูลไม่สำเร็จ", "error");
  }
});

$("logoutButton").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
    window.location.assign("/login");
  } catch (error) {
    showMessage(error.message || "ออกจากระบบไม่สำเร็จ", "error");
  }
});

loadProfile();
