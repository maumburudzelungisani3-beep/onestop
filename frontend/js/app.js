/**
 * DataBridge - Frontend Controller
 * Handles live multi-source searching, data inspection drawer, network source configuration, and exports.
 */

// Dynamic API Base URL resolver (supports Vercel rewrites, custom Render URL, and local dev)
function getApiUrl(path) {
  const customBase = localStorage.getItem('databridge_api_base') || window.DATABRIDGE_API_BASE || '';
  if (customBase) {
    return `${customBase.replace(/\/+$/, '')}${path}`;
  }
  return path;
}

// Centralized API fetch wrapper with token injection & 401 interception
async function apiFetch(path, options = {}) {
  const url = path.startsWith('http') ? path : getApiUrl(path);
  const token = localStorage.getItem('databridge_token');
  const headers = {
    ...(options.headers || {})
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 && !url.includes('/api/auth/')) {
    console.warn('[AUTH] Received 401. Showing access gate.');
    showAuthOverlay();
  }
  return res;
}


// Application State
const state = {
  query: '',
  sourceTypeFilter: 'all', // 'all', 'access', 'excel'
  activeSourceId: null,
  sources: [],
  results: [],
  selectedRecord: null,
  debounceTimer: null,
  isLoading: false,
};

// DOM Elements Cache
const elements = {
  // Search
  searchInput: document.getElementById('globalSearchInput'),
  clearSearchBtn: document.getElementById('clearSearchBtn'),
  searchSpinner: document.getElementById('searchSpinner'),
  sourceFilterPills: document.getElementById('sourceFilterPills'),
  quickChips: document.querySelectorAll('.chip'),
  
  // Results
  resultsCountText: document.getElementById('resultsCountText'),
  resultsDurationText: document.getElementById('resultsDurationText'),
  sourceBadgesBar: document.getElementById('sourceBadgesBar'),
  resultsTableBody: document.getElementById('resultsTableBody'),
  emptyState: document.getElementById('emptyState'),
  tableContainer: document.getElementById('tableContainer'),

  // Export
  btnExportCsv: document.getElementById('btnExportCsv'),
  btnExportExcel: document.getElementById('btnExportExcel'),

  // Detail Drawer
  detailDrawer: document.getElementById('detailDrawer'),
  drawerBackdrop: document.getElementById('drawerBackdrop'),
  closeDrawerBtn: document.getElementById('closeDrawerBtn'),
  drawerSourceBadge: document.getElementById('drawerSourceBadge'),
  drawerItemTitle: document.getElementById('drawerItemTitle'),
  drawerContainerPath: document.getElementById('drawerContainerPath'),
  drawerSourceName: document.getElementById('drawerSourceName'),
  drawerContainerName: document.getElementById('drawerContainerName'),
  drawerFilePath: document.getElementById('drawerFilePath'),
  drawerFieldsList: document.getElementById('drawerFieldsList'),

  // Sources Modal
  btnManageSources: document.getElementById('btnManageSources'),
  headerSourceCountBadge: document.getElementById('headerSourceCountBadge'),
  sourcesModal: document.getElementById('sourcesModal'),
  closeSourcesModalBtn: document.getElementById('closeSourcesModalBtn'),
  addSourceForm: document.getElementById('addSourceForm'),
  srcName: document.getElementById('srcName'),
  srcType: document.getElementById('srcType'),
  srcPath: document.getElementById('srcPath'),
  srcPassword: document.getElementById('srcPassword'),
  srcDesc: document.getElementById('srcDesc'),
  btnTestConnection: document.getElementById('btnTestConnection'),
  testResultBox: document.getElementById('testResultBox'),
  testBanner: document.getElementById('testBanner'),
  sourcesList: document.getElementById('sourcesList'),
  btnSeedDemo: document.getElementById('btnSeedDemo'),

  // Theme
  themeToggleBtn: document.getElementById('themeToggleBtn')
};

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  setupEventListeners();
  initAuthSystem();
  const isAuthenticated = await checkAuthStatus();
  if (isAuthenticated) {
    await loadSources();
    await initConsolidatedDb();
    await executeSearch();
  }
});

// =============================================================================
// Theme Management
// =============================================================================

function initTheme() {
  const saved = localStorage.getItem('databridge-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('databridge-theme', next);
}

// =============================================================================
// Event Listeners
// =============================================================================

function setupEventListeners() {
  // Dynamic download URL
  const btnDownloadDb = document.getElementById('btnDownloadDb');
  if (btnDownloadDb) {
    btnDownloadDb.href = getApiUrl('/api/database/download');
  }

  // Theme Toggle
  elements.themeToggleBtn.addEventListener('click', toggleTheme);

  // Search Input with Debounce
  elements.searchInput.addEventListener('input', (e) => {
    state.query = e.target.value;
    elements.clearSearchBtn.style.display = state.query ? 'flex' : 'none';
    
    clearTimeout(state.debounceTimer);
    state.debounceTimer = setTimeout(() => {
      executeSearch();
    }, 280);
  });

  // Clear Search
  elements.clearSearchBtn.addEventListener('click', () => {
    elements.searchInput.value = '';
    state.query = '';
    elements.clearSearchBtn.style.display = 'none';
    elements.searchInput.focus();
    executeSearch();
  });

  // Filter Pills (All / Access / Excel)
  elements.sourceFilterPills.addEventListener('click', (e) => {
    const pill = e.target.closest('.pill');
    if (!pill) return;

    elements.sourceFilterPills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');

    state.sourceTypeFilter = pill.dataset.type;
    executeSearch();
  });

  // Sample Query Quick Chips
  elements.quickChips.forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.dataset.query;
      elements.searchInput.value = q;
      state.query = q;
      elements.clearSearchBtn.style.display = 'flex';
      executeSearch();
    });
  });

  // Exports
  elements.btnExportCsv.addEventListener('click', () => exportData('csv'));
  elements.btnExportExcel.addEventListener('click', () => exportData('excel'));

  // Drawer Controls
  elements.closeDrawerBtn.addEventListener('click', closeDrawer);
  elements.drawerBackdrop.addEventListener('click', closeDrawer);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDrawer();
      closeSourcesModal();
    }
  });

  // Sources Modal Controls
  elements.btnManageSources.addEventListener('click', openSourcesModal);
  elements.closeSourcesModalBtn.addEventListener('click', closeSourcesModal);
  elements.sourcesModal.addEventListener('click', (e) => {
    if (e.target === elements.sourcesModal) closeSourcesModal();
  });

  // Test Connection Button
  elements.btnTestConnection.addEventListener('click', testSourceConnection);

  // Add Source Form Submit
  elements.addSourceForm.addEventListener('submit', handleAddSource);

  // Seed Demo Data Button
  elements.btnSeedDemo.addEventListener('click', handleSeedDemo);

  // Tab switching in modal
  const tabAddFile = document.getElementById('tabAddFile');
  const tabScanFolder = document.getElementById('tabScanFolder');
  const panelAddFile = document.getElementById('panelAddFile');
  const panelScanFolder = document.getElementById('panelScanFolder');

  tabAddFile.addEventListener('click', () => {
    tabAddFile.classList.add('active');
    tabScanFolder.classList.remove('active');
    panelAddFile.style.display = 'block';
    panelScanFolder.style.display = 'none';
  });

  tabScanFolder.addEventListener('click', () => {
    tabScanFolder.classList.add('active');
    tabAddFile.classList.remove('active');
    panelScanFolder.style.display = 'block';
    panelAddFile.style.display = 'none';
  });

  // Folder Scan execution
  document.getElementById('btnRunFolderScan').addEventListener('click', handleRunFolderScan);
}

// =============================================================================
// API & Data Fetching
// =============================================================================

async function loadSources() {
  try {
    const res = await apiFetch('/api/sources');
    if (res.ok) {
      state.sources = await res.json();
      updateSourcesUI();
    }
  } catch (err) {
    console.error('Failed to load sources:', err);
  }
}

function updateSourcesUI() {
  const activeCount = state.sources.filter(s => s.enabled).length;
  elements.headerSourceCountBadge.textContent = `${activeCount} / ${state.sources.length}`;
  renderSourcesModalList();
}

async function executeSearch() {
  state.isLoading = true;
  elements.searchSpinner.style.display = 'block';

  try {
    const params = new URLSearchParams({
      q: state.query,
      source_type: state.sourceTypeFilter,
      limit: '150'
    });

    if (state.activeSourceId) {
      params.append('source_id', state.activeSourceId);
    }

    const res = await apiFetch(`/api/search?${params.toString()}`);
    if (res.ok) {
      const data = await res.json();
      state.results = data.results || [];
      renderSearchResults(data);
    }
  } catch (err) {
    console.error('Search request error:', err);
  } finally {
    state.isLoading = false;
    elements.searchSpinner.style.display = 'none';
  }
}

// =============================================================================
// Rendering Results
// =============================================================================

function renderSearchResults(data) {
  const total = data.total_matches || 0;
  const duration = data.duration_ms || 0;

  // Metadata Headline
  if (state.query.trim()) {
    elements.resultsCountText.textContent = `Found ${total} ${total === 1 ? 'match' : 'matches'} for "${state.query}"`;
  } else {
    elements.resultsCountText.textContent = `Browsing all ${total} items`;
  }
  elements.resultsDurationText.textContent = `${duration} ms`;

  // Source Stats Badges
  renderSourceBadges(data.source_reports || []);

  // Results Table
  const tbody = elements.resultsTableBody;
  tbody.innerHTML = '';

  if (total === 0) {
    elements.tableContainer.style.display = 'none';
    elements.emptyState.style.display = 'block';
    return;
  }

  elements.tableContainer.style.display = 'block';
  elements.emptyState.style.display = 'none';

  data.results.forEach((record, idx) => {
    const tr = document.createElement('tr');
    tr.addEventListener('click', () => openDrawer(record));

    const land = extractEssentialLandData(record.data, record.container);
    const sType = (record.source_type || '').toLowerCase();
    const isAccess = sType.includes('access');
    const isSqlite = sType.includes('sqlite');

    let badgeClass = 'badge-excel';
    let dotClass = 'dot-excel';
    let badgeText = 'Excel';

    if (isAccess) {
      badgeClass = 'badge-access';
      dotClass = 'dot-access';
      badgeText = 'Access';
    } else if (isSqlite) {
      badgeClass = 'badge-sqlite';
      dotClass = 'dot-sqlite';
      badgeText = 'Local DB';
    }

    const highlight = (text) => highlightQuery(String(text || ''), state.query);

    // Fallback if no specific person name is found
    const displayName = land.fullName || (record.data ? Object.values(record.data)[0] : '—');

    tr.innerHTML = `
      <td>
        <div style="display: flex; flex-direction: column; gap: 0.25rem;">
          <span class="source-badge ${badgeClass}">
            <span class="pill-dot ${dotClass}"></span>
            ${badgeText}
          </span>
          <span class="container-tag" title="${escapeHtml(record.container || '')}">${escapeHtml(record.container || 'Table')}</span>
        </div>
      </td>
      <td>
        <div class="cell-name-box">
          <div class="person-full-name">${highlight(displayName)}</div>
          ${land.surname ? `<span class="person-surname-tag"><span class="tag-label">SURNAME:</span> ${highlight(land.surname)}</span>` : ''}
        </div>
      </td>
      <td>
        ${land.idNumber ? `<span class="id-badge font-mono">${highlight(land.idNumber)}</span>` : `<span class="empty-field">—</span>`}
      </td>
      <td>
        ${land.farmName ? `
          <div class="farm-name-cell" title="${escapeHtml(land.farmName)}">
            <svg class="farm-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
              <polyline points="9 22 9 12 15 12 15 22"></polyline>
            </svg>
            <span class="farm-name-text">${highlight(land.farmName)}</span>
          </div>
          ${land.whereTakenFrom ? `
            <div class="farm-origin-badge" title="Where farm was taken from: ${escapeHtml(land.whereTakenFrom)}">
              <span class="origin-tag-prefix">↳ Taken from:</span>
              <span class="origin-tag-content">${highlight(land.whereTakenFrom)}</span>
            </div>
          ` : ''}
        ` : (land.whereTakenFrom ? `
          <div class="farm-origin-badge" title="Where farm was taken from: ${escapeHtml(land.whereTakenFrom)}">
            <span class="origin-tag-prefix">↳ Taken from:</span>
            <span class="origin-tag-content">${highlight(land.whereTakenFrom)}</span>
          </div>
        ` : `<span class="empty-field">—</span>`)}
      </td>
      <td>
        ${land.subdivision ? `<span class="subdiv-badge font-mono">${highlight(land.subdivision)}</span>` : `<span class="empty-field">—</span>`}
      </td>
      <td>
        <div class="location-cell">
          <span class="location-text">${highlight(land.location || '—')}</span>
          ${land.areaHa ? `<span class="area-chip font-mono">${highlight(land.areaHa)}</span>` : ''}
        </div>
      </td>
      <td style="text-align: right;">
        <button class="btn btn-sm btn-outline" title="Inspect Record Details">Inspect</button>
      </td>
    `;

    tbody.appendChild(tr);
  });
}

function renderSourceBadges(reports) {
  const container = elements.sourceBadgesBar;
  container.innerHTML = '';

  reports.forEach(report => {
    const card = document.createElement('div');
    card.className = 'source-stat-card';
    const isAccess = report.source_type.toLowerCase() === 'access';

    card.innerHTML = `
      <span class="pill-dot ${isAccess ? 'dot-access' : 'dot-excel'}"></span>
      <span style="font-weight: 600;">${escapeHtml(report.source_name)}:</span>
      <span class="source-stat-count">${report.count}</span>
      <span style="color: var(--text-muted); font-size: 0.7rem;">(${report.duration_ms}ms)</span>
    `;
    container.appendChild(card);
  });
}

function extractEssentialLandData(data, container = '') {
  const d = data || {};

  // Case-insensitive lookup helper with whitespace/NaN filtering
  const getVal = (...keys) => {
    for (const k of keys) {
      for (const [prop, val] of Object.entries(d)) {
        if (prop.toLowerCase() === k.toLowerCase()) {
          if (val !== null && val !== undefined) {
            const strVal = String(val).trim();
            if (strVal !== '' && strVal.toLowerCase() !== 'none' && strVal !== 'nan' && strVal !== '-') {
              return strVal;
            }
          }
        }
      }
    }
    return '';
  };

  // 1. Names & Surnames
  const title = getVal('title', 'title_1', 'spouse_s_title');
  const firstName = getVal('first_name', 'first_nme', 'initials', 'company_dir_name', 'applicant_first_name');
  const surname = getVal('surname', 'company_dir_surname', 'applicant_surname');
  const rawName = getVal('name', 'applicant_name', 'owner_name', 'itemname', 'productname', 'machinename');
  const compName = getVal('company_name');

  let fullName = '';
  if (firstName && surname) {
    fullName = `${title ? title + ' ' : ''}${firstName} ${surname}`;
  } else if (rawName) {
    fullName = `${title ? title + ' ' : ''}${rawName}`;
  } else if (surname) {
    fullName = `${title ? title + ' ' : ''}${surname}`;
  } else if (firstName) {
    fullName = `${title ? title + ' ' : ''}${firstName}`;
  } else if (compName) {
    fullName = compName;
  }

  // 2. ID Number / National ID
  const idNumber = getVal('national_id', 'id_no', 'id_number', 'id__number', 'beneficiary_id', 'company_reg_number', 'partnumber', 'sku');

  // 3. Farm Name
  const farmName = getVal('farm_name', 'farm_withdrawn', 'property_name', 'farm');

  // 4. Subdivision Number / Plot #
  const subdivision = getVal('subdivision_number', 's_d_no', 'sd_no', 'subdiv_no', 'subdivision_no', 'subdivision', 'subdivision_id', 'planned_subdivision', 'plot_no', 'permit_number');

  // 5. District & Province
  const district = getVal('district', 'disrict', 'current_district', 'previous_district');
  const province = getVal('province', 'unnamed_1', 'province_name');
  let location = '';
  if (district && province) {
    if (/^\d+(\.0)?$/.test(province)) {
      location = district;
    } else {
      location = `${district}, ${province}`;
    }
  } else if (district) {
    location = district;
  } else if (province && !/^\d+(\.0)?$/.test(province)) {
    location = province;
  }

  // 6. Area / Land Size
  const areaRaw = getVal('extent_ha', 'size_in_hectare', 'area_ha', 'subdiv_size', 'plot_size', 'size', 'hectares');
  let areaHa = '';
  if (areaRaw) {
    const num = parseFloat(areaRaw);
    if (!isNaN(num) && num > 0) {
      areaHa = `${num.toLocaleString(undefined, { maximumFractionDigits: 2 })} Ha`;
    } else {
      areaHa = areaRaw;
    }
  }

  // 7. Status / Date Info
  const status = getVal('allocation_status', 'planning_status', 'gazette_status', 'status', 'land_use', 'plot_type', 'remarks');
  const dateInfo = getVal('allocation_date', 'date_offer_typed', 'date_printed', 'withdrawal_date');

  // 8. Where Farm Was Taken From (Lineage & Parent Farm Provenance)
  const explicitWhereTakenFrom = getVal('where_farm_taken_from', 'where_taken_from');
  const parentFarm = getVal('parent_farm', 'parent_farm_name', 'farm_name_2', 'from_farm_register', 'farm_withdrawn');
  const parentDiagram = getVal('parent_farm_diagm_no', 'diagram_no', 'sd_diagm_no', 'new_diagm_no', 'deed_no');
  const previousDistrict = getVal('previous_district');
  const formerOwner = getVal('owner_name', 'company_name');
  const srcDb = getVal('source_database');
  const srcTbl = getVal('source_table');

  let whereTakenFrom = explicitWhereTakenFrom;
  if (!whereTakenFrom) {
    const originParts = [];
    if (parentDiagram) originParts.push(`Parent Diagram: ${parentDiagram}`);
    if (parentFarm && parentFarm !== farmName) originParts.push(`Parent Farm: ${parentFarm}`);
    if (previousDistrict && previousDistrict !== district) originParts.push(`Previously in ${previousDistrict} (now ${district})`);
    else if (previousDistrict) originParts.push(`Original District: ${previousDistrict}`);
    if (formerOwner) originParts.push(`Former Owner: ${formerOwner}`);
    whereTakenFrom = originParts.join(' | ');
  }

  const sourceProvenance = [srcDb, srcTbl].filter(Boolean).join(' → ') || '';

  return {
    fullName,
    firstName,
    surname,
    idNumber,
    farmName,
    subdivision,
    district,
    province,
    location,
    areaHa,
    status,
    dateInfo,
    whereTakenFrom,
    parentFarm: parentFarm || (farmName ? `Estate of ${farmName}` : ''),
    parentDiagram,
    previousDistrict,
    formerOwner,
    sourceProvenance
  };
}

function extractDisplayAttributes(data) {
  const entries = Object.entries(data || {}).filter(([k, v]) => v !== null && v !== undefined && String(v).trim() !== '' && String(v).toLowerCase() !== 'none');
  if (entries.length === 0) {
    return { primaryKey: { key: 'Item', value: 'Record' }, secondaryKey: null, restAttrs: [] };
  }

  // Identifier candidates for warehouse, procurement, and Ministry of Lands
  const primaryCandidates = [
    'surname', 'farm_name', 'applicant_name', 'name', 'national_id', 'id_number', 
    'itemname', 'itemdescription', 'machinename', 'itemtitle', 'productname', 'description', 'partnumber', 'itemcode', 'assettag'
  ];
  const secondaryCandidates = [
    'first_name', 'initials', 'district', 'province', 'plot_no', 'permit_number', 'file_no',
    'itemid', 'partnumber', 'itemcode', 'sku', 'assettag', 'po_number', 'barcode'
  ];

  let primary = null;
  let secondary = null;

  for (const candidate of primaryCandidates) {
    const found = entries.find(([k]) => k.toLowerCase() === candidate);
    if (found && found[1]) {
      primary = { key: found[0], value: found[1] };
      break;
    }
  }

  for (const candidate of secondaryCandidates) {
    const found = entries.find(([k]) => k.toLowerCase() === candidate);
    if (found && found[1] && (!primary || found[0] !== primary.key)) {
      secondary = { key: found[0], value: found[1] };
      break;
    }
  }

  // Combine first_name + surname if both exist
  const firstNameEntry = entries.find(([k]) => k.toLowerCase() === 'first_name');
  const surnameEntry = entries.find(([k]) => k.toLowerCase() === 'surname');
  if (firstNameEntry && surnameEntry && firstNameEntry[1] && surnameEntry[1]) {
    primary = { key: 'Name', value: `${firstNameEntry[1]} ${surnameEntry[1]}` };
    const idEntry = entries.find(([k]) => k.toLowerCase() === 'national_id' || k.toLowerCase() === 'id_number');
    if (idEntry) {
      secondary = { key: idEntry[0], value: idEntry[1] };
    }
  }

  if (!primary && entries.length > 0) {
    primary = { key: entries[0][0], value: entries[0][1] };
  }

  const restAttrs = entries
    .filter(([k]) => k !== primary?.key && k !== secondary?.key && k.toLowerCase() !== 'first_name' && k.toLowerCase() !== 'surname')
    .map(([k, v]) => ({ key: k, value: v }));

  return { primaryKey: primary, secondaryKey: secondary, restAttrs };
}

function highlightQuery(text, query) {
  if (!query || !query.trim()) return escapeHtml(text);
  const escapedText = escapeHtml(text);
  const regex = new RegExp(`(${escapeRegex(query.trim())})`, 'gi');
  return escapedText.replace(regex, '<span class="highlight">$1</span>');
}

// =============================================================================
// Record Detail Drawer
// =============================================================================

function openDrawer(record) {
  state.selectedRecord = record;
  const sType = (record.source_type || '').toLowerCase();
  const isAccess = sType.includes('access');
  const isSqlite = sType.includes('sqlite');
  let drawerBadgeClass = isAccess ? 'badge-access' : (isSqlite ? 'badge-sqlite' : 'badge-excel');
  elements.drawerSourceBadge.className = `source-badge ${drawerBadgeClass}`;
  elements.drawerSourceBadge.textContent = isSqlite ? 'Consolidated Local DB' : (record.source_type || 'Database');

  const land = extractEssentialLandData(record.data, record.container);

  elements.drawerItemTitle.textContent = land.fullName || land.farmName || 'Record Details';
  elements.drawerContainerPath.textContent = `${record.source_name} → ${record.container}`;

  // Populate Essential Profile Card
  const dpFullName = document.getElementById('dpFullName');
  const dpSurname = document.getElementById('dpSurname');
  const dpIdNumber = document.getElementById('dpIdNumber');
  const dpFarmName = document.getElementById('dpFarmName');
  const dpSubdivision = document.getElementById('dpSubdivision');
  const dpLocation = document.getElementById('dpLocation');
  const dpArea = document.getElementById('dpArea');
  const dpStatus = document.getElementById('dpStatus');

  if (dpFullName) dpFullName.textContent = land.fullName || '—';
  if (dpSurname) dpSurname.textContent = land.surname || '—';
  if (dpIdNumber) dpIdNumber.textContent = land.idNumber || '—';
  if (dpFarmName) dpFarmName.textContent = land.farmName || '—';
  if (dpSubdivision) dpSubdivision.textContent = land.subdivision || '—';
  if (dpLocation) dpLocation.textContent = land.location || '—';
  if (dpArea) dpArea.textContent = land.areaHa || '—';
  if (dpStatus) dpStatus.textContent = [land.status, land.dateInfo].filter(Boolean).join(' • ') || '—';

  // Populate Farm Origin & Acquisition Lineage (Where Taken From) Card
  const dpWhereTakenFrom = document.getElementById('dpWhereTakenFrom');
  const dpParentFarm = document.getElementById('dpParentFarm');
  const dpParentDiagram = document.getElementById('dpParentDiagram');
  const dpPreviousDistrict = document.getElementById('dpPreviousDistrict');
  const dpFormerOwner = document.getElementById('dpFormerOwner');
  const dpSourceProvenance = document.getElementById('dpSourceProvenance');

  if (dpWhereTakenFrom) dpWhereTakenFrom.textContent = land.whereTakenFrom || 'Direct allocation / register entry';
  if (dpParentFarm) dpParentFarm.textContent = land.parentFarm || '—';
  if (dpParentDiagram) dpParentDiagram.textContent = land.parentDiagram || '—';
  if (dpPreviousDistrict) dpPreviousDistrict.textContent = land.previousDistrict || '—';
  if (dpFormerOwner) dpFormerOwner.textContent = land.formerOwner || '—';
  if (dpSourceProvenance) dpSourceProvenance.textContent = land.sourceProvenance || `${record.source_name} → ${record.container}`;

  // Metadata Card
  elements.drawerSourceName.textContent = record.source_name;
  elements.drawerContainerName.textContent = record.container;
  elements.drawerFilePath.textContent = record.file_path;

  // Build field list
  const entries = Object.entries(record.data || {});
  const attrsCountEl = document.getElementById('drawerAttrsCount');
  if (attrsCountEl) attrsCountEl.textContent = `${entries.length} fields`;

  const list = elements.drawerFieldsList;
  list.innerHTML = '';

  for (const [k, v] of entries) {
    const item = document.createElement('div');
    item.className = 'field-item';
    item.innerHTML = `
      <div class="field-key">${escapeHtml(k)}</div>
      <div class="field-value font-mono">${escapeHtml(v !== null && v !== undefined ? String(v) : '—')}</div>
    `;
    list.appendChild(item);
  }

  elements.detailDrawer.classList.add('open');
  elements.drawerBackdrop.classList.add('open');
}

function closeDrawer() {
  elements.detailDrawer.classList.remove('open');
  elements.drawerBackdrop.classList.remove('open');
}

// =============================================================================
// Data Sources Management Modal
// =============================================================================

function openSourcesModal() {
  elements.testResultBox.style.display = 'none';
  elements.sourcesModal.style.display = 'flex';
  renderSourcesModalList();
}

function closeSourcesModal() {
  elements.sourcesModal.style.display = 'none';
}

function renderSourcesModalList() {
  const container = elements.sourcesList;
  container.innerHTML = '';

  if (state.sources.length === 0) {
    container.innerHTML = `<p style="color: var(--text-muted); font-size: 0.85rem;">No sources configured yet.</p>`;
    return;
  }

  state.sources.forEach(src => {
    const card = document.createElement('div');
    card.className = 'source-item-card';

    const isAccess = src.type.toLowerCase() === 'access';
    const isReachable = src.is_reachable;

    card.innerHTML = `
      <div class="source-card-left">
        <span class="source-badge ${isAccess ? 'badge-access' : 'badge-excel'}">
          ${isAccess ? 'Access' : 'Excel'}
        </span>
        <div class="source-card-info">
          <h5>
            ${escapeHtml(src.name)}
            <span class="status-badge ${isReachable ? 'status-connected' : 'status-offline'}">
              ${isReachable ? 'Reachable' : 'Path Unreachable'}
            </span>
          </h5>
          <p>${escapeHtml(src.path)}</p>
        </div>
      </div>
      <div class="source-card-actions">
        <button class="btn btn-sm btn-outline btn-toggle-src" data-id="${src.id}">
          ${src.enabled ? 'Disable' : 'Enable'}
        </button>
        <button class="btn btn-sm btn-icon btn-delete-src" data-id="${src.id}" title="Delete source" style="color: var(--danger);">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>
      </div>
    `;

    card.querySelector('.btn-toggle-src').addEventListener('click', async () => {
      await toggleSourceEnabled(src.id, !src.enabled);
    });

    card.querySelector('.btn-delete-src').addEventListener('click', async () => {
      if (confirm(`Remove data source "${src.name}"?`)) {
        await deleteSource(src.id);
      }
    });

    container.appendChild(card);
  });
}

async function testSourceConnection() {
  const path = elements.srcPath.value.trim();
  const type = elements.srcType.value;
  const password = elements.srcPassword && elements.srcPassword.value.trim() ? elements.srcPassword.value.trim() : null;

  if (!path) {
    alert('Please enter a network or local file path to test.');
    return;
  }

  elements.btnTestConnection.disabled = true;
  elements.btnTestConnection.textContent = 'Testing...';

  try {
    const res = await apiFetch('/api/sources/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, path, password })
    });

    const result = await res.json();
    elements.testResultBox.style.display = 'block';

    if (result.success) {
      elements.testBanner.className = 'test-banner success';
      const tablesList = (result.tables || []).slice(0, 5).join(', ');
      elements.testBanner.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <div>
          <strong>Connected Successfully!</strong> Discovered ${result.tables.length} tables/sheets: <em>${escapeHtml(tablesList)}</em>
        </div>
      `;
    } else {
      elements.testBanner.className = 'test-banner error';
      elements.testBanner.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <div><strong>Connection Failed:</strong> ${escapeHtml(result.message)}</div>
      `;
    }
  } catch (err) {
    elements.testResultBox.style.display = 'block';
    elements.testBanner.className = 'test-banner error';
    elements.testBanner.textContent = 'Request error testing connection: ' + err.message;
  } finally {
    elements.btnTestConnection.disabled = false;
    elements.btnTestConnection.textContent = 'Test Connection';
  }
}

async function handleAddSource(e) {
  e.preventDefault();
  const name = elements.srcName.value.trim();
  const type = elements.srcType.value;
  const path = elements.srcPath.value.trim();
  const password = elements.srcPassword && elements.srcPassword.value.trim() ? elements.srcPassword.value.trim() : null;
  const description = elements.srcDesc.value.trim();

  try {
    const res = await apiFetch('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, type, path, password, description, enabled: true })
    });

    if (res.ok) {
      elements.addSourceForm.reset();
      elements.testResultBox.style.display = 'none';
      await loadSources();
      await executeSearch();
    } else {
      const err = await res.json();
      alert('Error adding source: ' + (err.detail || 'Unknown error'));
    }
  } catch (err) {
    alert('Failed to add source: ' + err.message);
  }
}

async function handleRunFolderScan() {
  const folderPath = document.getElementById('scanFolderPath').value.trim();
  const btn = document.getElementById('btnRunFolderScan');
  const resultsBox = document.getElementById('scanResultsContainer');
  const summaryEl = document.getElementById('scanResultsSummary');
  const listEl = document.getElementById('scanDiscoveredList');

  if (!folderPath) {
    alert('Please enter a network folder path (e.g. \\\\server\\share\\data or Z:\\Databases)');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Scanning...';

  try {
    const res = await apiFetch('/api/sources/scan-folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_path: folderPath, recursive: true })
    });

    const result = await res.json();
    resultsBox.style.display = 'block';
    summaryEl.textContent = result.message;
    listEl.innerHTML = '';

    if (result.success && result.files.length > 0) {
      result.files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'source-item-card';
        const isAccess = file.type === 'access';

        item.innerHTML = `
          <div class="source-card-left">
            <span class="source-badge ${isAccess ? 'badge-access' : 'badge-excel'}">
              ${isAccess ? 'Access' : 'Excel'}
            </span>
            <div class="source-card-info">
              <h5>${escapeHtml(file.name)}</h5>
              <p>${escapeHtml(file.path)}</p>
            </div>
          </div>
          <div>
            <button class="btn btn-sm btn-primary btn-add-discovered">Connect</button>
          </div>
        `;

        item.querySelector('.btn-add-discovered').addEventListener('click', async (e) => {
          const addBtn = e.target;
          addBtn.disabled = true;
          addBtn.textContent = 'Adding...';

          try {
            await apiFetch('/api/sources', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                name: file.name,
                type: file.type,
                path: file.path,
                enabled: true
              })
            });
            addBtn.textContent = 'Connected ✓';
            addBtn.classList.remove('btn-primary');
            addBtn.classList.add('btn-secondary');
            await loadSources();
            await executeSearch();
          } catch (err) {
            alert('Failed to connect source: ' + err.message);
            addBtn.disabled = false;
            addBtn.textContent = 'Connect';
          }
        });

        listEl.appendChild(item);
      });
    } else if (result.success) {
      listEl.innerHTML = `<p style="font-size: 0.8rem; color: var(--text-muted);">No .accdb, .mdb, or .xlsx files found in that folder.</p>`;
    } else {
      listEl.innerHTML = `<p style="font-size: 0.8rem; color: var(--danger);">${escapeHtml(result.message)}</p>`;
    }
  } catch (err) {
    resultsBox.style.display = 'block';
    summaryEl.textContent = 'Error scanning folder: ' + err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Scan Directory';
  }
}

async function toggleSourceEnabled(sourceId, enabled) {
  try {
    const res = await apiFetch(`/api/sources/${sourceId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    if (res.ok) {
      await loadSources();
      await executeSearch();
    }
  } catch (err) {
    console.error('Failed to toggle source:', err);
  }
}

async function deleteSource(sourceId) {
  try {
    const res = await apiFetch(`/api/sources/${sourceId}`, {
      method: 'DELETE'
    });
    if (res.ok) {
      await loadSources();
      await executeSearch();
    }
  } catch (err) {
    console.error('Failed to delete source:', err);
  }
}

async function handleSeedDemo() {
  if (!confirm('Re-generate sample Access database & Excel sheets?')) return;
  try {
    const res = await apiFetch('/api/demo/seed', { method: 'POST' });
    if (res.ok) {
      await loadSources();
      await executeSearch();
      alert('Demo data generated and registered successfully!');
    }
  } catch (err) {
    alert('Failed to seed demo data: ' + err.message);
  }
}

// =============================================================================
// Export Handler
// =============================================================================

function exportData(format) {
  const params = new URLSearchParams({
    q: state.query,
    format: format
  });
  if (state.activeSourceId) {
    params.append('source_id', state.activeSourceId);
  }
  window.location.href = `/api/export?${params.toString()}`;
}

// =============================================================================
// Utilities
// =============================================================================

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// =============================================================================
// Consolidated Database & SQL Explorer Controller
// =============================================================================

const cdbState = {
  stats: null,
  currentTable: '',
  page: 1,
  pageSize: 50,
  tableData: null,
  sqlResults: null,
  syncPollingTimer: null
};

async function initConsolidatedDb() {
  await loadConsolidatedDbStats();
  setupConsolidatedEventListeners();
}

async function loadConsolidatedDbStats() {
  try {
    const res = await apiFetch('/api/database/stats');
    if (!res.ok) return;
    const stats = await res.json();
    cdbState.stats = stats;

    const rowBadge = document.getElementById('consolidatedRowCountBadge');
    if (rowBadge && stats.total_rows) {
      rowBadge.textContent = `${(stats.total_rows / 1000).toFixed(0)}k rows`;
    }

    const statRowsEl = document.getElementById('cdbStatTotalRows');
    const statSizeEl = document.getElementById('cdbStatSize');
    const statTablesEl = document.getElementById('cdbStatTables');

    if (statRowsEl) statRowsEl.textContent = Number(stats.total_rows || 0).toLocaleString();
    if (statSizeEl) statSizeEl.textContent = `${stats.size_mb || 0} MB`;
    if (statTablesEl) statTablesEl.textContent = Object.keys(stats.tables || {}).length;

    // Populate table select
    const tableSelect = document.getElementById('cdbTableSelect');
    if (tableSelect && stats.tables) {
      tableSelect.innerHTML = '';
      const tableNames = Object.keys(stats.tables);
      tableNames.forEach((tbl) => {
        const opt = document.createElement('option');
        opt.value = tbl;
        opt.textContent = `${tbl} (${Number(stats.tables[tbl].row_count || 0).toLocaleString()} rows)`;
        tableSelect.appendChild(opt);
      });
      if (tableNames.length > 0 && !cdbState.currentTable) {
        cdbState.currentTable = tableNames[0];
      }
      if (tableSelect && cdbState.currentTable) {
        tableSelect.value = cdbState.currentTable;
      }
    }

    // Populate Schema Cards
    const schemaGrid = document.getElementById('cdbSchemaCards');
    if (schemaGrid && stats.tables) {
      schemaGrid.innerHTML = Object.entries(stats.tables).map(([name, info]) => `
        <div class="schema-card">
          <div class="schema-card-header">
            <span class="schema-card-title">${escapeHtml(name)}</span>
            <span class="schema-card-badge">${Number(info.row_count || 0).toLocaleString()} rows</span>
          </div>
          <div style="font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 0.25rem;">
            ${info.column_count} columns:
          </div>
          <div class="schema-col-list">
            ${(info.columns || []).map(c => `<span class="schema-col-pill">${escapeHtml(c)}</span>`).join('')}
          </div>
        </div>
      `).join('');
    }
  } catch (err) {
    console.error('Error loading consolidated DB stats:', err);
  }
}

function openConsolidatedModal() {
  const modal = document.getElementById('consolidatedModal');
  if (modal) {
    modal.style.display = 'flex';
    loadConsolidatedDbStats().then(() => {
      const tableSelect = document.getElementById('cdbTableSelect');
      const targetTable = (tableSelect && tableSelect.value) || cdbState.currentTable || 'ol2026_beneficiary_details';
      cdbState.currentTable = targetTable;
      if (tableSelect) tableSelect.value = targetTable;
      loadTableData(targetTable, 1);
    });
  }
}

function closeConsolidatedModal() {
  const modal = document.getElementById('consolidatedModal');
  if (modal) modal.style.display = 'none';
}

function setupConsolidatedEventListeners() {
  const btnOpen = document.getElementById('btnOpenConsolidatedModal');
  const btnClose = document.getElementById('closeConsolidatedModalBtn');
  if (btnOpen) btnOpen.addEventListener('click', openConsolidatedModal);
  if (btnClose) btnClose.addEventListener('click', closeConsolidatedModal);

  // Tab switching
  const tabViewer = document.getElementById('tabCdbViewer');
  const tabSql = document.getElementById('tabCdbSql');
  const tabSchema = document.getElementById('tabCdbSchema');

  const panelViewer = document.getElementById('panelCdbViewer');
  const panelSql = document.getElementById('panelCdbSql');
  const panelSchema = document.getElementById('panelCdbSchema');

  function switchTab(activeTab, activePanel) {
    [tabViewer, tabSql, tabSchema].forEach(t => t && t.classList.remove('active'));
    [panelViewer, panelSql, panelSchema].forEach(p => p && (p.style.display = 'none'));
    if (activeTab) activeTab.classList.add('active');
    if (activePanel) activePanel.style.display = 'block';
  }

  if (tabViewer) tabViewer.addEventListener('click', () => switchTab(tabViewer, panelViewer));
  if (tabSql) tabSql.addEventListener('click', () => switchTab(tabSql, panelSql));
  if (tabSchema) tabSchema.addEventListener('click', () => switchTab(tabSchema, panelSchema));

  // Table select
  const tableSelect = document.getElementById('cdbTableSelect');
  if (tableSelect) {
    tableSelect.addEventListener('change', (e) => {
      cdbState.currentTable = e.target.value;
      cdbState.page = 1;
      loadTableData(cdbState.currentTable, 1);
    });
  }

  // Table filter
  const tableFilter = document.getElementById('cdbTableFilter');
  if (tableFilter) {
    tableFilter.addEventListener('input', (e) => {
      filterLocalTableRows(e.target.value);
    });
  }

  // Pagination
  const prevBtn = document.getElementById('cdbPrevBtn');
  const nextBtn = document.getElementById('cdbNextBtn');
  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      if (cdbState.page > 1) {
        cdbState.page--;
        loadTableData(cdbState.currentTable, cdbState.page);
      }
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      cdbState.page++;
      loadTableData(cdbState.currentTable, cdbState.page);
    });
  }

  // SQL Console
  const btnExec = document.getElementById('btnExecuteSql');
  if (btnExec) btnExec.addEventListener('click', executeSqlQuery);

  // Quick SQL sample buttons
  document.querySelectorAll('.quick-sql-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sql = btn.dataset.sql;
      const input = document.getElementById('sqlConsoleInput');
      if (input && sql) {
        input.value = sql;
        executeSqlQuery();
      }
    });
  });

  // Export SQL CSV
  const btnExportCsv = document.getElementById('btnExportSqlCsv');
  if (btnExportCsv) {
    btnExportCsv.addEventListener('click', exportSqlResultsCsv);
  }

  // Sync Trigger
  const btnSync = document.getElementById('btnTriggerSync');
  if (btnSync) btnSync.addEventListener('click', startNetworkSync);
}

async function loadTableData(tableName, page = 1) {
  if (!tableName) return;
  cdbState.currentTable = tableName;
  cdbState.page = page;

  const offset = (page - 1) * cdbState.pageSize;
  const sql = `SELECT * FROM [${tableName}] LIMIT ${cdbState.pageSize} OFFSET ${offset};`;

  const metaEl = document.getElementById('cdbTableMeta');
  const pageInfoEl = document.getElementById('cdbPageInfo');
  const prevBtn = document.getElementById('cdbPrevBtn');
  const nextBtn = document.getElementById('cdbNextBtn');

  if (metaEl) metaEl.textContent = 'Querying local SQLite database...';

  try {
    const res = await apiFetch('/api/database/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Query failed');

    cdbState.tableData = data;

    // Render Grid
    renderGrid('cdbGridHead', 'cdbGridBody', data.columns, data.rows);

    const totalInTbl = cdbState.stats?.tables?.[tableName]?.row_count || 0;
    const fromRow = offset + 1;
    const toRow = offset + data.rows.length;

    if (pageInfoEl) {
      pageInfoEl.textContent = `Showing rows ${fromRow.toLocaleString()} - ${toRow.toLocaleString()} of ${Number(totalInTbl).toLocaleString()}`;
    }
    if (metaEl) {
      metaEl.textContent = `${data.execution_ms} ms | ${data.columns.length} columns`;
    }

    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = toRow >= totalInTbl || data.rows.length < cdbState.pageSize;
  } catch (err) {
    if (metaEl) metaEl.textContent = `Error: ${err.message}`;
  }
}

function renderGrid(headId, bodyId, columns, rows) {
  const thead = document.getElementById(headId);
  const tbody = document.getElementById(bodyId);
  if (!thead || !tbody) return;

  const essentialKeys = [
    'name', 'surname', 'first_name', 'national_id', 'id_number', 'id__number',
    'farm_name', 'subdivision_number', 's_d_no', 'subdivision_id', 'subdivision',
    'where_farm_taken_from', 'parent_farm_diagm_no', 'parent_farm', 'previous_district',
    'district', 'province', 'area_ha', 'size_in_hectare', 'applicant_name', 'source_database', 'source_table'
  ];

  thead.innerHTML = `<tr>${columns.map(c => {
    const cLow = c.toLowerCase();
    const isEssential = essentialKeys.some(k => cLow === k || cLow.includes(k));
    return `<th class="${isEssential ? 'col-essential-header' : ''}">${escapeHtml(c)}${isEssential ? ' ★' : ''}</th>`;
  }).join('')}</tr>`;

  if (!rows || rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}" style="text-align: center; padding: 2rem; color: var(--text-secondary);">No records found in this range.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(r => `
    <tr>
      ${r.map((cell, colIdx) => {
        const colName = (columns[colIdx] || '').toLowerCase();
        const isEssential = essentialKeys.some(k => colName === k || colName.includes(k));
        const val = cell === null || cell === undefined ? '<span style="color: var(--text-muted); font-style: italic;">NULL</span>' : escapeHtml(cell);
        return `<td class="${isEssential ? 'col-essential-cell' : ''}" title="${escapeHtml(cell || '')}">${val}</td>`;
      }).join('')}
    </tr>
  `).join('');
}

function filterLocalTableRows(filterText) {
  const filter = filterText.toLowerCase().trim();
  const rows = document.querySelectorAll('#cdbGridBody tr');
  rows.forEach(tr => {
    const text = tr.innerText.toLowerCase();
    tr.style.display = text.includes(filter) ? '' : 'none';
  });
}

async function executeSqlQuery() {
  const input = document.getElementById('sqlConsoleInput');
  const statusEl = document.getElementById('sqlExecutionStatus');
  const errorBox = document.getElementById('sqlErrorBox');
  const gridScroll = document.getElementById('sqlGridScroll');
  const exportBtn = document.getElementById('btnExportSqlCsv');

  if (!input) return;
  const sql = input.value.trim();
  if (!sql) return;

  if (statusEl) statusEl.textContent = 'Executing query...';
  if (errorBox) errorBox.style.display = 'none';

  try {
    const res = await apiFetch('/api/database/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql, limit: 100 })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'SQL Execution failed');

    cdbState.sqlResults = data;

    if (statusEl) {
      statusEl.textContent = `Done in ${data.execution_ms} ms (${data.row_count} rows returned)`;
    }

    renderGrid('sqlResultHead', 'sqlResultBody', data.columns, data.rows);
    if (gridScroll) gridScroll.style.display = 'block';
    if (exportBtn) exportBtn.style.display = 'inline-block';
  } catch (err) {
    if (statusEl) statusEl.textContent = 'Failed';
    if (errorBox) {
      errorBox.textContent = err.message;
      errorBox.style.display = 'block';
    }
    if (gridScroll) gridScroll.style.display = 'none';
    if (exportBtn) exportBtn.style.display = 'none';
  }
}

function exportSqlResultsCsv() {
  if (!cdbState.sqlResults || !cdbState.sqlResults.rows) return;
  const { columns, rows } = cdbState.sqlResults;

  let csvContent = "data:text/csv;charset=utf-8,";
  csvContent += columns.map(c => `"${String(c).replace(/"/g, '""')}"`).join(",") + "\r\n";

  rows.forEach(row => {
    const line = row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(",");
    csvContent += line + "\r\n";
  });

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `sql_export_${Date.now()}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

async function startNetworkSync() {
  const banner = document.getElementById('syncProgressBanner');
  const textEl = document.getElementById('syncProgressText');
  const countEl = document.getElementById('syncProgressCount');
  const barEl = document.getElementById('syncProgressBar');
  const btnSync = document.getElementById('btnTriggerSync');

  if (!confirm('Start full network database extraction and update local SQLite database?')) return;

  if (banner) banner.style.display = 'block';
  if (btnSync) btnSync.disabled = true;

  try {
    const res = await apiFetch('/api/sync/start', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to start sync');

    // Poll status
    clearInterval(cdbState.syncPollingTimer);
    cdbState.syncPollingTimer = setInterval(async () => {
      try {
        const sRes = await apiFetch('/api/sync/status');
        const sData = await sRes.json();

        if (sData.status === 'running') {
          if (textEl) textEl.textContent = `Extracting: ${sData.current_table || sData.current_source || 'In progress...'}`;
          const pct = sData.total_tables > 0 ? Math.round((sData.tables_completed / sData.total_tables) * 100) : 10;
          if (countEl) countEl.textContent = `${sData.tables_completed} / ${sData.total_tables} tables (${Number(sData.rows_copied || 0).toLocaleString()} rows)`;
          if (barEl) barEl.style.width = `${pct}%`;
        } else if (sData.status === 'completed') {
          clearInterval(cdbState.syncPollingTimer);
          if (textEl) textEl.textContent = `Extraction Complete! Copied ${Number(sData.rows_copied || 0).toLocaleString()} rows.`;
          if (barEl) barEl.style.width = '100%';
          if (btnSync) btnSync.disabled = false;
          setTimeout(() => {
            if (banner) banner.style.display = 'none';
          }, 3500);
          await loadConsolidatedDbStats();
          await loadSources();
        } else if (sData.status === 'error') {
          clearInterval(cdbState.syncPollingTimer);
          if (textEl) textEl.textContent = `Sync Error: ${sData.error_message}`;
          if (btnSync) btnSync.disabled = false;
        }
      } catch (pollErr) {
        console.error('Sync polling error:', pollErr);
      }
    }, 1000);
  } catch (err) {
    alert('Failed to trigger sync: ' + err.message);
    if (banner) banner.style.display = 'none';
    if (btnSync) btnSync.disabled = false;
  }
}

// =============================================================================
// Access Control & Mobile Biometrics (WebAuthn / Passkeys) Controller
// =============================================================================

function bufferToBase64URL(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function base64URLToBuffer(base64URL) {
  let base64 = base64URL.replace(/-/g, '+').replace(/_/g, '/');
  while (base64.length % 4) {
    base64 += '=';
  }
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function showAuthOverlay() {
  const overlay = document.getElementById('authGateOverlay');
  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.style.display = 'flex';
  }
}

function hideAuthOverlay() {
  const overlay = document.getElementById('authGateOverlay');
  if (overlay) {
    overlay.classList.add('hidden');
    setTimeout(() => { overlay.style.display = 'none'; }, 300);
  }
}

function showAuthBiometricView() {
  document.getElementById('authViewBiometric').style.display = 'block';
  document.getElementById('authViewPassword').style.display = 'none';
  document.getElementById('authViewSetup').style.display = 'none';
  clearAuthAlert();
}

function showAuthPasswordView() {
  document.getElementById('authViewBiometric').style.display = 'none';
  document.getElementById('authViewPassword').style.display = 'block';
  document.getElementById('authViewSetup').style.display = 'none';
  clearAuthAlert();
  const input = document.getElementById('loginUsername');
  if (input) input.focus();
}

function showAuthSetupView() {
  document.getElementById('authViewBiometric').style.display = 'none';
  document.getElementById('authViewPassword').style.display = 'none';
  document.getElementById('authViewSetup').style.display = 'block';
  clearAuthAlert();
  const input = document.getElementById('setupPassword');
  if (input) input.focus();
}

function setAuthAlert(message, type = 'error') {
  const banner = document.getElementById('authAlertBanner');
  if (banner) {
    banner.className = `auth-alert-banner ${type}`;
    banner.textContent = message;
    banner.style.display = 'block';
  }
}

function clearAuthAlert() {
  const banner = document.getElementById('authAlertBanner');
  if (banner) {
    banner.textContent = '';
    banner.style.display = 'none';
  }
}

function setLoggedInUser(user) {
  state.currentUser = user;
  const profileSection = document.getElementById('userProfileSection');
  const usernameLabel = document.getElementById('headerUsername');
  if (profileSection) profileSection.style.display = 'flex';
  if (usernameLabel && user) usernameLabel.textContent = user.username || user.display_name || 'Admin';
}

async function checkBiometricHardware() {
  const label = document.getElementById('biometricSupportLabel');
  const dot = document.querySelector('.status-dot-active') || document.querySelector('.status-dot-warning');
  if (window.PublicKeyCredential && PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable) {
    try {
      const available = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
      if (available) {
        if (label) label.textContent = 'Mobile Biometrics (Fingerprint / Face ID): Active & Ready';
        return true;
      } else {
        if (label) label.textContent = 'Passkey hardware detected. Use sensor or PIN below.';
        return true;
      }
    } catch (e) {
      if (label) label.textContent = 'Hardware biometrics ready via WebAuthn';
      return true;
    }
  } else {
    if (label) label.textContent = 'WebAuthn unavailable on this browser or protocol. Use Password/PIN.';
    if (dot) dot.className = 'status-dot-warning';
    return false;
  }
}

async function loginWithBiometrics() {
  clearAuthAlert();
  const btn = document.getElementById('btnBiometricLogin');
  if (btn) btn.classList.add('scanning');

  try {
    const optRes = await fetch(getApiUrl('/api/auth/webauthn/login-options'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });

    if (!optRes.ok) {
      const err = await optRes.json();
      throw new Error(err.detail || 'Unable to retrieve biometric challenge.');
    }

    const { challenge_id, options } = await optRes.json();

    options.challenge = base64URLToBuffer(options.challenge);
    if (options.allowCredentials && options.allowCredentials.length > 0) {
      options.allowCredentials = options.allowCredentials.map(c => ({
        ...c,
        id: base64URLToBuffer(c.id)
      }));
    }

    const assertion = await navigator.credentials.get({ publicKey: options });
    if (!assertion) {
      throw new Error('Biometric authentication cancelled.');
    }

    const assertionJSON = {
      id: assertion.id,
      rawId: bufferToBase64URL(assertion.rawId),
      type: assertion.type,
      response: {
        clientDataJSON: bufferToBase64URL(assertion.response.clientDataJSON),
        authenticatorData: bufferToBase64URL(assertion.response.authenticatorData),
        signature: bufferToBase64URL(assertion.response.signature),
        userHandle: assertion.response.userHandle ? bufferToBase64URL(assertion.response.userHandle) : null
      }
    };

    const verifyRes = await fetch(getApiUrl('/api/auth/webauthn/login-verify'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        challenge_id,
        credential: assertionJSON
      })
    });

    const data = await verifyRes.json();
    if (!verifyRes.ok) {
      throw new Error(data.detail || 'Biometric verification failed.');
    }

    localStorage.setItem('databridge_token', data.access_token);
    setLoggedInUser(data.user);
    hideAuthOverlay();
    setAuthAlert('Authenticated successfully!', 'success');

    await loadSources();
    await initConsolidatedDb();
    await executeSearch();

  } catch (err) {
    console.error('Biometric login error:', err);
    let msg = err.message || 'Biometric authentication failed.';
    if (err.name === 'NotAllowedError') {
      msg = 'Biometric scan was canceled or timed out. Tap again to retry.';
    } else if (err.name === 'SecurityError') {
      msg = 'WebAuthn requires HTTPS or localhost.';
    }
    setAuthAlert(msg, 'error');
  } finally {
    if (btn) btn.classList.remove('scanning');
  }
}

async function enrollCurrentDevice() {
  try {
    const btn = document.getElementById('btnEnrollCurrentDevice');
    if (btn) btn.disabled = true;

    let deviceName = 'Mobile Phone';
    const ua = navigator.userAgent;
    if (/Android/i.test(ua)) deviceName = 'Android Mobile (Fingerprint)';
    else if (/iPhone|iPad/i.test(ua)) deviceName = 'Apple Mobile (Face ID / Touch ID)';
    else if (/Windows/i.test(ua)) deviceName = 'Windows PC (Hello Biometrics)';
    else if (/Mac/i.test(ua)) deviceName = 'Mac (Touch ID)';

    const optRes = await apiFetch('/api/auth/webauthn/register-options');
    if (!optRes.ok) {
      const err = await optRes.json();
      throw new Error(err.detail || 'Failed to initialize biometric registration');
    }

    const { challenge_id, options } = await optRes.json();
    options.challenge = base64URLToBuffer(options.challenge);
    options.user.id = base64URLToBuffer(options.user.id);
    if (options.excludeCredentials) {
      options.excludeCredentials = options.excludeCredentials.map(c => ({
        ...c,
        id: base64URLToBuffer(c.id)
      }));
    }

    const credential = await navigator.credentials.create({ publicKey: options });
    if (!credential) {
      throw new Error('Device enrollment cancelled.');
    }

    const credJSON = {
      id: credential.id,
      rawId: bufferToBase64URL(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: bufferToBase64URL(credential.response.clientDataJSON),
        attestationObject: bufferToBase64URL(credential.response.attestationObject),
        transports: credential.response.getTransports ? credential.response.getTransports() : []
      }
    };

    const verifyRes = await apiFetch('/api/auth/webauthn/register-verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        challenge_id,
        credential: credJSON,
        device_name: deviceName
      })
    });

    const verifyData = await verifyRes.json();
    if (!verifyRes.ok) {
      throw new Error(verifyData.detail || 'Biometric enrollment failed');
    }

    alert('✅ Biometric device enrolled successfully! You can now use 1-tap fingerprint/Face ID sign-in.');
    await loadEnrolledDevices();

  } catch (err) {
    console.error('Enrollment error:', err);
    alert('Biometric Enrollment: ' + (err.message || 'Error creating passkey'));
  } finally {
    const btn = document.getElementById('btnEnrollCurrentDevice');
    if (btn) btn.disabled = false;
  }
}

async function loadEnrolledDevices() {
  const container = document.getElementById('enrolledDevicesContainer');
  if (!container) return;

  try {
    const res = await apiFetch('/api/auth/me');
    if (!res.ok) {
      container.innerHTML = '<div class="empty-devices-state">Sign in to view enrolled devices.</div>';
      return;
    }
    const data = await res.json();
    const devices = data.enrolled_devices || [];

    if (devices.length === 0) {
      container.innerHTML = `
        <div class="empty-devices-state">
          <p>No mobile phones or passkeys enrolled yet.</p>
          <p class="text-sm">Click "Enroll Sensor" above to register your mobile phone.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = devices.map(d => `
      <div class="device-item-row" data-id="${d.id}">
        <div class="device-item-left">
          <div class="device-phone-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
              <line x1="12" y1="18" x2="12.01" y2="18"></line>
            </svg>
          </div>
          <div>
            <div class="device-info-name">${escapeHtml(d.device_name || 'Mobile Phone')}</div>
            <div class="device-info-date">Enrolled ${new Date(d.created_at).toLocaleDateString()}</div>
          </div>
        </div>
        <button type="button" class="btn btn-sm btn-outline btn-delete-device" data-id="${d.id}" title="Remove Device">
          Remove
        </button>
      </div>
    `).join('');

    container.querySelectorAll('.btn-delete-device').forEach(b => {
      b.addEventListener('click', async (e) => {
        const id = e.currentTarget.getAttribute('data-id');
        if (confirm('Are you sure you want to remove this biometric authenticator?')) {
          await deleteEnrolledDevice(id);
        }
      });
    });

  } catch (err) {
    container.innerHTML = '<div class="empty-devices-state">Error loading devices.</div>';
  }
}

async function deleteEnrolledDevice(credId) {
  try {
    const res = await apiFetch(`/api/auth/credentials/${encodeURIComponent(credId)}`, { method: 'DELETE' });
    if (res.ok) {
      await loadEnrolledDevices();
    } else {
      alert('Failed to delete authenticator');
    }
  } catch (e) {
    alert('Error removing device');
  }
}

async function checkAuthStatus() {
  try {
    const token = localStorage.getItem('databridge_token');
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    const res = await fetch(getApiUrl('/api/auth/status'), { headers });
    const data = await res.json();

    if (!data.auth_configured) {
      showAuthSetupView();
      showAuthOverlay();
      return false;
    }

    if (data.current_user) {
      setLoggedInUser(data.current_user);
      hideAuthOverlay();
      return true;
    } else {
      showAuthBiometricView();
      showAuthOverlay();
      return false;
    }
  } catch (err) {
    console.error('Error checking auth:', err);
    showAuthOverlay();
    return false;
  }
}

function initAuthSystem() {
  checkBiometricHardware();

  const btnBio = document.getElementById('btnBiometricLogin');
  if (btnBio) btnBio.addEventListener('click', loginWithBiometrics);

  const btnToPwd = document.getElementById('btnSwitchToPassword');
  if (btnToPwd) btnToPwd.addEventListener('click', showAuthPasswordView);

  const btnToBio = document.getElementById('btnSwitchToBiometric');
  if (btnToBio) btnToBio.addEventListener('click', showAuthBiometricView);

  const formLogin = document.getElementById('formPasswordLogin');
  if (formLogin) {
    formLogin.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAuthAlert();
      const username = document.getElementById('loginUsername').value.trim();
      const password = document.getElementById('loginPassword').value;

      try {
        const res = await fetch(getApiUrl('/api/auth/login'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Invalid credentials');
        }

        localStorage.setItem('databridge_token', data.access_token);
        setLoggedInUser(data.user);
        hideAuthOverlay();

        await loadSources();
        await initConsolidatedDb();
        await executeSearch();

      } catch (err) {
        setAuthAlert(err.message || 'Login failed', 'error');
      }
    });
  }

  const formSetup = document.getElementById('formInitialSetup');
  if (formSetup) {
    formSetup.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAuthAlert();
      const username = document.getElementById('setupUsername').value.trim();
      const displayName = document.getElementById('setupDisplayName').value.trim();
      const password = document.getElementById('setupPassword').value;
      const confirm = document.getElementById('setupPasswordConfirm').value;

      if (password !== confirm) {
        setAuthAlert('Passwords do not match.', 'error');
        return;
      }

      try {
        const res = await fetch(getApiUrl('/api/auth/setup'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username,
            password,
            display_name: displayName
          })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Setup failed');
        }

        localStorage.setItem('databridge_token', data.access_token);
        setLoggedInUser(data.user);
        hideAuthOverlay();

        setTimeout(async () => {
          if (confirm('🎉 Administrator created! Would you like to enroll this mobile phone / device for 1-tap fingerprint/Face ID sign-in right now?')) {
            await enrollCurrentDevice();
          }
        }, 400);

        await loadSources();
        await initConsolidatedDb();
        await executeSearch();

      } catch (err) {
        setAuthAlert(err.message || 'Setup error', 'error');
      }
    });
  }

  const btnLogout = document.getElementById('btnLogoutBtn');
  if (btnLogout) {
    btnLogout.addEventListener('click', () => {
      if (confirm('Log out of DataBridge?')) {
        localStorage.removeItem('databridge_token');
        state.currentUser = null;
        const profileSection = document.getElementById('userProfileSection');
        if (profileSection) profileSection.style.display = 'none';
        showAuthBiometricView();
        showAuthOverlay();
      }
    });
  }

  const btnOpenDev = document.getElementById('btnOpenDevicesModal');
  const modalDev = document.getElementById('modalDevicesManager');
  const btnCloseDev = document.getElementById('btnCloseDevicesModal');
  const btnDoneDev = document.getElementById('btnDoneDevicesModal');
  const btnEnrollNow = document.getElementById('btnEnrollCurrentDevice');

  if (btnOpenDev && modalDev) {
    btnOpenDev.addEventListener('click', async () => {
      modalDev.style.display = 'flex';
      await loadEnrolledDevices();
    });
  }

  const closeDevModal = () => { if (modalDev) modalDev.style.display = 'none'; };
  if (btnCloseDev) btnCloseDev.addEventListener('click', closeDevModal);
  if (btnDoneDev) btnDoneDev.addEventListener('click', closeDevModal);
  if (btnEnrollNow) btnEnrollNow.addEventListener('click', enrollCurrentDevice);
}
