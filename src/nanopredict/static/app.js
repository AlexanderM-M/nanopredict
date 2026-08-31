const elements = {
  connection: document.querySelector('.connection'),
  connectionText: document.getElementById('connectionText'),
  sample: document.getElementById('sampleSelect'),
  target: document.getElementById('targetInput'),
  speed: document.getElementById('speedSelect'),
  start: document.getElementById('startButton'),
  advance: document.getElementById('advanceButton'),
  stop: document.getElementById('stopButton'),
  waiting: document.getElementById('waitingState'),
  run: document.getElementById('runState'),
  sampleName: document.getElementById('sampleName'),
  runMessage: document.getElementById('runMessage'),
  statusBadge: document.getElementById('statusBadge'),
  timelineFill: document.getElementById('timelineFill'),
  prediction: document.getElementById('predictionValue'),
  interval: document.getElementById('intervalValue'),
  probabilityRing: document.getElementById('probabilityRing'),
  probability: document.getElementById('probabilityValue'),
  targetValue: document.getElementById('targetValue'),
  observed: document.getElementById('observedValue'),
  reads: document.getElementById('readsValue'),
  temperature: document.getElementById('temperatureValue'),
  confidence: document.getElementById('confidenceValue'),
  explanation: document.getElementById('statusExplanation'),
  problems: document.getElementById('problemsList'),
  outcome: document.getElementById('outcomePanel'),
  actual: document.getElementById('actualValue'),
  toast: document.getElementById('toast')
};

let lastState = 'waiting';
let toastTimer;

function number(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function compactNumber(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value));
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => elements.toast.classList.remove('visible'), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}

function setConnected(connected) {
  elements.connection.classList.toggle('online', connected);
  elements.connectionText.textContent = connected ? 'Dashboard online' : 'Reconnecting';
}

function renderProblems(items) {
  elements.problems.replaceChildren();
  if (!items || items.length === 0) {
    const clear = document.createElement('div');
    clear.className = 'no-problems';
    clear.textContent = 'No extreme peer-based QC anomaly detected at this checkpoint.';
    elements.problems.append(clear);
    return;
  }
  items.slice(0, 5).forEach(item => {
    const row = document.createElement('article');
    row.className = `problem ${item.severity || ''}`;
    const marker = document.createElement('span');
    marker.className = 'problem-marker';
    const content = document.createElement('div');
    const title = document.createElement('h4');
    title.textContent = item.title;
    const detail = document.createElement('p');
    detail.textContent = item.suggested_check;
    content.append(title, detail);
    row.append(marker, content);
    elements.problems.append(row);
  });
}

function renderTimeline(horizon) {
  const positions = { null: 0, 30: 33.333, 60: 66.666, 120: 100 };
  elements.timelineFill.style.width = `${positions[horizon] || 0}%`;
  document.querySelectorAll('.checkpoint[data-horizon]').forEach(node => {
    node.classList.toggle('done', horizon !== null && Number(node.dataset.horizon) <= horizon);
  });
}

function renderStatus(data) {
  const waiting = data.state === 'waiting';
  elements.waiting.classList.toggle('hidden', !waiting);
  elements.run.classList.toggle('hidden', waiting);
  if (waiting) {
    elements.advance.disabled = true;
    elements.stop.disabled = true;
    lastState = data.state;
    return;
  }

  elements.sampleName.textContent = data.sample_id;
  elements.runMessage.textContent = data.message;
  elements.targetValue.textContent = `Target: ${number(data.target_gb)} GB`;
  elements.advance.disabled = data.state === 'complete' || data.state === 'stopped';
  elements.stop.disabled = data.state === 'complete' || data.state === 'stopped';
  elements.start.textContent = data.state === 'running' ? 'Restart replay' : 'Start replay';
  renderTimeline(data.current_horizon_minutes);

  const obs = data.observations;
  elements.observed.textContent = obs ? number(obs.passed_yield_gb, 2) : '—';
  elements.reads.textContent = obs ? compactNumber(obs.total_reads) : '—';
  elements.temperature.textContent = obs && obs.temperature_c !== null ? `${number(obs.temperature_c)} °C` : '—';

  const assessment = data.assessment;
  if (!assessment) {
    elements.statusBadge.className = 'status-badge pending';
    elements.statusBadge.querySelector('strong').textContent = 'COLLECTING';
    elements.prediction.textContent = '—';
    elements.interval.textContent = `Next prediction at ${data.next_horizon_minutes} minutes`;
    elements.probability.textContent = '—';
    elements.probabilityRing.style.setProperty('--probability', '0deg');
    elements.confidence.textContent = 'Waiting';
    elements.explanation.textContent = 'The first calibrated prediction will appear at the 30-minute checkpoint.';
    elements.problems.replaceChildren();
  } else {
    const prediction = assessment.prediction;
    const interval = prediction.prediction_intervals['90'];
    const probability = assessment.probability_of_reaching_target;
    const status = assessment.status.toLowerCase();
    elements.statusBadge.className = `status-badge ${status}`;
    elements.statusBadge.querySelector('strong').textContent = assessment.status;
    elements.prediction.textContent = number(prediction.point_prediction_gb);
    elements.interval.textContent = `90% interval: ${number(interval.lower_gb)}–${number(interval.upper_gb)} GB · ${prediction.horizon_minutes}-min model`;
    elements.probability.textContent = `${Math.round(probability * 100)}%`;
    elements.probabilityRing.style.setProperty('--probability', `${probability * 360}deg`);
    elements.confidence.textContent = `${assessment.status_confidence} confidence`;
    elements.explanation.textContent = assessment.status_explanation;
    renderProblems(assessment.suspected_problems);
  }

  const complete = data.state === 'complete' && data.actual_final_gb !== null;
  elements.outcome.classList.toggle('hidden', !complete);
  if (complete) elements.actual.textContent = number(data.actual_final_gb);
  if (lastState !== 'complete' && data.state === 'complete') showToast('Historical replay complete');
  lastState = data.state;
}

async function loadRuns() {
  const data = await api('/api/replays');
  elements.sample.replaceChildren();
  data.runs.forEach(run => {
    const option = document.createElement('option');
    option.value = run.sample_id;
    option.textContent = `${run.sample_id} · 30/60/120 min`;
    elements.sample.append(option);
  });
}

async function refresh() {
  try {
    const status = await api('/api/status');
    setConnected(true);
    renderStatus(status);
  } catch (error) {
    setConnected(false);
  }
}

elements.start.addEventListener('click', async () => {
  try {
    const target = Number(elements.target.value);
    if (!Number.isFinite(target) || target <= 0) throw new Error('Enter a positive target yield');
    const result = await api('/api/start', {
      method: 'POST',
      body: JSON.stringify({
        sample_id: elements.sample.value,
        target_gb: target,
        seconds_per_step: Number(elements.speed.value)
      })
    });
    renderStatus(result);
    showToast('Replay started');
  } catch (error) {
    showToast(error.message);
  }
});

elements.advance.addEventListener('click', async () => {
  try { renderStatus(await api('/api/advance', { method: 'POST', body: '{}' })); }
  catch (error) { showToast(error.message); }
});

elements.stop.addEventListener('click', async () => {
  try { renderStatus(await api('/api/stop', { method: 'POST', body: '{}' })); }
  catch (error) { showToast(error.message); }
});

(async function initialise() {
  try {
    await loadRuns();
    await refresh();
    setInterval(refresh, 1000);
  } catch (error) {
    setConnected(false);
    showToast('Could not initialise the dashboard');
  }
})();
