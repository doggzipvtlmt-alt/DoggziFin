const fmt = (n) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);

async function postJSON(url, payload) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  return res.json();
}

function showAlert(el, type, msg) {
  if (!el) return;
  el.className = `alert ${type}`;
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
}

function setLoading(btn, loading, text = 'Saving…') {
  if (!btn) return;
  if (loading) {
    btn.dataset.orig = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> ${text}`;
    btn.disabled = true;
  } else {
    btn.innerHTML = btn.dataset.orig;
    btn.disabled = false;
  }
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function transactionStatusPill(status) {
  const map = { pending: 'pill-pending', refunded: 'pill-refunded', failed: 'pill-failed', completed: 'pill-completed' };
  return `<span class="${map[status] || 'pill-completed'}">${esc(status)}</span>`;
}

async function generateId(moduleName, inputId) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const res = await fetch(`/api/generate_id/${moduleName}`).then((r) => r.json());
  if (res.success) input.value = res.value;
}

function wireGenerateIdButton(moduleName, buttonId, inputId) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  btn.addEventListener('click', () => generateId(moduleName, inputId));
}

function wireExcelDownload(buttonId, moduleName, userIdInputId) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  btn.addEventListener('click', () => {
    const userId = document.getElementById(userIdInputId)?.value?.trim() || 'unknown';
    window.location.href = `/api/export/${moduleName}?user_id=${encodeURIComponent(userId)}`;
  });
}

function initExpenseForm(formId, endpoint, tableId, totalId, countId) {
  const form = document.getElementById(formId);
  const alertEl = document.getElementById('form-alert');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('.btn-primary');
    const payload = Object.fromEntries(new FormData(form).entries());

    setLoading(btn, true);
    try {
      const res = await postJSON(endpoint, payload);
      if (res.success) {
        showAlert(alertEl, 'success', `✓ ${res.message}`);
        form.reset();
        await refreshTable(endpoint.replace('add_', 'get_'), tableId, totalId, countId);
      } else {
        showAlert(alertEl, 'error', `✗ ${(res.errors || [res.message]).join(', ')}`);
      }
    } finally {
      setLoading(btn, false);
    }
  });
}

async function refreshTable(getUrl, tableId, totalId, countId) {
  const tbody = document.getElementById(tableId);
  if (!tbody) return;
  const data = await fetch(getUrl).then((r) => r.json());
  const type = tableId.includes('capex') ? 'capex' : 'opex';

  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>No entries yet.</p></div></td></tr>';
  } else {
    tbody.innerHTML = data.map((row) => `
      <tr>
        <td><strong>${esc(row.capex_id || row.opex_id || row.id || '')}</strong></td>
        <td><strong>${esc(row.category)}</strong></td>
        <td>${esc(row.description)}</td>
        <td class="amt">${fmt(row.amount)}</td>
        <td>${esc(row.department)}</td>
        <td>${esc(row.date)}</td>
        <td>${esc(row.approved_by)}</td>
        <td style="color:var(--muted);font-size:12px">${esc(row.notes || '—')}</td>
        <td><button class="btn btn-danger btn-sm js-delete-btn" data-id="${row.id}" data-type="${type}">Delete</button></td>
      </tr>`).join('');
  }

  const total = data.reduce((s, r) => s + Number(r.amount || 0), 0);
  if (document.getElementById(totalId)) document.getElementById(totalId).textContent = fmt(total);
  if (document.getElementById(countId)) document.getElementById(countId).textContent = `${data.length} entr${data.length === 1 ? 'y' : 'ies'}`;
  const summaryCount = document.getElementById('entry-count-summary');
  if (summaryCount) summaryCount.textContent = `${data.length} entr${data.length === 1 ? 'y' : 'ies'}`;
}

function initDeleteModal(expenseType, getEndpoint, tableId, totalId, countId) {
  const modal = document.getElementById('delete-modal');
  if (!modal) return;
  const errorEl = document.getElementById('delete-error');
  const nameInput = document.getElementById('delete-name');
  const passwordInput = document.getElementById('delete-password');
  const reasonInput = document.getElementById('delete-reason');
  let selectedId = null;

  const close = () => {
    modal.style.display = 'none';
    selectedId = null;
    errorEl.style.display = 'none';
    nameInput.value = '';
    passwordInput.value = '';
    if (reasonInput) reasonInput.value = '';
  };

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.js-delete-btn');
    if (!btn || btn.dataset.type !== expenseType) return;
    selectedId = btn.dataset.id;
    modal.style.display = 'flex';
  });

  document.getElementById('delete-modal-close')?.addEventListener('click', close);
  document.getElementById('delete-cancel-btn')?.addEventListener('click', close);
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });

  document.getElementById('delete-confirm-btn')?.addEventListener('click', async (e) => {
    if (!selectedId) return;
    setLoading(e.target, true, 'Deleting…');
    try {
      const res = await fetch(`/api/delete_${expenseType}/${selectedId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deleted_by: nameInput.value.trim(), password: passwordInput.value.trim(), reason: reasonInput?.value?.trim() || '' }),
      });
      const data = await res.json();
      if (!res.ok) {
        errorEl.textContent = data.message || 'Unable to delete entry.';
        errorEl.style.display = 'block';
        return;
      }
      close();
      await refreshTable(getEndpoint, tableId, totalId, countId);
    } finally {
      setLoading(e.target, false);
    }
  });
}

async function loadTransactions(type, tableBodyId = 'transactions-tbody') {
  const tbody = document.getElementById(tableBodyId);
  if (!tbody) return;
  const rows = await fetch(`/api/get_transactions?transaction_type=${encodeURIComponent(type)}`).then((r) => r.json());
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><p>No transactions found.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((r) => type === 'inbound'
    ? `<tr><td>${esc(r.transaction_id)}</td><td>${esc(r.transaction_category)}</td><td>${transactionStatusPill(r.transaction_status)}</td><td class="amt">${fmt(r.amount)}</td><td>${esc(r.order_id || '—')}</td><td>${esc(r.customer_id || '—')}</td><td>${esc((r.created_at || '').replace('T', ' ').slice(0, 19))}</td></tr>`
    : `<tr><td>${esc(r.transaction_id)}</td><td>${esc(r.transaction_category)}</td><td>${transactionStatusPill(r.transaction_status)}</td><td class="amt">${fmt(r.amount)}</td><td>${esc(r.vendor_id || '—')}</td><td>${esc((r.created_at || '').replace('T', ' ').slice(0, 19))}</td></tr>`).join('');
}

function wireTransactionStatusUpdate(alertEl) {
  document.getElementById('update-status-btn')?.addEventListener('click', async () => {
    const txId = document.getElementById('status-tx-id').value.trim();
    const status = document.getElementById('status-new-value').value;
    const res = await fetch(`/api/update_transaction_status/${encodeURIComponent(txId)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ transaction_status: status }) }).then((r) => r.json());
    showAlert(alertEl, res.success ? 'success' : 'error', `${res.success ? '✓' : '✗'} ${res.message || 'Unable to update status'}`);
  });
}

function initInboundTransactionsModule() {
  const form = document.getElementById('inbound-transaction-form');
  const alertEl = document.getElementById('transaction-alert');
  if (!form) return;
  loadTransactions('inbound');
  wireTransactionStatusUpdate(alertEl);
  wireExcelDownload('download-inbound-excel', 'inbound', 'download-user-id');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.transaction_type = 'inbound';
    payload.payment_gateway_transaction_id = payload.transaction_id;
    const res = await postJSON('/api/add_transaction', payload);
    if (res.success) {
      showAlert(alertEl, 'success', `✓ ${res.message} (${res.transaction_id})`);
      form.reset();
      loadTransactions('inbound');
    } else showAlert(alertEl, 'error', `✗ ${(res.errors || [res.message]).join(', ')}`);
  });
}

function initOutboundTransactionsModule() {
  const form = document.getElementById('outbound-transaction-form');
  const alertEl = document.getElementById('transaction-alert');
  if (!form) return;
  loadTransactions('outbound');
  wireTransactionStatusUpdate(alertEl);
  wireGenerateIdButton('outbound', 'generate-outbound-id', 'transaction_id');
  wireExcelDownload('download-outbound-excel', 'outbound', 'download-user-id');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.transaction_type = 'outbound';
    const res = await postJSON('/api/add_transaction', payload);
    if (res.success) {
      showAlert(alertEl, 'success', `✓ ${res.message} (${res.transaction_id})`);
      form.reset();
      loadTransactions('outbound');
    } else showAlert(alertEl, 'error', `✗ ${(res.errors || [res.message]).join(', ')}`);
  });
}

async function loadIssues() {
  const tbody = document.getElementById('issues-tbody');
  if (!tbody) return;
  const rows = await fetch('/api/get_transaction_issues').then((r) => r.json());
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><p>No issues raised yet.</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((r) => `<tr><td>${esc(r.issue_id)}</td><td>${esc(r.transaction_id)}</td><td>${esc(r.issue_type)}</td><td>${esc(r.status)}</td><td>${esc(r.reported_by)}</td><td>${esc((r.created_at || '').replace('T', ' ').slice(0, 19))}</td></tr>`).join('');
}

function initTransactionIssuesModule() {
  const form = document.getElementById('issue-form');
  const alertEl = document.getElementById('issues-alert');
  if (!form) return;
  loadIssues();
  wireGenerateIdButton('issue', 'generate-issue-id', 'issue_id');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    const res = await postJSON('/api/add_transaction_issue', payload);
    if (res.success) {
      showAlert(alertEl, 'success', `✓ ${res.message} (${res.issue_id})`);
      form.reset();
      loadIssues();
    } else showAlert(alertEl, 'error', `✗ ${(res.errors || [res.message]).join(', ')}`);
  });

  document.getElementById('update-issue-status-btn')?.addEventListener('click', async () => {
    const issueId = document.getElementById('issue-status-id').value.trim();
    const status = document.getElementById('issue-status-value').value;
    const res = await fetch(`/api/update_transaction_issue_status/${encodeURIComponent(issueId)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) }).then((r) => r.json());
    showAlert(alertEl, res.success ? 'success' : 'error', `${res.success ? '✓' : '✗'} ${res.message || 'Unable to update issue status'}`);
    if (res.success) loadIssues();
  });
}

function initSystemLogsModule() {
  const btn = document.getElementById('filter-logs-btn');
  const tbody = document.getElementById('logs-tbody');
  if (!btn || !tbody) return;

  const load = async () => {
    const params = new URLSearchParams({
      module_name: document.getElementById('log-module-filter').value,
      action_type: document.getElementById('log-action-filter').value,
      start_date: document.getElementById('log-start-date').value,
      end_date: document.getElementById('log-end-date').value,
    });
    const rows = await fetch(`/api/system_logs?${params.toString()}`).then((r) => r.json());
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><p>No logs found.</p></div></td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((r) => `<tr><td>${esc(r.log_id)}</td><td>${esc(r.action_type)}</td><td>${esc(r.module_name)}</td><td>${esc(r.user_id)}</td><td>${esc((r.timestamp || '').replace('T', ' ').slice(0, 19))}</td><td>${esc(r.details || r.file_name || r.deleted_record_id || '—')}</td></tr>`).join('');
  };

  btn.addEventListener('click', load);
  load();
}
