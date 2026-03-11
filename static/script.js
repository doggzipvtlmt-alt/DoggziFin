// ── Utilities ──────────────────────────────────────────────────────────────────

const fmt = (n) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);

async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

function showAlert(el, type, msg) {
  el.className = `alert ${type}`;
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
}

function setLoading(btn, loading, text = 'Saving…') {
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
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

// ── Generic expense form handler ────────────────────────────────────────────

function initExpenseForm(formId, endpoint, tableId, totalId, countId) {
  const form    = document.getElementById(formId);
  const alertEl = document.getElementById('form-alert');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('.btn-primary');
    const fd  = new FormData(form);
    const payload = Object.fromEntries(fd.entries());

    setLoading(btn, true);
    try {
      const res = await postJSON(endpoint, payload);
      if (res.success) {
        showAlert(alertEl, 'success', '✓ ' + res.message);
        form.reset();
        await refreshTable(endpoint.replace('add_','get_'), tableId, totalId, countId);
      } else {
        showAlert(alertEl, 'error', '✗ ' + (res.errors || [res.message]).join(', '));
      }
    } catch (err) {
      showAlert(alertEl, 'error', '✗ Network error. Please try again.');
    } finally {
      setLoading(btn, false);
    }
  });
}

async function refreshTable(getUrl, tableId, totalId, countId) {
  const tbody = document.getElementById(tableId);
  if (!tbody) return;

  const data = await fetch(getUrl).then(r => r.json());
  const type = tableId.includes('capex') ? 'capex' : 'opex';

  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="8">
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        <p>No entries yet. Add your first record above.</p>
      </div>
    </td></tr>`;
  } else {
    tbody.innerHTML = data.map(row => `
      <tr>
        <td><strong>${esc(row.category)}</strong></td>
        <td>${esc(row.description)}</td>
        <td class="amt">${fmt(row.amount)}</td>
        <td>${esc(row.department)}</td>
        <td>${row.date}</td>
        <td>${esc(row.approved_by)}</td>
        <td style="color:var(--muted);font-size:12px">${esc(row.notes||'—')}</td>
        <td><button class="btn btn-danger btn-sm js-delete-btn" data-id="${row.id}" data-type="${type}">Delete</button></td>
      </tr>`).join('');
  }

  const total = data.reduce((s, r) => s + r.amount, 0);
  if (totalId && document.getElementById(totalId)) document.getElementById(totalId).textContent = fmt(total);
  if (countId && document.getElementById(countId)) document.getElementById(countId).textContent = data.length + ' entr' + (data.length === 1 ? 'y' : 'ies');
  const summaryCount = document.getElementById('entry-count-summary');
  if (summaryCount) summaryCount.textContent = data.length + ' entr' + (data.length === 1 ? 'y' : 'ies');
}

function initDeleteModal(expenseType, getEndpoint, tableId, totalId, countId) {
  const modal = document.getElementById('delete-modal');
  const closeBtn = document.getElementById('delete-modal-close');
  const cancelBtn = document.getElementById('delete-cancel-btn');
  const confirmBtn = document.getElementById('delete-confirm-btn');
  const errorEl = document.getElementById('delete-error');
  const nameInput = document.getElementById('delete-name');
  const passwordInput = document.getElementById('delete-password');
  if (!modal) return;

  let selectedId = null;

  const closeModal = () => {
    modal.style.display = 'none';
    selectedId = null;
    errorEl.style.display = 'none';
    errorEl.textContent = '';
    nameInput.value = '';
    passwordInput.value = '';
  };

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.js-delete-btn');
    if (!btn || btn.dataset.type !== expenseType) return;
    selectedId = btn.dataset.id;
    modal.style.display = 'flex';
    errorEl.style.display = 'none';
  });

  closeBtn.addEventListener('click', closeModal);
  cancelBtn.addEventListener('click', closeModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  confirmBtn.addEventListener('click', async () => {
    if (!selectedId) return;
    setLoading(confirmBtn, true, 'Deleting…');
    errorEl.style.display = 'none';

    try {
      const res = await fetch(`/api/delete_${expenseType}/${selectedId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          deleted_by: nameInput.value.trim(),
          password: passwordInput.value.trim(),
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        errorEl.textContent = data.message || 'Unable to delete entry.';
        errorEl.style.display = 'block';
        return;
      }

      closeModal();
      await refreshTable(getEndpoint, tableId, totalId, countId);
    } catch (err) {
      errorEl.textContent = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    } finally {
      setLoading(confirmBtn, false);
    }
  });
}

function transactionTypePill(type) {
  const cls = type === 'inbound' ? 'pill-inbound' : 'pill-outbound';
  return `<span class="${cls}">${esc(type)}</span>`;
}

function transactionStatusPill(status) {
  const map = {
    pending: 'pill-pending',
    refunded: 'pill-refunded',
    failed: 'pill-failed',
    completed: 'pill-completed',
  };
  return `<span class="${map[status] || 'pill-completed'}">${esc(status)}</span>`;
}

async function loadTransactions(filter = '') {
  const tbody = document.getElementById('transactions-tbody');
  if (!tbody) return;
  const q = filter ? `?transaction_type=${encodeURIComponent(filter)}` : '';
  const rows = await fetch(`/api/get_transactions${q}`).then(r => r.json());
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9"><div class="empty-state"><p>No transactions found.</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r) => `
    <tr>
      <td>${esc(r.transaction_id || '')}</td>
      <td>${transactionTypePill(r.transaction_type || '')}</td>
      <td>${esc(r.transaction_category || '')}</td>
      <td>${transactionStatusPill(r.transaction_status || '')}</td>
      <td class="amt">${fmt(r.amount || 0)}</td>
      <td>${esc(r.order_id || '—')}</td>
      <td>${esc(r.customer_id || '—')}</td>
      <td>${esc(r.vendor_id || '—')}</td>
      <td>${esc((r.created_at || '').replace('T', ' ').slice(0, 19))}</td>
    </tr>`).join('');
}

function initTransactionsModule() {
  const form = document.getElementById('transaction-form');
  const alertEl = document.getElementById('transaction-alert');
  if (!form) return;

  loadTransactions('');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    const res = await postJSON('/api/add_transaction', payload);
    if (res.success) {
      showAlert(alertEl, 'success', `✓ ${res.message}`);
      form.reset();
      loadTransactions(document.getElementById('transaction-filter').value);
    } else {
      showAlert(alertEl, 'error', `✗ ${(res.errors || [res.message]).join(', ')}`);
    }
  });

  document.getElementById('transaction-filter').addEventListener('change', (e) => {
    loadTransactions(e.target.value);
  });

  document.getElementById('update-status-btn').addEventListener('click', async () => {
    const txId = document.getElementById('status-tx-id').value.trim();
    const status = document.getElementById('status-new-value').value;
    if (!txId) return showAlert(alertEl, 'error', '✗ Transaction ID is required for status update');
    const res = await fetch(`/api/update_transaction_status/${encodeURIComponent(txId)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transaction_status: status }),
    }).then(r => r.json());
    if (res.success) {
      showAlert(alertEl, 'success', `✓ ${res.message}`);
      loadTransactions(document.getElementById('transaction-filter').value);
    } else {
      showAlert(alertEl, 'error', `✗ ${res.message || 'Unable to update status'}`);
    }
  });

  document.getElementById('record-refund-btn').addEventListener('click', async () => {
    const payload = {
      original_transaction_id: document.getElementById('refund-original-id').value.trim(),
      transaction_id: document.getElementById('refund-tx-id').value.trim(),
      amount: document.getElementById('refund-amount').value,
      payment_method: document.getElementById('refund-payment-method').value.trim(),
    };
    const res = await postJSON('/api/record_refund', payload);
    if (res.success) {
      showAlert(alertEl, 'success', `✓ ${res.message}`);
      loadTransactions(document.getElementById('transaction-filter').value);
    } else {
      showAlert(alertEl, 'error', `✗ ${res.message || 'Unable to record refund'}`);
    }
  });
}
