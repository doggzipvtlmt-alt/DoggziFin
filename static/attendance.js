async function postAttendance(action, employeeId) {
  const endpoint = action === 'check-in' ? '/api/attendance/check-in' : '/api/attendance/check-out';
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ employee_id: employeeId }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || 'Failed to update attendance');
  }
  return data;
}

function setStatus(employeeId, message, isError = false) {
  const el = document.getElementById(`status-${employeeId}`);
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? '#fecaca' : '#86efac';
}

async function loadWeeklyProgress() {
  const rowsContainer = document.getElementById('weeklyProgressRows');
  if (!rowsContainer) return;

  const response = await fetch('/api/attendance/weekly-progress');
  const data = await response.json();
  if (!response.ok) {
    rowsContainer.innerHTML = '<p>Unable to load weekly progress.</p>';
    return;
  }

  const weekRange = document.getElementById('weekRange');
  weekRange.textContent = `Week: ${data.week_start} to ${data.week_end}`;

  rowsContainer.innerHTML = data.weekly_progress.map((row) => `
    <div class="week-row">
      <strong>${row.employee_name}</strong>
      <span>Worked: ${row.worked_hours}h</span>
      <span>Remaining: ${row.remaining_hours}h</span>
    </div>
  `).join('');
}

async function loadSalaryAnalysis() {
  const tableBody = document.getElementById('salaryTableBody');
  if (!tableBody) return;

  const response = await fetch('/api/attendance/salary-analysis');
  const data = await response.json();
  if (!response.ok) {
    tableBody.innerHTML = '<tr><td colspan="5">Unable to load salary analysis.</td></tr>';
    return;
  }

  tableBody.innerHTML = data.salary_analysis.map((row) => `
    <tr>
      <td>${row.employee_name}</td>
      <td>${row.total_days_worked}</td>
      <td>${row.total_hours_worked}</td>
      <td>${row.extra_hours}</td>
      <td>₹${row.estimated_salary.toLocaleString()}</td>
    </tr>
  `).join('');

  const totalSalary = data.salary_analysis.reduce((sum, row) => sum + row.estimated_salary, 0);
  const totalHours = data.salary_analysis.reduce((sum, row) => sum + row.total_hours_worked, 0);
  const cards = document.getElementById('salaryCards');
  cards.innerHTML = `
    <div class="stat-card"><div class="stat-label">Team Salary Estimate</div><div class="stat-value">₹${totalSalary.toLocaleString()}</div></div>
    <div class="stat-card"><div class="stat-label">Total Hours</div><div class="stat-value">${totalHours}</div></div>
    <div class="stat-card"><div class="stat-label">Employees</div><div class="stat-value">${data.salary_analysis.length}</div></div>
  `;

  const maxHours = Math.max(...data.salary_analysis.map(r => r.total_hours_worked), 1);
  const chart = document.getElementById('hoursChart');
  chart.innerHTML = data.salary_analysis.map((row) => {
    const width = Math.round((row.total_hours_worked / maxHours) * 100);
    return `
      <div class="chart-bar-row">
        <span>${row.employee_name}</span>
        <div class="chart-bar"><div class="chart-bar-fill" style="width:${width}%"></div></div>
        <strong>${row.total_hours_worked}h</strong>
      </div>
    `;
  }).join('');
}

function initAttendanceTerminal() {
  const grid = document.getElementById('employeeGrid');
  if (!grid) return;

  grid.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;

    const card = button.closest('.employee-card');
    const employeeId = card.dataset.employeeId;
    const action = button.dataset.action;

    button.disabled = true;
    try {
      const result = await postAttendance(action, employeeId);
      const summary = result.working_hours
        ? `${result.message}. Hours: ${result.working_hours}, Day count: ${result.day_count}, Extra: ${result.extra_hours}`
        : result.message;
      setStatus(employeeId, summary);
      await loadWeeklyProgress();
    } catch (error) {
      setStatus(employeeId, error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  loadWeeklyProgress();
  setInterval(loadWeeklyProgress, 15000);
}

initAttendanceTerminal();
loadSalaryAnalysis();
setInterval(loadSalaryAnalysis, 30000);
