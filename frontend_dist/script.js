function checkAccess() {
  const input = document.getElementById("access").value.trim();
  const PASSWORD = atob("cHJhbnRhc2RhdHdhbnRh"); // your base64 password

  if (input === PASSWORD) {
    document.getElementById("password-gate").classList.add("hidden");
    document.getElementById("main-content").classList.remove("hidden");
    showSection('home');
  } else {
    document.getElementById("access-error").innerText = "Access Denied";
  }
}

function showSection(id) {
  document.querySelectorAll('.content-section').forEach(s => s.classList.add("hidden"));
  document.getElementById(id).classList.remove("hidden");

  if (id === "analyzer") {
    document.getElementById("scene-analyze").value = "";
    document.getElementById("analyze-result").textContent = "";
    document.getElementById("analyze-status").textContent = "";
  } else if (id === "editor") {
    document.getElementById("scene-edit").value = "";
    document.getElementById("edit-result").textContent = "";
    document.getElementById("edit-status").textContent = "";
  }
}

async function analyze() {
  const text = document.getElementById("scene-analyze").value;
  document.getElementById("analyze-status").textContent = "Analyzing...";
  const res = await fetch("/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-user-agreement": "true"
    },
    body: JSON.stringify({ scene: text })
  });
  const data = await res.json();
  document.getElementById("analyze-result").textContent = data.analysis || JSON.stringify(data);
  document.getElementById("analyze-status").textContent = "";
}

async function edit() {
  const text = document.getElementById("scene-edit").value;
  document.getElementById("edit-status").textContent = "Editing...";
  const res = await fetch("/editor", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-user-agreement": "true"
    },
    body: JSON.stringify({ scene: text })
  });
  const data = await res.json();
  document.getElementById("edit-result").textContent = data.rewrites || JSON.stringify(data);
  document.getElementById("edit-status").textContent = "";
}

// Disable right-click and keyboard copying
document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey && (e.key === 'c' || e.key === 'a')) || e.key === "PrintScreen") {
      e.preventDefault();
    }
  });
});
