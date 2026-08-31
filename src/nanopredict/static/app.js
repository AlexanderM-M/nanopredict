const elements = {
  connection: document.querySelector('.connection'),
  connectionText: document.getElementById('connectionText'),
  sample: document.getElementById('sampleSelect'),
  sampleControl: document.getElementById('sampleControl'),
  positionControl: document.getElementById('positionControl'),
  positionList: document.getElementById('positionList'),
  target: document.getElementById('targetInput'),
  targetEquivalent: document.getElementById('targetEquivalent'),
  speed: document.getElementById('speedSelect'),
  speedControl: document.getElementById('speedControl'),
  setupTitle: document.getElementById('setupTitle'),
  sourcePill: document.getElementById('sourcePill'),
  modeName: document.getElementById('modeName'),
  modeDetail: document.getElementById('modeDetail'),
  privacyCopy: document.getElementById('privacyCopy'),
  start: document.getElementById('startButton'),
  advance: document.getElementById('advanceButton'),
  stop: document.getElementById('stopButton'),
  waiting: document.getElementById('waitingState'),
  waitingTitle: document.getElementById('waitingTitle'),
  waitingCopy: document.getElementById('waitingCopy'),
  run: document.getElementById('runState'),
  sampleName: document.getElementById('sampleName'),
  runMode: document.getElementById('runMode'),
  runMessage: document.getElementById('runMessage'),
  statusBadge: document.getElementById('statusBadge'),
  liveProgressPanel: document.getElementById('liveProgressPanel'),
  liveProgressBadge: document.getElementById('liveProgressBadge'),
  liveBaseValue: document.getElementById('liveBaseValue'),
  liveGbValue: document.getElementById('liveGbValue'),
  yieldProgressFill: document.getElementById('yieldProgressFill'),
  yieldProgressCopy: document.getElementById('yieldProgressCopy'),
  yieldProgressPercent: document.getElementById('yieldProgressPercent'),
  remainingBases: document.getElementById('remainingBasesValue'),
  liveRate: document.getElementById('liveRateValue'),
  eta: document.getElementById('etaValue'),
  timelineFill: document.getElementById('timelineFill'),
  prediction: document.getElementById('predictionValue'),
  predictionUnit: document.getElementById('predictionUnit'),
  interval: document.getElementById('intervalValue'),
  probabilityRing: document.getElementById('probabilityRing'),
  probability: document.getElementById('probabilityValue'),
  targetValue: document.getElementById('targetValue'),
  metricGrid: document.getElementById('metricGrid'),
  observedCard: document.getElementById('observedCard'),
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
let currentMode = null;
let runsLoaded = false;
let toastTimer;
let selectedPosition = null;
let displayedPosition = null;
let refreshToken = 0;

function number(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function compactNumber(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value));
}

function bases(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return Math.round(Number(value)).toLocaleString();
}

function duration(minutes) {
  if (minutes === null || minutes === undefined || !Number.isFinite(Number(minutes))) return '—';
  if (minutes < 1) return '<1 min';
  if (minutes < 120) return `${Math.round(minutes)} min`;
  return `${number(minutes / 60, 1)} h`;
}

function yieldParts(gb) {
  const value = Number(gb);
  if (!Number.isFinite(value)) return { value: '—', unit: 'GB' };
  if (value === 0) return { value: '0', unit: 'Mb' };
  if (value >= 1) {
    return { value: number(value, value < 10 ? 2 : 1), unit: 'GB' };
  }
  if (value >= 0.001) {
    const mb = value * 1000;
    return { value: number(mb, mb < 10 ? 1 : 0), unit: 'Mb' };
  }
  const kb = value * 1e6;
  return { value: number(kb, kb < 10 ? 1 : 0), unit: 'kb' };
}

function yieldText(gb) {
  const parts = yieldParts(gb);
  return `${parts.value} ${parts.unit}`;
}

function renderTargetEquivalent() {
  const target = Number(elements.target.value);
  elements.targetEquivalent.textContent = Number.isFinite(target) && target > 0
    ? `${bases(target * 1e9)} bases`
    : 'Enter a positive target';
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => elements.toast.classList.remove('visible'), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}

function setConnected(connected) {
  elements.connection.classList.toggle('online', connected);
  elements.connectionText.textContent = connected ? 'Dashboard online' : 'Reconnecting';
}

function configureMode(mode, version, activeCount = 0) {
  const live = mode === 'minknow';
  currentMode = mode;
  elements.sampleControl.classList.toggle('hidden', live);
  elements.positionControl.classList.toggle('hidden', !live);
  elements.liveProgressPanel.classList.toggle('hidden', !live);
  elements.observedCard.classList.toggle('hidden', live);
  elements.metricGrid.classList.toggle('live', live);
  elements.speedControl.classList.toggle('hidden', live);
  elements.advance.parentElement.classList.toggle('hidden', live);
  elements.setupTitle.textContent = live ? 'Monitor a run' : 'Replay a run';
  elements.sourcePill.textContent = live ? 'Read-only' : 'Anonymous data';
  elements.modeName.textContent = live ? 'Live MinKNOW' : 'Historical replay';
  elements.modeDetail.textContent = live
    ? `${version || 'MinKNOW 6.10'} · ${activeCount} active position${activeCount === 1 ? '' : 's'} · local`
    : 'Anonymous MinION runs · accelerated';
  elements.start.textContent = live ? 'Apply target' : 'Start replay';
  elements.runMode.textContent = live ? 'Live' : 'Replay';
  elements.privacyCopy.innerHTML = live
    ? '<strong>Local and read-only.</strong><br>Nanopredict reads run statistics but cannot pause, stop, or alter sequencing.'
    : '<strong>Anonymous replay.</strong><br>Replay labels contain no patient names, run identifiers, or N-numbers.';
  if (!live && !runsLoaded) loadRuns().catch(error => showToast(error.message));
}

function renderPositions(data) {
  if (data.mode !== 'minknow') return;
  const positions = Array.isArray(data.positions) ? data.positions : [];
  selectedPosition = data.selected_position || null;
  elements.positionList.replaceChildren();
  if (positions.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'position-empty';
    empty.textContent = 'No active MinION positions yet.';
    elements.positionList.append(empty);
    return;
  }

  positions.forEach(position => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'position-option';
    button.classList.toggle('selected', position.position_name === selectedPosition);
    button.setAttribute('aria-pressed', position.position_name === selectedPosition ? 'true' : 'false');

    const copy = document.createElement('span');
    const name = document.createElement('strong');
    name.textContent = position.position_name;
    const detail = document.createElement('small');
    detail.textContent = position.passed_bases !== null && position.passed_bases !== undefined
      ? `${compactNumber(position.passed_bases)} bases · ${number(position.progress_percent, 0)}% of target`
      : position.current_horizon_minutes
        ? `${position.current_horizon_minutes}-min prediction · ${yieldText(position.prediction_gb)}`
      : position.state === 'waiting'
        ? 'Waiting for acquisition'
        : `Next prediction: ${position.next_horizon_minutes || 30} min`;
    copy.append(name, detail);

    const state = document.createElement('span');
    const label = ['error', 'waiting'].includes(position.state)
      ? position.state
      : position.target_reached
        ? 'reached'
        : position.assessment_status || position.state || 'connecting';
    state.className = `position-state ${String(label).toLowerCase()}`;
    state.textContent = String(label).toUpperCase();
    button.append(copy, state);
    button.addEventListener('click', () => {
      if (selectedPosition === position.position_name) return;
      selectedPosition = position.position_name;
      refresh();
    });
    elements.positionList.append(button);
  });
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
    content.append(title);
    row.append(marker, content);
    elements.problems.append(row);
  });
}

function renderLiveProgress(data) {
  if (data.mode !== 'minknow') return;
  const progress = data.live_progress;
  const targetBases = Number(data.target_gb) * 1e9;
  if (!progress) {
    elements.liveProgressBadge.className = 'target-status';
    elements.liveProgressBadge.textContent = 'COLLECTING';
    elements.liveBaseValue.textContent = '—';
    elements.liveGbValue.textContent = 'Waiting for live basecalling data';
    elements.yieldProgressFill.classList.remove('reached');
    elements.yieldProgressFill.style.width = '0%';
    elements.yieldProgressCopy.textContent = `Target: ${bases(targetBases)} bases`;
    elements.yieldProgressPercent.textContent = '0%';
    elements.remainingBases.textContent = bases(targetBases);
    elements.liveRate.textContent = '—';
    elements.eta.textContent = '—';
    return;
  }

  const reached = Boolean(progress.target_reached);
  elements.liveProgressBadge.className = `target-status ${reached ? 'reached' : ''}`;
  elements.liveProgressBadge.textContent = reached ? 'TARGET REACHED' : 'IN PROGRESS';
  elements.yieldProgressFill.classList.toggle('reached', reached);
  elements.liveBaseValue.textContent = bases(progress.passed_bases);
  elements.liveGbValue.textContent = `${number(progress.passed_yield_gb, 3)} GB passed`;
  elements.yieldProgressFill.style.width = `${Math.min(Number(progress.progress_percent), 100)}%`;
  elements.yieldProgressCopy.textContent = `${bases(progress.passed_bases)} of ${bases(progress.target_bases)} bases`;
  elements.yieldProgressPercent.textContent = `${number(progress.progress_percent, 1)}%`;
  elements.remainingBases.textContent = reached ? '0 bases' : `${bases(progress.remaining_bases)} bases`;
  elements.liveRate.textContent = progress.rate_bases_per_minute === null
    ? '—'
    : `${compactNumber(progress.rate_bases_per_minute)} bases/min`;
  elements.eta.textContent = reached
    ? `Reached at ${duration(progress.target_reached_elapsed_minutes)}`
    : duration(progress.eta_minutes);
}

function renderTimeline(horizon) {
  const positions = { null: 0, 30: 33.333, 60: 66.666, 120: 100 };
  elements.timelineFill.style.width = `${positions[horizon] || 0}%`;
  document.querySelectorAll('.checkpoint[data-horizon]').forEach(node => {
    node.classList.toggle('done', horizon !== null && Number(node.dataset.horizon) <= horizon);
  });
}

function renderStatus(data) {
  configureMode(data.mode, data.minknow_version, data.active_position_count || 0);
  renderPositions(data);
  const live = data.mode === 'minknow';
  if (live && data.position_name && data.position_name !== displayedPosition) {
    displayedPosition = data.position_name;
    elements.target.value = data.target_gb;
    renderTargetEquivalent();
  }
  const waiting = ['waiting', 'connecting', 'error'].includes(data.state);
  elements.waiting.classList.toggle('hidden', !waiting);
  elements.run.classList.toggle('hidden', waiting);
  if (waiting) {
    elements.waitingTitle.textContent = data.state === 'error'
      ? 'Live connection problem'
      : live ? 'Waiting for a MinION run' : 'Ready for a replay';
    elements.waitingCopy.textContent = data.message || (live
      ? 'Start a sequencing run in MinKNOW. Nanopredict will detect it automatically.'
      : 'Choose a historical run and target yield to begin.');
    elements.advance.disabled = true;
    elements.stop.disabled = true;
    lastState = data.state;
    return;
  }

  elements.sampleName.textContent = data.sample_id || 'Live MinION run';
  elements.runMessage.textContent = data.message;
  elements.targetValue.textContent = `Target: ${number(data.target_gb)} GB`;
  elements.advance.disabled = live || data.state === 'complete' || data.state === 'stopped';
  elements.stop.disabled = live || data.state === 'complete' || data.state === 'stopped';
  elements.start.textContent = live ? 'Apply target' : data.state === 'running' ? 'Restart replay' : 'Start replay';
  renderLiveProgress(data);
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
    elements.predictionUnit.textContent = 'GB';
    elements.interval.textContent = `Next prediction at ${data.next_horizon_minutes} minutes`;
    elements.probability.textContent = '—';
    elements.probabilityRing.style.setProperty('--probability', '0deg');
    elements.confidence.textContent = 'Waiting';
    elements.explanation.textContent = 'Prediction available at 30 minutes.';
    elements.problems.replaceChildren();
  } else {
    const prediction = assessment.prediction;
    const interval = prediction.prediction_intervals['90'];
    const probability = assessment.probability_of_reaching_target;
    const status = assessment.status.toLowerCase();
    const shownPrediction = yieldParts(prediction.point_prediction_gb);
    elements.statusBadge.className = `status-badge ${status}`;
    elements.statusBadge.querySelector('strong').textContent = assessment.status;
    elements.prediction.textContent = shownPrediction.value;
    elements.predictionUnit.textContent = shownPrediction.unit;
    elements.interval.textContent = `90% interval: ${yieldText(interval.lower_gb)}–${yieldText(interval.upper_gb)} · ${prediction.horizon_minutes}-min model`;
    elements.probability.textContent = `${Math.round(probability * 100)}%`;
    elements.probabilityRing.style.setProperty('--probability', `${probability * 360}deg`);
    elements.confidence.textContent = `${assessment.status_confidence} confidence`;
    elements.explanation.textContent = assessment.status_explanation;
    renderProblems(assessment.suspected_problems);
  }

  const complete = !live && data.state === 'complete' && data.actual_final_gb !== null;
  elements.outcome.classList.toggle('hidden', !complete);
  if (complete) elements.actual.textContent = number(data.actual_final_gb);
  if (!live && lastState !== 'complete' && data.state === 'complete') showToast('Historical replay complete');
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
  runsLoaded = true;
}

async function refresh() {
  const token = ++refreshToken;
  try {
    const query = currentMode === 'minknow' && selectedPosition
      ? `?position=${encodeURIComponent(selectedPosition)}`
      : '';
    const status = await api(`/api/status${query}`);
    if (token !== refreshToken) return;
    setConnected(true);
    renderStatus(status);
  } catch (error) {
    if (token === refreshToken) setConnected(false);
  }
}

elements.start.addEventListener('click', async () => {
  try {
    const target = Number(elements.target.value);
    if (!Number.isFinite(target) || target <= 0) throw new Error('Enter a positive target yield');
    const live = currentMode === 'minknow';
    const result = await api(live ? '/api/configure' : '/api/start', {
      method: 'POST',
      body: JSON.stringify(live ? { target_gb: target, position_name: selectedPosition } : {
        sample_id: elements.sample.value,
        target_gb: target,
        seconds_per_step: Number(elements.speed.value)
      })
    });
    renderStatus(result);
    showToast(live ? 'Target updated' : 'Replay started');
  } catch (error) {
    showToast(error.message);
  }
});

elements.target.addEventListener('input', renderTargetEquivalent);

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
    renderTargetEquivalent();
    await refresh();
    setInterval(refresh, 1000);
  } catch (error) {
    setConnected(false);
    showToast('Could not initialise the dashboard');
  }
})();
