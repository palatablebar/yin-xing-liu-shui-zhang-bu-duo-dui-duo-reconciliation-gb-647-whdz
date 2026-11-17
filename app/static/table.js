function cellText(row, index) {
  const cell = row.cells[index];
  return cell ? cell.textContent.trim() : "";
}

function numeric(text) {
  const cleaned = text.replace(/[,+\s]/g, "").replace(/[^0-9.-]/g, "");
  const value = Number(cleaned);
  return Number.isNaN(value) ? 0 : value;
}

function sortTable(table, index, mode, ascending) {
  const body = table.tBodies[0];
  if (!body) return;
  const rows = Array.from(body.rows);
  rows.sort((left, right) => {
    const a = cellText(left, index);
    const b = cellText(right, index);
    let order;
    if (mode === "num") {
      order = numeric(a) - numeric(b);
    } else {
      order = a.localeCompare(b, "zh-Hans-CN");
    }
    return ascending ? order : -order;
  });
  rows.forEach((row) => body.appendChild(row));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("table.grid").forEach((table) => {
    table.querySelectorAll("th[data-sort]").forEach((header) => {
      let ascending = true;
      header.addEventListener("click", () => {
        sortTable(table, header.cellIndex, header.dataset.sort, ascending);
        ascending = !ascending;
        header.dataset.order = ascending ? "desc" : "asc";
      });
    });
  });
});
