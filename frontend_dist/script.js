const PASSWORD = atob("cHJhbnRhc2RhdHdhbnRh"); 

function checkAccess() {
  const input = document.getElementById("access-key").value;
  if (input === PASSWORD) {
    document.getElementById("access-gate").style.display = "none";
  } else {
    document.getElementById("access-error").textContent = "Access Denied";
  }
}

function showSection(id) {
  document.querySelectorAll(".tool-section").forEach(sec => sec.classList.add("hidden"));
  document.getElementById("result-analyze").textContent = "";
  document.getElementById("result-edit").textContent = "";
  document.getElementById("scene-input-analyze").value = "";
  document.getElementById("scene-input-edit").value = "";
  document.getElementById(id).classList.remove("hidden");
}

async function analyze() {
  const input = document.getElementById("scene-input-analyze");
  const output = document.getElementById("result-analyze");
  const scene = input.value.trim();
  if (!scene) return;

  output.textContent = "Analyzing...";
  const res = await fetch("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-user-agreement": "true" },
    body: JSON.stringify({ scene })
  });
  const data = await res.json();
  output.textContent = data.analysis || JSON.stringify(data);
}

async function edit() {
  const input = document.getElementById("scene-input-edit");
  const output = document.getElementById("result-edit");
  const scene = input.value.trim();
  if (!scene) return;

  output.textContent = "Editing...";
  const res = await fetch("/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-user-agreement": "true" },
    body: JSON.stringify({ scene })
  });
  const data = await res.json();
  output.textContent = data.edit_suggestions || JSON.stringify(data);
}
