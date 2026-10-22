const $ = (id) => document.getElementById(id);

const form = $("loginForm");
const loginButton = $("loginButton");
const message = $("formMessage");
const accountPanel = $("accountPanel");
const authTabs = $("authTabs");
const alternateOptions = $("alternateOptions");

let mode = "login";
let busy = false;

function showMessage(text, kind = "error") {
  message.textContent = text;
  message.className = `form-message ${kind}`;
}

function setBusy(value, label) {
  busy = value;
  loginButton.disabled = value;
  $("guestButton").disabled = value;
  loginButton.textContent = value ? label : (
    mode === "login" ? "เข้าสู่ระบบ →" : "สมัครสมาชิก →"
  );
}

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
    const detail = typeof data.detail === "string"
      ? data.detail
      : "ดำเนินการไม่สำเร็จ กรุณาลองอีกครั้ง";
    throw new Error(detail);
  }
  return data;
}

function setMode(nextMode) {
  if (nextMode !== "login" && nextMode !== "register") return;
  mode = nextMode;

  authTabs.querySelectorAll("[data-mode]").forEach((tab) => {
    const active = tab.dataset.mode === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  $("loginTitle").textContent = mode === "login"
    ? "ยินดีต้อนรับกลับมา" : "สร้างบัญชี NourivaAI";
  $("pageIntro").textContent = mode === "login"
    ? "เข้าสู่ระบบเพื่อเริ่มต้นดูแลตัวเองไปด้วยกัน"
    : "สมัครสมาชิกเพื่อบันทึกข้อมูลและดูแลสุขภาพของคุณ";

  $("confirmPasswordGroup").classList.toggle("hidden", mode !== "register");
  $("displayNameGroup").classList.toggle("hidden", mode !== "register");
  $("confirmPassword").required = mode === "register";
  $("displayName").required = mode === "register";
  $("password").setAttribute(
    "autocomplete", mode === "login" ? "current-password" : "new-password"
  );
  $("email").setAttribute("autocomplete", "username");
  $("confirmPassword").value = "";
  showMessage("");

  loginButton.textContent = mode === "login"
    ? "เข้าสู่ระบบ →" : "สมัครสมาชิก →";
  alternateOptions.classList.toggle("hidden", mode !== "login");
}

function showAccount(user) {
  form.classList.add("hidden");
  authTabs.classList.add("hidden");
  alternateOptions.classList.add("hidden");
  accountPanel.classList.remove("hidden");

  const isGuest = user.account_type === "guest" ||
    user.is_guest === true ||
    (user.email || "").endsWith("@guest.nouriva.invalid");

  $("accountTitle").textContent = isGuest
    ? "คุณกำลังใช้งานแบบ Guest" : "เข้าสู่ระบบสำเร็จ";
  $("accountEmail").textContent = isGuest
    ? "บัญชีผู้เยี่ยมชม" : (user.email || "");
  $("accountRole").textContent = isGuest
    ? "ข้อมูลนี้เป็นบัญชี Guest" : `บทบาท: ${user.role || "user"}`;
  $("loginTitle").textContent = "บัญชีของคุณ";
  $("pageIntro").textContent = "ยืนยันตัวตนสำเร็จ พร้อมใช้งาน NourivaAI";
  showMessage("");
}

function showLoggedOut(text = "") {
  form.reset();
  form.classList.remove("hidden");
  authTabs.classList.remove("hidden");
  accountPanel.classList.add("hidden");
  alternateOptions.classList.remove("hidden");
  $("password").type = "password";
  $("togglePassword").textContent = "แสดง";
  $("togglePassword").setAttribute("aria-pressed", "false");
  setMode("login");
  if (text) showMessage(text, "success");
}

authTabs.querySelectorAll("[data-mode]").forEach((tab) => {
  tab.addEventListener("click", () => setMode(tab.dataset.mode));
});

$("togglePassword").addEventListener("click", () => {
  const input = $("password");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  $("togglePassword").textContent = show ? "ซ่อน" : "แสดง";
  $("togglePassword").setAttribute("aria-pressed", String(show));
  $("togglePassword").setAttribute(
    "aria-label", show ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"
  );
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;

  const email = $("email").value.trim();
  const password = $("password").value;

  if (mode === "register") {
    if (password !== $("confirmPassword").value) {
      showMessage("รหัสผ่านและการยืนยันรหัสผ่านไม่ตรงกัน");
      return;
    }
    if (!$("displayName").value.trim()) {
      showMessage("กรุณาระบุชื่อที่ต้องการให้แสดง");
      return;
    }
  }

  setBusy(true, mode === "login" ? "กำลังเข้าสู่ระบบ..." : "กำลังสมัครสมาชิก...");

  try {
    if (mode === "register") {
      const result = await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          display_name: $("displayName").value.trim(),
        }),
      });
      form.reset();
      setMode("login");
      $("email").value = email;
      showMessage(result.message || "สมัครสมาชิกสำเร็จ กรุณาเข้าสู่ระบบ", "success");
    } else {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });

      const result = await api("/auth/me");
      $("password").value = "";
      showAccount(result.user);
    }
  } catch (error) {
    showMessage(error.message || "เชื่อมต่อระบบไม่ได้ กรุณาลองอีกครั้ง");
  } finally {
    setBusy(false);
  }
});

$("guestButton").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true, "กำลังเข้าใช้งานแบบ Guest...");

  try {
    await api("/auth/guest", { method: "POST" });
    const result = await api("/auth/me");
    showAccount({ ...result.user, account_type: "guest" });
  } catch (error) {
    showMessage(error.message || "เข้าใช้งานแบบ Guest ไม่สำเร็จ");
  } finally {
    setBusy(false);
  }
});

$("continueButton").addEventListener("click", () => {
  window.location.assign("/");
});

$("profileButton").addEventListener("click", () => {
  window.location.assign("/my-profile");
});

$("logoutButton").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true, "กำลังออกจากระบบ...");
  try {
    const result = await api("/auth/logout", { method: "POST" });
    showLoggedOut(result.message || "ออกจากระบบแล้ว");
  } catch (error) {
    showMessage(error.message || "ออกจากระบบไม่สำเร็จ");
  } finally {
    setBusy(false);
  }
});

async function initializeLogin() {
  try {
    const result = await api("/auth/me");
    showAccount(result.user);
  } catch (_) {
    showLoggedOut();
  }
}

setMode("login");
initializeLogin();
