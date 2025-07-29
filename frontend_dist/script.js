function showSection(section) {
  document.getElementById("home-section").style.display = section === "home" ? "block" : "none";
  document.getElementById("analyzer-section").style.display = section === "analyzer" ? "block" : "none";
  document.getElementById("editor-section").style.display = section === "editor" ? "block" : "none";

  document.getElementById("analyzer-result").textContent = "";
  document.getElementById("editor-result").textContent = "";
}

async function analyze() {
  const agree = document.getElementById("analyzer-agree").checked;
  const scene = document.getElementById("analyze-input").value;
  if (!agree) return alert("Please accept the Terms & Conditions.");
  if (!scene.trim()) return alert("Please enter a scene.");
  
  const result = document.getElementById("analyzer-result");
  result.textContent = "Analyzing...";
  const res = await fetch("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-user-agreement": "true" },
    body: JSON.stringify({ scene })
  });
  const data = await res.json();
  result.textContent = data.analysis || JSON.stringify(data);
}

async function edit() {
  const agree = document.getElementById("editor-agree").checked;
  const scene = document.getElementById("edit-input").value;
  if (!agree) return alert("Please accept the Terms & Conditions.");
  if (!scene.trim()) return alert("Please enter a 2-page scene.");

  const result = document.getElementById("editor-result");
  result.textContent = "Editing...";
  const res = await fetch("/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-user-agreement": "true" },
    body: JSON.stringify({ scene })
  });
  const data = await res.json();
  result.textContent = data.edit_suggestions || JSON.stringify(data);
}

function showTerms() {
  document.getElementById("terms-modal").classList.remove("hidden");
}
function hideTerms() {
  document.getElementById("terms-modal").classList.add("hidden");
}

// Disable copy & right-click on output
document.addEventListener("DOMContentLoaded", () => {
  ["analyzer-result", "editor-result"].forEach(id => {
    const el = document.getElementById(id);
    el.addEventListener("contextmenu", e => e.preventDefault());
    el.addEventListener("copy", e => e.preventDefault());
  });
});

document.addEventListener("keydown", (e) => {
  const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
  if (((isMac && e.metaKey) || (!isMac && e.ctrlKey)) && ["c", "a"].includes(e.key.toLowerCase())) {
    const tag = e.target.tagName.toLowerCase();
    if (!["input", "textarea"].includes(tag)) e.preventDefault();
  }
});
