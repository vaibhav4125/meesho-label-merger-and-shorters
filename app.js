// Meesho Multi-Account Label Sorting and Merging Web App

let currentTab = "dashboard";
let currentOrdersPage = 1;
let selectedUnmappedSkus = new Set();
let activeGenSizes = new Set();
let allGenSizesList = [];
let availableGroups = [];
let availableCategories = [];
let targetGroupIdForNewCategory = null;
let currentSuggestions = [];

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  setupNavigation();
  setupUploadDropzone();
  setupSampleLoader();
  setupSearchInputs();
  loadCategories();
  loadDashboard();
  checkCloudServerStatus();
});

// Cloud Server Cold-Start Detection & Auto-Reconnection (Render.com free tier)
async function checkCloudServerStatus() {
  const banner = document.getElementById("cloud-wake-banner");
  const bannerText = document.getElementById("cloud-wake-text");
  if (!banner) return;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    const res = await fetch("/api/health", { signal: controller.signal });
    clearTimeout(timeoutId);

    if (res.ok) {
      banner.style.display = "none";
      return;
    }
  } catch (err) {
    // Cloud server is currently cold-booting or sleeping!
    banner.style.display = "flex";
    banner.style.background = "linear-gradient(90deg, #fef3c7, #fffbeb)";
    banner.style.border = "1px solid #f59e0b";
    banner.style.color = "#92400e";
    if (bannerText) {
      bannerText.innerHTML = `<strong>Cloud Server is waking up...</strong> Render free tier sleeps after 15 min. Automatically reconnecting in ~25s...`;
    }

    let awake = false;
    let attempts = 0;
    while (!awake && attempts < 40) {
      await new Promise(r => setTimeout(r, 2000));
      try {
        const pingRes = await fetch("/api/health");
        if (pingRes.ok) {
          awake = true;
          banner.style.background = "linear-gradient(90deg, #d1fae5, #ecfdf5)";
          banner.style.border = "1px solid #10b981";
          banner.style.color = "#065f46";
          if (bannerText) {
            bannerText.innerHTML = `<i class="fa-solid fa-circle-check text-emerald" style="margin-right:6px;"></i> <strong>Cloud Server Connected!</strong> Everything is ready.`;
          }
          setTimeout(() => {
            banner.style.display = "none";
          }, 2500);
          loadCategories();
          loadDashboard();
        }
      } catch (e) {
        attempts++;
      }
    }
  }
}

// Category Management Functions
async function loadCategories() {
  try {
    const res = await fetch("/api/categories");
    const data = await res.json();
    if (data.success && Array.isArray(data.categories)) {
      availableCategories = data.categories;
    } else {
      availableCategories = [
        { name: "Plazo", label: "👖 Plazo (Top)", icon: "👖", display_order: 1 },
        { name: "Women T-Shirt", label: "👕 Women T-Shirt (Middle)", icon: "👕", display_order: 2 },
        { name: "Men T-Shirt", label: "👕 Men T-Shirt", icon: "👕", display_order: 3 },
        { name: "Black Patti", label: "🏷️ Black Patti", icon: "🏷️", display_order: 4 },
        { name: "General", label: "📦 General", icon: "📦", display_order: 5 },
        { name: "Other", label: "📦 Other (Bottom)", icon: "📦", display_order: 6 }
      ];
    }
  } catch (err) {
    console.warn("Could not fetch categories:", err);
    availableCategories = [
      { name: "Plazo", label: "👖 Plazo (Top)", icon: "👖", display_order: 1 },
      { name: "Women T-Shirt", label: "👕 Women T-Shirt (Middle)", icon: "👕", display_order: 2 },
      { name: "Men T-Shirt", label: "👕 Men T-Shirt", icon: "👕", display_order: 3 },
      { name: "Black Patti", label: "🏷️ Black Patti", icon: "🏷️", display_order: 4 },
      { name: "General", label: "📦 General", icon: "📦", display_order: 5 },
      { name: "Other", label: "📦 Other (Bottom)", icon: "📦", display_order: 6 }
    ];
  }
  updateCategoryDropdowns();
}

function updateCategoryDropdowns() {
  const skuColorFilter = document.getElementById("sku-color-category-filter");
  if (skuColorFilter) {
    const currVal = skuColorFilter.value;
    skuColorFilter.innerHTML = `<option value="">All Categories</option>` +
      availableCategories.map(c => `<option value="${escapeHtml(c.name)}" ${currVal === c.name ? 'selected' : ''}>${escapeHtml(c.label || (c.icon + ' ' + c.name))}</option>`).join('');
  }

  const activeGroupsFilter = document.getElementById("active-groups-category-filter");
  if (activeGroupsFilter) {
    const currVal = activeGroupsFilter.value;
    activeGroupsFilter.innerHTML = `<option value="">All Categories</option>` +
      availableCategories.map(c => `<option value="${escapeHtml(c.name)}" ${currVal === c.name ? 'selected' : ''}>${escapeHtml(c.label || (c.icon + ' ' + c.name))}</option>`).join('');
  }
}

function onCategoryIconSelectChange(val) {
  const iconInput = document.getElementById("modal-category-icon");
  if (iconInput) iconInput.value = val;
}

function openAddCategoryModal(forGroupId = null) {
  targetGroupIdForNewCategory = forGroupId;
  const nameInput = document.getElementById("modal-category-name");
  const iconInput = document.getElementById("modal-category-icon");
  const iconSelect = document.getElementById("modal-category-icon-select");
  const placementSelect = document.getElementById("modal-category-placement");
  const noticeEl = document.getElementById("modal-category-target-group-notice");
  const gidInput = document.getElementById("modal-category-group-id");

  if (nameInput) nameInput.value = "";
  if (iconInput) iconInput.value = "🏷️";
  if (iconSelect) iconSelect.value = "🏷️";
  if (placementSelect) placementSelect.value = "default";
  if (gidInput) gidInput.value = forGroupId || "";

  if (noticeEl) {
    noticeEl.style.display = forGroupId ? "block" : "none";
  }

  openModal("modal-add-category");
  setTimeout(() => {
    if (nameInput) nameInput.focus();
  }, 100);
}

async function confirmAddCategory() {
  const nameInput = document.getElementById("modal-category-name");
  const iconInput = document.getElementById("modal-category-icon");
  const placementSelect = document.getElementById("modal-category-placement");
  const name = (nameInput?.value || "").trim();
  const icon = (iconInput?.value || "🏷️").trim() || "🏷️";

  if (!name) {
    showToast("Please enter a category name", "warning");
    if (nameInput) nameInput.focus();
    return;
  }

  let displayOrder = 10;
  const placement = placementSelect?.value || "default";
  if (placement === "after_plazo") displayOrder = 1.5;
  else if (placement === "after_womentee") displayOrder = 2.5;
  else if (placement === "after_mentee") displayOrder = 3.5;
  else if (placement === "bottom") displayOrder = 95;
  else displayOrder = 8;

  try {
    const res = await fetch("/api/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        label: `${icon} ${name}`,
        icon: icon,
        display_order: displayOrder
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showToast(`Category '${name}' created successfully!`, "success");
      const assignedGroupId = targetGroupIdForNewCategory;
      targetGroupIdForNewCategory = null;
      closeModal("modal-add-category");
      await loadCategories();

      if (assignedGroupId) {
        await changeGroupCategory(assignedGroupId, name);
      } else {
        renderActiveProductGroups();
      }
      loadSkuColorBreakdown();
    } else {
      let errMsg = "Failed to create category";
      if (typeof data.detail === "string") {
        errMsg = data.detail;
      } else if (Array.isArray(data.detail)) {
        errMsg = data.detail.map(d => d.msg || JSON.stringify(d)).join(", ");
      } else if (data.detail && typeof data.detail === "object") {
        errMsg = data.detail.msg || JSON.stringify(data.detail);
      }
      showToast(errMsg, "danger");
    }
  } catch (err) {
    showToast("Error saving category: " + err.message, "danger");
  }
}

// Toast notification helper
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  let icon = "fa-circle-info";
  if (type === "success") icon = "fa-circle-check";
  if (type === "danger") icon = "fa-circle-exclamation";
  if (type === "warning") icon = "fa-triangle-exclamation";

  toast.innerHTML = `
    <i class="fa-solid ${icon}" style="font-size:16px;"></i>
    <div style="flex:1;">${message}</div>
    <button style="border:none; background:none; cursor:pointer; color:#94a3b8;" onclick="this.parentElement.remove()">&times;</button>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4500);
}

// Navigation & Mobile Setup
function setupNavigation() {
  const navItems = document.querySelectorAll(".nav-item");
  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const tab = item.getAttribute("data-tab");
      switchTab(tab);
      closeMobileSidebar();
    });
  });

  // Mobile Bottom Navigation Items
  const bottomNavItems = document.querySelectorAll(".bottom-nav-item[data-tab]");
  bottomNavItems.forEach(item => {
    item.addEventListener("click", () => {
      const tab = item.getAttribute("data-tab");
      switchTab(tab);
      closeMobileSidebar();
    });
  });

  // Mobile Hamburger Toggle
  const toggleBtn = document.getElementById("mobile-sidebar-toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      toggleMobileSidebar();
    });
  }

  // Mobile Bottom Menu Button
  const bottomMenuBtn = document.getElementById("bottom-nav-menu-btn");
  if (bottomMenuBtn) {
    bottomMenuBtn.addEventListener("click", () => {
      toggleMobileSidebar();
    });
  }

  // Sidebar Close Button
  const closeBtn = document.getElementById("sidebar-close-btn");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      closeMobileSidebar();
    });
  }

  // Sidebar Overlay Click
  const overlay = document.getElementById("sidebar-overlay");
  if (overlay) {
    overlay.addEventListener("click", () => {
      closeMobileSidebar();
    });
  }
}

function toggleMobileSidebar() {
  const sidebar = document.getElementById("app-sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  if (sidebar && overlay) {
    const isOpen = sidebar.classList.contains("mobile-open");
    if (isOpen) {
      closeMobileSidebar();
    } else {
      sidebar.classList.add("mobile-open");
      overlay.classList.add("active");
    }
  }
}

function closeMobileSidebar() {
  const sidebar = document.getElementById("app-sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  if (sidebar) sidebar.classList.remove("mobile-open");
  if (overlay) overlay.classList.remove("active");
}

function switchTab(tabId) {
  currentTab = tabId;
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".bottom-nav-item").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));

  const navEl = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
  if (navEl) navEl.classList.add("active");

  const bottomEl = document.querySelector(`.bottom-nav-item[data-tab="${tabId}"]`);
  if (bottomEl) bottomEl.classList.add("active");

  const paneEl = document.getElementById(`tab-${tabId}`);
  if (paneEl) paneEl.classList.add("active");

  const titles = {
    dashboard: "Dashboard Overview",
    upload: "Upload Meesho PDF Shipping Labels",
    summary: "Order Summary Matrix by SKU & Size",
    mapping: "SKU Mapping & Product Groups",
    generator: "Generate Sorted Shipping-Label PDFs",
    orders: "Orders Explorer & Manual Review",
    history: "Processing History & Downloads",
    settings: "System Settings & Maintenance"
  };
  const titleEl = document.getElementById("page-title");
  if (titleEl) titleEl.innerText = titles[tabId] || "Dashboard";

  // Trigger data loader for the active tab
  if (tabId === "dashboard") loadDashboard();
  if (tabId === "upload") loadUploadedFiles();
  if (tabId === "summary") { loadFilterOptions(); loadSummaryTable(); }
  if (tabId === "mapping") { loadSkuGroups(); loadMappingSuggestions(); fetchSkuMappingsStatus(); }
  if (tabId === "generator") loadGeneratorOptions();
  if (tabId === "orders") { loadFilterOptions(); loadOrdersTable(1); }
  if (tabId === "history") loadHistory();
  if (tabId === "settings") fetchSkuMappingsStatus();
}

// Mobile Dashboard View Switcher (Matrix, Sellers, Sizes, All)
function setMobileDashboardView(view) {
  const container = document.getElementById("dashboard-split-layout");
  if (!container) return;

  document.querySelectorAll(".mobile-dash-tab").forEach(tab => {
    if (tab.getAttribute("data-view") === view) {
      tab.classList.add("active");
    } else {
      tab.classList.remove("active");
    }
  });

  container.classList.remove("mobile-view-matrix", "mobile-view-sellers", "mobile-view-sizes", "mobile-view-all");
  container.classList.add(`mobile-view-${view}`);
}
window.setMobileDashboardView = setMobileDashboardView;

// Modal Helpers
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add("active");
    modal.style.display = "flex";
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove("active");
    modal.style.display = "none";
  }
}

// Mobile Live Access Modal & QR Code
let cachedMobileUrls = {
  local: "",
  cloudflare: ""
};
let mobilePollTimer = null;

async function fetchMobileInfo() {
  try {
    const res = await fetch("/api/mobile-info");
    if (res.ok) {
      const data = await res.json();
      cachedMobileUrls.local = data.local_url || "";
      cachedMobileUrls.cloudflare = data.tunnel_url || "";

      const cfEl = document.getElementById("modal-cloudflare-url");
      const badgeText = document.getElementById("modal-cf-badge-text");
      const badgeDot = document.getElementById("modal-cf-badge-dot");
      const qrImg = document.getElementById("mobile-qr-image");
      const qrHint = document.getElementById("mobile-qr-hint");
      const localEl = document.getElementById("modal-local-wifi-url");

      if (localEl && cachedMobileUrls.local) {
        localEl.innerText = cachedMobileUrls.local;
      }

      if (data.tunnel_status === "online" && data.tunnel_url) {
        if (badgeText) badgeText.innerText = "Online Live Link (Any Mobile / 4G / 5G)";
        if (badgeDot) {
          badgeDot.style.background = "var(--success)";
          badgeDot.classList.remove("pulse-anim");
        }
        if (cfEl) {
          cfEl.innerHTML = `<a href="${data.tunnel_url}" target="_blank" rel="noopener noreferrer" style="color:var(--primary); text-decoration:underline;">${data.tunnel_url}</a>`;
        }
        if (qrImg) {
          qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(data.tunnel_url)}&margin=1`;
        }
        if (qrHint) qrHint.innerHTML = '<i class="fa-solid fa-camera"></i> Scan with Phone Camera to Open (Anywhere Live)';
        if (mobilePollTimer) {
          clearInterval(mobilePollTimer);
          mobilePollTimer = null;
        }
      } else if (data.tunnel_status === "connecting") {
        if (badgeText) badgeText.innerText = "Connecting Secure Live Tunnel (Please wait ~5s)...";
        if (badgeDot) {
          badgeDot.style.background = "#f59e0b";
          badgeDot.classList.add("pulse-anim");
        }
        if (cfEl) cfEl.innerText = "Generating live Cloudflare link...";
        if (qrImg && cachedMobileUrls.local) {
          qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(cachedMobileUrls.local)}&margin=1`;
        }
        if (qrHint) qrHint.innerHTML = '<i class="fa-solid fa-camera"></i> Scan to open on Same Wi-Fi (Live link connecting...)';
      } else {
        if (badgeText) badgeText.innerText = "Live Tunnel Offline";
        if (badgeDot) {
          badgeDot.style.background = "var(--text-muted)";
          badgeDot.classList.remove("pulse-anim");
        }
        if (cfEl) cfEl.innerText = "Tunnel offline. Click Refresh icon to start or use Local Wi-Fi link below.";
        if (qrImg && cachedMobileUrls.local) {
          qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(cachedMobileUrls.local)}&margin=1`;
        }
        if (qrHint) qrHint.innerHTML = '<i class="fa-solid fa-camera"></i> Scan to open on Same Wi-Fi';
      }
      return data;
    }
  } catch (err) {
    console.warn("Could not fetch /api/mobile-info:", err);
  }
  return null;
}

async function openMobileModal() {
  closeMobileSidebar();
  openModal("modal-mobile-live");

  const data = await fetchMobileInfo();
  if (data && data.tunnel_status === "connecting") {
    if (mobilePollTimer) clearInterval(mobilePollTimer);
    let attempts = 0;
    mobilePollTimer = setInterval(async () => {
      attempts++;
      const res = await fetchMobileInfo();
      if ((res && res.tunnel_status === "online") || attempts >= 10) {
        clearInterval(mobilePollTimer);
        mobilePollTimer = null;
      }
    }, 1500);
  }
}

async function restartTunnel() {
  const icon = document.getElementById("restart-tunnel-icon");
  if (icon) icon.classList.add("fa-spin");
  const badgeText = document.getElementById("modal-cf-badge-text");
  const badgeDot = document.getElementById("modal-cf-badge-dot");
  const cfEl = document.getElementById("modal-cloudflare-url");

  if (badgeText) badgeText.innerText = "Restarting Live Tunnel...";
  if (badgeDot) {
    badgeDot.style.background = "#f59e0b";
    badgeDot.classList.add("pulse-anim");
  }
  if (cfEl) cfEl.innerText = "Acquiring new secure URL...";

  try {
    const res = await fetch("/api/mobile-tunnel/restart", { method: "POST" });
    if (res.ok) {
      showToast("Live tunnel restart initiated...", "info");
      await fetchMobileInfo();
      if (mobilePollTimer) clearInterval(mobilePollTimer);
      let attempts = 0;
      mobilePollTimer = setInterval(async () => {
        attempts++;
        const info = await fetchMobileInfo();
        if ((info && info.tunnel_status === "online") || attempts >= 10) {
          clearInterval(mobilePollTimer);
          mobilePollTimer = null;
          if (icon) icon.classList.remove("fa-spin");
          if (info && info.tunnel_status === "online") {
            showToast("New Live Link connected!", "success");
          }
        }
      }, 1500);
    }
  } catch (err) {
    if (icon) icon.classList.remove("fa-spin");
    showToast("Failed to restart tunnel: " + err.message, "error");
  }
}

function copyLiveUrl(type) {
  const urlToCopy = type === "cloudflare" ? cachedMobileUrls.cloudflare : cachedMobileUrls.local;
  if (!urlToCopy) {
    showToast("Link not available yet. Please wait...", "warning");
    return;
  }

  navigator.clipboard.writeText(urlToCopy).then(() => {
    showToast(`Copied ${type === "cloudflare" ? "Live" : "Local Wi-Fi"} link to clipboard!`, "success");
  }).catch(() => {
    const input = document.createElement("input");
    input.value = urlToCopy;
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    document.body.removeChild(input);
    showToast("Link copied to clipboard!", "success");
  });
}


// --- 1. Dashboard & All SKUs Color Breakdown ---
// --- 1. Dashboard & All SKUs Color Breakdown ---
let currentSkuViewMode = "merged"; // "merged" | "sku" | "flat"
let allProductsExpanded = false;
let skuColorData = null;
let skuColorSearchTimer = null;

function setSkuViewMode(mode) {
  currentSkuViewMode = mode;
  const btnMerged = document.getElementById("btn-view-merged");
  const btnSku = document.getElementById("btn-view-sku");
  const btnFlat = document.getElementById("btn-view-flat");
  if (btnMerged) btnMerged.className = mode === "merged" ? "btn btn-sm btn-primary" : "btn btn-sm btn-secondary";
  if (btnSku) btnSku.className = mode === "sku" ? "btn btn-sm btn-primary" : "btn btn-sm btn-secondary";
  if (btnFlat) btnFlat.className = mode === "flat" ? "btn btn-sm btn-primary" : "btn btn-sm btn-secondary";

  loadSkuColorBreakdown();
}

function toggleProductColorDetail(idx) {
  const row = document.getElementById(`product-detail-row-${idx}`);
  const chevron = document.getElementById(`product-chevron-${idx}`);
  const mainRow = document.getElementById(`product-main-row-${idx}`);
  if (!row) return;
  const isHidden = row.style.display === "none";
  row.style.display = isHidden ? "table-row" : "none";
  if (chevron) {
    chevron.className = isHidden ? "fa-solid fa-chevron-up" : "fa-solid fa-chevron-down";
  }
  if (mainRow) {
    if (isHidden) mainRow.classList.add("expanded");
    else mainRow.classList.remove("expanded");
  }
}

function toggleAllProductAccordions() {
  allProductsExpanded = !allProductsExpanded;
  const rows = document.querySelectorAll("[id^='product-detail-row-']");
  const chevrons = document.querySelectorAll("[id^='product-chevron-']");
  const mainRows = document.querySelectorAll("[id^='product-main-row-']");

  rows.forEach(r => {
    r.style.display = allProductsExpanded ? "table-row" : "none";
  });
  chevrons.forEach(c => {
    c.className = allProductsExpanded ? "fa-solid fa-chevron-up" : "fa-solid fa-chevron-down";
  });
  mainRows.forEach(m => {
    if (allProductsExpanded) m.classList.add("expanded");
    else m.classList.remove("expanded");
  });

  const btn = document.getElementById("btn-toggle-all-products");
  if (btn) {
    btn.innerHTML = allProductsExpanded
      ? `<i class="fa-solid fa-compress"></i> Collapse All Colors`
      : `<i class="fa-solid fa-layer-group"></i> Expand All Colors`;
  }
}

function selectCategoryPill(cat) {
  const select = document.getElementById("sku-color-category-filter");
  if (select) select.value = cat;

  document.querySelectorAll("#category-pills-bar .cat-pill").forEach(p => {
    if (p.getAttribute("data-cat") === cat) p.classList.add("active");
    else p.classList.remove("active");
  });

  loadProductColorMatrix();
}

function onCategoryFilterChange() {
  const select = document.getElementById("sku-color-category-filter");
  const cat = select ? select.value : "";
  document.querySelectorAll("#category-pills-bar .cat-pill").forEach(p => {
    if (p.getAttribute("data-cat") === cat) p.classList.add("active");
    else p.classList.remove("active");
  });
  loadProductColorMatrix();
}

async function loadSkuColorBreakdown() {
  const searchInput = document.getElementById("sku-color-search");
  const sellerSelect = document.getElementById("sku-color-seller-filter");
  const groupSelect = document.getElementById("sku-color-group-filter");

  const search = searchInput ? searchInput.value.trim() : "";
  const seller = sellerSelect ? sellerSelect.value : "";
  const group = groupSelect ? groupSelect.value : "";
  const categorySelect = document.getElementById("sku-color-category-filter");
  const sortSelect = document.getElementById("sku-color-sort-mode");
  const category = categorySelect ? categorySelect.value : "";
  const sortBy = sortSelect ? sortSelect.value : "category";

  const params = new URLSearchParams();
  if (search) params.append("search", search);
  if (seller) params.append("seller", seller);
  if (group) params.append("group", group);
  if (category) params.append("category", category);
  if (sortBy) params.append("sort_by", sortBy);
  params.append("group_by", currentSkuViewMode === "sku" ? "sku" : "group");

  const tbody = document.getElementById("dashboard-skus-tbody");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:#64748b;"><i class="fa-solid fa-circle-notch fa-spin"></i> Loading SKUs & color breakdown...</td></tr>`;
  }

  try {
    const res = await fetch(`/api/skus-color-breakdown?${params.toString()}`);
    const data = await res.json();
    skuColorData = data;

    // Update Category Pills dynamically from data.categories_summary
    const pillsBar = document.getElementById("category-pills-bar");
    if (pillsBar && data.categories_summary) {
      let pillsHtml = `
        <span style="font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Categories:</span>
        <button class="cat-pill ${!category ? 'active' : ''}" onclick="selectCategoryPill('')" data-cat="">
          All Products (<span id="cat-count-all">${data.total_orders || 0}</span>)
        </button>
      `;

      data.categories_summary.forEach(c => {
        const isActive = (category && category.toLowerCase() === c.category.toLowerCase());
        const icon = c.icon || "🏷️";
        const label = c.label || `${icon} ${c.category}`;
        pillsHtml += `
          <button class="cat-pill ${isActive ? 'active' : ''}" onclick="selectCategoryPill('${escapeHtml(c.category)}')" data-cat="${escapeHtml(c.category)}">
            ${escapeHtml(label)} (<span>${c.orders_count || 0}</span>)
          </button>
        `;
      });
      pillsBar.innerHTML = pillsHtml;
    }

    const badge = document.getElementById("sku-color-summary-badge");
    if (badge) {
      const modeLabel = currentSkuViewMode === "merged" ? "Unified Groups" : (currentSkuViewMode === "sku" ? "Catalog SKUs" : "Raw SKUs");
      badge.innerText = `${data.total_products || 0} ${modeLabel} | ${data.total_colors || 0} Colors | ${data.total_orders || 0} Orders`;
    }

    const dlBtn = document.getElementById("btn-download-all-bills-pdf");
    if (dlBtn && data.total_orders) {
      dlBtn.innerHTML = `<i class="fa-solid fa-file-pdf"></i> Color-Wise PDF (${data.total_orders} Pages)`;
    }
    const sizeDlBtn = document.getElementById("btn-download-size-wise-pdf");
    if (sizeDlBtn && data.total_orders) {
      sizeDlBtn.innerHTML = `<i class="fa-solid fa-arrow-down-short-wide"></i> Size-Wise PDF (${data.total_orders} Pages)`;
    }

    renderSkuColorTable(data);
  } catch (err) {
    console.error("Error loading SKU color breakdown:", err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#ef4444; padding:16px;">Failed to load SKU color breakdown. Please refresh.</td></tr>`;
    }
  }
}

function renderSkuColorTable(data) {
  const theadRow = document.getElementById("dashboard-skus-thead-row");
  const tbody = document.getElementById("dashboard-skus-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!data || !data.products || data.products.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#94a3b8; padding:20px;">No SKUs match the filter criteria</td></tr>`;
    return;
  }

  if (currentSkuViewMode === "merged" || currentSkuViewMode === "sku") {
    // --- MERGED PRODUCT GROUP OR CATALOG SKU VIEW ---
    if (theadRow) {
      const colTitle = currentSkuViewMode === "merged" ? "Product Group / Physical Product" : "Catalog SKU / Design Name";
      theadRow.innerHTML = `
        <th style="width:36px; text-align:center;">#</th>
        <th>${colTitle}</th>
        <th>Available Colors (Merged - Click to View)</th>
        <th>Overall Size Breakdown</th>
        <th style="text-align:center; width:110px;">Total Orders</th>
        <th style="text-align:center; width:90px;">Action</th>
      `;
    }

    let lastCategory = null;
    const sortMode = document.getElementById("sku-color-sort-mode")?.value || "category";
    const catFilter = document.getElementById("sku-color-category-filter")?.value || "";
    const showDividers = sortMode === "category" && !catFilter;

    data.products.forEach((p, idx) => {
      // Category Divider Banner Row
      if (showDividers && p.category && p.category !== lastCategory) {
        lastCategory = p.category;
        const catMeta = data.categories_summary?.find(c => c.category === p.category) || {};
        const divTr = document.createElement("tr");
        divTr.className = "category-divider-tr";
        divTr.innerHTML = `
          <td colspan="6">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:700; color:#0f172a; font-size:12.5px; display:flex; align-items:center; gap:6px;">
                ${p.category_label || p.category}
              </span>
              <span class="badge" style="background:#ffffff; color:#334155; border:1px solid #cbd5e1; font-size:11px; font-weight:600;">
                ${catMeta.products_count || ''} Groups | ${catMeta.orders_count || ''} Orders | ${catMeta.pieces_count || ''} Pieces
              </span>
            </div>
          </td>
        `;
        tbody.appendChild(divTr);
      }

      // 1. Color Pills for the header row
      const colorPillsHtml = p.colors.map(c => `
        <span class="color-pill" title="${c.color}: ${c.orders_count} orders (${c.color_share_pct}%)">
          <span class="color-dot"></span>
          <span>${c.color}</span>
          <span class="color-cnt">${c.orders_count}</span>
        </span>
      `).join("");

      // 2. Overall Size tags for the base product
      const overallSizeTagsHtml = (p.overall_sizes && p.overall_sizes.length > 0)
        ? p.overall_sizes.map(s => `
            <span class="size-tag" title="${s.tooltip || `${s.size}: ${s.orders_count} orders (${s.percentage}%)`}">
              <span class="size-tag-name">${s.size}:</span>
              <span class="size-tag-count">${s.orders_count}</span>
            </span>
          `).join("")
        : `<span style="color:#94a3b8; font-size:12px;">No sizes</span>`;

      // Merged badge if multiple SKUs merged
      const mergedBadgeHtml = (p.included_skus_count && p.included_skus_count > 1)
        ? `<span class="badge badge-info" style="font-size:11px; margin-left:6px;" title="${p.included_skus.slice(0, 5).join(', ')}..."><i class="fa-solid fa-layer-group"></i> ${p.included_skus_count} SKUs Merged</span>`
        : '';

      // Category badge
      const isBlackPatti = p.category === 'Black Patti' || p.category === 'Black Pati';
      const catBadgeStyle = p.category === 'Plazo'
        ? 'background:#fef3c7; color:#92400e;'
        : (p.category === 'Women T-Shirt'
          ? 'background:#e0e7ff; color:#3730a3;'
          : (p.category === 'Men T-Shirt'
            ? 'background:#dbeafe; color:#1e40af;'
            : (isBlackPatti
              ? 'background:#1e293b; color:#f8fafc;'
              : 'background:#f1f5f9; color:#475569;')));
      const catBadgeText = p.category === 'Plazo'
        ? '👖 Plazo'
        : (p.category === 'Women T-Shirt'
          ? '👕 Women T-Shirt'
          : (p.category === 'Men T-Shirt'
            ? '👕 Men T-Shirt'
            : (isBlackPatti
              ? '🏷️ Black Patti'
              : (p.category_label || ('🏷️ ' + p.category)))));
      const categoryBadgeHtml = `<span class="category-badge-pill" style="${catBadgeStyle}">${catBadgeText}</span>`;

      // Main Product Row
      const mainTr = document.createElement("tr");
      mainTr.id = `product-main-row-${idx}`;
      mainTr.className = "product-row-header";
      mainTr.style.cursor = "pointer";
      mainTr.title = "Click to toggle color-wise & size-wise breakdown";
      mainTr.innerHTML = `
        <td style="text-align:center; color:#64748b; font-weight:600;">${idx + 1}</td>
        <td>
          <div style="display:flex; align-items:center; flex-wrap:wrap; gap:6px;">
            <span style="font-weight:700; color:#0f172a; font-size:14px; line-height:1.3;">${p.display_name}</span>
            ${categoryBadgeHtml}
            ${mergedBadgeHtml}
          </div>
          ${p.sellers && p.sellers.length > 0 ? `<div style="font-size:11px; color:#64748b; margin-top:2px;">Sellers: ${p.sellers.join(', ')}</div>` : ''}
        </td>
        <td>
          <div style="display:flex; flex-wrap:wrap; align-items:center;">
            ${colorPillsHtml}
          </div>
        </td>
        <td>
          <div style="display:flex; flex-wrap:wrap; align-items:center;">
            ${overallSizeTagsHtml}
          </div>
        </td>
        <td style="text-align:center;">
          <strong style="font-size:15px; color:#0f172a;">${p.total_orders}</strong>
          <div style="font-size:11px; color:#64748b;">${p.total_pieces || p.total_orders} pcs</div>
        </td>
        <td style="text-align:center;">
          <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); toggleProductColorDetail(${idx})" id="product-toggle-btn-${idx}" title="Expand color breakdown">
            <i class="fa-solid fa-chevron-down" id="product-chevron-${idx}"></i>
          </button>
        </td>
      `;

      mainTr.addEventListener("click", () => {
        toggleProductColorDetail(idx);
      });

      // Expandable Subrow (Color-wise breakdown)
      const subTr = document.createElement("tr");
      subTr.id = `product-detail-row-${idx}`;
      subTr.style.display = allProductsExpanded ? "table-row" : "none";
      subTr.className = "sku-subrow-container";

      // Build rows for each color inside the product
      const colorRowsHtml = p.colors.map(c => {
        const cSizesHtml = c.sizes.map(s => `
          <span class="size-tag" title="${s.tooltip || `${s.size}: ${s.orders_count} orders (${s.percentage}%)`}">
            <span class="size-tag-name">${s.size}:</span>
            <span class="size-tag-count">${s.orders_count}</span>
          </span>
        `).join("");

        const skusBadge = c.full_skus && c.full_skus.length > 1
          ? `<span class="badge badge-neutral" style="margin-bottom:4px; font-size:10.5px;">${c.full_skus.length} SKUs Merged</span><br>`
          : '';

        return `
          <tr>
            <td>
              <div class="color-badge">
                <span class="color-dot"></span>
                <span>${c.color}</span>
              </div>
            </td>
            <td>
              <div style="font-size:11.5px; color:#475569; font-family:monospace; word-break:break-all; max-width:280px;">
                ${skusBadge}
                ${c.full_skus.join("<br>")}
              </div>
            </td>
            <td>
              <div style="display:flex; flex-wrap:wrap; align-items:center;">
                ${cSizesHtml}
              </div>
            </td>
            <td style="text-align:center; font-weight:700; color:var(--primary); font-size:13px;">
              ${c.orders_count}
            </td>
            <td style="text-align:center; color:#334155;">
              ${c.pieces_count}
            </td>
            <td style="width:170px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <div class="progress-bar-bg" style="flex:1;">
                  <div class="progress-bar-fill" style="width:${c.color_share_pct}%;"></div>
                </div>
                <span style="font-size:11.5px; font-weight:600; min-width:36px; text-align:right;">${c.color_share_pct}%</span>
              </div>
            </td>
          </tr>
        `;
      }).join("");

      subTr.innerHTML = `
        <td colspan="6" style="padding:10px 16px;">
          <div class="sku-subrow-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;">
              <div style="font-size:13.5px; font-weight:700; color:#1e293b;">
                <i class="fa-solid fa-palette" style="color:var(--primary); margin-right:6px;"></i>
                Merged Color & Size Breakdown for: <span style="color:var(--primary);">${p.display_name}</span>
              </div>
              <div style="display:flex; gap:8px; align-items:center;">
                ${p.included_skus_count ? `<span class="badge badge-info">${p.included_skus_count} SKUs</span>` : ''}
                <span class="badge badge-info">${p.colors_count} Colors</span>
                <span class="badge badge-success">${p.total_orders} Total Orders</span>
              </div>
            </div>
            <table class="sku-subrow-table">
              <thead>
                <tr>
                  <th style="width:130px;">Color</th>
                  <th style="min-width:180px;">Merged Meesho SKUs</th>
                  <th>Sizes Breakdown (Merged)</th>
                  <th style="text-align:center; width:80px;">Orders</th>
                  <th style="text-align:center; width:70px;">Pieces</th>
                  <th style="width:170px;">Color Share (% of Group)</th>
                </tr>
              </thead>
              <tbody>
                ${colorRowsHtml}
              </tbody>
            </table>
          </div>
        </td>
      `;

      tbody.appendChild(mainTr);
      tbody.appendChild(subTr);
    });

  } else {
    // --- FLAT RAW SKU LIST VIEW ---
    if (theadRow) {
      theadRow.innerHTML = `
        <th style="width:36px; text-align:center;">#</th>
        <th>Full Meesho SKU</th>
        <th>Product Base Name</th>
        <th>Color</th>
        <th>Size Breakdown</th>
        <th style="text-align:center; width:100px;">Orders</th>
        <th style="text-align:center; width:80px;">Pieces</th>
      `;
    }

    let flatIdx = 1;
    data.products.forEach(p => {
      p.colors.forEach(c => {
        c.full_skus.forEach(skuName => {
          const cSizesHtml = c.sizes.map(s => `
            <span class="size-tag" title="${s.tooltip || `${s.size}: ${s.orders_count}`}">
              <span class="size-tag-name">${s.size}:</span>
              <span class="size-tag-count">${s.orders_count}</span>
            </span>
          `).join("");

          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td style="text-align:center; color:#64748b;">${flatIdx++}</td>
            <td><strong style="color:#0f172a;">${skuName}</strong></td>
            <td><span style="color:#475569;">${p.display_name}</span></td>
            <td><span class="color-badge"><span class="color-dot"></span> ${c.color}</span></td>
            <td><div style="display:flex; flex-wrap:wrap;">${cSizesHtml}</div></td>
            <td style="text-align:center; font-weight:700; color:var(--primary);">${c.orders_count}</td>
            <td style="text-align:center;">${c.pieces_count}</td>
          `;
          tbody.appendChild(tr);
        });
      });
    });
  }
}

function exportSkuColorBreakdown(format = "xlsx") {
  const searchInput = document.getElementById("sku-color-search");
  const sellerSelect = document.getElementById("sku-color-seller-filter");
  const groupSelect = document.getElementById("sku-color-group-filter");

  const search = searchInput ? searchInput.value.trim() : "";
  const seller = sellerSelect ? sellerSelect.value : "";
  const group = groupSelect ? groupSelect.value : "";

  const params = new URLSearchParams();
  params.append("format", format);
  if (search) params.append("search", search);
  if (seller) params.append("seller", seller);
  if (group) params.append("group", group);
  params.append("group_by", currentSkuViewMode === "sku" ? "sku" : "group");

  window.location.href = `/api/skus-color-breakdown/export?${params.toString()}`;
}

async function downloadAllMergedBillsPdf() {
  const btn = document.getElementById("btn-download-all-bills-pdf");
  const origHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Merging All Bills (100% Intact)...`;
  }
  showToast("Merging all label pages in Product -> Color -> Size order... Zero pages lost!", "info");

  try {
    const res = await fetch("/api/generate-all-merged-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sort_preset: "auto",
        secondary_sort: "sku",
        output_filename: "Meesho_All_Orders_Merged_Sorted.pdf"
      })
    });
    const data = await res.json();
    if (data.verified) {
      showToast(`SUCCESS! Merged all ${data.page_count} pages with bookmarks!`, "success");
      const a = document.createElement("a");
      a.href = data.download_url;
      a.download = data.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } else {
      showToast(data.detail || "Error merging PDF", "danger");
    }
  } catch (err) {
    showToast("Merge error: " + err.message, "danger");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

async function downloadAllMergedBillsSizeWisePdf() {
  const btn = document.getElementById("btn-download-size-wise-pdf");
  const origHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Merging Size-Wise (0-1Y, 1-2Y...)...`;
  }
  showToast("Merging all label pages in Design -> Size -> Color order... Zero pages lost!", "info");

  try {
    const res = await fetch("/api/generate-all-merged-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sort_preset: "auto",
        sort_mode: "size_first",
        secondary_sort: "sku",
        output_filename: "Meesho_All_Orders_Size_Wise_Merged.pdf"
      })
    });
    const data = await res.json();
    if (data.verified) {
      showToast(`SUCCESS! Merged all ${data.page_count} pages size-wise with bookmarks!`, "success");
      const a = document.createElement("a");
      a.href = data.download_url;
      a.download = data.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } else {
      showToast(data.detail || "Error generating size-wise PDF", "danger");
    }
  } catch (err) {
    showToast("PDF merge error: " + err.message, "danger");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

async function loadDashboard() {
  try {
    const res = await fetch("/api/dashboard");
    const data = await res.json();

    document.getElementById("stat-files").innerText = data.total_files || 0;
    document.getElementById("stat-pages").innerText = data.total_pages || 0;
    document.getElementById("stat-orders").innerText = data.total_orders || 0;
    document.getElementById("stat-pieces").innerText = data.total_pieces || 0;
    document.getElementById("stat-groups").innerText = data.groups_count || 0;

    // 1. Render Sellers Table
    const sellersTbody = document.querySelector("#dashboard-sellers-table tbody");
    if (sellersTbody) {
      sellersTbody.innerHTML = "";
      if (data.sellers && data.sellers.length > 0) {
        data.sellers.forEach(s => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><strong>${s.seller_account || "Unknown"}</strong></td>
            <td style="text-align:center;">${s.orders_count}</td>
            <td style="text-align:center;">${s.pieces_count}</td>
          `;
          sellersTbody.appendChild(tr);
        });
      } else {
        sellersTbody.innerHTML = `<tr><td colspan="3" style="text-align:center; color:#94a3b8;">No data loaded yet</td></tr>`;
      }
    }

    // 2. Populate Seller Filter dropdown on SKU Color card
    const sellerFilterSelect = document.getElementById("sku-color-seller-filter");
    if (sellerFilterSelect && data.sellers) {
      const currentVal = sellerFilterSelect.value;
      sellerFilterSelect.innerHTML = `<option value="">All Sellers</option>`;
      data.sellers.forEach(s => {
        if (s.seller_account) {
          const opt = document.createElement("option");
          opt.value = s.seller_account;
          opt.textContent = `${s.seller_account} (${s.orders_count})`;
          sellerFilterSelect.appendChild(opt);
        }
      });
      sellerFilterSelect.value = currentVal;
      sellerFilterSelect.onchange = () => loadSkuColorBreakdown();
    }

    // 3. Populate Product Group Filter dropdown on SKU Color card
    const groupFilterSelect = document.getElementById("sku-color-group-filter");
    if (groupFilterSelect) {
      fetch("/api/sku-groups").then(r => r.json()).then(gdata => {
        if (gdata && gdata.groups) {
          const curVal = groupFilterSelect.value;
          groupFilterSelect.innerHTML = `<option value="">All Product Groups</option><option value="__unmapped__">Unmapped Only</option>`;
          gdata.groups.forEach(g => {
            const opt = document.createElement("option");
            opt.value = g.name;
            opt.textContent = `${g.name} (${g.total_orders || 0})`;
            groupFilterSelect.appendChild(opt);
          });
          groupFilterSelect.value = curVal;
          groupFilterSelect.onchange = () => loadSkuColorBreakdown();
        }
      }).catch(e => console.error("Error loading groups for filter:", e));
    }

    // 4. Render Orders by Size Breakdown Table (Side card)
    const sizesTbody = document.querySelector("#dashboard-sizes-table tbody");
    if (sizesTbody) {
      sizesTbody.innerHTML = "";
      if (data.sizes && data.sizes.length > 0) {
        data.sizes.forEach(sz => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><span class="badge badge-info" style="font-size:12px;">${sz.size}</span></td>
            <td style="text-align:center; font-weight:700;">${sz.orders_count}</td>
            <td style="text-align:center;">${sz.pieces_count}</td>
            <td style="text-align:center;">
              <div style="display:flex; align-items:center; gap:6px; justify-content:center;">
                <span style="font-size:11.5px; color:#64748b; min-width:38px;">${sz.percentage || 0}%</span>
                <div class="progress-bar-bg" style="width:50px;">
                  <div class="progress-bar-fill" style="width:${sz.percentage || 0}%;"></div>
                </div>
              </div>
            </td>
          `;
          sizesTbody.appendChild(tr);
        });
      } else {
        sizesTbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:#94a3b8;">No data loaded yet</td></tr>`;
      }
    }

    // 5. Setup search input with debouncing
    const searchInput = document.getElementById("sku-color-search");
    if (searchInput) {
      searchInput.oninput = () => {
        clearTimeout(skuColorSearchTimer);
        skuColorSearchTimer = setTimeout(() => {
          loadSkuColorBreakdown();
        }, 300);
      };
    }

    // 6. Load the full Product & Color breakdown (ALL SKUs)
    loadSkuColorBreakdown();

  } catch (err) {
    console.error("Dashboard error:", err);
  }
}

// --- 2. Upload PDFs ---
function setupUploadDropzone() {
  const dropzone = document.getElementById("pdf-dropzone");
  const fileInput = document.getElementById("file-input");

  dropzone.addEventListener("click", (e) => {
    // Only open dialog if not clicking an existing inner button directly
    if (e.target.tagName !== "BUTTON") {
      fileInput.click();
    }
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFilesUpload(e.dataTransfer.files);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFilesUpload(e.target.files);
    }
  });
}

function setupSampleLoader() {
  const triggerLoad = async () => {
    showToast("Loading sample Meesho PDFs...", "info");
    const prog = document.getElementById("upload-progress-container");
    const progBar = document.getElementById("upload-progress-bar");
    const progText = document.getElementById("upload-progress-text");
    const progPercent = document.getElementById("upload-progress-percent");

    if (prog) {
      prog.style.display = "block";
      progBar.style.width = "20%";
      progText.innerText = "Initiating sample files...";
      progPercent.innerText = "20%";
    }

    try {
      const res = await fetch("/api/load-sample", { method: "POST" });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Server returned HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.success && data.loaded && data.loaded.length > 0) {
        // Poll background extraction
        progBar.style.width = "40%";
        progPercent.innerText = "40%";
        progText.innerText = `Extracting ${data.loaded.length} sample PDF files...`;

        const pendingIds = data.loaded.map(x => x.file_id);
        let pollCount = 0;
        let allDone = false;

        while (pollCount < 120 && !allDone) {
          await new Promise(r => setTimeout(r, 1500));
          try {
            const filesRes = await fetch("/api/files");
            if (filesRes.ok) {
              const fileList = await filesRes.json();
              const relevant = fileList.filter(f => pendingIds.includes(f.id));
              const stillProcessing = relevant.filter(f => f.status === "processing" || f.status === "pending");
              const totalExtracted = relevant.reduce((acc, f) => acc + (f.page_count || 0), 0);

              if (relevant.length > 0) {
                progText.innerText = `Extracting sample PDFs: ${totalExtracted} pages read...`;
                progBar.style.width = stillProcessing.length === 0 ? "100%" : "70%";
                progPercent.innerText = stillProcessing.length === 0 ? "100%" : "70%";
              }

              if (stillProcessing.length === 0) {
                allDone = true;
                showToast(`Loaded ${relevant.length} sample PDF files (${totalExtracted} pages) successfully!`, "success");
                await loadUploadedFiles();
                await loadDashboard();
              }
            }
          } catch (pollErr) {
            console.warn("Sample poll error:", pollErr);
          }
          pollCount++;
        }

        if (!allDone) {
          showToast("Sample files are processing in the background. Check files table shortly.", "info");
          await loadUploadedFiles();
          await loadDashboard();
        }
      } else {
        showToast(data.detail || "Error loading samples", "danger");
      }
    } catch (err) {
      if (err.message.includes("Failed to fetch") || err.message.includes("NetworkError")) {
        showToast("Server connection error: Render cloud server may be waking up. Please wait 15 seconds and try again.", "danger");
      } else {
        showToast("Error loading sample files: " + err.message, "danger");
      }
    } finally {
      setTimeout(() => {
        if (prog) prog.style.display = "none";
      }, 1500);
    }
  };

  const btnTop = document.getElementById("btn-load-sample-top");
  if (btnTop) btnTop.addEventListener("click", triggerLoad);

  const btnUpload = document.getElementById("btn-load-sample-upload");
  if (btnUpload) btnUpload.addEventListener("click", triggerLoad);
}

async function handleFilesUpload(files) {
  const fileInput = document.getElementById("file-input");
  const pdfFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith(".pdf"));

  if (pdfFiles.length === 0) {
    showToast("Please upload PDF files only.", "warning");
    if (fileInput) fileInput.value = "";
    return;
  }

  const progContainer = document.getElementById("upload-progress-container");
  const progBar = document.getElementById("upload-progress-bar");
  const progText = document.getElementById("upload-progress-text");
  const progPercent = document.getElementById("upload-progress-percent");

  progContainer.style.display = "block";
  let totalProcessed = 0;

  for (let i = 0; i < pdfFiles.length; i++) {
    const file = pdfFiles[i];
    const pct = Math.round((i / pdfFiles.length) * 100);
    progBar.style.width = `${pct}%`;
    progPercent.innerText = `${pct}%`;
    progText.innerText = `Uploading file ${i + 1} of ${pdfFiles.length}: ${file.name}...`;

    const formData = new FormData();
    formData.append("files", file);

    try {
      // 1. Upload file (fast, streams in 1-2s)
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        throw new Error(`Server returned HTTP ${res.status}: ${errText.substring(0, 100)}`);
      }

      const data = await res.json();

      if (data.success && data.uploaded && data.uploaded.length > 0) {
        const upItem = data.uploaded[0];
        const fId = upItem.file_id;

        // If completed immediately (e.g. 1-page PDF)
        if (upItem.status === "completed") {
          totalProcessed++;
          const pCnt = upItem.page_count;
          showToast(`Parsed ${file.name}: ${pCnt} pages extracted!`, "success");
          await loadUploadedFiles();
          await loadDashboard();
        } else {
          // 2. Poll for background parsing completion
          progText.innerText = `Extracting orders from ${file.name}...`;
          let pollAttempts = 0;
          let isDone = false;

          while (pollAttempts < 240 && !isDone) { // up to 6 minutes
            await new Promise(r => setTimeout(r, 1500));
            try {
              const sRes = await fetch(`/api/files/${fId}/status`);
              if (sRes.ok) {
                const sData = await sRes.json();
                if (sData.status === "completed") {
                  totalProcessed++;
                  showToast(`Parsed ${file.name}: ${sData.page_count} pages extracted!`, "success");
                  await loadUploadedFiles();
                  await loadDashboard();
                  isDone = true;
                } else if (sData.status === "error") {
                  showToast(`Error processing ${file.name}: ${sData.error_message || "Parsing error"}`, "danger");
                  isDone = true;
                } else if (sData.page_count > 0) {
                  progText.innerText = `Extracting ${file.name}: ${sData.page_count} pages read...`;
                }
              }
            } catch (pollErr) {
              console.warn("Poll attempt error:", pollErr);
            }
            pollAttempts++;
          }

          if (!isDone) {
            showToast(`${file.name} is still processing in the background. Check files table shortly.`, "info");
            await loadUploadedFiles();
          }
        }
      } else {
        showToast(`Error processing ${file.name}: ${(data.errors || []).join(", ")}`, "danger");
      }
    } catch (err) {
      console.error("Upload error:", err);
      if (err.message.includes("Failed to fetch") || err.message.includes("NetworkError")) {
        showToast(`Connection error for ${file.name}: Cloud server is waking up or connection dropped. Please wait 15 seconds and try again.`, "danger");
      } else {
        showToast(`Failed uploading ${file.name}: ${err.message}`, "danger");
      }
    }
  }

  progBar.style.width = "100%";
  progPercent.innerText = "100%";
  progText.innerText = `Completed processing!`;
  if (fileInput) fileInput.value = "";

  setTimeout(() => {
    progContainer.style.display = "none";
    progBar.style.width = "0%";
  }, 1800);
}

async function loadUploadedFiles() {
  try {
    const res = await fetch("/api/files");
    const files = await res.json();
    const tbody = document.querySelector("#files-table tbody");
    tbody.innerHTML = "";

    if (files.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#94a3b8;">No PDF files uploaded yet</td></tr>`;
      return;
    }

    files.forEach(f => {
      const tr = document.createElement("tr");
      const sizeMb = (f.file_size / (1024 * 1024)).toFixed(2);
      tr.innerHTML = `
        <td><i class="fa-solid fa-file-pdf text-indigo" style="margin-right:8px;"></i><strong>${f.filename}</strong></td>
        <td style="text-align:center;"><strong>${f.page_count}</strong></td>
        <td style="text-align:center;">${sizeMb} MB</td>
        <td style="text-align:center;"><span class="badge badge-success">${f.status}</span></td>
        <td>${f.uploaded_at ? f.uploaded_at.substring(0, 19).replace('T', ' ') : '-'}</td>
        <td style="text-align:center;">
          <button class="btn btn-danger btn-sm" onclick="deleteUploadedFile(${f.id})">
            <i class="fa-solid fa-trash-can"></i>
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error loading files:", err);
  }
}

async function deleteUploadedFile(fileId) {
  if (!confirm("Are you sure you want to remove this file and its extracted orders?")) return;
  try {
    const res = await fetch(`/api/files/${fileId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      showToast("File removed successfully", "success");
      loadUploadedFiles();
      loadDashboard();
    }
  } catch (err) {
    showToast("Failed to remove file: " + err.message, "danger");
  }
}

// --- 3. Order Summary / Matrix ---
async function loadFilterOptions() {
  try {
    const res = await fetch("/api/dashboard");
    const data = await res.json();

    const summarySeller = document.getElementById("summary-seller-filter");
    const ordersSeller = document.getElementById("orders-seller-filter");

    const curSumVal = summarySeller.value;
    const curOrdVal = ordersSeller.value;

    summarySeller.innerHTML = '<option value="">All Sellers</option>';
    ordersSeller.innerHTML = '<option value="">All Sellers</option>';

    if (data.sellers) {
      data.sellers.forEach(s => {
        if (!s.seller_account) return;
        const opt1 = document.createElement("option");
        opt1.value = s.seller_account;
        opt1.innerText = `${s.seller_account} (${s.orders_count})`;
        summarySeller.appendChild(opt1);

        const opt2 = document.createElement("option");
        opt2.value = s.seller_account;
        opt2.innerText = s.seller_account;
        ordersSeller.appendChild(opt2);
      });
    }

    summarySeller.value = curSumVal;
    ordersSeller.value = curOrdVal;

    // Populate Group Filter for summary
    const groupRes = await fetch("/api/sku-groups");
    const groupData = await groupRes.json();
    const summaryGroup = document.getElementById("summary-group-filter");
    const curGroupVal = summaryGroup.value;
    summaryGroup.innerHTML = `
      <option value="">All Product Groups</option>
      <option value="__unmapped__">Unmapped SKUs Only</option>
    `;
    if (groupData.groups) {
      groupData.groups.forEach(g => {
        const opt = document.createElement("option");
        opt.value = g.name;
        opt.innerText = g.name;
        summaryGroup.appendChild(opt);
      });
    }
    summaryGroup.value = curGroupVal;
  } catch (err) {
    console.error("Filter options error:", err);
  }
}

async function loadSummaryTable() {
  const search = document.getElementById("summary-search").value.trim();
  const seller = document.getElementById("summary-seller-filter").value;
  const group = document.getElementById("summary-group-filter").value;

  const url = new URL("/api/summary", window.location.origin);
  if (search) url.searchParams.set("search", search);
  if (seller) url.searchParams.set("seller", seller);
  if (group) url.searchParams.set("group", group);

  try {
    const res = await fetch(url);
    const data = await res.json();

    const thead = document.querySelector("#matrix-table thead");
    const tbody = document.querySelector("#matrix-table tbody");

    thead.innerHTML = "";
    tbody.innerHTML = "";

    if (!data.columns || data.columns.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#94a3b8; padding:30px;">No order data found matching criteria</td></tr>`;
      return;
    }

    // Build Header
    let headHtml = `
      <tr>
        <th style="min-width:220px;">Physical Product / Group</th>
        <th style="min-width:200px;">Original SKU</th>
    `;
    data.columns.forEach(col => {
      headHtml += `<th style="text-align:center; min-width:65px;">${col}</th>`;
    });
    headHtml += `
        <th style="text-align:center; min-width:80px;">Total Pieces</th>
        <th style="text-align:center; min-width:80px;">Orders</th>
      </tr>
    `;
    thead.innerHTML = headHtml;

    // Build Rows
    data.rows.forEach(r => {
      const isGroup = r.type === "group_header";
      const tr = document.createElement("tr");
      tr.className = isGroup ? "matrix-group-row" : "";

      let rowHtml = `
        <td><strong>${r.group_name}</strong></td>
        <td>${r.sku}</td>
      `;
      data.columns.forEach(col => {
        const cnt = r.sizes[col] || 0;
        rowHtml += `<td class="matrix-number" style="${cnt > 0 ? 'font-weight:600;' : 'color:#cbd5e1;'}">${cnt}</td>`;
      });
      rowHtml += `
        <td class="matrix-number"><strong>${r.total_pieces}</strong></td>
        <td class="matrix-number"><strong>${r.total_orders}</strong></td>
      `;
      tr.innerHTML = rowHtml;
      tbody.appendChild(tr);

      // Child sub-rows for mapped SKUs
      if (r.subrows && r.subrows.length > 0) {
        r.subrows.forEach(sub => {
          const subTr = document.createElement("tr");
          subTr.className = "matrix-sku-row";
          let subHtml = `
            <td style="color:#64748b; font-size:12px; padding-left:24px;">↳ ${sub.sku}</td>
            <td style="color:#64748b; font-size:12px;">(Original)</td>
          `;
          data.columns.forEach(col => {
            const cnt = sub.sizes[col] || 0;
            subHtml += `<td class="matrix-number" style="font-size:12px; ${cnt > 0 ? '' : 'color:#cbd5e1;'}">${cnt}</td>`;
          });
          subHtml += `
            <td class="matrix-number" style="font-size:12px;">${sub.total_pieces}</td>
            <td class="matrix-number" style="font-size:12px;">${sub.total_orders}</td>
          `;
          subTr.innerHTML = subHtml;
          tbody.appendChild(subTr);
        });
      }
    });

    // Grand Total Row
    const totTr = document.createElement("tr");
    totTr.className = "matrix-total-row";
    let totHtml = `
      <td><strong>COMBINED GRAND TOTAL</strong></td>
      <td><strong>All Products</strong></td>
    `;
    data.columns.forEach(col => {
      const cnt = data.column_totals[col] || 0;
      totHtml += `<td class="matrix-number"><strong>${cnt}</strong></td>`;
    });
    totHtml += `
      <td class="matrix-number"><strong>${data.grand_total.pieces}</strong></td>
      <td class="matrix-number"><strong>${data.grand_total.orders}</strong></td>
    `;
    totTr.innerHTML = totHtml;
    tbody.appendChild(totTr);

  } catch (err) {
    console.error("Summary error:", err);
  }
}

function exportSummary(format) {
  const search = document.getElementById("summary-search").value.trim();
  const seller = document.getElementById("summary-seller-filter").value;
  const group = document.getElementById("summary-group-filter").value;

  const url = new URL("/api/summary/export", window.location.origin);
  url.searchParams.set("format", format);
  if (search) url.searchParams.set("search", search);
  if (seller) url.searchParams.set("seller", seller);
  if (group) url.searchParams.set("group", group);

  window.open(url.toString(), "_blank");
}

let rawUnmappedList = [];
let unmappedSortOrder = "name_asc";

let groupsCompactMode = true;
let groupOpenState = {}; // { [groupId]: boolean }

async function loadSkuGroups() {
  try {
    const [groupsRes, catsRes] = await Promise.all([
      fetch("/api/sku-groups"),
      fetch("/api/categories")
    ]);
    const data = await groupsRes.json();
    availableGroups = data.groups || [];
    rawUnmappedList = data.unmapped_skus || [];

    try {
      const catsData = await catsRes.json();
      if (catsData.success && Array.isArray(catsData.categories)) {
        availableCategories = catsData.categories;
        updateCategoryDropdowns();
      }
    } catch (_) {}

    renderSortedUnmappedList();
    renderActiveProductGroups();
  } catch (err) {
    console.error("Mapping error:", err);
  }
}

function toggleAllGroupsCollapse() {
  groupsCompactMode = !groupsCompactMode;
  const btn = document.getElementById("btn-toggle-all-groups");
  if (btn) {
    btn.innerHTML = groupsCompactMode
      ? '<i class="fa-solid fa-expand"></i> Expand All'
      : '<i class="fa-solid fa-compress"></i> Compact View';
  }
  availableGroups.forEach(g => {
    groupOpenState[g.id] = !groupsCompactMode;
  });
  renderActiveProductGroups();
}

function toggleGroupAccordion(groupId) {
  groupOpenState[groupId] = !groupOpenState[groupId];
  renderActiveProductGroups();
}

function renderActiveProductGroups() {
  const groupsContainer = document.getElementById("product-groups-container");
  if (!groupsContainer) return;

  const searchQuery = (document.getElementById("active-groups-search")?.value || "").toLowerCase().trim();
  const categoryFilter = document.getElementById("active-groups-category-filter")?.value || "";
  const sortMode = document.getElementById("active-groups-sort")?.value || "orders_desc";

  let list = [...availableGroups];

  // 1. Search Filter (by group name, category, or any mapped SKU)
  if (searchQuery) {
    list = list.filter(g =>
      g.name.toLowerCase().includes(searchQuery) ||
      (g.category && g.category.toLowerCase().includes(searchQuery)) ||
      (g.skus && g.skus.some(s => s.sku.toLowerCase().includes(searchQuery)))
    );
  }

  // 2. Category Filter
  if (categoryFilter) {
    const cf = categoryFilter.toLowerCase();
    list = list.filter(g => {
      const gc = (g.category || "General").toLowerCase();
      if (cf === "black patti" || cf === "black pati") return gc === "black patti" || gc === "black pati";
      return gc === cf;
    });
  }

  // 3. Sorting
  if (sortMode === "orders_desc") {
    list.sort((a, b) => (b.total_orders || 0) - (a.total_orders || 0));
  } else if (sortMode === "name_asc") {
    list.sort((a, b) => a.name.localeCompare(b.name));
  } else if (sortMode === "skus_desc") {
    list.sort((a, b) => (b.skus?.length || 0) - (a.skus?.length || 0));
  } else if (sortMode === "category") {
    const catOrderMap = {};
    availableCategories.forEach((c, idx) => {
      catOrderMap[c.name.toLowerCase()] = c.display_order || (idx + 1);
    });
    list.sort((a, b) => {
      const ca = catOrderMap[(a.category || '').toLowerCase()] || 99;
      const cb = catOrderMap[(b.category || '').toLowerCase()] || 99;
      if (ca !== cb) return ca - cb;
      return a.name.localeCompare(b.name);
    });
  }

  // 4. Update Count Badge
  const countBadge = document.getElementById("active-groups-count-badge");
  if (countBadge) {
    if (searchQuery || categoryFilter) {
      countBadge.innerText = `${list.length} of ${availableGroups.length} Groups`;
    } else {
      const totalSkus = availableGroups.reduce((acc, g) => acc + (g.skus?.length || 0), 0);
      countBadge.innerText = `${availableGroups.length} Groups (${totalSkus} SKUs)`;
    }
  }

  groupsContainer.innerHTML = "";

  if (list.length === 0) {
    groupsContainer.innerHTML = `
      <div style="text-align:center; padding:35px; color:#94a3b8; font-size:13px;">
        <i class="fa-solid fa-magnifying-glass" style="font-size:24px; margin-bottom:8px; display:block; opacity:0.4;"></i>
        ${searchQuery || categoryFilter ? 'No product groups match your search or filter.' : 'No product groups created yet. Select SKUs on the left or use ⚡ 1-Click Auto-Group!'}
      </div>
    `;
    return;
  }

  list.forEach(g => {
    const isExpanded = searchQuery ? true : (groupOpenState[g.id] !== undefined ? groupOpenState[g.id] : !groupsCompactMode);
    const cat = g.category || 'General';
    const isBlackPatti = cat === 'Black Patti' || cat === 'Black Pati';
    const catBadgeStyle = cat === 'Plazo'
      ? 'background:#fef3c7; color:#92400e; border:1px solid #fde68a;'
      : (cat === 'Women T-Shirt'
        ? 'background:#e0e7ff; color:#3730a3; border:1px solid #c7d2fe;'
        : (cat === 'Men T-Shirt'
          ? 'background:#dbeafe; color:#1e40af; border:1px solid #93c5fd;'
          : (isBlackPatti
            ? 'background:#1e293b; color:#f8fafc; border:1px solid #0f172a;'
            : 'background:#f1f5f9; color:#475569; border:1px solid #e2e8f0;')));
    const foundCatObj = availableCategories.find(c => c.name.toLowerCase() === cat.toLowerCase());
    const catIcon = foundCatObj ? (foundCatObj.label || `${foundCatObj.icon || '🏷️'} ${cat}`) : (isBlackPatti ? '🏷️ Black Patti' : '🏷️ ' + cat);

    // Build category options
    let catOptionsHtml = "";
    let hasCurrentCat = false;
    availableCategories.forEach(c => {
      const isSel = (cat.toLowerCase() === c.name.toLowerCase());
      if (isSel) hasCurrentCat = true;
      const label = c.label || `${c.icon || '🏷️'} ${c.name}`;
      catOptionsHtml += `<option value="${escapeHtml(c.name)}" ${isSel ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    });
    if (!hasCurrentCat && cat) {
      catOptionsHtml += `<option value="${escapeHtml(cat)}" selected>🏷️ ${escapeHtml(cat)}</option>`;
    }
    catOptionsHtml += `<option value="__add_new__" style="color:#0284c7; font-weight:700;">➕ Add New Category...</option>`;

    const div = document.createElement("div");
    div.style.cssText = "border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; background:#ffffff; box-shadow:0 1px 2px rgba(0,0,0,0.02); transition:box-shadow 0.15s;";
    div.onmouseenter = () => div.style.boxShadow = "0 3px 6px rgba(0,0,0,0.06)";
    div.onmouseleave = () => div.style.boxShadow = "0 1px 2px rgba(0,0,0,0.02)";

    div.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <div style="flex:1; min-width:200px; cursor:pointer;" onclick="toggleGroupAccordion(${g.id})">
          <div style="font-weight:700; font-size:14.5px; color:#0f172a; display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <i class="fa-solid fa-chevron-${isExpanded ? 'down' : 'right'}" style="font-size:11px; color:#94a3b8; width:12px;"></i>
            <span>${escapeHtml(g.name)}</span>
            <span class="category-badge-pill" style="${catBadgeStyle} font-size:11px; padding:1px 7px; border-radius:10px; font-weight:600;">
              ${catIcon}
            </span>
          </div>
          <div style="font-size:12px; color:#64748b; margin-top:3px; padding-left:18px;">
            <strong style="color:#0284c7;">${g.skus?.length || 0}</strong> SKUs mapped | <strong style="color:#16a34a;">${g.total_orders || 0}</strong> Orders | <strong>${g.total_pieces || 0}</strong> Pieces
          </div>
        </div>

        <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
          <select onchange="changeGroupCategory(${g.id}, this.value)" style="font-size:11.5px; padding:3px 6px; border-radius:4px; border:1px solid #cbd5e1; background:#ffffff; color:#334155; font-weight:600; cursor:pointer;" title="Change category placement">
            ${catOptionsHtml}
          </select>
          <button class="btn btn-primary btn-sm" onclick="openManageGroupSkusModal(${g.id})" title="Add or remove SKUs for this group" style="font-size:12px; padding:4px 8px;">
            <i class="fa-solid fa-layer-group"></i> Add / Remove SKUs
          </button>
          <button class="btn btn-secondary btn-sm" onclick="renameProductGroup(${g.id}, '${escapeHtml(g.name)}')" title="Rename group" style="font-size:12px; padding:4px 8px;">
            <i class="fa-solid fa-pen"></i>
          </button>
          <button class="btn btn-danger btn-sm" onclick="deleteProductGroup(${g.id})" title="Delete entire group" style="font-size:12px; padding:4px 8px;">
            <i class="fa-solid fa-trash-can"></i>
          </button>
          <button class="btn btn-secondary btn-sm" onclick="toggleGroupAccordion(${g.id})" title="${isExpanded ? 'Collapse SKUs' : 'Expand SKUs'}" style="font-size:12px; padding:4px 8px;">
            <i class="fa-solid fa-${isExpanded ? 'chevron-up' : 'chevron-down'}"></i>
          </button>
        </div>
      </div>

      <!-- Mapped SKUs Accordion Body -->
      <div id="group-skus-body-${g.id}" style="display:${isExpanded ? 'block' : 'none'}; margin-top:10px; background:#f8fafc; border-radius:6px; padding:10px 12px; font-size:12.5px; border-top:1px solid #f1f5f9;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding-bottom:5px; border-bottom:1px solid #e2e8f0;">
          <span style="font-size:11px; font-weight:700; text-transform:uppercase; color:#64748b; letter-spacing:0.5px;">
            Mapped SKUs (${g.skus?.length || 0})
          </span>
          <button class="btn btn-xs btn-outline-primary" onclick="openManageGroupSkusModal(${g.id})" style="font-size:11px; padding:2px 8px; border-radius:4px; font-weight:600;">
            <i class="fa-solid fa-plus"></i> Add SKUs
          </button>
        </div>
        ${g.skus && g.skus.length > 0 ? `
          <ul style="padding:0; margin:0; list-style:none; color:#475569; max-height:220px; overflow-y:auto; display:flex; flex-direction:column; gap:4px;">
            ${g.skus.map(s => `
              <li style="display:flex; justify-content:space-between; align-items:center; padding:4px 8px; border-radius:4px; background:#ffffff; border:1px solid #edf2f7; transition:all 0.15s;" onmouseover="this.style.borderColor='#cbd5e1'" onmouseout="this.style.borderColor='#edf2f7'">
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-right:8px;" title="${escapeHtml(s.sku)}">
                  <span style="font-weight:500; color:#1e293b;">${escapeHtml(s.sku)}</span>
                  <span style="color:#94a3b8; font-size:11.5px; margin-left:4px;">(${s.orders_count} orders${s.pieces_count ? ', ' + s.pieces_count + ' pcs' : ''})</span>
                </span>
                <button class="btn-sku-remove-quick" data-group-id="${g.id}" data-sku="${escapeHtml(s.sku)}" onclick="quickRemoveSkuFromGroup(event)" title="Remove from this group (moves back outside to unmapped list)" style="border:none; background:none; color:#94a3b8; cursor:pointer; padding:2px 6px; border-radius:3px; font-size:12px; line-height:1;" onmouseover="this.style.color='#ef4444'; this.style.background='#fee2e2';" onmouseout="this.style.color='#94a3b8'; this.style.background='transparent';">
                  <i class="fa-solid fa-xmark"></i>
                </button>
              </li>
            `).join('')}
          </ul>
        ` : `
          <div style="text-align:center; padding:12px; color:#94a3b8; font-size:12px;">
            No SKUs currently mapped to this group.<br>
            <button class="btn btn-xs btn-primary" style="margin-top:6px;" onclick="openManageGroupSkusModal(${g.id})"><i class="fa-solid fa-plus"></i> Add SKUs Now</button>
          </div>
        `}
      </div>
    `;
    groupsContainer.appendChild(div);
  });
}

function onUnmappedSortChange() {
  const sortSelect = document.getElementById("unmapped-sort");
  if (sortSelect) {
    unmappedSortOrder = sortSelect.value;
    renderSortedUnmappedList();
  }
}

function renderSortedUnmappedList() {
  let list = [...rawUnmappedList];
  if (unmappedSortOrder === "name_asc") {
    list.sort((a, b) => a.sku.localeCompare(b.sku));
  } else {
    list.sort((a, b) => b.orders_count - a.orders_count);
  }

  const query = (document.getElementById("unmapped-search")?.value || "").toLowerCase().trim();
  if (query) {
    list = list.filter(u => u.sku.toLowerCase().includes(query) || (u.sellers || "").toLowerCase().includes(query));
  }

  // Update match count & quick select bar
  const actionsBar = document.getElementById("unmapped-search-actions");
  const matchCount = document.getElementById("unmapped-match-count");
  if (actionsBar && matchCount) {
    if (query) {
      actionsBar.style.display = "flex";
      matchCount.innerText = `Found ${list.length} SKUs matching "${query}"`;
    } else {
      actionsBar.style.display = "none";
    }
  }

  const unmappedTbody = document.querySelector("#unmapped-sku-table tbody");
  unmappedTbody.innerHTML = "";

  if (list.length === 0) {
    unmappedTbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:#94a3b8; padding:24px;">No matching unmapped SKUs</td></tr>`;
    return;
  }

  list.forEach(u => {
    const isChecked = selectedUnmappedSkus.has(u.sku);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="unmapped-checkbox" data-sku="${escapeHtml(u.sku)}" ${isChecked ? 'checked' : ''}></td>
      <td>
        <div style="font-weight:600; color:#1e293b;">${u.sku}</div>
        <div style="font-size:11px; color:#64748b;"><i class="fa-solid fa-store" style="font-size:10px;"></i> ${u.sellers || "Unknown Seller"}</div>
      </td>
      <td style="text-align:center; font-weight:600;">${u.orders_count}</td>
      <td style="text-align:center;">${u.pieces_count}</td>
    `;
    unmappedTbody.appendChild(tr);
  });

  // Attach checkbox listeners
  document.querySelectorAll(".unmapped-checkbox").forEach(cb => {
    cb.addEventListener("change", (e) => {
      const sku = e.target.getAttribute("data-sku");
      if (e.target.checked) {
        selectedUnmappedSkus.add(sku);
      } else {
        selectedUnmappedSkus.delete(sku);
      }
      updateCombineButtonState();
    });
  });

  // Check All Checkbox
  const checkAll = document.getElementById("check-all-unmapped");
  if (checkAll) {
    checkAll.checked = false;
    checkAll.onchange = (e) => {
      const isChecked = e.target.checked;
      document.querySelectorAll(".unmapped-checkbox").forEach(cb => {
        cb.checked = isChecked;
        const sku = cb.getAttribute("data-sku");
        if (isChecked) selectedUnmappedSkus.add(sku);
        else selectedUnmappedSkus.delete(sku);
      });
      updateCombineButtonState();
    };
  }
}

function selectAllFilteredSkus() {
  const query = (document.getElementById("unmapped-search")?.value || "").toLowerCase().trim();
  if (!query) return;

  const matching = rawUnmappedList.filter(u => u.sku.toLowerCase().includes(query) || (u.sellers || "").toLowerCase().includes(query));
  matching.forEach(u => selectedUnmappedSkus.add(u.sku));

  renderSortedUnmappedList();
  updateCombineButtonState();
  showToast(`Selected all ${matching.length} SKUs matching "${query}"! Click "Combine Selected" to create group.`, "info");
}

async function triggerAutoGroupAll() {
  if (!confirm("This will automatically detect and combine all common products across your seller accounts (e.g. all BEST MOOD PLAZO, all Hug Me Taddy, all IFM variants). Continue?")) return;

  showToast("Auto-grouping common products across seller accounts...", "info");
  try {
    const res = await fetch("/api/sku-clusters/auto-group-all", { method: "POST" });
    const data = await res.json();
    if (data.success && data.created) {
      showToast(`Successfully created ${data.created.length} product groups combining multiple accounts!`, "success");
      await loadSkuGroups();
      await loadDashboard();
    } else {
      showToast("No additional groups could be automatically created.", "info");
    }
  } catch (err) {
    showToast("Auto-group error: " + err.message, "danger");
  }
}

function updateCombineButtonState() {
  const btn = document.getElementById("btn-open-group-modal");
  if (btn) {
    btn.disabled = selectedUnmappedSkus.size === 0;
  }
}

// Modal for Group Creation
document.getElementById("btn-open-group-modal").addEventListener("click", () => {
  if (selectedUnmappedSkus.size === 0) return;
  const listEl = document.getElementById("modal-selected-skus-list");
  listEl.innerHTML = "";
  selectedUnmappedSkus.forEach(s => {
    const li = document.createElement("li");
    li.innerText = s;
    listEl.appendChild(li);
  });

  // Suggest clean name from first SKU
  const firstSku = Array.from(selectedUnmappedSkus)[0];
  const suggestedName = firstSku.replace(/[()\[\]]/g, "").replace(/\s+/g, " ").trim();
  document.getElementById("modal-group-name").value = suggestedName;

  openModal("modal-create-group");
});

async function confirmCreateGroup() {
  const name = document.getElementById("modal-group-name").value.trim();
  if (!name) {
    showToast("Please enter a product group name", "warning");
    return;
  }

  const skus = Array.from(selectedUnmappedSkus);
  try {
    const res = await fetch("/api/sku-groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, skus })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Product Group '${name}' created successfully!`, "success");
      closeModal("modal-create-group");
      loadSkuGroups();
      loadDashboard();
    } else {
      showToast(data.detail || "Error creating group", "danger");
    }
  } catch (err) {
    showToast("Failed to create group: " + err.message, "danger");
  }
}

async function renameProductGroup(groupId, currentName) {
  const newName = prompt("Enter new name for product group:", currentName);
  if (!newName || !newName.trim() || newName.trim() === currentName) return;

  try {
    const res = await fetch(`/api/sku-groups/${groupId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Group renamed successfully", "success");
      loadSkuGroups();
    }
  } catch (err) {
    showToast("Failed to rename group: " + err.message, "danger");
  }
}

async function deleteProductGroup(groupId) {
  if (!confirm("Remove this product group? The mapped SKUs will return to unmapped status.")) return;
  try {
    const res = await fetch(`/api/sku-groups/${groupId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      showToast("Group removed", "info");
      loadSkuGroups();
      loadDashboard();
    }
  } catch (err) {
    showToast("Failed to delete group: " + err.message, "danger");
  }
}

async function changeGroupCategory(groupId, newCategory) {
  if (newCategory === "__add_new__") {
    openAddCategoryModal(groupId);
    return;
  }
  try {
    const res = await fetch(`/api/sku-groups/${groupId}/category`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: newCategory })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Updated category to ${newCategory}`, "success");
      await loadSkuGroups();
      loadSkuColorBreakdown();
    } else {
      showToast(data.detail || "Failed to update category", "danger");
      renderActiveProductGroups();
    }
  } catch (err) {
    showToast("Failed to update category: " + err.message, "danger");
    renderActiveProductGroups();
  }
}

// --- Manage Group SKUs (Add / Remove) Logic ---
let currentManageGroupId = null;
let manageGroupData = null; // { group: ..., unmapped_skus: ... }
let manageInsideSelected = new Set();
let manageOutsideSelected = new Set();

async function openManageGroupSkusModal(groupId) {
  currentManageGroupId = groupId;
  manageInsideSelected.clear();
  manageOutsideSelected.clear();

  const titleEl = document.getElementById("manage-group-modal-title");
  const subtitleEl = document.getElementById("manage-group-modal-subtitle");
  document.getElementById("manage-group-modal-id").value = groupId;

  titleEl.innerText = "Loading Group...";
  subtitleEl.innerText = "Please wait while fetching SKUs...";
  document.getElementById("manage-inside-list").innerHTML = `<div style="text-align:center; padding:30px; color:#94a3b8;"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>`;
  document.getElementById("manage-outside-list").innerHTML = `<div style="text-align:center; padding:30px; color:#94a3b8;"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>`;

  openModal("modal-manage-group-skus");

  try {
    const res = await fetch(`/api/sku-groups/${groupId}`);
    const data = await res.json();
    if (!data.success && !data.group) {
      showToast("Group not found", "danger");
      closeModal("modal-manage-group-skus");
      return;
    }

    manageGroupData = data;
    titleEl.innerText = data.group.name;
    subtitleEl.innerText = `${data.group.skus.length} SKUs combined | ${data.group.total_orders} Orders | ${data.group.total_pieces} Pieces`;

    document.getElementById("manage-search-inside").value = "";
    document.getElementById("manage-search-outside").value = "";
    document.getElementById("manage-check-all-inside").checked = false;
    document.getElementById("manage-check-all-outside").checked = false;

    renderManageModalLists();
  } catch (err) {
    showToast("Failed to load group details: " + err.message, "danger");
    closeModal("modal-manage-group-skus");
  }
}

function renderManageModalLists() {
  if (!manageGroupData || !manageGroupData.group) return;

  const insideList = manageGroupData.group.skus || [];
  const outsideList = manageGroupData.unmapped_skus || [];

  // 1. Filter and render INSIDE list
  const insideQuery = (document.getElementById("manage-search-inside")?.value || "").toLowerCase().trim();
  let filteredInside = insideList;
  if (insideQuery) {
    filteredInside = insideList.filter(s =>
      s.sku.toLowerCase().includes(insideQuery) || (s.sellers || "").toLowerCase().includes(insideQuery)
    );
  }

  document.getElementById("manage-count-inside").innerText = `${filteredInside.length}${insideQuery ? ' of ' + insideList.length : ''} SKUs`;
  const insideContainer = document.getElementById("manage-inside-list");
  insideContainer.innerHTML = "";

  if (filteredInside.length === 0) {
    insideContainer.innerHTML = `
      <div style="text-align:center; padding:30px; color:#94a3b8; font-size:12.5px;">
        ${insideQuery ? 'No matching SKUs in group' : 'No SKUs currently in this group.<br>Add from the outside column.'}
      </div>
    `;
  } else {
    filteredInside.forEach(s => {
      const isChecked = manageInsideSelected.has(s.sku);
      const row = document.createElement("div");
      row.className = "manage-sku-item";
      row.innerHTML = `
        <label style="display:flex; align-items:center; gap:8px; margin:0; cursor:pointer; flex:1; overflow:hidden;">
          <input type="checkbox" class="inside-cb" data-sku="${escapeHtml(s.sku)}" ${isChecked ? 'checked' : ''}>
          <div style="overflow:hidden;">
            <div style="font-weight:600; font-size:12px; color:#1e293b; text-overflow:ellipsis; overflow:hidden; white-space:nowrap;" title="${escapeHtml(s.sku)}">
              ${escapeHtml(s.sku)}
            </div>
            <div style="font-size:11px; color:#64748b; display:flex; align-items:center; gap:4px; flex-wrap:wrap; margin-top:2px;">
              <span class="badge" style="background:#e2e8f0; color:#334155; font-size:10px; padding:1px 5px; border-radius:3px;">${s.orders_count} orders</span>
              <span class="badge" style="background:#e2e8f0; color:#334155; font-size:10px; padding:1px 5px; border-radius:3px;">${s.pieces_count} pcs</span>
              ${s.sellers ? `<span style="color:#94a3b8; font-size:10.5px;"><i class="fa-solid fa-store" style="font-size:9px;"></i> ${escapeHtml(s.sellers)}</span>` : ''}
            </div>
          </div>
        </label>
        <button class="btn btn-xs btn-outline-danger btn-remove-inside-sku" data-sku="${escapeHtml(s.sku)}" title="Remove this SKU from group (moves back outside)" style="padding:2px 8px; font-size:11px; margin-left:6px; white-space:nowrap;">
          <i class="fa-solid fa-arrow-right-from-bracket"></i> Remove
        </button>
      `;
      insideContainer.appendChild(row);
    });
  }

  // Attach event listeners for inside
  insideContainer.querySelectorAll(".inside-cb").forEach(cb => {
    cb.addEventListener("change", (e) => {
      const sku = e.target.getAttribute("data-sku");
      if (e.target.checked) manageInsideSelected.add(sku);
      else manageInsideSelected.delete(sku);
      updateManageInsideButtons();
    });
  });

  insideContainer.querySelectorAll(".btn-remove-inside-sku").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const sku = btn.getAttribute("data-sku");
      removeSingleSkuFromModal(sku);
    });
  });

  updateManageInsideButtons();

  // 2. Filter and render OUTSIDE list
  const outsideQuery = (document.getElementById("manage-search-outside")?.value || "").toLowerCase().trim();
  const outsideFilterMode = document.getElementById("manage-filter-outside-mode")?.value || "unmapped";

  let baseOutside = [...outsideList];
  if (outsideFilterMode === "all" && availableGroups) {
    availableGroups.forEach(grp => {
      if (grp.id !== currentManageGroupId && grp.skus) {
        grp.skus.forEach(os => {
          if (!insideList.some(ins => ins.sku === os.sku) && !baseOutside.some(bo => bo.sku === os.sku)) {
            baseOutside.push({
              ...os,
              sellers: os.sellers || (grp.name ? `Group: ${grp.name}` : '')
            });
          }
        });
      }
    });
  }

  let filteredOutside = baseOutside;
  if (outsideQuery) {
    filteredOutside = baseOutside.filter(u =>
      u.sku.toLowerCase().includes(outsideQuery) || (u.sellers || "").toLowerCase().includes(outsideQuery)
    );
  }

  document.getElementById("manage-count-outside").innerText = `${filteredOutside.length}${outsideQuery ? ' of ' + baseOutside.length : ''} SKUs`;
  const outsideContainer = document.getElementById("manage-outside-list");
  outsideContainer.innerHTML = "";

  if (filteredOutside.length === 0) {
    outsideContainer.innerHTML = `
      <div style="text-align:center; padding:30px; color:#94a3b8; font-size:12.5px;">
        ${outsideQuery ? 'No matching outside SKUs' : 'No available unmapped SKUs outside.'}
      </div>
    `;
  } else {
    filteredOutside.forEach(u => {
      const isChecked = manageOutsideSelected.has(u.sku);
      const row = document.createElement("div");
      row.className = "manage-sku-item";
      row.innerHTML = `
        <label style="display:flex; align-items:center; gap:8px; margin:0; cursor:pointer; flex:1; overflow:hidden;">
          <input type="checkbox" class="outside-cb" data-sku="${escapeHtml(u.sku)}" ${isChecked ? 'checked' : ''}>
          <div style="overflow:hidden;">
            <div style="font-weight:600; font-size:12px; color:#1e293b; text-overflow:ellipsis; overflow:hidden; white-space:nowrap;" title="${escapeHtml(u.sku)}">
              ${escapeHtml(u.sku)}
            </div>
            <div style="font-size:11px; color:#64748b; display:flex; align-items:center; gap:4px; flex-wrap:wrap; margin-top:2px;">
              <span class="badge" style="background:#e2e8f0; color:#334155; font-size:10px; padding:1px 5px; border-radius:3px;">${u.orders_count || 0} orders</span>
              <span class="badge" style="background:#e2e8f0; color:#334155; font-size:10px; padding:1px 5px; border-radius:3px;">${u.pieces_count || 0} pcs</span>
              ${u.sellers ? `<span style="color:#94a3b8; font-size:10.5px;"><i class="fa-solid fa-store" style="font-size:9px;"></i> ${escapeHtml(u.sellers)}</span>` : ''}
            </div>
          </div>
        </label>
        <button class="btn btn-xs btn-primary btn-add-outside-sku" data-sku="${escapeHtml(u.sku)}" title="Add this SKU into group" style="padding:2px 8px; font-size:11px; margin-left:6px; white-space:nowrap;">
          <i class="fa-solid fa-plus"></i> Add
        </button>
      `;
      outsideContainer.appendChild(row);
    });
  }

  // Attach event listeners for outside
  outsideContainer.querySelectorAll(".outside-cb").forEach(cb => {
    cb.addEventListener("change", (e) => {
      const sku = e.target.getAttribute("data-sku");
      if (e.target.checked) manageOutsideSelected.add(sku);
      else manageOutsideSelected.delete(sku);
      updateManageOutsideButtons();
    });
  });

  outsideContainer.querySelectorAll(".btn-add-outside-sku").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const sku = btn.getAttribute("data-sku");
      addSingleSkuFromModal(sku);
    });
  });

  updateManageOutsideButtons();
}

function filterInsideSkus() {
  renderManageModalLists();
}

function filterOutsideSkus() {
  renderManageModalLists();
}

function toggleSelectAllInside(isChecked) {
  const query = (document.getElementById("manage-search-inside")?.value || "").toLowerCase().trim();
  const insideList = manageGroupData?.group?.skus || [];
  const filtered = query
    ? insideList.filter(s => s.sku.toLowerCase().includes(query) || (s.sellers || "").toLowerCase().includes(query))
    : insideList;

  filtered.forEach(s => {
    if (isChecked) manageInsideSelected.add(s.sku);
    else manageInsideSelected.delete(s.sku);
  });
  renderManageModalLists();
}

function toggleSelectAllOutside(isChecked) {
  const query = (document.getElementById("manage-search-outside")?.value || "").toLowerCase().trim();
  const outsideList = manageGroupData?.unmapped_skus || [];
  const filtered = query
    ? outsideList.filter(u => u.sku.toLowerCase().includes(query) || (u.sellers || "").toLowerCase().includes(query))
    : outsideList;

  filtered.forEach(u => {
    if (isChecked) manageOutsideSelected.add(u.sku);
    else manageOutsideSelected.delete(u.sku);
  });
  renderManageModalLists();
}

function updateManageInsideButtons() {
  const btn = document.getElementById("btn-remove-selected-skus");
  const countSpan = document.getElementById("manage-selected-inside-count");
  if (btn) {
    btn.disabled = manageInsideSelected.size === 0;
    btn.innerHTML = `<i class="fa-solid fa-arrow-right-from-bracket"></i> Remove Selected (${manageInsideSelected.size})`;
  }
  if (countSpan) {
    countSpan.innerText = `${manageInsideSelected.size} selected`;
  }
}

function updateManageOutsideButtons() {
  const btn = document.getElementById("btn-add-selected-skus");
  const countSpan = document.getElementById("manage-selected-outside-count");
  if (btn) {
    btn.disabled = manageOutsideSelected.size === 0;
    btn.innerHTML = `<i class="fa-solid fa-plus"></i> Add Selected (${manageOutsideSelected.size})`;
  }
  if (countSpan) {
    countSpan.innerText = `${manageOutsideSelected.size} selected`;
  }
}

async function addSingleSkuFromModal(sku) {
  if (!currentManageGroupId || !sku) return;
  try {
    const res = await fetch(`/api/sku-groups/${currentManageGroupId}/add-skus`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skus: [sku] })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Added "${sku}" into group!`, "success");
      const idx = manageGroupData.unmapped_skus.findIndex(u => u.sku === sku);
      let item = null;
      if (idx !== -1) {
        item = manageGroupData.unmapped_skus.splice(idx, 1)[0];
      } else {
        item = { sku, orders_count: 0, pieces_count: 0, sellers: "" };
      }
      manageGroupData.group.skus.push(item);
      manageOutsideSelected.delete(sku);

      updateModalGroupTotals();
      renderManageModalLists();
      loadSkuGroups();
      loadDashboard();
    } else {
      showToast(data.detail || "Error adding SKU", "danger");
    }
  } catch (err) {
    showToast("Failed to add SKU: " + err.message, "danger");
  }
}

async function addSelectedSkusFromModal() {
  if (!currentManageGroupId || manageOutsideSelected.size === 0) return;
  const skusToAdd = Array.from(manageOutsideSelected);

  try {
    const res = await fetch(`/api/sku-groups/${currentManageGroupId}/add-skus`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skus: skusToAdd })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Added ${skusToAdd.length} SKU(s) into group!`, "success");
      skusToAdd.forEach(sku => {
        const idx = manageGroupData.unmapped_skus.findIndex(u => u.sku === sku);
        let item = null;
        if (idx !== -1) {
          item = manageGroupData.unmapped_skus.splice(idx, 1)[0];
        } else {
          item = { sku, orders_count: 0, pieces_count: 0, sellers: "" };
        }
        manageGroupData.group.skus.push(item);
      });
      manageOutsideSelected.clear();

      updateModalGroupTotals();
      renderManageModalLists();
      loadSkuGroups();
      loadDashboard();
    } else {
      showToast(data.detail || "Error adding SKUs", "danger");
    }
  } catch (err) {
    showToast("Failed to add SKUs: " + err.message, "danger");
  }
}

async function removeSingleSkuFromModal(sku) {
  if (!currentManageGroupId || !sku) return;
  try {
    const res = await fetch(`/api/sku-groups/${currentManageGroupId}/remove-skus`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skus: [sku] })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Removed "${sku}" from group. It is now outside in unmapped list.`, "info");
      const idx = manageGroupData.group.skus.findIndex(s => s.sku === sku);
      if (idx !== -1) {
        const item = manageGroupData.group.skus.splice(idx, 1)[0];
        manageGroupData.unmapped_skus.unshift(item);
      }
      manageInsideSelected.delete(sku);

      updateModalGroupTotals();
      renderManageModalLists();
      loadSkuGroups();
      loadDashboard();
    } else {
      showToast(data.detail || "Error removing SKU", "danger");
    }
  } catch (err) {
    showToast("Failed to remove SKU: " + err.message, "danger");
  }
}

async function removeSelectedSkusFromModal() {
  if (!currentManageGroupId || manageInsideSelected.size === 0) return;
  const skusToRemove = Array.from(manageInsideSelected);

  try {
    const res = await fetch(`/api/sku-groups/${currentManageGroupId}/remove-skus`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skus: skusToRemove })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Removed ${skusToRemove.length} SKU(s) from group. They are now outside in unmapped list.`, "info");
      skusToRemove.forEach(sku => {
        const idx = manageGroupData.group.skus.findIndex(s => s.sku === sku);
        if (idx !== -1) {
          const item = manageGroupData.group.skus.splice(idx, 1)[0];
          manageGroupData.unmapped_skus.unshift(item);
        }
      });
      manageInsideSelected.clear();

      updateModalGroupTotals();
      renderManageModalLists();
      loadSkuGroups();
      loadDashboard();
    } else {
      showToast(data.detail || "Error removing SKUs", "danger");
    }
  } catch (err) {
    showToast("Failed to remove SKUs: " + err.message, "danger");
  }
}

function updateModalGroupTotals() {
  if (!manageGroupData || !manageGroupData.group) return;
  const skus = manageGroupData.group.skus || [];
  manageGroupData.group.total_orders = skus.reduce((acc, s) => acc + (s.orders_count || 0), 0);
  manageGroupData.group.total_pieces = skus.reduce((acc, s) => acc + (s.pieces_count || 0), 0);
  document.getElementById("manage-group-modal-subtitle").innerText =
    `${skus.length} SKUs combined | ${manageGroupData.group.total_orders} Orders | ${manageGroupData.group.total_pieces} Pieces`;
}

async function quickRemoveSkuFromGroup(e) {
  e.stopPropagation();
  const btn = e.currentTarget;
  const groupId = parseInt(btn.getAttribute("data-group-id"));
  const sku = btn.getAttribute("data-sku");
  if (!groupId || !sku) return;

  const targetGroup = availableGroups.find(g => g.id === groupId);
  const groupName = targetGroup ? targetGroup.name : "this group";

  if (!confirm(`Remove "${sku}" from "${groupName}"?\n\nIt will move outside to the unmapped list. All orders and items are 100% preserved.`)) {
    return;
  }

  try {
    const res = await fetch(`/api/sku-groups/${groupId}/remove-skus`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skus: [sku] })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Removed "${sku}" from "${groupName}". It is now outside in the unmapped list.`, "info");
      await loadSkuGroups();
      await loadDashboard();
    } else {
      showToast(data.detail || "Error removing SKU", "danger");
    }
  } catch (err) {
    showToast("Failed to remove SKU: " + err.message, "danger");
  }
}

async function loadMappingSuggestions() {
  try {
    const res = await fetch("/api/sku-suggestions");
    const suggestions = await res.json();
    currentSuggestions = suggestions;
    const banner = document.getElementById("mapping-suggestions-container");

    if (suggestions && suggestions.length > 0) {
      const first = suggestions[0];
      document.getElementById("suggestion-text").innerText =
        `Detected ${first.skus.length} similar SKUs matching "${first.suggested_name}" across accounts.`;
      banner.style.display = "block";

      document.getElementById("btn-apply-suggestion").onclick = () => {
        selectedUnmappedSkus.clear();
        first.skus.forEach(s => selectedUnmappedSkus.add(s));
        document.getElementById("modal-group-name").value = first.suggested_name;

        const listEl = document.getElementById("modal-selected-skus-list");
        listEl.innerHTML = "";
        first.skus.forEach(s => {
          const li = document.createElement("li");
          li.innerText = s;
          listEl.appendChild(li);
        });

        openModal("modal-create-group");
      };
    } else {
      banner.style.display = "none";
    }
  } catch (err) {
    console.error("Suggestions error:", err);
  }
}

// --- 5. Generate Sorted PDF ---
function switchGenMode(mode) {
  const single = document.getElementById("gen-single-mode");
  const batch = document.getElementById("gen-batch-mode");
  const btnSingle = document.getElementById("btn-mode-single");
  const btnBatch = document.getElementById("btn-mode-batch");

  if (mode === "single") {
    single.style.display = "block";
    batch.style.display = "none";
    btnSingle.className = "btn btn-primary";
    btnBatch.className = "btn btn-secondary";
  } else {
    single.style.display = "none";
    batch.style.display = "block";
    btnSingle.className = "btn btn-secondary";
    btnBatch.className = "btn btn-primary";
    loadBatchGroupsTable();
  }
}

async function loadGeneratorOptions() {
  try {
    const res = await fetch("/api/sku-groups");
    const data = await res.json();
    const select = document.getElementById("gen-group-select");
    select.innerHTML = '<option value="">-- Choose Product Group or Unmapped SKU --</option>';

    if (data.groups) {
      const optGroup = document.createElement("optgroup");
      optGroup.label = "Mapped Product Groups";
      data.groups.forEach(g => {
        const opt = document.createElement("option");
        opt.value = `group:${g.id}`;
        opt.innerText = `${g.name} (${g.total_orders} orders)`;
        optGroup.appendChild(opt);
      });
      select.appendChild(optGroup);
    }

    if (data.unmapped_skus) {
      const optGroup = document.createElement("optgroup");
      optGroup.label = "Individual Unmapped SKUs";
      data.unmapped_skus.forEach(u => {
        const opt = document.createElement("option");
        opt.value = `sku:${u.sku}`;
        opt.innerText = `${u.sku} (${u.orders_count} orders)`;
        optGroup.appendChild(opt);
      });
      select.appendChild(optGroup);
    }
  } catch (err) {
    console.error("Generator options error:", err);
  }
}

async function onGenGroupSelected() {
  const select = document.getElementById("gen-group-select");
  const val = select.value;
  const container = document.getElementById("gen-sizes-container");
  container.innerHTML = "";
  activeGenSizes.clear();

  if (!val) {
    container.innerHTML = '<div style="color:#94a3b8; font-size:13px;">Please select a Product Group in Step 1 first</div>';
    updateGenPreview("-", "-", "-");
    return;
  }

  // Fetch available sizes for this group
  let groupId = null;
  let skuVal = null;
  if (val.startsWith("group:")) groupId = parseInt(val.replace("group:", ""));
  else if (val.startsWith("sku:")) skuVal = val.replace("sku:", "");

  const url = new URL("/api/summary", window.location.origin);
  if (groupId) {
    const selectedGroup = availableGroups.find(g => g.id === groupId);
    if (selectedGroup) url.searchParams.set("group", selectedGroup.name);
  } else if (skuVal) {
    url.searchParams.set("search", skuVal);
  }

  try {
    const res = await fetch(url);
    const data = await res.json();

    allGenSizesList = data.columns || [];
    let groupRow = data.rows[0];

    if (!groupRow) {
      container.innerHTML = '<div style="color:#ef4444;">No orders found for this selection</div>';
      return;
    }

    // Populate Size Pills
    allGenSizesList.forEach(s => {
      const cnt = groupRow.sizes[s] || 0;
      if (cnt > 0) {
        activeGenSizes.add(s);
        const pill = document.createElement("div");
        pill.className = "size-pill selected";
        pill.setAttribute("data-size", s);
        pill.innerHTML = `<span>${s}</span> <span class="badge badge-info">${cnt}</span>`;
        pill.onclick = () => {
          if (activeGenSizes.has(s)) {
            activeGenSizes.delete(s);
            pill.classList.remove("selected");
          } else {
            activeGenSizes.add(s);
            pill.classList.add("selected");
          }
          refreshGenPreview();
        };
        container.appendChild(pill);
      }
    });

    // Auto-detect preset
    const kidsCount = Array.from(activeGenSizes).filter(s => s.toLowerCase().includes("year") || s.toLowerCase().includes("month")).length;
    const presetSelect = document.getElementById("gen-sort-preset");
    if (kidsCount > activeGenSizes.size / 2) {
      presetSelect.value = "children";
    } else {
      presetSelect.value = "adult";
    }

    // Show Group Details Card with seller accounts and SKUs
    const detailsCard = document.getElementById("gen-group-details");
    const detailsTitle = document.getElementById("gen-details-title");
    const detailsSellers = document.getElementById("gen-details-sellers");

    if (groupId && detailsCard) {
      const g = availableGroups.find(x => x.id === groupId);
      if (g) {
        detailsCard.style.display = "block";
        detailsTitle.innerHTML = `<strong>${g.name}</strong> (${g.skus.length} SKUs combined | ${g.total_orders} Total Orders across accounts)`;
        detailsSellers.innerHTML = `<strong>Multi-Account Merging Active:</strong> All order labels from all accounts for ${g.name} will be sorted together by size into a single output PDF!`;
      }
    } else if (detailsCard) {
      detailsCard.style.display = "none";
    }

    refreshGenPreview();
  } catch (err) {
    console.error("Size breakdown fetch error:", err);
  }
}

function toggleAllGenSizes(select) {
  const pills = document.querySelectorAll("#gen-sizes-container .size-pill");
  pills.forEach(p => {
    const s = p.getAttribute("data-size");
    if (select) {
      activeGenSizes.add(s);
      p.classList.add("selected");
    } else {
      activeGenSizes.delete(s);
      p.classList.remove("selected");
    }
  });
  refreshGenPreview();
}

function refreshGenPreview() {
  const select = document.getElementById("gen-group-select");
  const selectedText = select.options[select.selectedIndex]?.text || "-";
  const groupName = selectedText.split("(")[0].trim();
  const sizesArr = Array.from(activeGenSizes);
  updateGenPreview(groupName, sizesArr.length > 0 ? `${sizesArr.length} Sizes Included` : "None Selected", `${sizesArr.length} sizes`);
}

function updateGenPreview(group, skus, pages) {
  document.getElementById("prev-group-name").innerText = group;
  document.getElementById("prev-skus-count").innerText = skus;
  document.getElementById("prev-expected-pages").innerText = pages;
}

async function executePdfGeneration() {
  const select = document.getElementById("gen-group-select");
  const val = select.value;
  if (!val) {
    showToast("Please choose a Product Group to generate", "warning");
    return;
  }

  if (activeGenSizes.size === 0) {
    showToast("Please select at least one size to include", "warning");
    return;
  }

  let groupId = null;
  let skuVal = null;
  if (val.startsWith("group:")) groupId = parseInt(val.replace("group:", ""));
  else if (val.startsWith("sku:")) skuVal = val.replace("sku:", "");

  const sortPreset = document.getElementById("gen-sort-preset").value;
  const secondarySort = document.getElementById("gen-secondary-sort").value;
  const customFilename = document.getElementById("gen-output-filename").value.trim();

  const reqBody = {
    group_id: groupId,
    sku: skuVal,
    included_sizes: Array.from(activeGenSizes),
    sort_preset: sortPreset,
    secondary_sort: secondarySort,
    output_filename: customFilename || null
  };

  const btn = document.getElementById("btn-generate-pdf");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Merging & Verifying...`;

  try {
    const res = await fetch("/api/generate-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody)
    });
    const data = await res.json();

    if (data.verified) {
      showToast(`Generated & 100% Verified! ${data.page_count} pages merged.`, "success");
      // Trigger download
      window.open(data.download_url, "_blank");
      switchTab("history");
    } else {
      showToast(data.detail || "Error generating PDF", "danger");
    }
  } catch (err) {
    showToast("Generation error: " + err.message, "danger");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-file-pdf"></i> Generate Sorted PDF`;
  }
}

// Batch Mode
async function loadBatchGroupsTable() {
  try {
    const res = await fetch("/api/sku-groups");
    const data = await res.json();
    const tbody = document.querySelector("#batch-groups-table tbody");
    tbody.innerHTML = "";

    if (data.groups && data.groups.length > 0) {
      data.groups.forEach(g => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><input type="checkbox" class="batch-group-checkbox" data-id="${g.id}"></td>
          <td><strong>${g.name}</strong></td>
          <td style="text-align:center;">${g.skus.length}</td>
          <td style="text-align:center;"><strong>${g.total_orders}</strong></td>
          <td style="text-align:center;">${g.total_pieces}</td>
        `;
        tbody.appendChild(tr);
      });
    } else {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No product groups available. Create groups first!</td></tr>`;
    }

    const checkAll = document.getElementById("check-all-batch");
    if (checkAll) {
      checkAll.checked = false;
      checkAll.onchange = (e) => {
        document.querySelectorAll(".batch-group-checkbox").forEach(cb => {
          cb.checked = e.target.checked;
        });
      };
    }
  } catch (err) {
    console.error("Batch groups error:", err);
  }
}

async function executeMergeAllIntoSinglePdf() {
  const selectedCbs = document.querySelectorAll(".batch-group-checkbox:checked");
  let groupIds = [];
  if (selectedCbs.length > 0) {
    groupIds = Array.from(selectedCbs).map(cb => parseInt(cb.getAttribute("data-id")));
  }

  const promptMsg = groupIds.length > 0
    ? `Merge all ${groupIds.length} selected product groups into ONE single sorted PDF file without creating a ZIP? (Zero pages will be removed)`
    : `No specific groups checked. Do you want to merge ALL 100% of uploaded orders across ALL products into ONE single sorted PDF? (Not a single page will be removed)`;

  if (!confirm(promptMsg)) return;

  const btn = document.getElementById("btn-merge-all-single");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Merging All Pages (100% Intact)...`;
  }

  showToast("Merging all label pages into a single sorted PDF... Zero pages removed!", "info");

  try {
    const res = await fetch("/api/generate-all-merged-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        group_ids: groupIds.length > 0 ? groupIds : null,
        output_filename: "Meesho_All_Orders_Merged_Sorted.pdf"
      })
    });
    const data = await res.json();

    if (data.verified) {
      showToast(`SUCCESS! Merged all ${data.page_count} pages into ONE PDF without ZIP!`, "success");
      window.open(data.download_url, "_blank");
      switchTab("history");
    } else {
      showToast(data.detail || "Error merging PDF", "danger");
    }
  } catch (err) {
    showToast("Merge error: " + err.message, "danger");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-file-pdf"></i> 📄 Merge All into ONE Single PDF (No ZIP)`;
    }
  }
}

async function executeBatchGeneration() {
  const selectedCbs = document.querySelectorAll(".batch-group-checkbox:checked");
  if (selectedCbs.length === 0) {
    showToast("Please select at least one product group for batch generation", "warning");
    return;
  }

  const groupIds = Array.from(selectedCbs).map(cb => parseInt(cb.getAttribute("data-id")));

  showToast(`Generating ${groupIds.length} PDFs and building ZIP archive...`, "info");
  try {
    const res = await fetch("/api/generate-batch-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        group_ids: groupIds,
        create_zip: true
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Batch completed! Created ${data.total_generated} PDFs.`, "success");
      if (data.zip_url) {
        window.open(data.zip_url, "_blank");
      }
      switchTab("history");
    } else {
      showToast(data.detail || "Batch generation error", "danger");
    }
  } catch (err) {
    showToast("Batch error: " + err.message, "danger");
  }
}

// --- 6. Orders Explorer ---
async function loadOrdersTable(page = 1) {
  currentOrdersPage = page;
  const search = document.getElementById("orders-search").value.trim();
  const status = document.getElementById("orders-status-filter").value;
  const seller = document.getElementById("orders-seller-filter").value;

  const url = new URL("/api/orders", window.location.origin);
  url.searchParams.set("page", page);
  url.searchParams.set("page_size", 50);
  if (search) url.searchParams.set("search", search);
  if (status) url.searchParams.set("status", status);
  if (seller) url.searchParams.set("seller", seller);

  try {
    const res = await fetch(url);
    const data = await res.json();

    document.getElementById("orders-total-count").innerText = data.total;
    document.getElementById("orders-pagination-info").innerText = `Page ${data.page} of ${Math.ceil(data.total / data.page_size) || 1}`;

    document.getElementById("btn-orders-prev").disabled = data.page <= 1;
    document.getElementById("btn-orders-next").disabled = data.page >= Math.ceil(data.total / data.page_size);

    const tbody = document.querySelector("#orders-explorer-table tbody");
    tbody.innerHTML = "";

    if (data.orders.length === 0) {
      tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; color:#94a3b8; padding:30px;">No orders found</td></tr>`;
      return;
    }

    data.orders.forEach(o => {
      const tr = document.createElement("tr");
      if (o.is_excluded === 1) tr.style.opacity = "0.5";

      let statusBadge = `<span class="badge badge-success">Valid</span>`;
      if (o.validation_status === "Needs Review") {
        statusBadge = `<span class="badge badge-warning">Needs Review</span>`;
      } else if (o.validation_status === "Duplicate") {
        statusBadge = `<span class="badge badge-danger">Duplicate</span>`;
      }

      tr.innerHTML = `
        <td><span style="font-family:monospace; font-weight:600;">${o.order_no}</span></td>
        <td><div style="font-weight:500; max-width:240px; overflow:hidden; text-overflow:ellipsis;">${o.sku}</div></td>
        <td><span class="badge ${o.group_name !== 'Unmapped' ? 'badge-info' : 'badge-neutral'}">${o.group_name}</span></td>
        <td><strong>${o.size}</strong></td>
        <td style="text-align:center;">${o.qty}</td>
        <td>${o.color || "NA"}</td>
        <td><div style="max-width:180px; overflow:hidden; text-overflow:ellipsis;">${o.seller_account || "Unknown"}</div></td>
        <td><span style="font-family:monospace;">${o.awb || "-"}</span></td>
        <td>${o.src_filename} (p.${o.page_number})</td>
        <td>${statusBadge}</td>
        <td style="text-align:center;">
          <div style="display:flex; gap:4px; justify-content:center;">
            <button class="btn btn-secondary btn-sm" onclick="openEditOrderModal(${o.id}, '${escapeHtml(o.sku)}', '${escapeHtml(o.size)}', ${o.qty}, '${escapeHtml(o.color || '')}', '${escapeHtml(o.seller_account || '')}', '${o.validation_status}')">
              <i class="fa-solid fa-pen"></i>
            </button>
            <button class="btn ${o.is_excluded === 1 ? 'btn-success' : 'btn-secondary'} btn-sm" onclick="toggleExcludeOrder(${o.id})" title="${o.is_excluded === 1 ? 'Include in generation' : 'Exclude from generation'}">
              <i class="fa-solid ${o.is_excluded === 1 ? 'fa-eye' : 'fa-eye-slash'}"></i>
            </button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Orders table error:", err);
  }
}

function changeOrdersPage(delta) {
  loadOrdersTable(currentOrdersPage + delta);
}

function openEditOrderModal(id, sku, size, qty, color, seller, status) {
  document.getElementById("edit-order-id").value = id;
  document.getElementById("edit-order-sku").value = sku;
  document.getElementById("edit-order-size").value = size;
  document.getElementById("edit-order-qty").value = qty;
  document.getElementById("edit-order-color").value = color;
  document.getElementById("edit-order-seller").value = seller;
  document.getElementById("edit-order-status").value = status;
  openModal("modal-edit-order");
}

async function confirmSaveOrderEdit() {
  const id = document.getElementById("edit-order-id").value;
  const sku = document.getElementById("edit-order-sku").value.trim();
  const size = document.getElementById("edit-order-size").value.trim();
  const qty = parseInt(document.getElementById("edit-order-qty").value) || 1;
  const color = document.getElementById("edit-order-color").value.trim();
  const seller = document.getElementById("edit-order-seller").value.trim();
  const status = document.getElementById("edit-order-status").value;

  try {
    const res = await fetch(`/api/orders/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sku, size, qty, color, seller_account: seller, validation_status: status
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Order updated successfully", "success");
      closeModal("modal-edit-order");
      loadOrdersTable(currentOrdersPage);
      loadDashboard();
    }
  } catch (err) {
    showToast("Failed to update order: " + err.message, "danger");
  }
}

async function toggleExcludeOrder(orderId) {
  try {
    const res = await fetch(`/api/orders/${orderId}/toggle-exclude`, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(data.is_excluded === 1 ? "Order excluded from PDF generation" : "Order re-included", "info");
      loadOrdersTable(currentOrdersPage);
      loadDashboard();
    }
  } catch (err) {
    showToast("Toggle error: " + err.message, "danger");
  }
}

// --- 7. Processing History ---
async function loadHistory() {
  try {
    const res = await fetch("/api/generated-pdfs");
    const list = await res.json();
    const tbody = document.querySelector("#history-table tbody");
    tbody.innerHTML = "";

    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#94a3b8; padding:30px;">No PDFs generated yet</td></tr>`;
      return;
    }

    list.forEach(item => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><i class="fa-solid fa-file-pdf text-indigo" style="margin-right:6px;"></i><strong>${item.filename}</strong></td>
        <td><span class="badge badge-info">${item.group_name}</span></td>
        <td style="text-align:center;">${item.order_count}</td>
        <td style="text-align:center;"><strong>${item.page_count}</strong></td>
        <td style="text-align:center;"><span class="badge badge-success"><i class="fa-solid fa-check"></i> 100% Verified</span></td>
        <td>${item.created_at ? item.created_at.substring(0, 19).replace('T', ' ') : '-'}</td>
        <td style="text-align:center;">
          <div style="display:flex; gap:6px; justify-content:center;">
            <a href="/api/download/${item.filename}" class="btn btn-primary btn-sm" download target="_blank">
              <i class="fa-solid fa-download"></i> Download
            </a>
            <button class="btn btn-danger btn-sm" onclick="deleteHistoryPdf(${item.id})">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("History error:", err);
  }
}

async function deleteHistoryPdf(pdfId) {
  if (!confirm("Delete this generated PDF?")) return;
  try {
    const res = await fetch(`/api/generated-pdfs/${pdfId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      showToast("Record removed", "info");
      loadHistory();
    }
  } catch (err) {
    showToast("Delete error: " + err.message, "danger");
  }
}

// --- 8. Settings & SKU Mappings Persistence Helpers ---
async function fetchSkuMappingsStatus() {
  try {
    const res = await fetch("/api/sku-mappings/status");
    if (!res.ok) return;
    const data = await res.json();
    const bannerStatus = document.getElementById("mapping-storage-status");
    if (bannerStatus) {
      bannerStatus.innerHTML = `(${data.db_groups} Groups, ${data.db_mappings} Mapped SKUs saved safely to disk & auto-restored on restart)`;
    }
    const settingsSummary = document.getElementById("settings-storage-summary");
    if (settingsSummary) {
      settingsSummary.innerHTML = `Auto-saved to disk (${data.db_groups} Product Groups, ${data.db_mappings} Mappings). Safe from program restarts and daily order clears.`;
    }
  } catch (err) {
    console.warn("Could not fetch SKU mappings status:", err);
  }
}

function exportSkuMappings() {
  window.location.href = "/api/sku-mappings/export";
  showToast("Downloading SKU Mappings backup (.json)...", "info");
}

function triggerImportMappings() {
  const input = document.getElementById("input-import-mappings");
  if (input) {
    input.value = "";
    input.click();
  }
}

async function handleImportMappingsFile(event) {
  const file = event.target.files[0];
  if (!file) return;

  if (!confirm(`Restore SKU mappings from "${file.name}"?\n\nThis will restore your product groups and mapped SKUs into the database.`)) {
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  showToast("Restoring SKU mappings from file...", "info");
  try {
    const res = await fetch("/api/sku-mappings/import", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || "Mappings restored successfully!", "success");
      await loadSkuGroups();
      await fetchSkuMappingsStatus();
      await loadDashboard();
    } else {
      showToast(data.detail || "Error importing mappings", "danger");
    }
  } catch (err) {
    showToast("Import error: " + err.message, "danger");
  }
}

async function manualSyncMappings() {
  showToast("Saving and securing SKU mappings to disk...", "info");
  try {
    const res = await fetch("/api/sku-mappings/sync", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(`Saved! ${data.total_groups} Groups & ${data.total_mappings} SKUs are 100% secured on disk.`, "success");
      fetchSkuMappingsStatus();
    } else {
      showToast("Sync failed", "danger");
    }
  } catch (err) {
    showToast("Sync error: " + err.message, "danger");
  }
}

async function clearDailyOrders() {
  if (!confirm("Clear uploaded PDF shipping labels and orders for a new day?\n\n✓ All your Product Groups and SKU mappings will remain 100% saved and untouched.\n\nContinue?")) return;

  try {
    const res = await fetch("/api/clear-orders", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Today's orders cleared! All SKU mappings are 100% safe.", "success");
      switchTab("upload");
      loadDashboard();
    }
  } catch (err) {
    showToast("Clear orders error: " + err.message, "danger");
  }
}

async function fullFactoryReset() {
  if (!confirm("DANGER: This will delete ALL data including uploaded PDFs, parsed orders, AND SKU mappings.\n\nAn automated safety backup of your mappings will be created in data/backups/ first.\n\nAre you sure you want to completely reset?")) return;
  const doubleCheck = prompt("Type RESET in uppercase to confirm complete factory reset:");
  if (doubleCheck !== "RESET") {
    showToast("Factory reset cancelled", "info");
    return;
  }

  try {
    const res = await fetch("/api/reset?reset_mappings=true", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast("Factory reset completed (backup created)", "info");
      switchTab("dashboard");
      loadDashboard();
    }
  } catch (err) {
    showToast("Reset error: " + err.message, "danger");
  }
}

// Deprecated legacy alias kept for backward compatibility
async function resetWorkspace() {
  return clearDailyOrders();
}

// Modals helper
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("active");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("active");
  if (id === "modal-add-category") {
    targetGroupIdForNewCategory = null;
    renderActiveProductGroups();
  }
}

// --- A4 Order Picking & Packing Checklist Logic ---
let checklistCurrentCategory = "";
let checklistCurrentGroup = "";
let checklistRawData = null;

async function openPickingChecklistModal(preselectedCategory = null, preselectedGroup = null) {
  // Determine default category to show
  if (preselectedCategory !== null) {
    checklistCurrentCategory = preselectedCategory;
  } else {
    const matrixCatFilter = document.getElementById("sku-color-category-filter");
    checklistCurrentCategory = matrixCatFilter ? matrixCatFilter.value : "";
  }
  checklistCurrentGroup = preselectedGroup || "";

  // 1. Populate category dropdown in modal
  const catSelect = document.getElementById("checklist-category-select");
  if (catSelect) {
    let catOptions = `<option value="">All Categories</option>`;
    availableCategories.forEach(c => {
      const isSel = (checklistCurrentCategory && checklistCurrentCategory.toLowerCase() === c.name.toLowerCase());
      const label = c.label || `${c.icon || '🏷️'} ${c.name}`;
      catOptions += `<option value="${escapeHtml(c.name)}" ${isSel ? 'selected' : ''}>${escapeHtml(label)}</option>`;
    });
    catSelect.innerHTML = catOptions;
  }

  // 2. Populate groups dropdown
  populateChecklistGroupSelect();

  openModal("modal-picking-checklist");

  // 3. Load & Render Checklist Preview
  await loadAndRenderChecklistPreview();
}

function populateChecklistGroupSelect() {
  const grpSelect = document.getElementById("checklist-group-select");
  if (!grpSelect) return;

  let filteredGroups = availableGroups;
  if (checklistCurrentCategory) {
    const cf = checklistCurrentCategory.toLowerCase();
    filteredGroups = availableGroups.filter(g => (g.category || "General").toLowerCase() === cf);
  }

  let grpOptions = `<option value="">All Groups (${filteredGroups.length})</option>`;
  filteredGroups.forEach(g => {
    const isSel = (checklistCurrentGroup === g.name);
    grpOptions += `<option value="${escapeHtml(g.name)}" ${isSel ? 'selected' : ''}>${escapeHtml(g.name)} (${g.total_pieces || 0} pcs)</option>`;
  });
  grpSelect.innerHTML = grpOptions;
}

async function onChecklistFilterChange() {
  const catSelect = document.getElementById("checklist-category-select");
  const grpSelect = document.getElementById("checklist-group-select");

  checklistCurrentCategory = catSelect ? catSelect.value : "";
  checklistCurrentGroup = grpSelect ? grpSelect.value : "";

  populateChecklistGroupSelect();
  await loadAndRenderChecklistPreview();
}

async function loadAndRenderChecklistPreview() {
  const contentArea = document.getElementById("checklist-content-area");
  if (!contentArea) return;

  contentArea.innerHTML = `<div style="text-align:center; padding:40px; color:#64748b;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><br><span style="margin-top:8px; display:inline-block;">Loading A4 Picking Checklist...</span></div>`;

  try {
    const params = new URLSearchParams();
    if (checklistCurrentCategory) params.append("category", checklistCurrentCategory);
    if (checklistCurrentGroup) params.append("group", checklistCurrentGroup);
    params.append("sort_by", "category");
    params.append("group_by", "group");

    const res = await fetch(`/api/skus-color-breakdown?${params.toString()}`);
    const data = await res.json();
    checklistRawData = data;

    renderChecklistPreviewHtml(data);
  } catch (err) {
    contentArea.innerHTML = `<div style="text-align:center; padding:30px; color:#ef4444;"><i class="fa-solid fa-triangle-exclamation"></i> Error loading checklist: ${escapeHtml(err.message)}</div>`;
  }
}

function renderChecklistPreviewHtml(data) {
  const contentArea = document.getElementById("checklist-content-area");
  if (!contentArea) return;

  let products = data.products || [];
  if (checklistCurrentGroup) {
    products = products.filter(p => p.group_name === checklistCurrentGroup || p.display_name === checklistCurrentGroup);
  }

  if (products.length === 0) {
    contentArea.innerHTML = `
      <div style="text-align:center; padding:50px; color:#94a3b8;">
        <i class="fa-solid fa-clipboard-list" style="font-size:36px; margin-bottom:12px; display:block; opacity:0.4;"></i>
        <h4 style="color:#475569; margin-bottom:6px;">No Orders Found</h4>
        <p style="font-size:13px; margin:0;">There are no active orders for the selected category / group.</p>
      </div>
    `;
    return;
  }

  const categoryName = checklistCurrentCategory || "All Categories";
  const totalPieces = products.reduce((acc, p) => acc + (p.total_pieces || 0), 0);
  const totalOrders = products.reduce((acc, p) => acc + (p.total_orders || 0), 0);
  const totalColors = products.reduce((acc, p) => acc + (p.colors?.length || 0), 0);
  const nowStr = new Date().toLocaleString();

  let html = `
    <!-- A4 Printable Header -->
    <div style="background:#0f172a; color:#ffffff; padding:12px 16px; border-radius:6px 6px 0 0; margin-bottom:0;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
        <div>
          <h2 style="font-size:16px; font-weight:800; letter-spacing:0.5px; margin:0; text-transform:uppercase;">
            ORDER PICKING & PACKING CHECKLIST
          </h2>
          <div style="font-size:12px; color:#94a3b8; margin-top:2px;">
            Category: <strong style="color:#ffffff;">${escapeHtml(categoryName)}</strong> | Date: ${nowStr}
          </div>
        </div>
        <div style="text-align:right;">
          <span style="background:#1e293b; padding:4px 10px; border-radius:4px; font-size:12px; font-weight:700; color:#38bdf8;">
            A4 PRINTABLE SHEET
          </span>
        </div>
      </div>
    </div>

    <!-- Summary Stats Bar -->
    <div style="background:#f1f5f9; border:1px solid #cbd5e1; border-top:none; padding:8px 16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; font-size:12.5px; margin-bottom:16px;">
      <div style="display:flex; gap:16px; font-weight:600; color:#1e293b;">
        <span>Products: <strong style="color:#0284c7;">${products.length}</strong></span>
        <span>Colors: <strong style="color:#0284c7;">${totalColors}</strong></span>
        <span>Total Pieces: <strong style="color:#16a34a;">${totalPieces}</strong></span>
        <span>Orders: <strong>${totalOrders}</strong></span>
      </div>
      <div style="font-size:11.5px; color:#64748b; font-style:italic;">
        Tick each box [ ✓ ] as you pull pieces from racks
      </div>
    </div>
  `;

  // Render Product Groups
  products.forEach((p, pIdx) => {
    html += `
      <div class="checklist-product-card">
        <!-- Product Header Banner -->
        <div style="background:#eef2ff; border-bottom:1px solid #c7d2fe; padding:8px 14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
          <div style="font-weight:800; font-size:14px; color:#1e1b4b; display:flex; align-items:center; gap:8px;">
            <span>${pIdx + 1}. PRODUCT: ${escapeHtml(p.display_name.toUpperCase())}</span>
            <span style="background:#ffffff; border:1px solid #c7d2fe; color:#4338ca; font-size:11px; padding:1px 6px; border-radius:4px; font-weight:600;">
              ${escapeHtml(p.category || 'General')}
            </span>
          </div>
          <div style="font-weight:700; font-size:13px; color:#15803d;">
            Total: ${p.total_pieces || 0} Pcs (${p.total_orders || 0} Orders)
          </div>
        </div>

        <div style="padding:12px 14px; display:flex; flex-direction:column; gap:10px;">
    `;

    (p.colors || []).forEach((c, cIdx) => {
      html += `
        <div class="checklist-color-block">
          <!-- Color Title -->
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; padding-bottom:5px; border-bottom:1px solid #edf2f7;">
            <div style="font-weight:700; font-size:13px; color:#0f172a; display:flex; align-items:center; gap:6px;">
              <span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#4f46e5;"></span>
              <span>COLOR: ${escapeHtml(c.color.toUpperCase())}</span>
            </div>
            <span style="font-weight:600; font-size:12px; color:#475569;">
              ${c.pieces_count || 0} pcs (${c.orders_count || 0} orders)
            </span>
          </div>

          <!-- Size Checklist Grid (5 columns) -->
          <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(130px, 1fr)); gap:6px; margin-bottom:8px;">
      `;

      (c.sizes || []).forEach(s => {
        html += `
          <div class="checklist-size-box" onclick="toggleChecklistTick(this)">
            <div style="display:flex; align-items:center;">
              <span class="checklist-box-tick"><i class="fa-solid fa-check"></i></span>
              <span class="checklist-sz-name" style="font-weight:600;">${escapeHtml(s.size)}</span>
            </div>
            <strong style="color:#0f172a; font-size:13px; margin-left:6px;">${s.orders_count} pcs</strong>
          </div>
        `;
      });

      html += `
          </div>

          <!-- Subtotal / Pack Complete Tick Box -->
          <div style="display:flex; align-items:center; padding:5px 8px; background:#f8fafc; border-radius:4px; font-size:12px; cursor:pointer;" onclick="toggleChecklistTick(this)">
            <span class="checklist-box-tick"><i class="fa-solid fa-check"></i></span>
            <span style="font-weight:600; color:#334155;">
              Check & Pack Complete: ${escapeHtml(c.color.toUpperCase())} (${c.pieces_count || 0} Pieces Total)
            </span>
          </div>
        </div>
      `;
    });

    html += `
        </div>
      </div>
    `;
  });

  // Footer for printable preview
  html += `
    <div style="border-top:1px solid #cbd5e1; padding-top:10px; margin-top:16px; display:flex; justify-content:space-between; align-items:center; font-size:11.5px; color:#64748b;">
      <span>Meesho Inventory Order Sorting System</span>
      <span>A4 Checklist Verification Sheet</span>
    </div>
  `;

  contentArea.innerHTML = html;
}

function toggleChecklistTick(element) {
  element.classList.toggle("checked");
  const tickBox = element.querySelector(".checklist-box-tick");
  if (tickBox) {
    if (element.classList.contains("checked")) {
      tickBox.classList.add("checked");
    } else {
      tickBox.classList.remove("checked");
    }
  }
}

function printChecklistSheet() {
  window.print();
}

function downloadChecklistPdf() {
  const catSelect = document.getElementById("checklist-category-select");
  const grpSelect = document.getElementById("checklist-group-select");

  const category = catSelect ? catSelect.value : "";
  const group = grpSelect ? grpSelect.value : "";

  const params = new URLSearchParams();
  if (category) params.append("category", category);
  if (group) params.append("group", group);
  params.append("sort_by", "category");

  const url = `/api/checklist/pdf?${params.toString()}`;
  window.open(url, "_blank");
}

function setupSearchInputs() {
  const unmappedSearch = document.getElementById("unmapped-search");
  if (unmappedSearch) {
    unmappedSearch.addEventListener("input", () => {
      renderSortedUnmappedList();
    });
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// ========================================================
// PROGRESSIVE WEB APP (PWA) & MOBILE APP INSTALLATION
// ========================================================
let deferredPwaPrompt = null;

// Register Service Worker for caching and offline resilience
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then((reg) => {
        console.log('[PWA] Service Worker registered with scope:', reg.scope);
      })
      .catch((err) => {
        console.warn('[PWA] Service Worker registration failed:', err);
      });
  });
}

// Listen for browser install prompt
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPwaPrompt = e;
  console.log('[PWA] captured beforeinstallprompt event');

  // Show install button in topbar and mobile banner
  const installBtnTop = document.getElementById('btn-install-pwa');
  if (installBtnTop) installBtnTop.style.display = 'inline-flex';

  const modalInstallBtn = document.getElementById('modal-install-pwa-btn');
  if (modalInstallBtn) modalInstallBtn.style.display = 'inline-flex';

  // Check if previously dismissed in this session
  if (!sessionStorage.getItem('pwa_banner_dismissed')) {
    const banner = document.getElementById('pwa-install-banner');
    if (banner) banner.style.display = 'flex';
  }
});

// App installed event handler
window.addEventListener('appinstalled', () => {
  console.log('[PWA] Meesho Label Hub was successfully installed');
  deferredPwaPrompt = null;
  const installBtnTop = document.getElementById('btn-install-pwa');
  if (installBtnTop) installBtnTop.style.display = 'none';

  const banner = document.getElementById('pwa-install-banner');
  if (banner) banner.style.display = 'none';

  const modalInstallBtn = document.getElementById('modal-install-pwa-btn');
  if (modalInstallBtn) modalInstallBtn.style.display = 'none';

  showToast('Meesho Hub તમારા ફોનમાં એપ તરીકે ઇન્સ્ટોલ થઈ ગયું!', 'success');
});

// Trigger installation
async function triggerPwaInstall() {
  if (deferredPwaPrompt) {
    try {
      deferredPwaPrompt.prompt();
      const choiceResult = await deferredPwaPrompt.userChoice;
      console.log(`[PWA] User response to install prompt: ${choiceResult.outcome}`);
      if (choiceResult.outcome === 'accepted') {
        showToast('ઇન્સ્ટોલેશન શરૂ થયું છે...', 'info');
      }
      deferredPwaPrompt = null;
    } catch (err) {
      console.warn('[PWA] Error showing prompt:', err);
    }
  } else {
    // If deferredPrompt is not yet ready or iOS Safari
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    if (isIOS) {
      alert("📲 iPhone / iPad માં ઇન્સ્ટોલ કરવાની રીત:\n\n1. નીચે Safari ના Share બટન [ ⎋ ] પર ટેપ કરો.\n2. નીચે સ્ક્રોલ કરીને 'Add to Home Screen' [ ➕ ] પસંદ કરો.\n3. ઉપર 'Add' પર ક્લિક કરો!\n\nઆમ કરવાથી ફોનમાં સીધી એપ બની જશે.");
    } else {
      alert("📲 Android ફોનમાં ઇન્સ્ટોલ કરવાની રીત:\n\n1. તમારા Chrome બ્રાઉઝરમાં ઉપર જમણી બાજુ 3 ટપકાં ( ⋮ ) પર ટેપ કરો.\n2. 'Install app' અથવા 'Add to Home screen' પસંદ કરો.\n3. 'Install' પર ક્લિક કરો!\n\nઆમ કરવાથી ફોનની હોમ સ્ક્રીન પર Meesho Hub એપ આઇકોન આવી જશે.");
    }
  }
}

function dismissPwaBanner() {
  const banner = document.getElementById('pwa-install-banner');
  if (banner) banner.style.display = 'none';
  sessionStorage.setItem('pwa_banner_dismissed', '1');
}
