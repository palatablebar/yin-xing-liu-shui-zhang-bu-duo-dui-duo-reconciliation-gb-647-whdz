function highlight(pair) {
  if (!pair) return;
  document.querySelectorAll('[data-pair="' + pair + '"]').forEach((row) => {
    row.classList.add("pair");
  });
}

function clearHighlight() {
  document.querySelectorAll("tr.pair").forEach((row) => row.classList.remove("pair"));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("tr[data-pair]").forEach((row) => {
    const pair = row.dataset.pair;
    if (!pair) return;
    row.addEventListener("mouseenter", () => highlight(pair));
    row.addEventListener("mouseleave", clearHighlight);
  });

  const toggle = document.querySelector("#only-diff");
  if (toggle) {
    toggle.addEventListener("change", () => {
      document.querySelectorAll(".workbench tbody tr").forEach((row) => {
        const unmatched = row.classList.contains("unmatched");
        row.classList.toggle("hidden", toggle.checked && !unmatched);
      });
    });
  }
});
